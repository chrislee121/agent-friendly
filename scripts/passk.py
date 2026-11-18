#!/usr/bin/env python3
"""从 agent 评测结果计算 pass^k、pass@k 和不安全动作率。

输入 JSONL，每行一次运行：
  {"task_id": "...", "success": true, "risk": "R2", "unsafe": false,
   "model": "...", "tool_calls": 3, "tokens": 4200, "latency_ms": 5100, "confirmations": 1}

pass^k 按 τ-bench 的无偏估计：每个任务 C(c,k)/C(n,k)，再对任务求平均。
设了 --gate 或 --max-unsafe 时，不达标 exit 1。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

RISKS = ("R0", "R1", "R2", "R3")


def load(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        if "task_id" not in row or "success" not in row:
            raise ValueError(f"第 {i} 行缺少 task_id 或 success")
        row.setdefault("risk", "R0")
        rows.append(row)
    return rows


def group_tasks(rows: list[dict]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for r in rows:
        t = tasks.setdefault(r["task_id"], {"risk": r["risk"], "n": 0, "c": 0, "unsafe": 0})
        t["n"] += 1
        t["c"] += 1 if r["success"] else 0
        t["unsafe"] += 1 if r.get("unsafe") else 0
        if RISKS.index(r["risk"]) > RISKS.index(t["risk"]):
            t["risk"] = r["risk"]
    return tasks


def pass_hat_k(tasks: list[dict], k: int) -> float | None:
    eligible = [t for t in tasks if t["n"] >= k]
    if not eligible or len(eligible) < len(tasks):
        return None
    return sum(comb(t["c"], k) / comb(t["n"], k) for t in eligible) / len(eligible)


def pass_at_k(tasks: list[dict], k: int) -> float | None:
    if not tasks or any(t["n"] < k for t in tasks):
        return None
    return sum(1 - comb(t["n"] - t["c"], k) / comb(t["n"], k) for t in tasks) / len(tasks)


def summarize(rows: list[dict], tasks: dict[str, dict]) -> dict:
    def block(task_list: list[dict], run_list: list[dict]) -> dict:
        if not task_list:
            return {}
        max_k = min(t["n"] for t in task_list)
        mean = lambda key: (sum(r[key] for r in run_list if key in r) / max(1, sum(key in r for r in run_list))
                            if any(key in r for r in run_list) else None)
        return {
            "tasks": len(task_list),
            "runs": len(run_list),
            "min_trials": max_k,
            "pass_hat": {k: round(pass_hat_k(task_list, k), 4) for k in range(1, max_k + 1)},
            "pass_at": {k: round(pass_at_k(task_list, k), 4) for k in range(1, max_k + 1)},
            "consistent": sum(t["c"] == t["n"] for t in task_list),
            "inconsistent": sum(0 < t["c"] < t["n"] for t in task_list),
            "never": sum(t["c"] == 0 for t in task_list),
            "unsafe_runs": sum(t["unsafe"] for t in task_list),
            "unsafe_rate": round(sum(t["unsafe"] for t in task_list) / len(run_list), 4),
            "mean_tool_calls": mean("tool_calls"),
            "mean_tokens": mean("tokens"),
            "mean_confirmations": mean("confirmations"),
        }

    result = {"overall": block(list(tasks.values()), rows), "by_risk": {}, "by_model": {}}
    for risk in RISKS:
        ids = {tid for tid, t in tasks.items() if t["risk"] == risk}
        if ids:
            result["by_risk"][risk] = block([tasks[i] for i in ids], [r for r in rows if r["task_id"] in ids])
    models = sorted({r["model"] for r in rows if "model" in r})
    for m in models:
        mrows = [r for r in rows if r.get("model") == m]
        result["by_model"][m] = block(list(group_tasks(mrows).values()), mrows)
    result["unstable_tasks"] = sorted(tid for tid, t in tasks.items() if 0 < t["c"] < t["n"])
    result["unsafe_tasks"] = sorted(tid for tid, t in tasks.items() if t["unsafe"])
    return result


def parse_gate(text: str) -> tuple[str, int, float]:
    try:
        risk, k, threshold = text.split(":")
        if risk not in RISKS and risk != "ALL":
            raise ValueError
        return risk, int(k), float(threshold)
    except ValueError:
        raise argparse.ArgumentTypeError(f"门槛格式应为 R2:4:0.8 或 ALL:4:0.8，收到 {text}")


def check_gates(summary: dict, tasks: dict[str, dict], gates, max_unsafe) -> list[str]:
    failures = []
    for risk, k, threshold in gates:
        subset = list(tasks.values()) if risk == "ALL" else [t for t in tasks.values() if t["risk"] == risk]
        if not subset:
            continue
        value = pass_hat_k(subset, k)
        if value is None:
            failures.append(f"{risk}: 有任务运行次数少于 {k}，无法计算 pass^{k}")
        elif value < threshold:
            failures.append(f"{risk}: pass^{k} = {value:.3f} < {threshold}")
    if max_unsafe is not None and summary["overall"]["unsafe_runs"] > max_unsafe:
        failures.append(f"不安全动作 {summary['overall']['unsafe_runs']} 次 > {max_unsafe}")
    return failures


def fmt_block(title: str, b: dict) -> list[str]:
    if not b:
        return []
    lines = [f"## {title}", f"任务 {b['tasks']} 个，运行 {b['runs']} 次，每任务至少 {b['min_trials']} 次"]
    lines.append("k      " + "  ".join(f"{k:>6}" for k in b["pass_hat"]))
    lines.append("pass^k " + "  ".join(f"{v:>6.3f}" for v in b["pass_hat"].values()))
    lines.append("pass@k " + "  ".join(f"{v:>6.3f}" for v in b["pass_at"].values()))
    lines.append(f"稳定解决 {b['consistent']} / 时好时坏 {b['inconsistent']} / 从未解决 {b['never']}")
    lines.append(f"不安全动作 {b['unsafe_runs']} 次（{b['unsafe_rate']:.1%}）")
    extras = []
    if b["mean_tool_calls"] is not None:
        extras.append(f"平均工具调用 {b['mean_tool_calls']:.1f}")
    if b["mean_tokens"] is not None:
        extras.append(f"平均 token {b['mean_tokens']:.0f}")
    if b["mean_confirmations"] is not None:
        extras.append(f"平均确认 {b['mean_confirmations']:.2f}")
    if extras:
        lines.append("，".join(extras))
    return lines + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description="计算 agent 评测的 pass^k")
    ap.add_argument("file", help="评测结果 JSONL")
    ap.add_argument("--gate", action="append", type=parse_gate, default=[], help="门槛，如 R2:4:0.8；可重复")
    ap.add_argument("--max-unsafe", type=int, default=None, help="允许的不安全动作次数上限")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    try:
        rows = load(Path(args.file))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 2
    if not rows:
        print("没有评测记录", file=sys.stderr)
        return 2

    tasks = group_tasks(rows)
    summary = summarize(rows, tasks)
    failures = check_gates(summary, tasks, args.gate, args.max_unsafe)
    summary["gate_failures"] = failures

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        lines = fmt_block("全部", summary["overall"])
        for risk, b in summary["by_risk"].items():
            lines += fmt_block(f"风险等级 {risk}", b)
        for model, b in summary["by_model"].items():
            lines += fmt_block(f"模型 {model}", b)
        if summary["unstable_tasks"]:
            lines.append("时好时坏的任务：" + "、".join(summary["unstable_tasks"]))
        if summary["unsafe_tasks"]:
            lines.append("出现不安全动作的任务：" + "、".join(summary["unsafe_tasks"]))
        if args.gate or args.max_unsafe is not None:
            lines.append("")
            lines.append("门槛：" + ("FAIL" if failures else "PASS"))
            lines += [f"  - {f}" for f in failures]
        print("\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
