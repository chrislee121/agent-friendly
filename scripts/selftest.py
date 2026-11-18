#!/usr/bin/env python3
"""冒烟测试：不联网，用 examples/ 和内置假站点验证四个脚本。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(SCRIPTS))

import scan_site  # noqa: E402

failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def run(*args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout + p.stderr


def test_lint() -> None:
    code, out = run("scripts/lint_tools.py", "examples/tools.good.json", "--json")
    data = json.loads(out)
    check(code == 0 and data["counts"]["error"] == 0, "lint：正例无 error")
    check(data["counts"]["warn"] == 0, "lint：正例无 warn")

    code, out = run("scripts/lint_tools.py", "examples/tools.bad.json", "--json")
    data = json.loads(out)
    rules = {f["rule"] for f in data["findings"]}
    check(code == 1, "lint：反例 exit 1")
    for rule, why in [("T001", "名称含空格"), ("T024", "required 指向未定义参数"), ("T031", "写操作标成只读"),
                      ("T050", "描述投毒"), ("T041", "列表缺分页"), ("T033", "付款缺幂等键"), ("T023", "参数名笼统")]:
        check(rule in rules, f"lint：反例命中 {rule}（{why}）")

    openapi = {
        "openapi": "3.1.0",
        "paths": {"/orders": {"get": {"operationId": "orders_list", "summary": "列出订单",
                                      "responses": {"200": {"description": "ok"}}}}},
    }
    tools = __import__("lint_tools").tools_from_openapi(openapi)
    findings = __import__("lint_tools").lint(tools)
    check(any(f.rule == "T070" for f in findings), "lint：OpenAPI 缺 4xx 响应被发现")


def test_passk() -> None:
    code, out = run("scripts/passk.py", "examples/eval-results.sample.jsonl", "--json")
    data = json.loads(out)
    o = data["overall"]
    check(code == 0, "passk：无门槛时 exit 0")
    check(abs(o["pass_hat"]["1"] - 0.85) < 1e-9, "passk：pass^1 = 0.85")
    check(abs(o["pass_hat"]["4"] - 0.6) < 1e-9, "passk：pass^4 = 0.6")
    check(o["unsafe_runs"] == 1, "passk：不安全动作 1 次")
    check(data["unstable_tasks"] == ["cancel_with_injection", "find_slot"], "passk：识别时好时坏的任务")

    code, _ = run("scripts/passk.py", "examples/eval-results.sample.jsonl", "--gate", "R0:4:0.9", "--max-unsafe", "0")
    check(code == 1, "passk：不达门槛 exit 1")
    code, _ = run("scripts/passk.py", "examples/eval-results.sample.jsonl", "--gate", "R3:4:0.9")
    check(code == 0, "passk：R3 达门槛 exit 0")


def test_score() -> None:
    code, out = run("scripts/score.py", "examples/scorecard.sample.json", "--json")
    data = json.loads(out)
    check(code == 1, "score：红线未过 exit 1")
    check(data["level"] == "L2", "score：红线未过时等级封顶 L2")
    check(data["redlines_failed"] == ["H3", "H4"], "score：列出未过红线")
    check(abs(data["weighted_score"] - 64.3) < 0.05, "score：commerce 加权分 64.3")

    card = json.loads((EXAMPLES / "scorecard.sample.json").read_text(encoding="utf-8"))
    for k in ("H3", "H4"):
        card["redlines"][k] = {"status": "pass", "evidence": "已修复"}
    card["dimensions"]["D5"] = {"score": 3, "evidence": "系统级确认已接入"}
    tmp = ROOT / "examples" / ".tmp-scorecard.json"
    tmp.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    try:
        code, out = run("scripts/score.py", str(tmp), "--json")
        data = json.loads(out)
        check(code == 0 and data["level"] == "L3", "score：修复后达到 L3")
        card["dimensions"]["D9"] = {"score": 3, "evidence": ""}
        tmp.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        _, out = run("scripts/score.py", str(tmp), "--json")
        check(json.loads(out)["scores"]["D9"] == 0, "score：没有证据的分数按 0 计")
    finally:
        tmp.unlink(missing_ok=True)


def fake_site(pages: dict[str, scan_site.Resp]):
    def fetch(url: str, headers: dict) -> scan_site.Resp:
        accept = headers.get("Accept", "")
        key = url + ("#md" if accept == "text/markdown" else "")
        return pages.get(key) or pages.get(url) or scan_site.Resp(404, {"content-type": "text/html"}, "<h1>404</h1>")
    return fetch


def test_scan() -> None:
    base = "https://shop.example"
    html = ('<html lang="zh-CN"><head><script type="application/ld+json">{}</script></head><body>'
            + "<p>" + "欢迎光临。" * 60 + "</p>"
            + '<label for="q">搜索</label><input id="q" name="q"><input name="email">'
            + '<label><input type="checkbox" name="remember">记住我</label>'
            + '<div onclick="go()">下单</div><img src="a.png"></body></html>')
    pages = {
        f"{base}": scan_site.Resp(200, {"content-type": "text/html; charset=utf-8",
                                        "link": '</.well-known/api-catalog>; rel="api-catalog"'}, html),
        f"{base}#md": scan_site.Resp(200, {"content-type": "text/markdown"}, "# Shop"),
        f"{base}/robots.txt": scan_site.Resp(200, {"content-type": "text/plain"},
                                             "User-agent: *\nAllow: /\nUser-agent: GPTBot\nDisallow: /\n"
                                             "Content-Signal: search=yes, ai-input=yes, ai-train=no\nSitemap: /sitemap.xml\n"),
        f"{base}/llms.txt": scan_site.Resp(200, {"content-type": "text/plain"}, "# Shop\n\n- [Docs](/docs.md)\n"),
        f"{base}/.well-known/api-catalog": scan_site.Resp(200, {"content-type": "application/linkset+json"},
                                                          '{"linkset": [{"anchor": "https://shop.example/api"}]}'),
        f"{base}/.well-known/oauth-protected-resource": scan_site.Resp(
            200, {"content-type": "application/json"},
            '{"resource": "https://shop.example/mcp", "authorization_servers": ["https://auth.shop.example"]}'),
    }
    checks = {c.id: c for c in scan_site.Scanner(base, fake_site(pages)).run()}
    expect = {
        "robots": "pass", "ai_bot_rules": "pass", "content_signals": "pass", "sitemap": "pass",
        "link_headers": "pass", "markdown_negotiation": "pass", "llms_txt": "pass", "html_lang": "pass",
        "json_ld": "pass", "fake_buttons": "warn", "input_labels": "warn", "img_alt": "warn", "ssr_text": "pass",
        "api_catalog": "pass", "oauth_prm": "pass", "mcp_card": "info", "a2a_card": "info",
        "dns_aid": "skip", "auth_md": "info", "ai_catalog": "info", "poppy": "info", "x402": "info", "mpp": "info",
    }
    for cid, status in expect.items():
        got = checks.get(cid).status if cid in checks else "missing"
        check(got == status, f"scan：{cid} = {status}（实际 {got}）")
    labels = checks["input_labels"].message
    check(labels.startswith("1 个"), f"scan：<label> 包住的输入框算有标签（实际 {labels}）")

    down = scan_site.Scanner("https://down.example", lambda u, h: scan_site.Resp(0, {}, "", "timeout")).run()
    check(len(down) == 1 and down[0].status == "fail", "scan：首页不可达时只报一条失败")

    quiet = scan_site.Scanner(base, fake_site(pages), doh=None).run()
    dns = next(c for c in quiet if c.id == "dns_aid")
    check(dns.status == "skip" and "--no-dns" in dns.message, "scan：--no-dns 不发 DNS 查询")


def test_scan_discovery() -> None:
    base = "https://book.example"
    doh = scan_site.DEFAULT_DOH
    q = f"{doh}?{urlencode({'name': '_index._agents.book.example', 'type': 'SVCB'})}"
    ard = json.dumps({
        "entries": [{
            "identifier": "urn:air:book.example:reserve",
            "displayName": "订座",
            "type": "application/openapi+json",
            "url": "https://book.example/openapi.json",
            "representativeQueries": ["今晚有位吗", "订一个四人位"],
        }],
    })
    pages = {
        base: scan_site.Resp(200, {"content-type": "text/html"}, "<html lang=\"zh\"><body>" + "有位。" * 80 + "</body></html>"),
        q: scan_site.Resp(200, {"content-type": "application/dns-json"},
                          json.dumps({"Status": 0, "AD": True, "Answer": [{"type": 64, "data": "1 book.example. alpn=\"h2\""}]})),
        f"{base}/auth.md": scan_site.Resp(200, {"content-type": "text/markdown"}, "# auth.md\n\n注册后换令牌。\n"),
        f"{base}/.well-known/oauth-protected-resource": scan_site.Resp(
            200, {"content-type": "application/json"},
            '{"resource": "https://book.example", "authorization_servers": ["https://book.example"]}'),
        f"{base}/.well-known/oauth-authorization-server": scan_site.Resp(
            200, {"content-type": "application/json"},
            json.dumps({"issuer": "https://book.example", "token_endpoint": "https://book.example/token",
                        "protected_resources": ["https://book.example"],
                        "agent_auth": {"skill": "https://book.example/auth.md",
                                       "identity_endpoint": "https://book.example/agent/identity"}})),
        f"{base}/.well-known/ard.json": scan_site.Resp(200, {"content-type": "application/json"}, ard),
        f"{base}/.well-known/poppy.json": scan_site.Resp(
            200, {"content-type": "application/json"},
            json.dumps({"protocol_version": "1.0", "organization": {"name": "南风", "domain": "book.example"}, "web": {}})),
        f"{base}/.well-known/x402": scan_site.Resp(
            200, {"content-type": "application/json"}, '{"x402Version": 2, "kind": "resource-server"}'),
        f"{base}/openapi.json": scan_site.Resp(
            200, {"content-type": "application/json"},
            json.dumps({"openapi": "3.1.0", "paths": {"/deposit": {"post": {
                "x-payment-info": {"offers": [{"amount": "2000", "currency": "cny", "intent": "charge", "method": "stripe"}]},
                "responses": {"200": {"description": "ok"}, "402": {"description": "Payment Required"}}}}}})),
    }
    checks = {c.id: c for c in scan_site.Scanner(base, fake_site(pages)).run()}
    for cid in ("dns_aid", "auth_md", "ai_catalog", "poppy", "x402", "mpp"):
        got = checks[cid].status
        check(got == "pass", f"scan：{cid} 正例通过（实际 {got}：{checks[cid].message}）")

    no402 = dict(pages)
    no402[f"{base}/openapi.json"] = scan_site.Resp(
        200, {"content-type": "application/json"},
        json.dumps({"openapi": "3.1.0", "paths": {"/deposit": {"post": {
            "x-payment-info": {"offers": [{"amount": "2000", "intent": "charge", "method": "stripe"}]},
            "responses": {"200": {"description": "ok"}}}}}}))
    got = {c.id: c for c in scan_site.Scanner(base, fake_site(no402), doh=None).run()}["mpp"]
    check(got.status == "warn" and "402" in got.message, f"scan：付费操作缺 402 响应时警告（实际 {got.status}）")

    unsigned = dict(pages)
    unsigned[q] = scan_site.Resp(200, {"content-type": "application/dns-json"},
                                 json.dumps({"Status": 0, "AD": False, "Answer": [{"type": 64, "data": "1 book.example."}]}))
    got = {c.id: c for c in scan_site.Scanner(base, fake_site(unsigned)).run()}["dns_aid"]
    check(got.status == "warn", f"scan：SVCB 没有 AD 时警告（实际 {got.status}）")

    mcp = dict(pages)
    del mcp[f"{base}/.well-known/ard.json"]
    mcp[f"{base}/.well-known/ai-catalog.json"] = scan_site.Resp(200, {"content-type": "application/json"}, json.dumps({
        "specVersion": "1.0",
        "entries": [{"identifier": "urn:air:book.example:mcp:reserve", "displayName": "订座 MCP",
                     "type": "application/mcp-server-card+json", "url": "https://book.example/mcp/server-card"}]}))
    mcp[f"{base}/mcp/server-card"] = scan_site.Resp(200, {"content-type": "application/mcp-server-card+json"},
                                                    '{"name": "example.book/reserve", "version": "1.0.0"}')
    got = {c.id: c for c in scan_site.Scanner(base, fake_site(mcp), doh=None).run()}
    check(got["ai_catalog"].status == "pass", f"scan：只发布 ai-catalog.json 也算通过（实际 {got['ai_catalog'].status}）")
    check(got["mcp_card"].status == "pass" and "/mcp/server-card" in got["mcp_card"].message,
          f"scan：经 AI Catalog 找到端点下的 /server-card（实际 {got['mcp_card'].status}：{got['mcp_card'].message}）")

    leaked = []
    evil_home = scan_site.Resp(200, {"content-type": "text/html",
                                     "link": '<https://evil.example/ard.json>; rel="ard", <https://evil.example/c.json>; rel="ai-catalog"'},
                               pages[base].body + '<link rel="ard" href="https://evil.example/page.json">')
    evil_pages = {base: evil_home}

    def watching(url: str, headers: dict) -> scan_site.Resp:
        leaked.append(url)
        if url.startswith("https://evil.example/"):
            return scan_site.Resp(200, {"content-type": "application/json"}, pages[f"{base}/.well-known/ard.json"].body)
        return fake_site(evil_pages)(url, headers)

    got = {c.id: c for c in scan_site.Scanner(base, watching, doh=None).run()}["ai_catalog"]
    check(not any(u.startswith("https://evil.example/") for u in leaked),
          f"scan：不跟随跨域 rel=ard / rel=ai-catalog / <link>（实际请求了 {[u for u in leaked if 'evil' in u]}）")
    check("未跟随外域链接 3 个" in got.message, f"scan：报告未跟随的外域目录链接（实际 {got.message}）")

    bad_pay = dict(pages)
    bad_pay[f"{base}/.well-known/x402"] = scan_site.Resp(
        200, {"content-type": "application/json"},
        '{"x402Version": 2, "kind": "facilitator", "facilitator": {"baseUrl": "https://evil.example", "endpoints": {}, "kinds": []}}')
    got = {c.id: c for c in scan_site.Scanner(base, fake_site(bad_pay)).run()}["x402"]
    check(got.status == "warn", f"scan：x402 facilitator 指向外域时警告（实际 {got.status}）")


def redirect(location: str) -> scan_site.Resp:
    return scan_site.Resp(302, {"location": location, "content-type": "text/html"}, "")


def test_scan_redirects() -> None:
    base = "https://shop.example"
    html = scan_site.Resp(200, {"content-type": "text/html"}, '<html lang="zh"><body>' + "好。" * 120 + "</body></html>")
    poppy = json.dumps({"protocol_version": "1.0", "organization": {"name": "x", "domain": "shop.example"}, "web": {}})
    requested = []

    def fetch(pages):
        def inner(url: str, headers: dict) -> scan_site.Resp:
            requested.append(url)
            return pages.get(url) or scan_site.Resp(404, {"content-type": "text/html"}, "")
        return inner

    pages = {
        base: html,
        f"{base}/.well-known/poppy.json": redirect("https://other.example/poppy.json"),
        "https://other.example/poppy.json": scan_site.Resp(200, {"content-type": "application/json"}, poppy),
        f"{base}/.well-known/x402": redirect("http://169.254.169.254/latest"),
        f"{base}/robots.txt": redirect("/robots-real.txt"),
        f"{base}/robots-real.txt": scan_site.Resp(200, {"content-type": "text/plain"}, "User-agent: *\nAllow: /\n"),
    }
    checks = {c.id: c for c in scan_site.Scanner(base, fetch(pages), doh=None).run()}
    check(not any("other.example" in u or "169.254" in u for u in requested), "scan：不跟随跨主机和内网跳转")
    check(checks["poppy"].status == "info", f"scan：跨主机跳转的 poppy.json 不算发布（实际 {checks['poppy'].status}）")
    check(checks["robots"].status == "pass", f"scan：同主机跳转照常跟随（实际 {checks['robots'].status}）")

    requested.clear()
    moved = {
        "https://shop.example": redirect("https://www.shop.example/"),
        "https://www.shop.example/": html,
        "https://www.shop.example/robots.txt": scan_site.Resp(200, {"content-type": "text/plain"}, "User-agent: *\n"),
    }
    checks = {c.id: c for c in scan_site.Scanner("https://shop.example", fetch(moved), doh=None).run()}
    check(checks["home"].status == "pass" and "www.shop.example" in checks["home"].message,
          f"scan：首页跳到规范主机后按新主机检查（实际 {checks['home'].message}）")
    check(checks["robots"].status == "pass", "scan：首页换主机后，其余路径跟着换")

    requested.clear()
    scan_site.Scanner("https://shop.example", fetch(moved)).run()
    dns = [u for u in requested if "_agents" in u]
    check(len(dns) == 1 and "_index._agents.shop.example" in dns[0] and "www" not in dns[0],
          f"scan：DNS-AID 查用户给的域名，不查跳转后的 www（实际 {dns}）")

    inner = {"https://shop.example": redirect("http://127.0.0.1:8080/")}
    checks = scan_site.Scanner("https://shop.example", fetch(inner), doh=None).run()
    check(checks[0].status == "fail" and "内网" in checks[0].message, f"scan：首页跳到内网地址时不跟随（实际 {checks[0].message}）")

    import http.server
    import threading

    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        resp = scan_site.http_fetch(f"http://127.0.0.1:{server.server_port}/start", {}, 5)
    finally:
        server.shutdown()
    check(resp.status == 302 and hits == ["/start"], f"scan：http_fetch 不自动跟随跳转（实际 {resp.status}，{hits}）")


def test_passk_input() -> None:
    tmp = ROOT / "examples" / ".tmp-eval.jsonl"
    cases = [
        ('{"task_id": "pay", "success": true}', 2, "缺 risk 报错，不默认 R0"),
        ('{"task_id": "pay", "success": "false", "risk": "R3"}', 2, "success 为字符串时报错"),
        ('{"task_id": "pay", "success": true, "risk": "R9"}', 2, "未知风险等级报错"),
        ('{"task_id": "pay", "success": true, "risk": "r2"}', 0, "小写 r2 按 R2 处理"),
    ]
    try:
        for line, want, label in cases:
            tmp.write_text(line + "\n", encoding="utf-8")
            code, _ = run("scripts/passk.py", str(tmp))
            check(code == want, f"passk：{label}（exit {code}）")
        tmp.write_text('{"task_id": "pay", "success": true, "risk": "R2"}\n', encoding="utf-8")
        code, _ = run("scripts/passk.py", str(tmp), "--gate", "R2:0:0.9")
        check(code == 2, f"passk：k = 0 的门槛被拒绝（exit {code}）")
        code, _ = run("scripts/passk.py", str(tmp), "--gate", "R2:1:1.5")
        check(code == 2, f"passk：门槛大于 1 被拒绝（exit {code}）")
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    for t in (test_lint, test_passk, test_passk_input, test_score, test_scan, test_scan_discovery, test_scan_redirects):
        print(f"\n== {t.__name__}")
        t()
    print(f"\n{'PASS' if not failures else 'FAIL'}（失败 {len(failures)} 项）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
