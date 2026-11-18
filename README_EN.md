# Agent-Friendly

> Agents can find it, understand it, get things done, and stay safe. Humans can see it, confirm it, and undo it.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-Standard-green)](https://agentskills.io)
[![skills.sh](https://img.shields.io/badge/skills.sh-Compatible-blue)](https://skills.sh)
[![selftest](https://github.com/chrislee121/agent-friendly/actions/workflows/test.yml/badge.svg)](https://github.com/chrislee121/agent-friendly/actions/workflows/test.yml)

A skill that guides websites, apps, APIs, devices, and internal systems through agent-friendly transformation, in any industry. It covers the full loop from capability analysis to testing, acceptance, and review.

Built on [Agent Skills](https://agentskills.io). Works with Cursor, Claude Code, Codex, and other compatible runtimes.

The skill body and references are written in Simplified Chinese. Agents read them fine and answer in your language.

**Other languages:** [简体中文](README.md)

---

## What it does

Ten phases. Follow-ups from the last phase feed back into the second:

```
P0 Charter → P1 Inventory → P2 Task modeling → P3 Surfaces & architecture → P4 Contracts
     ↑                                                                        ↓
P9 Review ← P8 Acceptance ← P7 Testing & eval ← P6 Staged rollout ← P5 Security & governance
```

1. **Inventory and modeling**: list system capabilities, then write the jobs you want agents to do as tasks with a risk tier (R0 public read through R3 irreversible) and an assertable end state. The task set doubles as the eval set.
2. **Surface selection**: pick from semantic HTML, llms.txt, Markdown negotiation, OpenAPI / Arazzo, MCP, WebMCP, A2A, App Intents, Android AppFunctions, HarmonyOS intents, ACP / UCP, and more, based on system shape and target agents. One core, many surfaces: business rules and permissions live only in the capability layer; protocols are thin adapters.
3. **Contracts and security**: tool naming, descriptions, schemas, errors, two-step writes, idempotency; agent identity, audience-bound tokens, no token passthrough, system-level confirmation, breaking the lethal trifecta, audit, kill switches. Mapped to the OWASP Agentic Top 10 (2026).
4. **Evaluation and acceptance**: multiple models, multiple runs, report pass^k rather than one-shot success; a 9-dimension scorecard with gated levels L0–L5, 8 veto red lines, and 10 industry weighting profiles.
5. **Review and feedback**: adversarial review, residual risk, production metrics, next-round backlog.

Standards status was checked as of 2026-11; see [references/standards-map.md](references/standards-map.md). Draft standards are marked as drafts and come with a fallback that does not depend on them.

## Install

Tell your agent:

```
Install this skill: https://github.com/chrislee121/agent-friendly
```

Or:

```bash
npx skills add chrislee121/agent-friendly
```

Manual paths: [references/runtimes.md](references/runtimes.md).

## Usage

Tell your agent:

```
Use agent-friendly to make our booking system agent-friendly, starting at P0
```

```
Use agent-friendly to assess the agent readiness of https://example.com
```

```
Use agent-friendly to run acceptance on these MCP tools, target L3
```

Deliverables go to the target project's `agent-friendly/` folder by default. Templates live in [templates/](templates/).

Scripts need only the Python 3.9+ standard library:

```bash
# External site scan (GET only; one DNS-over-HTTPS lookup by default, disable with --no-dns)
python3 scripts/scan_site.py https://example.com

# Tool contract lint: MCP tools/list output, a tool array, or OpenAPI 3.x; exits 1 on errors
python3 scripts/lint_tools.py examples/tools.good.json

# pass^k from eval results, with per-risk-tier gates
python3 scripts/passk.py examples/eval-results.sample.jsonl --gate R2:4:0.8 --max-unsafe 0

# Level, red lines, and industry-weighted score from a scorecard
python3 scripts/score.py examples/scorecard.sample.json --profile commerce --gate L3
```

## Self-test

```bash
python3 -m py_compile scripts/*.py
python3 scripts/selftest.py
```

Expect `PASS（失败 0 项）`. The self-test runs offline.

## Disclaimer

- Scores are a self-assessment against this skill's scorecard, not a certification by any platform or body.
- Meeting the standards and passing evals does not guarantee any AI assistant will call you. That is up to the platform.
- The compliance material is an engineering checklist, not legal advice.
- The external scan covers discoverability and readability only; it does not replace task evaluation.

## License

MIT. See [LICENSE](LICENSE).
