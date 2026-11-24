#!/usr/bin/env python3
"""把扫描、评分、工具契约和评测收成一份 HTML 报告和一份 Markdown。

至少给一份输入。报告只整理已有结果，缺的部分不补造。
评分规则与 scripts/score.py 相同，契约检查与 scripts/lint_tools.py 相同，
pass^k 与 scripts/passk.py 相同。扫描读的是 scan_site.py --json 写出的文件，不重新请求网站。
扫描分只统计已经判定的项，未发布和跳过不扣分，也不进入 L0–L5 等级。
报告语言用 --lang（zh en hi es fr ar bn pt ru ur）。省略时读 LC_ALL、LC_MESSAGES、LANG，识别不了用中文。

例：
  python3 scripts/report.py \\
    --scorecard examples/scorecard.sample.json \\
    --tools examples/tools.good.json \\
    --evals examples/eval-results.sample.jsonl \\
    --scan agent-friendly/scan.json \\
    --out agent-friendly
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

import i18n
import lint_tools
import passk
import score

SCAN_ORDER = ("pass", "warn", "fail", "info", "skip")


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"读不了 {path}：{e}") from None


def build_score(path: Path, profile: str | None, gate: str | None) -> dict:
    card = load_json(path)
    if not isinstance(card, dict):
        raise ValueError(f"{path} 须为 JSON 对象")
    scores, notes = score.read_scores(card)
    redlines = score.read_redlines(card)
    profile = profile or card.get("profile") or "default"
    if profile not in score.PROFILES:
        raise ValueError(f"未知行业剖面 {profile}，可选：{', '.join(sorted(score.PROFILES))}")
    failed = [k for k, v in redlines.items() if v == "fail"]
    unverified = [k for k, v in redlines.items() if v == "unverified"]
    redlines_ok = not failed and not unverified
    level = score.compute_level(scores, redlines_ok)
    gate = gate or card.get("target_level")
    accepted = redlines_ok and (gate is None or score.LEVELS.index(level) >= score.LEVELS.index(gate))
    evidence = {}
    for key, entry in (card.get("dimensions") or {}).items():
        if isinstance(entry, dict) and entry.get("evidence"):
            evidence[key] = str(entry["evidence"])
    redline_evidence = {}
    for key, entry in (card.get("redlines") or {}).items():
        if isinstance(entry, dict) and entry.get("evidence"):
            redline_evidence[key] = str(entry["evidence"])
    return {
        "system": card.get("system") or "",
        "profile": profile,
        "scores": scores,
        "evidence": evidence,
        "weighted_score": score.weighted(scores, profile),
        "level": level,
        "level_name": score.LEVEL_NAMES[level],
        "redlines": redlines,
        "redline_evidence": redline_evidence,
        "redlines_failed": failed,
        "redlines_unverified": unverified,
        "target_level": gate,
        "accepted": accepted,
        "gaps": score.next_level_gaps(scores, level, redlines_ok),
        "notes": notes,
    }


def _bucket_score(bucket: dict) -> float | None:
    judged = int(bucket.get("pass", 0)) + int(bucket.get("warn", 0)) + int(bucket.get("fail", 0))
    if judged == 0:
        return None
    points = int(bucket.get("pass", 0)) + int(bucket.get("warn", 0)) * 0.5
    return round(points / judged * 100, 1)


def scan_band(score: float | None, counts: dict) -> str:
    if score is None:
        return "none"
    if counts["fail"] and score < 40:
        return "hard"
    if counts["fail"]:
        return "gaps"
    if score >= 90 and counts["warn"] == 0:
        return "clear"
    if score >= 70:
        return "mostly"
    if score >= 40:
        return "gaps"
    return "hard"


def scan_grade(checks: list) -> dict:
    counts = {s: 0 for s in SCAN_ORDER}
    by_dim: dict[str, dict] = {}
    for check in checks:
        status = check.get("status")
        if status not in counts:
            continue
        counts[status] += 1
        bucket = by_dim.setdefault(check.get("dimension") or "?", {s: 0 for s in SCAN_ORDER})
        bucket[status] += 1
    score = _bucket_score(counts)
    return {
        "score": score,
        "band": scan_band(score, counts),
        "counts": counts,
        "by_dim": {dim: _bucket_score(bucket) for dim, bucket in by_dim.items()},
        "judged": counts["pass"] + counts["warn"] + counts["fail"],
        "aside": counts["info"] + counts["skip"],
    }


def fmt_score(value) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.1f}"


def build_scan(path: Path) -> dict:
    data = load_json(path)
    checks = data.get("checks")
    if not isinstance(checks, list):
        raise ValueError(f"{path} 不是 scan_site.py --json 的输出")
    summary = data.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        for c in checks:
            bucket = summary.setdefault(c.get("dimension") or "?", {s: 0 for s in SCAN_ORDER})
            status = c.get("status")
            if status in SCAN_ORDER:
                bucket[status] = bucket.get(status, 0) + 1
    return {"url": data.get("url") or "", "summary": summary, "checks": checks, "grade": scan_grade(checks)}


def build_lint(path: Path) -> dict:
    data = load_json(path)
    tools = lint_tools.load_tools(data)
    findings = lint_tools.lint(tools)
    counts = {lvl: sum(f.level == lvl for f in findings) for lvl in ("error", "warn", "info")}
    return {
        "tools": len(tools),
        "counts": counts,
        "ok": counts["error"] == 0,
        "findings": [f.__dict__ for f in findings],
    }


def build_evals(path: Path) -> dict:
    rows = passk.load(path)
    if not rows:
        raise ValueError(f"{path} 没有评测记录")
    return passk.summarize(rows, passk.group_tasks(rows))


def pct(value) -> str:
    if value is None:
        return "—"
    return f"{round(float(value) * 100):.0f}%"


def bar(value: float, full: float, tone: str) -> str:
    width = 0 if full <= 0 else max(0, min(100, value / full * 100))
    return (
        f'<span class="track"><span class="fill {tone}" style="width:{width:.1f}%"></span></span>'
        f'<span class="num">{esc(value if isinstance(value, int) else round(value, 2))}</span>'
    )


def stacked(counts: dict, lang: str) -> str:
    total = sum(int(counts.get(s, 0)) for s in SCAN_ORDER)
    if total <= 0:
        return '<span class="track"></span>'
    parts = []
    for status in SCAN_ORDER:
        n = int(counts.get(status, 0))
        if n:
            label = i18n.t(lang, "status." + status)
            parts.append(f'<span class="seg {status}" style="width:{n / total * 100:.1f}%" title="{esc(label)} {n}"></span>')
    return f'<span class="stack">{"".join(parts)}</span><span class="num">{total}</span>'


def columns(pairs: list[tuple[str, float]]) -> str:
    if not pairs:
        return ""
    bars = []
    for label, value in pairs:
        height = max(0, min(100, float(value) * 100))
        bars.append(
            f'<div class="col"><span class="stem" style="height:{height:.1f}%"></span>'
            f'<b>{esc(pct(value))}</b><i>k={esc(label)}</i></div>'
        )
    return f'<div class="cols" role="img" aria-label="pass^k">{"".join(bars)}</div>'


def tr(report: dict, key: str, **kw) -> str:
    return i18n.t(report["lang"], key, **kw)


def grade_fields(model: dict) -> dict:
    grade = model["scan"]["grade"]
    counts = grade["counts"]
    return {
        "score": fmt_score(grade["score"]),
        "band": tr(model, "scan.band." + grade["band"]),
        "judged": grade["judged"],
        "pass_n": counts["pass"],
        "warn": counts["warn"],
        "fail": counts["fail"],
        "aside": grade["aside"],
    }


def hero(model: dict) -> str:
    lang = model["lang"]
    sc = model["score"]
    if sc:
        gate = sc["target_level"]
        gate_html = ""
        if gate:
            mark = tr(model, "reached" if sc["accepted"] else "missed")
            gate_html = f'<span class="pill {"ok" if sc["accepted"] else "bad"}">{esc(tr(model, "target", gate=gate, mark=mark))}</span>'
        return f"""
        <p class="eyebrow">{esc(tr(model, "eyebrow.level"))}</p>
        <div class="hero-row">
          <div><b class="level">{esc(sc["level"])}</b><span class="level-name">{esc(i18n.t(lang, "level." + sc["level"]))}</span></div>
          <div class="metrics">
            <div><b>{esc(sc["weighted_score"])}</b><span>{esc(tr(model, "weighted"))} · {esc(sc["profile"])}</span></div>
            {gate_html}
          </div>
        </div>"""
    scan = model["scan"]
    if scan:
        fields = grade_fields(model)
        return f"""
        <p class="eyebrow">{esc(tr(model, "scan.score"))}</p>
        <div class="hero-row">
          <div><b class="level">{esc(fields["score"])}</b><span class="level-name">{esc(fields["band"])}</span></div>
          <div class="metrics"><div><b>{fields["warn"]}</b><span>{esc(tr(model, "unit.warnings"))}</span></div>
          <div><b>{fields["fail"]}</b><span>{esc(tr(model, "unit.failures"))}</span></div></div>
        </div>
        <p class="deck">{esc(tr(model, "scan.tally", **fields))}</p>"""
    lint = model["lint"]
    if lint:
        word = "PASS" if lint["ok"] else "FAIL"
        return f"""
        <p class="eyebrow">{esc(tr(model, "eyebrow.lint"))}</p>
        <div class="hero-row"><div><b class="level">{word}</b><span class="level-name">{lint["tools"]} {esc(tr(model, "unit.tools"))}</span></div>
        <div class="metrics"><div><b>{lint["counts"]["error"]}</b><span>error</span></div>
        <div><b>{lint["counts"]["warn"]}</b><span>warn</span></div></div></div>"""
    overall = model["evals"]["overall"]
    hat = overall.get("pass_hat") or {}
    first = hat.get(1) if 1 in hat else hat.get("1")
    return f"""
    <p class="eyebrow">{esc(tr(model, "eyebrow.evals"))}</p>
    <div class="hero-row"><div><b class="level">{esc(pct(first))}</b><span class="level-name">pass^1</span></div>
    <div class="metrics"><div><b>{overall.get("tasks", 0)}</b><span>{esc(tr(model, "unit.tasks"))}</span></div>
    <div><b>{overall.get("runs", 0)}</b><span>{esc(tr(model, "unit.runs"))}</span></div></div></div>"""


def redline_name(lang: str, key: str) -> str:
    name = "redline." + key
    return i18n.t(lang, name) if name in i18n.TEXT else i18n.t(lang, "redline.extra")


def check_bits(model: dict, check: dict) -> tuple[str, str, str, str]:
    lang = model["lang"]
    title, message, fix = i18n.localize_check(check, lang)
    status = i18n.t(lang, "status." + check.get("status", ""), ) if "status." + str(check.get("status")) in i18n.TEXT else check.get("status", "")
    return title, status, message, fix


def actions(model: dict) -> str:
    lang = model["lang"]
    items = []
    sc = model["score"]
    if sc:
        for key in sc["redlines_failed"]:
            evidence = sc["redline_evidence"].get(key, "")
            items.append(f"<li><b>{esc(key)} {esc(redline_name(lang, key))} {esc(tr(model, 'failed'))}</b>{('<span>' + esc(evidence) + '</span>') if evidence else ''}</li>")
        for key in sc["redlines_unverified"]:
            items.append(f"<li><b>{esc(key)} {esc(tr(model, 'unverified'))}</b><span>{esc(tr(model, 'unverified.detail'))}</span></li>")
        for gap in sc["gaps"]:
            items.append(f"<li><b>{esc(tr(model, 'gap.label'))}</b><span>{esc(i18n.gap(lang, gap))}</span></li>")
        for note in sc["notes"]:
            items.append(f"<li><b>{esc(tr(model, 'note.label'))}</b><span>{esc(i18n.note(lang, note))}</span></li>")
    scan = model["scan"]
    if scan:
        bad = [c for c in scan["checks"] if c.get("status") in ("fail", "warn")]
        for c in bad[:6]:
            title, status, message, fix = check_bits(model, c)
            fix_html = (" " + esc(tr(model, "md.suggest", fix=fix))) if fix else ""
            items.append(f"<li><b>{esc(title)}</b><span>{esc(status)}. {esc(message)}{fix_html}</span></li>")
        if len(bad) > 6:
            items.append(f"<li><b>{esc(tr(model, 'more.scan', n=len(bad) - 6))}</b><span>{esc(tr(model, 'more.detail'))}</span></li>")
    lint = model["lint"]
    if lint:
        errors = [f for f in lint["findings"] if f["level"] == "error"]
        for f in errors[:6]:
            items.append(f"<li><b>{esc(f['tool'])}</b><span>{esc(f['rule'])} {esc(i18n.translate_phrase(f['message'], lang))}</span></li>")
        if len(errors) > 6:
            items.append(f"<li><b>{esc(tr(model, 'more.lint', n=len(errors) - 6))}</b><span>{esc(tr(model, 'more.detail'))}</span></li>")
    if not items:
        return f"<p class='quiet'>{esc(tr(model, 'next.none'))}</p>"
    return "<ol class='actions'>" + "".join(items) + "</ol>"


def score_section(model: dict, idx: str) -> str:
    sc = model["score"]
    lang = model["lang"]
    rows = []
    blocking = {g.split()[0] for g in sc["gaps"] if g.startswith("D")}
    for key in score.DIMENSIONS:
        value = sc["scores"][key]
        tone = "bad" if key in blocking else "ink"
        evidence = sc["evidence"].get(key, "")
        rows.append(
            f"<tr><th>{esc(key)}</th><td>{esc(i18n.t(lang, 'dim.' + key))}</td><td class='chart'>{bar(value, 4, tone)}</td>"
            f"<td class='muted'>{esc(evidence)}</td></tr>"
        )
    cells = []
    for key, status in sc["redlines"].items():
        cells.append(
            f"<li class='{esc(status)}'><b>{esc(key)}</b><span>{esc(redline_name(lang, key))}</span>"
            f"<i>{esc(i18n.t(lang, 'status.' + status) if 'status.' + status in i18n.TEXT else status)}</i></li>"
        )
    return f"""
    <section id="score">
      <p class="idx">{idx}</p><h2>{esc(tr(model, "score.title"))}</h2>
      <p class="deck">{esc(tr(model, "score.deck"))}</p>
      <table class="bars"><tbody>{''.join(rows)}</tbody></table>
      <h3>{esc(tr(model, "score.redlines"))}</h3>
      <ul class="redlines">{''.join(cells)}</ul>
    </section>"""


def scan_section(model: dict, idx: str) -> str:
    scan = model["scan"]
    lang = model["lang"]
    rows = []
    for dim in sorted(scan["summary"]):
        counts = scan["summary"][dim]
        bits = " · ".join(
            f"{i18n.t(lang, 'status.' + s)} {int(counts.get(s, 0))}" for s in SCAN_ORDER if int(counts.get(s, 0))
        )
        dim_score = scan["grade"]["by_dim"].get(dim)
        mark = tr(model, "scan.excluded") if dim_score is None else fmt_score(dim_score)
        bits = f"{mark} · {bits}" if bits else mark
        rows.append(f"<tr><th>{esc(dim)}</th><td class='chart'>{stacked(counts, lang)}</td><td class='muted'>{esc(bits)}</td></tr>")
    details = []
    for c in scan["checks"]:
        title, status, message, fix = check_bits(model, c)
        fix_html = f"<span class='fix'>{esc(fix)}</span>" if fix and c.get("status") in ("fail", "warn") else ""
        details.append(
            f"<li class='{esc(c.get('status'))}'><b>{esc(title)}</b><i>{esc(status)}</i><span>{esc(message)}</span>{fix_html}</li>"
        )
    url = f"<p class='deck'>{esc(scan['url'])}</p>" if scan.get("url") else ""
    legend = " ".join(
        f"<i class='{s}'></i>{esc(i18n.t(lang, 'status.' + s))}" for s in SCAN_ORDER
    )
    fields = grade_fields(model)
    grade_html = ""
    if model["score"]:
        grade_html = (
            f"<div class='scan-grade'><b>{esc(fields['score'])}</b><div>"
            f"<strong>{esc(tr(model, 'scan.score'))} · {esc(fields['band'])}</strong>"
            f"<span>{esc(tr(model, 'scan.tally', **fields))}</span></div></div>"
        )
    return f"""
    <section id="scan">
      <p class="idx">{idx}</p><h2>{esc(tr(model, "scan.title"))}</h2>
      {url}
      {grade_html}
      <p class="deck">{esc(tr(model, "scan.deck"))}</p>
      <p class="legend">{legend}</p>
      <table class="bars"><tbody>{''.join(rows)}</tbody></table>
      <details><summary>{esc(tr(model, "scan.all"))}</summary><ol class="findings">{''.join(details)}</ol></details>
    </section>"""


def lint_section(model: dict, idx: str) -> str:
    lint = model["lint"]
    lang = model["lang"]
    order = {"error": 0, "warn": 1, "info": 2}
    findings = sorted(lint["findings"], key=lambda f: (order[f["level"]], f["tool"], f["rule"]))

    def items(rows: list) -> str:
        return "".join(
            f"<li class='{esc(f['level'])}'><b>{esc(f['tool'])}</b><i>{esc(f['level'])} {esc(f['rule'])}</i>"
            f"<span>{esc(i18n.translate_phrase(f['message'], lang))}</span></li>"
            for f in rows
        )

    shown = [f for f in findings if f["level"] != "info"]
    hidden = [f for f in findings if f["level"] == "info"]
    extra = f"<details><summary>{esc(tr(model, 'lint.info', n=len(hidden)))}</summary><ol class='findings'>{items(hidden)}</ol></details>" if hidden else ""
    word = tr(model, "lint.ok" if lint["ok"] else "lint.bad")
    deck = tr(model, "lint.deck", tools=lint["tools"], error=lint["counts"]["error"], warn=lint["counts"]["warn"], info=lint["counts"]["info"], word=word)
    return f"""
    <section id="lint">
      <p class="idx">{idx}</p><h2>{esc(tr(model, "lint.title"))}</h2>
      <p class="deck">{esc(deck)}</p>
      <ol class="findings">{items(shown) or '<li><span>' + esc(tr(model, 'lint.none')) + '</span></li>'}</ol>
      {extra}
    </section>"""


def eval_section(report: dict, idx: str) -> str:
    summary = report["evals"]
    overall = summary["overall"]
    hat = overall.get("pass_hat") or {}
    pairs = [(str(k), hat[k]) for k in sorted(hat, key=lambda x: int(x))]
    blocks = [(tr(report, "eval.all"), overall)]
    for risk, block in summary.get("by_risk", {}).items():
        blocks.append((tr(report, "eval.risk", risk=risk), block))
    for name, block in summary.get("by_model", {}).items():
        blocks.append((tr(report, "eval.model", model=name), block))
    cards = []
    for title, block in blocks:
        local = block.get("pass_hat") or {}
        k1 = local.get(1) if 1 in local else local.get("1")
        last_key = max(local, key=lambda x: int(x)) if local else None
        meta = tr(report, "eval.meta", tasks=block.get("tasks", 0), runs=block.get("runs", 0), rate=pct(block.get("unsafe_rate")))
        cards.append(
            f"<article><h3>{esc(title)}</h3><b>{esc(pct(k1))}</b><span>pass^1"
            f"{(' → ' + esc(pct(local[last_key])) + ' pass^' + esc(last_key)) if last_key and str(last_key) != '1' else ''}</span>"
            f"<i>{esc(meta)}</i></article>"
        )
    extra = []
    sep = tr(report, "sep")
    if summary.get("unstable_tasks"):
        extra.append("<p>" + esc(tr(report, "eval.unstable") + sep + sep.join(summary["unstable_tasks"])) + "</p>")
    if summary.get("unsafe_tasks"):
        extra.append("<p>" + esc(tr(report, "eval.unsafe") + sep + sep.join(summary["unsafe_tasks"])) + "</p>")
    return f"""
    <section id="evals">
      <p class="idx">{idx}</p><h2>{esc(tr(report, "eval.title"))}</h2>
      <p class="deck">{esc(tr(report, "eval.deck"))}</p>
      {columns(pairs)}
      <div class="cards">{''.join(cards)}</div>
      {''.join(extra)}
    </section>"""


def render_html(model: dict) -> str:
    lang = model["lang"]
    nav = [
        f'<a href="#top">{esc(tr(model, "nav.top"))}</a>',
        f'<a href="#next">{esc(tr(model, "nav.next"))}</a>',
    ]
    body = []
    n = 1

    def idx() -> str:
        nonlocal n
        text = f"{n:02d}"
        n += 1
        return text

    if model["score"]:
        nav.append(f'<a href="#score">{esc(tr(model, "nav.score"))}</a>')
        body.append(score_section(model, idx()))
    if model["scan"]:
        nav.append(f'<a href="#scan">{esc(tr(model, "nav.scan"))}</a>')
        body.append(scan_section(model, idx()))
    if model["lint"]:
        nav.append(f'<a href="#lint">{esc(tr(model, "nav.lint"))}</a>')
        body.append(lint_section(model, idx()))
    if model["evals"]:
        nav.append(f'<a href="#evals">{esc(tr(model, "nav.evals"))}</a>')
        body.append(eval_section(model, idx()))
    included = " · ".join(i18n.t(lang, "included." + code) for code in model["included"])
    direction = ' dir="rtl"' if lang in i18n.RTL else ""
    return """<!DOCTYPE html>
<html lang=\"""" + i18n.HTML_LANG[lang] + "\"" + direction + """>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>""" + esc(model["title"]) + """ · agent-friendly</title>
<style>""" + CSS + """</style>
</head>
<body>
<header class="top"><span>agent-friendly</span><nav>""" + "".join(nav) + """</nav></header>
<main id="top">
  <p class="kicker">""" + esc(tr(model, "kicker")) + """ · <span dir="ltr">""" + esc(model["generated"]) + "</span> · " + esc(included) + """</p>
  <h1>""" + esc(model["title"]) + """</h1>
  <section class="verdict">""" + hero(model) + """</section>
  <section id="next">
    <p class="idx">00</p><h2>""" + esc(tr(model, "next.title")) + """</h2>
    <p class="deck">""" + esc(tr(model, "next.deck" if model["score"] or not model["scan"] else "next.deck.scan")) + """</p>
    """ + actions(model) + """
  </section>
  """ + "".join(body) + """
  <footer>""" + esc(tr(model, "footer")) + """</footer>
</main>
</body>
</html>
"""


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in row) + " |" for row in rows]
    return "\n".join([line, rule, *body])


def render_md(model: dict) -> str:
    lang = model["lang"]
    sep = i18n.t(lang, "sep")
    stop = "。" if lang == "zh" else "।" if lang in {"hi", "bn"} else "۔" if lang == "ur" else "."
    included = sep.join(i18n.t(lang, "included." + code) for code in model["included"])
    lines = [
        f"# {model['title']}",
        "",
        tr(model, "md.generated", when=model["generated"]),
        "",
        tr(model, "md.included", items=included),
        "",
    ]
    sc = model["score"]

    def scan_bullets(checks: list) -> list[str]:
        rows = []
        for c in checks:
            if c.get("status") not in ("fail", "warn"):
                continue
            title, status, message, fix = check_bits(model, c)
            suggestion = (" " + tr(model, "md.suggest", fix=fix)) if fix else ""
            rows.append(f"- {title}{sep}{status}. {message}{suggestion}")
        return rows

    if sc:
        gate = ""
        if sc["target_level"]:
            mark = tr(model, "reached" if sc["accepted"] else "missed")
            gate = tr(model, "md.gate", gate=sc["target_level"], mark=mark)
        level_name = i18n.t(lang, "level." + sc["level"])
        lines += [
            tr(model, "md.level", level=sc["level"], name=level_name, score=sc["weighted_score"], profile=sc["profile"], gate=gate) + stop,
            "",
            "## " + tr(model, "next.title"),
            "",
        ]
        bullets = []
        for key in sc["redlines_failed"]:
            bullets.append(f"- {key} {redline_name(lang, key)} {tr(model, 'failed')}{stop}{sc['redline_evidence'].get(key, '')}")
        for key in sc["redlines_unverified"]:
            bullets.append(f"- {key} {tr(model, 'unverified')}{stop}")
        bullets += [f"- {tr(model, 'gap.label')}{sep}{i18n.gap(lang, g)}" for g in sc["gaps"]]
        bullets += [f"- {i18n.note(lang, n)}" for n in sc["notes"]]
        if model["scan"]:
            bullets += scan_bullets(model["scan"]["checks"])
        lines += (bullets or ["- " + tr(model, "next.none")]) + ["", "## " + tr(model, "score.title"), ""]
        lines.append(md_table([tr(model, "md.dim"), tr(model, "md.points"), tr(model, "md.evidence")], [
            [f"{k} {i18n.t(lang, 'dim.' + k)}", str(sc["scores"][k]), sc["evidence"].get(k, "")]
            for k in score.DIMENSIONS
        ]))
        lines += ["", "## " + tr(model, "score.redlines"), ""]
        lines.append(md_table([tr(model, "md.redline"), tr(model, "md.status"), tr(model, "md.evidence")], [
            [f"{k} {redline_name(lang, k)}", i18n.t(lang, "status." + v) if "status." + v in i18n.TEXT else v, sc["redline_evidence"].get(k, "")]
            for k, v in sc["redlines"].items()
        ]))
        lines.append("")
    else:
        lead = scan_bullets(model["scan"]["checks"]) if model["scan"] else []
        if model["lint"]:
            for f in model["lint"]["findings"]:
                if f["level"] == "error":
                    lead.append(f"- {f['tool']}{sep}{f['rule']} {i18n.translate_phrase(f['message'], lang)}")
        if model["scan"]:
            lines += [tr(model, "scan.line", **grade_fields(model)), "", tr(model, "scan.deck"), ""]
        lines += ["## " + tr(model, "next.title"), ""]
        lines += (lead or ["- " + tr(model, "next.none")]) + [""]
    scan = model["scan"]
    if scan:
        lines += ["## " + tr(model, "scan.title"), ""]
        if scan.get("url"):
            lines += [scan["url"], ""]
        if sc:
            lines += [tr(model, "scan.line", **grade_fields(model)), "", tr(model, "scan.deck"), ""]
        lines += [md_table(
            [tr(model, "md.dim"), tr(model, "md.pass"), tr(model, "md.warn"), tr(model, "md.fail"), tr(model, "md.info"), tr(model, "md.skip")],
            [[dim, *[str(int(scan["summary"][dim].get(s, 0))) for s in SCAN_ORDER]] for dim in sorted(scan["summary"])],
        ), ""]
    lint = model["lint"]
    if lint:
        word = tr(model, "lint.ok" if lint["ok"] else "lint.bad")
        lines += [
            "## " + tr(model, "lint.title"),
            "",
            tr(model, "lint.deck", tools=lint["tools"], error=lint["counts"]["error"], warn=lint["counts"]["warn"], info=lint["counts"]["info"], word=word),
            "",
        ]
        for f in lint["findings"]:
            lines.append(f"- [{f['level']}] {f['rule']} {f['tool']}{sep}{i18n.translate_phrase(f['message'], lang)}")
        lines.append("")
    summary = model["evals"]
    if summary:
        lines += ["## " + tr(model, "eval.title"), ""]
        overall = summary["overall"]
        hat = overall.get("pass_hat") or {}
        bits = sep.join(f"pass^{k} {pct(hat[k])}" for k in sorted(hat, key=lambda x: int(x)))
        lines.append(tr(model, "eval.all") + sep + bits)
        if summary.get("unstable_tasks"):
            lines += ["", tr(model, "eval.unstable") + sep + sep.join(summary["unstable_tasks"])]
        if summary.get("unsafe_tasks"):
            lines += ["", tr(model, "eval.unsafe") + sep + sep.join(summary["unsafe_tasks"])]
        lines.append("")
    lines += [tr(model, "footer"), ""]
    return "\n".join(lines)


CSS = """
:root { --paper:#EFEAE2; --card:#F7F4EE; --ink:#1C1915; --muted:#6E675F; --line:#DDD6CB; --bad:#B03A1E; --ok:#1E4D3A; --warn:#8A5A12; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 "Avenir Next","PingFang SC","Hiragino Sans GB",sans-serif; }
.top { position:sticky; top:0; z-index:2; display:flex; justify-content:space-between; gap:24px; align-items:center;
  padding:14px 28px; background:rgba(239,234,226,.92); border-bottom:1px solid var(--line); backdrop-filter:blur(8px); }
.top span { font:600 12px/1 "Helvetica Neue",sans-serif; letter-spacing:.22em; text-transform:uppercase; }
.top nav { display:flex; gap:18px; }
.top a { color:var(--muted); text-decoration:none; font-size:13px; }
.top a:hover { color:var(--ink); }
main { width:min(980px, calc(100% - 40px)); margin:0 auto; padding:36px 0 72px; }
.kicker { margin:0; font:600 12px/1.4 "Helvetica Neue",sans-serif; letter-spacing:.16em; text-transform:uppercase; color:var(--bad); }
h1 { margin:10px 0 22px; font:700 34px/1.25 "Songti SC","Iowan Old Style","Kohinoor Devanagari","Noto Sans Devanagari","Bangla Sangam MN","Noto Sans Bengali","Geeza Pro","Noto Naskh Arabic",serif; letter-spacing:.01em; }
h2 { margin:0 0 6px; font:700 26px/1.3 "Songti SC","Iowan Old Style","Kohinoor Devanagari","Noto Sans Devanagari","Bangla Sangam MN","Noto Sans Bengali","Geeza Pro","Noto Naskh Arabic",serif; }
h3 { margin:22px 0 10px; font-size:15px; letter-spacing:.04em; }
.idx { margin:0; font:600 12px/1 "Helvetica Neue",sans-serif; letter-spacing:.18em; color:var(--bad); }
.deck, .quiet { color:var(--muted); margin:0 0 16px; }
.verdict, section { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:22px 24px 20px; margin:0 0 14px; }
.scan-grade { display:flex; gap:18px; align-items:flex-start; margin:0 0 8px; }
.scan-grade b { font:700 42px/0.9 "Songti SC","Iowan Old Style","Kohinoor Devanagari","Noto Sans Devanagari","Bangla Sangam MN","Noto Sans Bengali","Geeza Pro","Noto Naskh Arabic",serif; }
.scan-grade strong { display:block; }
.scan-grade span { display:block; color:var(--muted); font-size:13px; }
.hero-row { display:flex; justify-content:space-between; gap:24px; align-items:flex-end; }
.level { font:700 84px/0.85 "Songti SC","Iowan Old Style","Kohinoor Devanagari","Noto Sans Devanagari","Bangla Sangam MN","Noto Sans Bengali","Geeza Pro","Noto Naskh Arabic",serif; letter-spacing:-.03em; }
.level-name { display:block; margin-top:8px; font-size:18px; }
.metrics { display:flex; gap:22px; align-items:flex-end; text-align:right; }
.metrics b { display:block; font:700 28px/1 "Songti SC","Iowan Old Style","Kohinoor Devanagari","Noto Sans Devanagari","Bangla Sangam MN","Noto Sans Bengali","Geeza Pro","Noto Naskh Arabic",serif; }
.metrics span { color:var(--muted); font-size:13px; }
.pill { align-self:center; border-radius:999px; padding:6px 12px; font-size:13px; font-weight:600; }
.pill.ok { color:var(--ok); background:#E5EFE9; }
.pill.bad { color:var(--bad); background:#F6E6E1; }
.eyebrow { margin:0 0 8px; color:var(--muted); font-size:13px; letter-spacing:.08em; }
ol.actions { margin:0; padding:0; list-style:none; }
ol.actions li { display:grid; grid-template-columns:220px 1fr; gap:16px; padding:12px 0; border-top:1px solid var(--line); }
ol.actions li:first-child { border-top:0; }
ol.actions span, .muted { color:var(--muted); }
table.bars { width:100%; border-collapse:collapse; }
table.bars th { width:48px; text-align:left; font:600 13px/1.2 "Helvetica Neue",sans-serif; padding-right:8px; }
table.bars td { padding:8px 0; vertical-align:middle; }
table.bars td:nth-child(2) { width:190px; padding-right:16px; }
table.bars td.chart { width:250px; }
table.bars td.muted { padding-left:18px; }
.chart { display:flex; align-items:center; gap:12px; }
.track, .stack { width:180px; flex:none; height:10px; background:#E7E1D7; border-radius:99px; overflow:hidden; display:flex; }
.fill { display:block; height:100%; border-radius:99px; }
.fill.ink { background:var(--ink); }
.fill.bad { background:var(--bad); }
.seg { display:block; height:100%; }
.seg.pass { background:var(--ok); } .seg.warn { background:#C4842A; } .seg.fail { background:var(--bad); }
.seg.info { background:#C8C0B4; } .seg.skip { background:#E4DDD3; }
.num { width:42px; text-align:right; font:600 13px/1 "Helvetica Neue",sans-serif; }
.legend { display:flex; gap:14px; align-items:center; color:var(--muted); font-size:13px; }
.legend i { width:10px; height:10px; border-radius:2px; display:inline-block; }
ul.redlines { display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; margin:0; padding:0; list-style:none; }
ul.redlines li { border:1px solid var(--line); border-radius:10px; padding:10px 12px; display:grid; grid-template-columns:auto 1fr; gap:2px 8px; }
ul.redlines b { font:600 13px/1.2 "Helvetica Neue",sans-serif; }
ul.redlines span { grid-column:1 / -1; font-size:13px; }
ul.redlines i { font-style:normal; font-size:12px; color:var(--muted); }
ul.redlines li.fail { border-color:#E4C2B8; background:#FBF4F2; }
ul.redlines li.fail i { color:var(--bad); }
ul.redlines li.pass i { color:var(--ok); }
ol.findings { margin:0; padding:0; list-style:none; }
ol.findings li { padding:10px 0; border-top:1px solid var(--line); display:grid; grid-template-columns:180px 1fr; gap:4px 16px; }
ol.findings li:first-child { border-top:0; }
ol.findings i { font-style:normal; color:var(--muted); font-size:13px; }
ol.findings span, ol.findings .fix { grid-column:2; }
ol.findings .fix { color:var(--ink); }
ol.findings li.error b, ol.findings li.fail b { color:var(--bad); }
ol.findings li.warn b { color:var(--warn); }
details summary { cursor:pointer; color:var(--muted); margin-top:8px; }
.cols { display:flex; align-items:flex-end; gap:14px; height:160px; margin:8px 0 18px; }
.col { flex:1; display:flex; flex-direction:column; justify-content:flex-end; align-items:center; height:100%; }
.stem { width:100%; max-width:36px; background:var(--ink); border-radius:5px 5px 0 0; min-height:2px; }
.col b { margin-top:8px; font-size:13px; }
.col i { font-style:normal; color:var(--muted); font-size:12px; }
.cards { display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; }
.cards article { border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
.cards h3 { margin:0; font-size:13px; color:var(--muted); font-weight:600; }
.cards b { display:block; margin-top:6px; font:700 22px/1 "Songti SC","Iowan Old Style","Kohinoor Devanagari","Noto Sans Devanagari","Bangla Sangam MN","Noto Sans Bengali","Geeza Pro","Noto Naskh Arabic",serif; }
.cards span, .cards i { display:block; color:var(--muted); font-size:12px; font-style:normal; }
footer { color:var(--muted); font-size:13px; padding:8px 4px 0; }
.chart, .cols, .num, .level, .scan-grade b { unicode-bidi:isolate; }
html[dir="rtl"] .chart, html[dir="rtl"] .cols, html[dir="rtl"] .num, html[dir="rtl"] .level, html[dir="rtl"] .scan-grade b { direction:ltr; }
@media (max-width:720px) {
  .hero-row, ol.actions li, ol.findings li, .cards, ul.redlines { display:block; }
  ul.redlines li, .cards article { margin-bottom:8px; }
  .level { font-size:64px; }
  .top nav { display:none; }
  .metrics { text-align:left; margin-top:12px; }
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 agent 友好化 HTML 报告和 Markdown")
    ap.add_argument("--scorecard", type=Path, help="评分卡 JSON，算法同 score.py")
    ap.add_argument("--profile", choices=sorted(score.PROFILES), help="行业剖面，覆盖评分卡里的 profile")
    ap.add_argument("--gate", choices=score.LEVELS, help="要求达到的等级，覆盖评分卡里的 target_level")
    ap.add_argument("--scan", type=Path, help="scan_site.py --json 的输出")
    ap.add_argument("--tools", type=Path, help="MCP tools/list、工具数组或 OpenAPI 3.x")
    ap.add_argument("--evals", type=Path, help="评测 JSONL，算法同 passk.py")
    ap.add_argument("--out", type=Path, default=Path("agent-friendly-report"), help="输出目录，默认 ./agent-friendly-report")
    ap.add_argument("--lang", help="报告语言：zh en hi es fr ar bn pt ru ur。省略时读 LC_ALL、LC_MESSAGES、LANG，读不到用中文")
    args = ap.parse_args()

    try:
        lang = i18n.resolve(args.lang)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not any((args.scorecard, args.scan, args.tools, args.evals)):
        print("至少给一份输入：--scorecard、--scan、--tools、--evals", file=sys.stderr)
        return 2
    try:
        sc = build_score(args.scorecard, args.profile, args.gate) if args.scorecard else None
        scan_data = build_scan(args.scan) if args.scan else None
        lint = build_lint(args.tools) if args.tools else None
        evals = build_evals(args.evals) if args.evals else None
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 2

    included = []
    if sc:
        included.append("score")
    if scan_data:
        included.append("scan")
    if lint:
        included.append("lint")
    if evals:
        included.append("evals")
    title = (sc or {}).get("system") or (scan_data or {}).get("url") or "agent-friendly"
    model = {
        "lang": lang,
        "title": title,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "included": included,
        "score": sc,
        "scan": scan_data,
        "lint": lint,
        "evals": evals,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    html_path = args.out / "report.html"
    md_path = args.out / "report.md"
    html_path.write_text(render_html(model), encoding="utf-8")
    md_path.write_text(render_md(model), encoding="utf-8")
    print(html_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
