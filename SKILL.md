---
name: agent-friendly
description: Guides closed-loop agent-friendly transformation of any website, app, API, device, or internal system across industries. Covers capability inventory, agent task modeling with risk tiers, surface selection (semantic HTML, llms.txt, Markdown negotiation, OpenAPI/Arazzo, MCP, WebMCP, A2A, App Intents, Android AppFunctions, HarmonyOS intents, commerce protocols), tool contract design, identity/authorization, human confirmation, security and compliance controls, pass^k evaluation, acceptance scorecard, and review. Use when the user asks to 做 agent 友好化, AI agent 友好, agent-ready, 让 AI 助手能调用我们的产品, 接入 MCP / 智能体, agent 就绪度评估, 验收 agent 接入, 或 audit agent readiness.
---

# Agent 友好化

目标一句话：让 agent **找得到、读得懂、办得成、办得安全**，同时让人 **看得见、确认得了、撤销得掉**。

本 skill 根目录记为 `$SKILL_ROOT`。交付物默认写到被改造项目的 `agent-friendly/` 目录（用户指定了别处就按用户的）。

## 闭环总览

```
P0 立项定界 → P1 现状盘点 → P2 任务建模 → P3 接入面与架构 → P4 契约设计
     ↑                                                         ↓
P9 审核评估 ← P8 验收 ← P7 测试评测 ← P6 分批实施 ← P5 安全与治理
```

| 阶段 | 产出 | 模板 | 退出条件 |
|---|---|---|---|
| P0 立项定界 | 目标、对象 agent、红线 | [00-charter](templates/00-charter.md) | 红线清单经负责人确认 |
| P1 现状盘点 | 能力清单、外部扫描结果 | [01-capability-inventory](templates/01-capability-inventory.md) | 每项能力有数据归属与权限说明 |
| P2 任务建模 | Agent 任务集与金标准终态 | [02-agent-task-catalog](templates/02-agent-task-catalog.md) | 每个任务有风险等级和可校验终态 |
| P3 接入面与架构 | 接入面选型、一核多面架构 | [03-design-spec](templates/03-design-spec.md) 前半 | 每个任务映射到至少一个接入面 |
| P4 契约设计 | 工具 / 实体 / 资源定义 | [03-design-spec](templates/03-design-spec.md) 后半 | `lint_tools.py` 无 error |
| P5 安全与治理 | 威胁模型、控制、红线落实 | [04-risk-register](templates/04-risk-register.md) | 每条红线有对应控制和验证方法 |
| P6 分批实施 | 代码与配置 | — | 先只读、后可逆写、最后高风险 |
| P7 测试评测 | 测试计划、评测结果 | [05-acceptance-plan](templates/05-acceptance-plan.md) | 各层测试跑完，`passk.py` 出数 |
| P8 验收 | 评分卡、门槛结论 | [06-scorecard](templates/06-scorecard.md) | `score.py` 达到目标等级且红线全过 |
| P9 审核评估 | 审核报告、上线监控、下一轮待办 | [07-review-report](templates/07-review-report.md) | 待办回流到 P1/P2 |

每次只推进一个阶段。阶段的退出条件不满足，就不要进入下一阶段。用户只要某一段（例如只做评估），直接从对应阶段开始，但要说明跳过了什么。

## P0 立项定界

先问清三件事，不清楚就用提问工具问，不要猜：

1. **对象 agent 是谁**：外部通用助手（ChatGPT、Claude、Gemini、Grok、豆包等）、系统级 agent（Siri、Gemini on Android、小艺）、浏览器 agent、自家 agent、合作方 agent。不同对象决定接入面。
2. **要它办的事**：列 5～20 个最高频或最有价值的任务，用用户的话写，不用接口名写。
3. **不许它做的事**：产品边界和合规边界。默认红线见 [references/security.md](references/security.md) 的「验收红线」，项目可以加，不能删。

同时确认：上线地区（决定合规）、主体资质（个人还是企业，影响鸿蒙意图框架、支付等）、是否允许新增服务端。

## P1 现状盘点

```
- [ ] 1. 列出系统全部用户可见能力（读 / 写 / 通知 / 导出），标数据归属和现有权限
- [ ] 2. 列出现有接口：公开 API、内部 API、深链、Webhook、导出格式、SDK
- [ ] 3. 有网站就跑外部扫描
- [ ] 4. 有 MCP / OpenAPI 定义就跑契约检查，作为基线
- [ ] 5. 记录 agent 现在实际怎么用你：日志里的 AI 爬虫与 agent UA、客服里「用 AI 助手操作」的反馈
```

```bash
python3 $SKILL_ROOT/scripts/scan_site.py https://example.com
python3 $SKILL_ROOT/scripts/scan_site.py https://example.com --json > agent-friendly/scan.json
python3 $SKILL_ROOT/scripts/lint_tools.py path/to/tools.json   # MCP tools/list 结果或 OpenAPI 3.x
```

扫描只发 GET。它读取首页和约定的发现路径，不爬站内其他页面，不跟随跨域链接。默认还会向 `cloudflare-dns.com` 查一条 DNS-AID（`_index._agents` 的 SVCB）；这条查询会把域名告诉该解析器，不需要时加 `--no-dns`。用户没给网址时不要擅自扫。扫描只覆盖「可发现、可读取」的一部分，评不了能不能办成事，不能拿它代替 P7 评测。

## P2 任务建模

把 P0 的任务写成可校验的条目，每条都要有：

- **初始状态**：账号、数据、前置条件
- **用户原话**：至少 3 种说法，含口语、错别字、缺参数的说法
- **金标准终态**：任务完成后系统里应该是什么样，要能用程序断言
- **风险等级**：

| 等级 | 含义 | 例子 | 最低控制 |
|---|---|---|---|
| R0 | 公开只读 | 查营业时间、查文档 | 限流 |
| R1 | 私有只读 | 查我的订单、查病历摘要 | 授权范围、数据最小化、审计 |
| R2 | 可逆写 | 加购物车、建草稿、可取消的预约 | 预览或草稿、幂等、撤销窗口、审计 |
| R3 | 不可逆或高影响 | 付款、转账、删除、对外发消息、改权限、医疗与人身相关 | 系统级人工确认或带范围的预授权、限额、审计、默认关闭 |

拿不准就往高一级算。任务集同时就是 P7 的评测集，写的时候就要能跑。

## P3 接入面与架构

按系统形态和对象 agent 选接入面，决策表见 [references/surfaces.md](references/surfaces.md)。各标准的状态、维护方和适用场景见 [references/standards-map.md](references/standards-map.md)。

架构上必须做到 **一核多面**：

```
          ┌───────── 适配层（只做协议转换）─────────┐
  MCP · WebMCP · OpenAPI · A2A · App Intents · AppFunctions · 鸿蒙意图 · 网页 UI
          └───────────────┬────────────────────────┘
                 能力层（单一真源）
       业务规则 · 权限校验 · 风险分级 · 确认 · 幂等 · 审计
                          │
                       数据层
```

- 业务规则和权限只写在能力层。适配层里出现业务判断，就是设计错误。
- agent 通道能做的事，不能超过同一用户在 UI 里能做的事（红线 H1）。
- 协议在快速演进，所以协议细节只放在适配层，以后升级不必动业务。

## P4 契约设计

按 [references/tool-design.md](references/tool-design.md) 写工具、实体、资源的定义，要点：

- 以任务为单位设计，不要把 REST 接口逐个原样包一层
- 名称带命名空间；描述写清做什么、何时用、何时不用、副作用
- 输入强类型，用枚举、格式和示例；返回结构化结果，信息要精炼，带分页
- 错误可行动，告诉模型怎么改；写操作带幂等键，分预览和执行两段
- 如实标注只读、破坏性、幂等、开放世界这几类注解

写完立即检查，有 error 就改到通过：

```bash
python3 $SKILL_ROOT/scripts/lint_tools.py agent-friendly/tools.json
```

## P5 安全与治理

读 [references/security.md](references/security.md)，按其中清单逐条落实，填 [04-risk-register](templates/04-risk-register.md)。不可省略的几项：

- agent 要有自己的身份，令牌只接受签发给本服务的（受众绑定），短期有效、可撤销，**不得把令牌透传给下游**
- 不可信内容（用户生成内容、第三方返回、网页）只当数据处理，不能未经检查点就触发特权动作。要断开「致命三角」：私有数据、不可信内容、对外通信三者不能同时可用
- R3 确认由系统 UI 或带外渠道完成，并绑定具体参数；模型输出的文字不能算确认
- 审计日志记录 agent 身份、委托人、工具、参数摘要、结果、确认记录
- 有一键关停：按 agent、按用户、全局都能停

合规按上线地区读 [references/compliance.md](references/compliance.md)。合规部分只给工程上的对照，不构成法律意见，涉及资质、备案、跨境的事项要提示用户找法务确认。

## P6 分批实施

顺序固定：**内容可读 → R0/R1 只读 → R2 可逆写 → R3 高风险**。每批都要走完 P7 和 P8 再开下一批。R3 默认关闭，按用户、按 agent 逐个开放。

改动遵守被改造项目自己的规则（分支、提交、文案、隐私政策），新增网络请求和数据流要同步更新隐私政策。

## P7 测试评测

分层做，方法见 [references/testing.md](references/testing.md)：

1. 契约测试：schema、注解、错误格式
2. 业务测试：按模型风格构造输入，覆盖空串、同义词、越界值、缺参数
3. 协议一致性：各接入面的官方检查工具
4. Agent 端到端评测：P2 任务集，≥2 个模型，每任务 ≥4 次，校验终态
5. 对抗测试：间接注入、工具投毒、越权、重放、绕过限额
6. 灰度：真实流量小比例上线，盯不安全动作

评测结果写成 JSONL 后计算：

```bash
python3 $SKILL_ROOT/scripts/passk.py agent-friendly/eval-results.jsonl \
  --gate R0:4:0.9 --gate R1:4:0.85 --gate R2:4:0.8 --gate R3:8:0.9 --max-unsafe 0
```

必须报 pass^k（k 次都成功），不能只报单次成功率。

## P8 验收

按 [references/scorecard.md](references/scorecard.md) 给 9 个维度打 0～4 分，每个分数都要附证据（链接、日志、评测结果），没有证据按 0 分算。填好 JSON 后：

```bash
python3 $SKILL_ROOT/scripts/score.py agent-friendly/scorecard.json --gate L3
```

等级是逐级门槛制，平均分高不能抵消短板。任一红线不过，等级最多只能到 L2，验收不通过。

## P9 审核评估

- 用对立视角审一遍：假设自己是攻击者、是抱怨的用户、是监管方，各找三个问题
- 写 [07-review-report](templates/07-review-report.md)：结论、证据、残余风险、上线监控指标、下一轮待办
- 上线后按周看：任务成功率、不安全动作数、确认打扰率、撤销率、agent 来源分布
- 待办回流到 P1/P2，形成下一轮。标准有新版本时（见 standards-map 核验日期），重跑 P3/P4 的相关部分

## 行业差异

不同行业的典型任务、高风险动作、额外红线和评分权重见 [references/industries.md](references/industries.md)。`score.py --profile` 支持 `finance`、`health`、`commerce`、`content`、`saas`、`gov`、`iot`、`travel`、`education`、`enterprise` 十种行业剖面。

## 写结论的规矩

- 每个结论注明依据：标准链接、实测命令输出、评测数据
- 标准状态以 standards-map 为起点，正式落地前去官网确认最新版本，引用时写版本号或日期
- 草案标准（WebMCP、AIPREF、Web Bot Auth、Server Card 等）要标「草案」，同时给出不依赖它的兜底方案
- 不要承诺「接入后某某助手一定会调用」。是否调用由平台决定，能承诺的只有「符合标准、通过评测」

## 常见错误

| 错误 | 正确做法 |
|---|---|
| 把全部 REST 接口自动转成工具 | 按任务合并，控制工具数量 |
| 只给 agent 开读权限，写操作让它去点 UI | 写操作走两段式工具，UI 只作兜底 |
| 用 API Key 代表用户 | 用 OAuth 委托，细粒度授权，可撤销 |
| 拿模型的「我确认」当确认 | 系统 UI 或带外确认，绑定参数 |
| 只跑一次演示就宣布可用 | 多模型多次运行，报 pass^k |
| 只做 llms.txt 就说完成了 agent 友好 | 那只是可读层，能不能办成事要看 P3 到 P8 |
| 为讨好扫描器加隐藏内容 | 不做。它损害无障碍，还可能被判为注入 |

## 脚本

全部只用 Python 3.9+ 标准库。

| 文件 | 用途 |
|---|---|
| [scripts/scan_site.py](scripts/scan_site.py) | 网站外部扫描：robots、内容偏好、Markdown 协商、llms.txt、发现文件（含 ARD、Poppy、auth.md、x402、MPP）、DNS-AID、OAuth 元数据、页面语义 |
| [scripts/lint_tools.py](scripts/lint_tools.py) | 工具契约检查：MCP `tools/list` 或 OpenAPI 3.x，失败 exit 1 |
| [scripts/passk.py](scripts/passk.py) | 评测结果计算 pass^k、pass@k、不安全动作率，可设门槛 |
| [scripts/score.py](scripts/score.py) | 评分卡计算等级、红线、加权分，可设门槛 |
| [scripts/selftest.py](scripts/selftest.py) | 冒烟测试 |
