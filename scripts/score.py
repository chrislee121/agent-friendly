#!/usr/bin/env python3
"""根据评分卡计算 agent 友好等级、红线结论和加权分。

规则见 references/scorecard.md：等级逐级判门槛；任一红线不过，等级最多 L2。
设了 --gate 时，未达到指定等级 exit 1。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DIMENSIONS = {
    "D1": "可发现",
    "D2": "可理解",
    "D3": "可操作",
    "D4": "身份与授权",
    "D5": "人的控制",
    "D6": "可靠性",
    "D7": "安全",
    "D8": "可追溯与合规",
    "D9": "评测与运营",
}
REDLINES = {
    "H1": "越权",
    "H2": "令牌受众与透传",
    "H3": "R3 无确认",
    "H4": "致命三角",
    "H5": "审计与撤销",
    "H6": "可见与 AI 身份",
    "H7": "数据超范围",
    "H8": "重复执行",
}
LEVELS = ["L0", "L1", "L2", "L3", "L4", "L5"]
LEVEL_NAMES = {"L0": "不可用", "L1": "可读", "L2": "可查询", "L3": "可代办", "L4": "可托付", "L5": "原生"}
PROFILES = {
    "default": {},
    "commerce": {"D3": 1.5, "D5": 1.5, "D6": 1.5},
    "finance": {"D4": 1.5, "D5": 1.5, "D7": 1.5, "D8": 1.5},
    "health": {"D4": 1.5, "D5": 1.5, "D7": 1.5, "D8": 2},
    "travel": {"D3": 1.5, "D5": 1.5, "D6": 1.5},
    "content": {"D1": 1.5, "D2": 2, "D8": 1.5},
    "saas": {"D3": 1.5, "D4": 1.5, "D6": 1.5},
    "gov": {"D2": 1.5, "D4": 1.5, "D8": 2},
    "education": {"D5": 1.5, "D7": 1.5, "D8": 1.5},
    "iot": {"D5": 2, "D6": 1.5, "D7": 1.5},
    "enterprise": {"D4": 1.5, "D7": 1.5, "D8": 1.5},
}


def read_scores(card: dict) -> tuple[dict[str, int], list[str]]:
    scores, notes = {}, []
    dims = card.get("dimensions") or {}
    for key in DIMENSIONS:
        entry = dims.get(key)
        if entry is None:
            scores[key] = 0
            notes.append(f"{key} 缺失，按 0 分计")
            continue
        score = entry.get("score") if isinstance(entry, dict) else entry
        evidence = entry.get("evidence") if isinstance(entry, dict) else None
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 4:
            raise ValueError(f"{key} 的 score 须为 0～4 的整数")
        if score > 0 and not (evidence and str(evidence).strip()):
            notes.append(f"{key} 没有证据，按 0 分计")
            score = 0
        scores[key] = score
    return scores, notes


def read_redlines(card: dict) -> dict[str, str]:
    lines = card.get("redlines") or {}
    result = {}
    for key in list(REDLINES) + [k for k in lines if k not in REDLINES]:
        entry = lines.get(key)
        status = (entry.get("status") if isinstance(entry, dict) else entry) or "unverified"
        status = str(status).lower()
        if status not in {"pass", "fail", "na", "unverified"}:
            raise ValueError(f"{key} 的 status 须为 pass / fail / na / unverified")
        if status == "na" and not (isinstance(entry, dict) and str(entry.get("evidence") or "").strip()):
            status = "unverified"
        result[key] = status
    return result


def compute_level(s: dict[str, int], redlines_ok: bool) -> str:
    level = "L0"
    if s["D1"] >= 2 and s["D2"] >= 2:
        level = "L1"
    else:
        return level
    if s["D3"] >= 2 and s["D6"] >= 2 and s["D7"] >= 2 and s["D9"] >= 1:
        level = "L2"
    else:
        return level
    if not redlines_ok:
        return level
    if s["D4"] >= 3 and s["D5"] >= 3 and s["D8"] >= 2 and s["D9"] >= 2:
        level = "L3"
    else:
        return level
    if all(v >= 3 for v in s.values()) and s["D5"] == 4 and s["D7"] == 4 and s["D9"] == 4:
        level = "L4"
    else:
        return level
    if all(v == 4 for v in s.values()):
        level = "L5"
    return level


def next_level_gaps(s: dict[str, int], level: str, redlines_ok: bool) -> list[str]:
    need = {
        "L1": {"D1": 2, "D2": 2},
        "L2": {"D3": 2, "D6": 2, "D7": 2, "D9": 1},
        "L3": {"D4": 3, "D5": 3, "D8": 2, "D9": 2},
        "L4": {**{k: 3 for k in DIMENSIONS}, "D5": 4, "D7": 4, "D9": 4},
        "L5": {k: 4 for k in DIMENSIONS},
    }
    if level == "L5":
        return []
    target = LEVELS[LEVELS.index(level) + 1]
    gaps = [f"{k} {DIMENSIONS[k]}：{s[k]} → {v}" for k, v in need[target].items() if s[k] < v]
    if target == "L3" and not redlines_ok:
        gaps.append("红线未全部通过")
    return gaps


def weighted(s: dict[str, int], profile: str) -> float:
    w = {k: PROFILES[profile].get(k, 1) for k in DIMENSIONS}
    return round(sum(s[k] * w[k] for k in DIMENSIONS) / sum(4 * w[k] for k in DIMENSIONS) * 100, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description="计算 agent 友好评分卡")
    ap.add_argument("file", help="评分卡 JSON")
    ap.add_argument("--profile", choices=sorted(PROFILES), help="行业剖面，覆盖文件里的 profile")
    ap.add_argument("--gate", choices=LEVELS, help="要求达到的等级")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    try:
        card = json.loads(Path(args.file).read_text(encoding="utf-8"))
        scores, notes = read_scores(card)
        redlines = read_redlines(card)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 2

    profile = args.profile or card.get("profile") or "default"
    if profile not in PROFILES:
        print(f"未知行业剖面 {profile}，可选：{', '.join(sorted(PROFILES))}", file=sys.stderr)
        return 2

    failed = [k for k, v in redlines.items() if v == "fail"]
    unverified = [k for k, v in redlines.items() if v == "unverified"]
    redlines_ok = not failed and not unverified
    level = compute_level(scores, redlines_ok)
    gate = args.gate or card.get("target_level")
    gate_ok = gate is None or LEVELS.index(level) >= LEVELS.index(gate)
    accepted = redlines_ok and gate_ok
    result = {
        "system": card.get("system", ""),
        "profile": profile,
        "scores": scores,
        "weighted_score": weighted(scores, profile),
        "level": level,
        "level_name": LEVEL_NAMES[level],
        "redlines": redlines,
        "redlines_failed": failed,
        "redlines_unverified": unverified,
        "target_level": gate,
        "accepted": accepted,
        "gaps_to_next_level": next_level_gaps(scores, level, redlines_ok),
        "notes": notes,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"# 评分卡：{result['system'] or '未命名系统'}（剖面 {profile}）\n")
        print("| 维度 | 分 |\n|---|---|")
        for k, name in DIMENSIONS.items():
            print(f"| {k} {name} | {scores[k]} |")
        print("\n| 红线 | 状态 |\n|---|---|")
        for k, v in redlines.items():
            print(f"| {k} {REDLINES.get(k, '项目追加')} | {v} |")
        print(f"\n等级：**{level} {LEVEL_NAMES[level]}**　加权分：{result['weighted_score']}")
        if failed:
            print(f"红线未通过：{'、'.join(failed)}（等级封顶 L2）")
        if unverified:
            print(f"红线未验证：{'、'.join(unverified)}（视同未通过）")
        if result["gaps_to_next_level"]:
            print("升到下一级还差：")
            for g in result["gaps_to_next_level"]:
                print(f"  - {g}")
        for n in notes:
            print(f"注意：{n}")
        if gate:
            print(f"\n目标 {gate}：" + ("PASS" if accepted else "FAIL"))
        else:
            print("\n验收：" + ("PASS" if accepted else "FAIL"))
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
