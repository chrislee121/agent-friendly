#!/usr/bin/env python3
"""冒烟测试：不联网，用 examples/ 和内置假站点验证四个脚本。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
    }
    for cid, status in expect.items():
        got = checks.get(cid).status if cid in checks else "missing"
        check(got == status, f"scan：{cid} = {status}（实际 {got}）")
    labels = checks["input_labels"].message
    check(labels.startswith("1 个"), f"scan：<label> 包住的输入框算有标签（实际 {labels}）")

    down = scan_site.Scanner("https://down.example", lambda u, h: scan_site.Resp(0, {}, "", "timeout")).run()
    check(len(down) == 1 and down[0].status == "fail", "scan：首页不可达时只报一条失败")


def main() -> int:
    for t in (test_lint, test_passk, test_score, test_scan):
        print(f"\n== {t.__name__}")
        t()
    print(f"\n{'PASS' if not failures else 'FAIL'}（失败 {len(failures)} 项）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
