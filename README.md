# Agent 友好化

> 让 agent 找得到、读得懂、办得成、办得安全；让人看得见、确认得了、撤销得掉。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-Standard-green)](https://agentskills.io)
[![skills.sh](https://img.shields.io/badge/skills.sh-Compatible-blue)](https://skills.sh)
[![selftest](https://github.com/chrislee121/agent-friendly/actions/workflows/test.yml/badge.svg)](https://github.com/chrislee121/agent-friendly/actions/workflows/test.yml)

指导网站、App、API、设备和内部系统做 agent 友好化改造。覆盖从系统功能分析到测试、验收、审核评估的完整闭环，各行业通用。

基于 [Agent Skills](https://agentskills.io)，可用于 Cursor、Claude Code、Codex 等兼容 runtime。

**Other languages:** [English](README_EN.md)

---

## 它做什么

十个阶段，最后一步的待办回流到第二步：

```
P0 立项定界 → P1 现状盘点 → P2 任务建模 → P3 接入面与架构 → P4 契约设计
     ↑                                                         ↓
P9 审核评估 ← P8 验收 ← P7 测试评测 ← P6 分批实施 ← P5 安全与治理
```

1. **盘点与建模**：列出系统能力，把要 agent 办的事写成带风险等级（R0 公开只读 ～ R3 不可逆）、带可断言终态的任务集。任务集直接就是评测集。
2. **选接入面**：按系统形态和对象 agent 选择语义 HTML、llms.txt、Markdown 协商、OpenAPI / Arazzo、MCP、WebMCP、A2A、App Intents、Android AppFunctions、鸿蒙意图框架、ACP / UCP 等。架构上一核多面：业务规则和权限只写在能力层，各协议只做适配。
3. **契约与安全**：工具命名、描述、schema、错误、两段式写操作、幂等；agent 身份、受众绑定令牌、禁止透传、系统级确认、断开致命三角、审计、一键关停。对照 OWASP Agentic Top 10（2026）。
4. **评测与验收**：多模型多次运行，报 pass^k，不只报单次成功率；9 维评分卡，L0～L5 逐级门槛，8 条红线一票否决；10 个行业剖面加权。
5. **审核与回流**：对立视角审查、残余风险、上线监控指标、下一轮待办。

标准状态核验到 2026-11，见 [references/standards-map.md](references/standards-map.md)。草案标准都标了「草案」，并给出不依赖它的兜底做法。

## 安装

对 Agent 说：

```
帮我安装这个 skill：https://github.com/chrislee121/agent-friendly
```

或：

```bash
npx skills add chrislee121/agent-friendly
```

手动路径见 [references/runtimes.md](references/runtimes.md)。

## 用法

对 Agent 说：

```
按 agent-friendly 给我们的订座系统做 agent 友好化，先从 P0 开始
```

```
按 agent-friendly 评估 https://example.com 的 agent 就绪度
```

```
按 agent-friendly 验收这套 MCP 工具，目标 L3
```

交付物默认写到被改造项目的 `agent-friendly/` 目录，模板在 [templates/](templates/)。连锁餐厅订座的闭环示例见 [examples/walkthrough.md](examples/walkthrough.md)。

脚本只用 Python 3.9+ 标准库：

```bash
# 网站外部扫描（只发 GET，跳转只跟同一主机；默认多一条 DNS-over-HTTPS，--no-dns 可关）
python3 scripts/scan_site.py https://example.com
# 国内网络连不上 Cloudflare DoH 时
python3 scripts/scan_site.py https://example.com --doh https://dns.alidns.com/resolve

# 工具契约检查：MCP tools/list 结果、工具数组或 OpenAPI 3.x，有 error 时 exit 1
python3 scripts/lint_tools.py examples/tools.good.json

# 评测结果算 pass^k，可按风险等级设门槛
python3 scripts/passk.py examples/eval-results.sample.jsonl --gate R2:4:0.8 --max-unsafe 0

# 评分卡算等级、红线和行业加权分
python3 scripts/score.py examples/scorecard.sample.json --profile commerce --gate L3
```

流程见 [SKILL.md](SKILL.md)。评分规则见 [references/scorecard.md](references/scorecard.md)，测试方法见 [references/testing.md](references/testing.md)。

## 最小自检

```bash
python3 -m py_compile scripts/*.py
python3 scripts/selftest.py
```

应输出 `PASS（失败 0 项）`。自检不联网。

## 对外口径

- 评分是按本 skill 的评分卡给出的自评，不是任何平台或机构的认证。
- 做到「符合标准、通过评测」，不等于某个 AI 助手一定会调用你。调用与否由平台决定。
- 合规部分只做工程对照，不构成法律意见。资质、备案、跨境数据等事项请找法务确认。
- 外部扫描只覆盖「可发现、可读取」，不能代替任务评测。

## 许可

MIT。见 [LICENSE](LICENSE)。
