#!/usr/bin/env python3
"""对网站做外部 agent 就绪度扫描。

只发 GET 请求，只读首页和约定的发现路径，不爬站内其他页面，不跟随跨域链接。
默认额外向 cloudflare-dns.com 发一条 DNS-over-HTTPS，查询 DNS-AID 的
`_index._agents` SVCB 记录；`--no-dns` 可以关掉。这条查询会把域名告诉该解析器。
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
from urllib.parse import urlencode, urljoin, urlparse

UA = "agent-friendly-scan/1.0 (+https://github.com/chrislee121/agent-friendly)"
MAX_BYTES = 1024 * 1024
DEFAULT_DOH = "https://cloudflare-dns.com/dns-query"
ARD_URN_RE = re.compile(r"^urn:air:[a-z0-9.-]+(?::[^\s:]+)+$", re.I)
VERSION_RE = re.compile(r"^\d+\.\d+$")
AMOUNT_RE = re.compile(r"^(0|[1-9][0-9]*)$")
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


def same_origin(origin: str, url: str) -> str | None:
    absolute = urljoin(origin + "/", url)
    part = urlparse(absolute)
    if part.scheme == "https" and f"{part.scheme}://{part.netloc}" == origin:
        return absolute.split("#", 1)[0]
    return None


def host_in_domain(hostname: str | None, domain: str) -> bool:
    host = (hostname or "").lower().rstrip(".")
    base = domain.lower().rstrip(".")
    return bool(host) and (host == base or host.endswith("." + base))


def link_header_targets(header: str, rel: str) -> list[str]:
    targets = []
    for part in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", header):
        if re.search(rf'rel="?[^";]*\b{re.escape(rel)}\b', part, re.I):
            match = re.search(r"<([^>]+)>", part)
            if match:
                targets.append(match.group(1).strip())
    return targets


def ard_entry_errors(entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return ["条目不是对象"]
    errors = []
    identifier = entry.get("identifier")
    if not isinstance(identifier, str) or not ARD_URN_RE.match(identifier):
        errors.append("identifier 须为 urn:air:<域名>:<名称>")
    if not isinstance(entry.get("displayName"), str) or not entry.get("displayName", "").strip():
        errors.append("缺少 displayName")
    kind = entry.get("type")
    if not isinstance(kind, str) or "/" not in kind:
        errors.append("type 须为媒体类型")
    has_url = isinstance(entry.get("url"), str) and entry["url"].startswith("https://")
    has_data = "data" in entry and entry.get("data") is not None
    if has_url == has_data:
        errors.append("url 与 data 必须且只能有一个，url 须为 https")
    return errors


def ard_entries(data: object) -> tuple[list[dict], list[str]]:
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return [], ["缺少 entries 数组"]
    good, notes = [], []
    for i, entry in enumerate(data["entries"], 1):
        errors = ard_entry_errors(entry)
        if errors:
            notes.append(f"第 {i} 条：" + "；".join(errors))
        else:
            good.append(entry)
            queries = entry.get("representativeQueries")
            if not isinstance(queries, list) or not 2 <= len(queries) <= 5:
                notes.append(f"第 {i} 条建议补 2～5 条 representativeQueries")
    return good, notes


def payment_offer_ok(offer: object) -> bool:
    if not isinstance(offer, dict):
        return False
    if offer.get("intent") not in ("charge", "session"):
        return False
    if not isinstance(offer.get("method"), str) or not offer["method"].strip():
        return False
    amount = offer.get("amount", None)
    return amount is None or (isinstance(amount, str) and bool(AMOUNT_RE.match(amount)))


def payment_info_ok(info: object) -> bool:
    if not isinstance(info, dict):
        return False
    offers = info.get("offers")
    if isinstance(offers, list):
        return bool(offers) and all(payment_offer_ok(item) for item in offers) and not any(
            key in info for key in ("amount", "currency", "intent", "method")
        )
    return payment_offer_ok(info)


def mpp_operation_count(doc: object) -> tuple[int, int]:
    """返回（合法的付费操作数，带 x-payment-info 但格式不对的操作数）。"""
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        return 0, 0
    ok = bad = 0
    for item in doc["paths"].values():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.startswith("x-") or method in ("parameters", "summary", "description", "servers"):
                continue
            if not isinstance(op, dict) or "x-payment-info" not in op:
                continue
            if payment_info_ok(op["x-payment-info"]):
                ok += 1
            else:
                bad += 1
    return ok, bad


def svcb_answers(data: dict) -> tuple[list[str], list[str], bool]:
    service: list[str] = []
    aliases: list[str] = []
    for item in data.get("Answer") or []:
        if not isinstance(item, dict) or str(item.get("type")) not in ("64", "SVCB"):
            continue
        match = re.match(r"\s*(\d+)\s+(\S+)", str(item.get("data") or ""))
        if not match:
            continue
        priority = int(match.group(1))
        target = match.group(2).rstrip(".") or "记录名本身"
        if priority == 0 and target != "记录名本身":
            aliases.append(target)
        elif priority > 0:
            service.append(target)
    return service, aliases, data.get("AD") is True


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
    def __init__(self, base: str, fetch: Fetcher, doh: str | None = DEFAULT_DOH):
        p = urlparse(base if "://" in base else f"https://{base}")
        self.origin = f"{p.scheme}://{p.netloc}"
        self.home = base if "://" in base else f"https://{base}"
        self.host = (p.hostname or "").lower()
        self.fetch = fetch
        self.doh = doh
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
        self.dns_aid()
        self.auth_md()
        self.ard(home)
        self.poppy()
        self.x402()
        self.mpp()
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

    def dns_aid(self):
        title = "DNS-AID（草案）"
        if not self.host:
            self.add("dns_aid", "D1", title, "skip", "网址没有域名，跳过")
            return
        if not self.doh:
            self.add("dns_aid", "D1", title, "skip", "已用 --no-dns 跳过。需要时发布 _index._agents 的 ServiceMode SVCB")
            return
        name = f"_index._agents.{self.host}"
        data, error = self.doh_query(name)
        if error:
            self.add("dns_aid", "D1", title, "skip",
                     f"DNS-over-HTTPS 查询失败（{error}）。这不表示站点没有记录",
                     "解析器可用后再查；记录本身是 _index._agents 上 priority≥1 的 SVCB")
            return
        service, aliases, ad = svcb_answers(data)
        if not service and aliases:
            data, error = self.doh_query(aliases[0])
            if error:
                self.add("dns_aid", "D1", title, "skip", f"AliasMode 指向 {aliases[0]}，继续查询失败（{error}）")
                return
            service, _, ad = svcb_answers(data)
        if not service:
            self.add("dns_aid", "D1", title, "info",
                     f"{name} 没有 ServiceMode SVCB。草案，没有 agent 索引时不需要",
                     "有组织级 agent 索引时再发布，并用 DNSSEC 签名。HTTPS 记录（type 65）不能代替这条 SVCB")
            return
        where = "、".join(service[:3])
        if ad:
            self.add("dns_aid", "D1", title, "pass", f"ServiceMode SVCB → {where}，本次响应带 AD")
        else:
            self.add("dns_aid", "D1", title, "warn",
                     f"有 ServiceMode SVCB → {where}，但本次 DoH 响应没有 AD，不能当作已通过 DNSSEC 验证",
                     "给发现记录所在区做 DNSSEC 签名，并用会验证 DNSSEC 的解析器复查")

    def doh_query(self, name: str) -> tuple[dict | None, str | None]:
        sep = "&" if "?" in (self.doh or "") else "?"
        url = f"{self.doh}{sep}{urlencode({'name': name, 'type': 'SVCB'})}"
        resp = self.get(url, "application/dns-json")
        if resp.status != 200:
            return None, resp.error or f"HTTP {resp.status}"
        data = resp.json()
        if not isinstance(data, dict) or "Status" not in data:
            return None, "响应不是 DNS JSON"
        return data, None

    def auth_md(self):
        title = "auth.md"
        doc = self.get("/auth.md", "text/markdown")
        text = doc.body if doc.status == 200 and "html" not in doc.ctype else ""
        has_doc = bool(re.search(r"(?m)^#\s+.*\bauth\.md\b", text, re.I))
        prm = self.get("/.well-known/oauth-protected-resource", "application/json")
        prm_data = prm.json() if prm.status == 200 else None
        has_prm = isinstance(prm_data, dict) and "resource" in prm_data and "authorization_servers" in prm_data
        agent_auth = None
        for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            meta = self.get(path, "application/json")
            data = meta.json() if meta.status == 200 else None
            if isinstance(data, dict) and isinstance(data.get("agent_auth"), dict):
                agent_auth = data["agent_auth"]
                break
        keys = ("skill", "identity_endpoint", "register_uri", "identity_types_supported", "claim_endpoint")
        has_auth = isinstance(agent_auth, dict) and any(agent_auth.get(key) for key in keys)
        if not has_doc and not has_auth:
            self.add("auth_md", "D4", title, "info", "未发布 /auth.md。只在要给 agent 做注册或登录时需要",
                     "发布 /auth.md（一级标题含 auth.md），并在本域授权服务器元数据里放 agent_auth")
            return
        missing = [name for name, ok in ((" /auth.md", has_doc), (" 本域受保护资源元数据", has_prm),
                                         (" 本域授权服务器的 agent_auth", has_auth)) if not ok]
        if missing:
            self.add("auth_md", "D4", title, "warn",
                     "缺" + "、".join(item.strip() for item in missing) + "。扫描不跟随跨域授权服务器",
                     "三件套都放在本域：/auth.md、/.well-known/oauth-protected-resource、带 agent_auth 的授权服务器元数据")
            return
        self.add("auth_md", "D4", title, "pass", "本域已有 /auth.md、受保护资源元数据和 agent_auth")

    def ard(self, home: Resp):
        title = "ARD 清单（草案）"
        primary = self.get("/.well-known/ard.json", "application/json")
        primary_data = primary.json() if primary.status == 200 else None
        good, notes = ard_entries(primary_data) if isinstance(primary_data, dict) else ([], [])
        source = "/.well-known/ard.json" if good else ""
        if not good:
            for raw in link_header_targets(home.headers.get("link", ""), "ard"):
                target = same_origin(self.origin, raw)
                found = self.ard_at(target) if target else None
                if found:
                    good, notes, source = found
                    break
            if not good:
                for match in re.finditer(r"<link\b[^>]*>", home.body or "", re.I):
                    tag = match.group(0)
                    if not re.search(r"\brel=[\"'][^\"']*\bard\b", tag, re.I):
                        continue
                    href = re.search(r"\bhref=[\"']([^\"']+)", tag, re.I)
                    target = same_origin(self.origin, href.group(1)) if href else None
                    found = self.ard_at(target) if target else None
                    if found:
                        good, notes, source = found
                        break
        legacy = None
        if not good:
            legacy_resp = self.get("/.well-known/ai-catalog.json", "application/json")
            legacy = legacy_resp.json() if legacy_resp.status == 200 else None
            if isinstance(legacy, dict):
                good, notes = ard_entries(legacy)
            if good:
                self.add("ard", "D1", title, "warn",
                         f"只在前代路径 /.well-known/ai-catalog.json 发现 {len(good)} 条合法条目",
                         "改到 /.well-known/ard.json，并加 Link: </.well-known/ard.json>; rel=\"ard\"。前代路径消费者可以不看")
                return
        if good:
            hint = f"；{'；'.join(notes[:2])}" if notes else ""
            self.add("ard", "D1", title, "pass", f"{source} 有 {len(good)} 条合法条目{hint}")
            return
        if primary.status == 200 or (isinstance(legacy, dict) and legacy.get("entries")):
            detail = "；".join(notes[:3]) or "条目缺少 identifier、displayName、type，或 url/data 不互斥"
            self.add("ard", "D1", title, "warn", f"发现清单，但没有合法条目。{detail}",
                     "每条要有 urn:air: 标识、displayName、媒体类型，且 url 与 data 二选一")
            return
        self.add("ard", "D1", title, "info", "未发布 /.well-known/ard.json",
                 "一个域名下有多个 agent 资源时发布，条目带 2～5 条 representativeQueries")

    def ard_at(self, url: str) -> tuple[list[dict], list[str], str] | None:
        linked = self.get(url, "application/json")
        data = linked.json() if linked.status == 200 else None
        if not isinstance(data, dict):
            return None
        good, notes = ard_entries(data)
        if not good:
            return None
        return good, notes, url

    def poppy(self):
        title = "Personal Agent Protocol"
        resp = self.get("/.well-known/poppy.json", "application/json")
        data = resp.json() if resp.status == 200 else None
        if not isinstance(data, dict):
            self.add("poppy", "D1", title, "info", "未发布 /.well-known/poppy.json（v1.0）",
                     "要让个人 agent 代表用户办事时再发布。至少要有 protocol_version、organization，以及 agent、apis、web 之一")
            return
        problems = []
        version = data.get("protocol_version")
        if not isinstance(version, str) or not VERSION_RE.match(version):
            problems.append("protocol_version 须为 major.minor")
        org = data.get("organization") if isinstance(data.get("organization"), dict) else {}
        if not isinstance(org.get("name"), str) or not org.get("name", "").strip():
            problems.append("缺少 organization.name")
        expected = self.host
        port = urlparse(self.origin).port
        if port and port != 443:
            expected = f"{self.host}:{port}"
        domain = org.get("domain")
        if not isinstance(domain, str) or domain.lower() != expected:
            problems.append(f"organization.domain 须为 {expected}")
        channels = []
        agent = data.get("agent")
        if isinstance(agent, dict) and isinstance(agent.get("protocols"), list) and agent["protocols"] and all(
            isinstance(item, dict) and isinstance(item.get("type"), str)
            and isinstance(item.get("endpoint"), str) and item["endpoint"].startswith("https://")
            and isinstance(item.get("description"), str) and item["description"].strip()
            for item in agent["protocols"]
        ):
            channels.append("agent")
        elif agent is not None:
            problems.append("agent.protocols 每项要有 type、https endpoint 和 description")
        apis = data.get("apis")
        if isinstance(apis, list) and apis and all(
            isinstance(item, dict) and isinstance(item.get("type"), str)
            and isinstance(item.get("url"), str) and item["url"].startswith("https://")
            and isinstance(item.get("description"), str) and item["description"].strip()
            for item in apis
        ):
            channels.append("apis")
        elif apis is not None:
            problems.append("apis 每项要有 type、https url 和 description")
        web = data.get("web")
        if isinstance(web, dict):
            channels.append("web")
        elif web is not None:
            problems.append("web 须为对象")
        if not channels and not any(item.startswith(("agent", "apis", "web")) for item in problems):
            problems.append("agent、apis、web 至少要有一个")
        if problems:
            self.add("poppy", "D1", title, "warn", "；".join(problems[:4]),
                     "按 v1.0 发布：版本、组织域名必须等于提供该文件的主机，并给出至少一个通道")
            return
        note = ""
        auth = data.get("auth")
        if isinstance(auth, dict) and isinstance(auth.get("issuer"), str):
            issuer_host = urlparse(auth["issuer"]).hostname
            if not host_in_domain(issuer_host, self.host):
                note = "；auth.issuer 不在本域，未跟随核验 protected_resources"
            else:
                meta = self.authorization_metadata()
                resources = meta.get("protected_resources") if isinstance(meta, dict) else None
                want = f"https://{expected}"
                if not isinstance(resources, list) or want not in resources:
                    self.add("poppy", "D1", title, "warn",
                             f"文档结构有效（{version}，通道 {'、'.join(channels)}），但本域授权服务器元数据的 protected_resources 未包含 {want}",
                             "按 v1.0，issuer 的 RFC 8414 元数据必须列回 https://<organization.domain>")
                    return
        self.add("poppy", "D1", title, "pass", f"v{version if isinstance(version, str) else ''}，通道 {'、'.join(channels)}{note}")

    def authorization_metadata(self) -> dict | None:
        for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            resp = self.get(path, "application/json")
            data = resp.json() if resp.status == 200 else None
            if isinstance(data, dict) and data.get("issuer"):
                return data
        return None

    def x402(self):
        title = "x402 发现（草案）"
        resp = self.get("/.well-known/x402", "application/json")
        data = resp.json() if resp.status == 200 else None
        if not isinstance(data, dict):
            self.add("x402", "D3", title, "info",
                     "未发布 /.well-known/x402。按次付费的 402 质询在具体资源上，本扫描不猜测路径",
                     "要让 agent 发现付费能力时，发布含 x402Version 和 kind 的清单。kind 为 facilitator 或 both 时，baseUrl 必须在本域")
            return
        problems = []
        if not isinstance(data.get("x402Version"), int) or isinstance(data.get("x402Version"), bool) or data["x402Version"] < 1:
            problems.append("x402Version 须为正整数")
        kind = data.get("kind")
        if kind not in ("facilitator", "resource-server", "both"):
            problems.append("kind 须为 facilitator、resource-server 或 both")
        if kind in ("facilitator", "both"):
            fac = data.get("facilitator") if isinstance(data.get("facilitator"), dict) else {}
            base = fac.get("baseUrl")
            if not isinstance(base, str) or not base.startswith("https://") or not host_in_domain(urlparse(base).hostname, self.host):
                problems.append("facilitator.baseUrl 须为 https 且在本域或子域")
            if not isinstance(fac.get("endpoints"), dict) or not isinstance(fac.get("kinds"), list):
                problems.append("facilitator 须含 endpoints 对象和 kinds 数组")
        resources = data.get("resources")
        offsite = []
        if isinstance(resources, list):
            for item in resources:
                url = item.get("url") if isinstance(item, dict) else None
                if isinstance(url, str) and not host_in_domain(urlparse(url).hostname, self.host):
                    offsite.append(url)
        if offsite:
            problems.append("resources 含本域以外的 URL，按草案不应被跟随")
        if problems:
            self.add("x402", "D3", title, "warn", "；".join(problems[:3]))
            return
        self.add("x402", "D3", title, "pass", f"x402Version {data.get('x402Version')}，kind={kind}。未请求付费资源")

    def mpp(self):
        title = "MPP 发现"
        resp = self.get("/openapi.json", "application/json")
        data = resp.json() if resp.status == 200 else None
        if not isinstance(data, dict):
            self.add("mpp", "D3", title, "info", "未发布 /openapi.json。没有按次付费就不需要",
                     "有 MPP 时在付费操作上加 x-payment-info，intent 用 charge 或 session")
            return
        ok, bad = mpp_operation_count(data)
        if bad:
            self.add("mpp", "D3", title, "warn", f"{bad} 个操作的 x-payment-info 格式不对，{ok} 个合法",
                     "新文档用 offers 数组；每项 intent 为 charge 或 session，method 非空，amount 为整数字符串或 null")
            return
        if ok:
            self.add("mpp", "D3", title, "pass", f"/openapi.json 有 {ok} 个带合法 x-payment-info 的操作。运行时仍以 402 质询为准")
            return
        self.add("mpp", "D3", title, "info", "已有 /openapi.json，没有 x-payment-info",
                 "只有按次向 agent 收费时才加。发现文档是提示，402 质询才是准的")

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
    ap.add_argument("--no-dns", action="store_true", help="不向公共解析器查询 DNS-AID")
    args = ap.parse_args()

    socket.create_connection = happy_eyeballs_connect
    scanner = Scanner(args.url, lambda u, h: http_fetch(u, h, args.timeout), doh=None if args.no_dns else DEFAULT_DOH)
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
        print(f"  {d}: 通过 {s['pass']}，警告 {s['warn']}，失败 {s['fail']}，未发布 {s['info']}，跳过 {s['skip']}")
    print("\n说明：「未发布」不等于有问题，按 references/surfaces.md 判断你是否需要该项。")
    print("DNS-AID 默认问 cloudflare-dns.com，域名会发给该解析器；不需要时加 --no-dns。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
