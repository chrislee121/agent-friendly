#!/usr/bin/env python3
"""对网站做外部 agent 就绪度扫描。

只发 GET 请求，只读首页和约定的 well-known 路径，不爬站内其他页面。
只覆盖评分卡里「可发现」「可理解」两个维度的一部分，以及授权元数据、内容偏好。
能不能办成事要靠任务评测，扫描结果不能代替。
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import socket
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlparse

UA = "agent-friendly-scan/1.0 (+https://github.com/chrislee121/agent-friendly)"
MAX_BYTES = 1024 * 1024
AI_BOTS = (
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User",
    "Google-Extended", "PerplexityBot", "Perplexity-User", "Applebot-Extended", "Bytespider",
    "CCBot", "meta-externalagent", "Amazonbot", "DuckAssistBot", "MistralAI-User",
)
LINK_RELS = ("service-desc", "service-doc", "describedby", "api-catalog", "llms-txt")


@dataclass
class Resp:
    status: int
    headers: dict = field(default_factory=dict)
    body: str = ""
    error: str | None = None

    @property
    def ctype(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def json(self):
        try:
            return json.loads(self.body)
        except ValueError:
            return None


Fetcher = Callable[[str, dict], Resp]


def happy_eyeballs_connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    """IPv6 出口不通时，标准库会把每个 IPv6 地址等满超时；这里错开 250ms 并发连接，取最先成功的。"""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"getaddrinfo 无结果：{host}")
    results: queue.Queue = queue.Queue()
    done = threading.Event()

    def attempt(info):
        fam, typ, proto, _, addr = info
        sock = socket.socket(fam, typ, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(addr)
        except OSError as e:
            sock.close()
            results.put(e)
            return
        if done.is_set():
            sock.close()
        else:
            results.put(sock)

    for i, info in enumerate(infos):
        t = threading.Timer(0.25 * i, attempt, args=(info,))
        t.daemon = True
        t.start()
    last_err: OSError | None = None
    for _ in infos:
        r = results.get()
        if isinstance(r, socket.socket):
            done.set()
            return r
        last_err = r
    raise last_err or OSError(f"无法连接 {host}:{port}")


def http_fetch(url: str, headers: dict, timeout: float = 10.0) -> Resp:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            hdrs = {}
            for k in set(r.headers.keys()):
                hdrs[k.lower()] = ", ".join(r.headers.get_all(k) or [])
            return Resp(r.status, hdrs, r.read(MAX_BYTES).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
        return Resp(e.code, hdrs, e.read(65536).decode("utf-8", "replace") if e.fp else "")
    except Exception as e:  # noqa: BLE001
        return Resp(0, {}, "", f"{type(e).__name__}: {e}")


@dataclass
class Check:
    id: str
    dimension: str
    title: str
    status: str
    message: str
    fix: str = ""


class Scanner:
    def __init__(self, base: str, fetch: Fetcher):
        p = urlparse(base if "://" in base else f"https://{base}")
        self.origin = f"{p.scheme}://{p.netloc}"
        self.home = base if "://" in base else f"https://{base}"
        self.fetch = fetch
        self.cache: dict[tuple, Resp] = {}
        self.checks: list[Check] = []

    def get(self, path: str, accept: str = "*/*") -> Resp:
        url = path if "://" in path else urljoin(self.origin, path)
        key = (url, accept)
        if key not in self.cache:
            self.cache[key] = self.fetch(url, {"Accept": accept})
        return self.cache[key]

    def add(self, *args, **kwargs):
        self.checks.append(Check(*args, **kwargs))

    def run(self) -> list[Check]:
        home = self.get(self.home, "text/html")
        if home.status == 0:
            self.add("home", "D1", "首页可访问", "fail", f"无法访问首页：{home.error}", "检查网址、证书和防火墙规则")
            return self.checks
        self.add("home", "D1", "首页可访问", "pass" if 200 <= home.status < 400 else "fail", f"HTTP {home.status}")
        self.robots()
        self.sitemap()
        self.link_headers(home)
        self.markdown()
        self.llms_txt()
        self.html_semantics(home)
        self.well_known()
        self.webmcp(home)
        return self.checks

    def robots(self):
        r = self.get("/robots.txt", "text/plain")
        ok = r.status == 200 and "user-agent" in r.body.lower() and "<html" not in r.body[:500].lower()
        self.add("robots", "D1", "robots.txt", "pass" if ok else "fail",
                 "存在且含 User-agent" if ok else f"HTTP {r.status}，或内容不是 robots 格式",
                 "在根目录发布纯文本 robots.txt，写明 User-agent 与 Allow / Disallow")
        body = r.body if ok else ""
        named = [b for b in AI_BOTS if re.search(rf"user-agent:\s*{re.escape(b)}\b", body, re.I)]
        self.add("ai_bot_rules", "D8", "AI 爬虫与 agent 规则", "pass" if named else "warn",
                 f"已对 {len(named)} 个 AI UA 单独表态：{', '.join(named[:6])}" if named else "未对任何 AI 爬虫或 agent 单独表态",
                 "区分搜索类（OAI-SearchBot、Claude-SearchBot、PerplexityBot）、训练类（GPTBot、ClaudeBot、Google-Extended）、用户代理类（ChatGPT-User、Claude-User），分别写规则")
        signal = re.search(r"^\s*content-signal\s*:\s*(.+)$", body, re.I | re.M)
        usage = re.search(r"^\s*content-usage\s*:\s*(.+)$", body, re.I | re.M)
        if signal or usage:
            msg = "；".join(x for x in [
                f"Content-Signal: {signal.group(1).strip()}" if signal else "",
                f"Content-Usage: {usage.group(1).strip()}" if usage else "",
            ] if x)
            self.add("content_signals", "D8", "AI 内容使用偏好", "pass", msg)
        else:
            self.add("content_signals", "D8", "AI 内容使用偏好", "warn", "robots.txt 未声明内容使用偏好",
                     "加一行，例如 Content-Signal: search=yes, ai-input=yes, ai-train=no；与用户协议保持一致")

    def sitemap(self):
        r = self.get("/sitemap.xml", "application/xml")
        robots = self.get("/robots.txt", "text/plain")
        in_robots = bool(re.search(r"^\s*sitemap\s*:", robots.body, re.I | re.M)) if robots.status == 200 else False
        ok = (r.status == 200 and ("<urlset" in r.body or "<sitemapindex" in r.body)) or in_robots
        self.add("sitemap", "D1", "sitemap", "pass" if ok else "warn",
                 "已发布" if ok else "未找到 /sitemap.xml，robots.txt 也没有 Sitemap 指令",
                 "生成 sitemap.xml 并在 robots.txt 里引用")

    def link_headers(self, home: Resp):
        link = home.headers.get("link", "")
        rels = [rel for rel in LINK_RELS if re.search(rf'rel="?[^";]*\b{rel}\b', link)]
        self.add("link_headers", "D1", "首页 Link 响应头", "pass" if rels else "info",
                 f"含 {', '.join(rels)}" if rels else "首页响应头没有指向 API 描述或文档的 Link",
                 '加 Link: </.well-known/api-catalog>; rel="api-catalog"（RFC 8288 / RFC 9727）')

    def markdown(self):
        r = self.get(self.home, "text/markdown")
        ok = r.status == 200 and r.ctype in ("text/markdown", "text/x-markdown")
        self.add("markdown_negotiation", "D2", "Markdown 内容协商", "pass" if ok else "warn",
                 "Accept: text/markdown 时返回 Markdown" if ok else f"返回 {r.ctype or '未知类型'}",
                 "请求头为 Accept: text/markdown 时返回 Markdown 版本，浏览器仍返回 HTML")

    def llms_txt(self):
        r = self.get("/llms.txt", "text/plain")
        first = next((ln for ln in r.body.splitlines() if ln.strip()), "")
        ok = r.status == 200 and "html" not in r.ctype and first.lstrip().startswith("#")
        self.add("llms_txt", "D2", "llms.txt", "pass" if ok else "info",
                 "存在且为 Markdown" if ok else "未发布，或返回的不是 Markdown",
                 "可选：在根目录发布 llms.txt，用一级标题写站名，再列关键文档链接")

    def html_semantics(self, home: Resp):
        html = home.body if "html" in home.ctype or "<html" in home.body[:2000].lower() else ""
        if not html:
            self.add("html", "D2", "页面语义", "skip", "首页不是 HTML，跳过")
            return
        lower = html.lower()
        self.add("html_lang", "D2", "<html lang>", "pass" if re.search(r"<html[^>]*\blang=", lower) else "warn",
                 "已声明语言" if re.search(r"<html[^>]*\blang=", lower) else "未声明页面语言", "给 <html> 加 lang 属性")
        has_ld = "application/ld+json" in lower
        self.add("json_ld", "D2", "结构化数据（JSON-LD）", "pass" if has_ld else "info",
                 "首页含 JSON-LD" if has_ld else "首页未发现 JSON-LD", "按页面类型加 schema.org JSON-LD")
        fake_buttons = len(re.findall(r"<(div|span)[^>]*\bonclick=", lower))
        self.add("fake_buttons", "D2", "可点击元素语义", "warn" if fake_buttons else "pass",
                 f"发现 {fake_buttons} 个带 onclick 的 div / span" if fake_buttons else "未发现 div / span 冒充按钮",
                 "可点击的用 <button> 或 <a>；实在不能改时补 role 和 tabindex")
        label_for = set(re.findall(r"<label[^>]*\bfor=[\"']?([^\"'\s>]+)", html, re.I))
        unlabeled = 0
        outside_labels = re.sub(r"<label\b.*?</label>", "", html, flags=re.I | re.S)
        for tag in re.findall(r"<input\b[^>]*>", outside_labels, re.I):
            t = tag.lower()
            if re.search(r"type=[\"']?(hidden|submit|button|image|reset)", t):
                continue
            if "aria-label" in t or "aria-labelledby" in t:
                continue
            m = re.search(r"\bid=[\"']?([^\"'\s>]+)", tag, re.I)
            if m and m.group(1) in label_for:
                continue
            unlabeled += 1
        self.add("input_labels", "D2", "输入框标签", "warn" if unlabeled else "pass",
                 f"{unlabeled} 个输入框没有关联标签" if unlabeled else "输入框均有标签（静态检查）",
                 "用 <label for> 关联，或加 aria-label；placeholder 不能代替标签")
        no_alt = len(re.findall(r"<img\b(?![^>]*\balt=)[^>]*>", lower))
        self.add("img_alt", "D2", "图片替代文本", "warn" if no_alt else "pass",
                 f"{no_alt} 张图片缺 alt" if no_alt else "图片均有 alt", "给内容图片写 alt，装饰图写 alt=\"\"")
        text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        visible = len(re.sub(r"\s+", " ", text).strip())
        self.add("ssr_text", "D2", "服务端渲染文本", "pass" if visible >= 200 else "warn",
                 f"初始 HTML 可见文本约 {visible} 字符",
                 "关键内容、导航和表单放进服务端渲染的 HTML，不依赖客户端脚本")

    def well_known(self):
        def found(paths, validate):
            for p in paths:
                r = self.get(p, "application/json")
                if r.status == 200:
                    data = r.json()
                    if data is not None and validate(data):
                        return p
            return None

        p = found(["/.well-known/api-catalog"], lambda d: isinstance(d, dict) and "linkset" in d)
        self.add("api_catalog", "D1", "API Catalog（RFC 9727）", "pass" if p else "info",
                 f"{p}" if p else "未发布", "有公开 API 时发布 /.well-known/api-catalog（application/linkset+json）")

        p = found(["/.well-known/ai-catalog.json"], lambda d: isinstance(d, dict) and isinstance(d.get("entries"), list))
        self.add("ai_catalog", "D1", "AI Catalog（草案）", "pass" if p else "info",
                 f"{p}" if p else "未发布", "一个域名下有多个 MCP / agent 服务时，用 /.well-known/ai-catalog.json 汇总")

        p = found(["/.well-known/mcp/server-card.json", "/.well-known/mcp.json", "/.well-known/mcp/server.json"],
                  lambda d: isinstance(d, dict) and bool(d.get("name") or (d.get("serverInfo") or {}).get("name")))
        self.add("mcp_card", "D1", "MCP 服务发现", "pass" if p else "info",
                 f"{p}" if p else "未发现 MCP Server Card 或 server.json",
                 "提供远程 MCP 时：在端点下发布 /server-card，并在 MCP Registry 登记 server.json")

        p = found(["/.well-known/agent-card.json"],
                  lambda d: isinstance(d, dict) and d.get("name") and (d.get("supportedInterfaces") or d.get("url")))
        self.add("a2a_card", "D1", "A2A Agent Card", "pass" if p else "info",
                  f"{p}" if p else "未发布", "提供 agent 服务时发布 /.well-known/agent-card.json")

        p = found(["/.well-known/agent-skills/index.json", "/.well-known/skills/index.json"],
                  lambda d: isinstance(d, dict) and isinstance(d.get("skills"), list))
        self.add("agent_skills", "D1", "Agent Skills 索引（草案）", "pass" if p else "info",
                 f"{p}" if p else "未发布", "有面向 agent 的操作指南时发布 /.well-known/agent-skills/index.json")

        p = found(["/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"],
                  lambda d: isinstance(d, dict) and "issuer" in d and "token_endpoint" in d)
        self.add("oauth_metadata", "D4", "授权服务器元数据（RFC 8414 / OIDC）", "pass" if p else "info",
                 f"{p}" if p else "未发布", "有需要用户授权的 API 或 MCP 时发布")

        p = found(["/.well-known/oauth-protected-resource"],
                  lambda d: isinstance(d, dict) and "resource" in d and "authorization_servers" in d)
        self.add("oauth_prm", "D4", "受保护资源元数据（RFC 9728）", "pass" if p else "info",
                 f"{p}" if p else "未发布", "远程 MCP 必需：发布 resource、authorization_servers、scopes_supported")

        r = self.get("/.well-known/http-message-signatures-directory", "application/http-message-signatures-directory+json")
        ok = r.status == 200 and isinstance(r.json(), dict) and "keys" in (r.json() or {})
        self.add("web_bot_auth", "D4", "Web Bot Auth 密钥目录", "pass" if ok else "info",
                 "已发布" if ok else "未发布（只有你对外发出 agent 流量时才需要）")

        for path, title in (("/.well-known/ucp", "UCP"), ("/.well-known/acp.json", "ACP")):
            r = self.get(path, "application/json")
            ok = r.status == 200 and r.json() is not None
            self.add(f"commerce_{title.lower()}", "D3", f"交易协议 {title}", "pass" if ok else "info",
                     "已发布" if ok else "未发布（卖东西时再考虑）")

    def webmcp(self, home: Resp):
        html = home.body
        hit = re.search(r"modelContext\s*\.\s*registerTool", html) or re.search(r"<form[^>]*\btoolname=", html, re.I)
        self.add("webmcp", "D3", "WebMCP（草案）", "pass" if hit else "info",
                 "首页静态 HTML 中发现 WebMCP 工具声明" if hit else "静态 HTML 中未发现。外部脚本注册的工具要用浏览器确认",
                 "复杂网页应用可用 document.modelContext.registerTool() 或给表单加 toolname 注解")


def summarize(checks: list[Check]) -> dict:
    dims: dict[str, dict] = {}
    for c in checks:
        d = dims.setdefault(c.dimension, {"pass": 0, "warn": 0, "fail": 0, "info": 0, "skip": 0})
        d[c.status] += 1
    return dims


def main() -> int:
    ap = argparse.ArgumentParser(description="网站外部 agent 就绪度扫描（只读 GET）")
    ap.add_argument("url", help="网站首页，例如 https://example.com")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--timeout", type=float, default=10.0, help="单个请求超时秒数")
    args = ap.parse_args()

    socket.create_connection = happy_eyeballs_connect
    scanner = Scanner(args.url, lambda u, h: http_fetch(u, h, args.timeout))
    checks = scanner.run()
    summary = summarize(checks)

    if args.json:
        print(json.dumps({"url": scanner.home, "summary": summary, "checks": [c.__dict__ for c in checks]},
                         ensure_ascii=False, indent=2))
        return 0

    icon = {"pass": "✓", "warn": "!", "fail": "✗", "info": "·", "skip": "-"}
    print(f"# 外部扫描：{scanner.home}\n")
    for c in checks:
        print(f"{icon[c.status]} [{c.dimension}] {c.title}：{c.message}")
        if c.status in ("warn", "fail") and c.fix:
            print(f"    建议：{c.fix}")
    print("\n按维度汇总：")
    for d in sorted(summary):
        s = summary[d]
        print(f"  {d}: 通过 {s['pass']}，警告 {s['warn']}，失败 {s['fail']}，未发布 {s['info']}")
    print("\n说明：「未发布」不等于有问题，按 references/surfaces.md 判断你是否需要该项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
