# 业内共识：十二条原则

从 MCP 规范、A2A、WebMCP、Apple / Google / 华为平台文档、OWASP、NIST、Anthropic 与 Cloudflare 的工程指南、τ-bench 等评测研究中提炼。每条附主要出处，便于自行核对。

## 1. Agent 是一类新用户，但不能另立一套规则

Agent 既不是爬虫，也不是人。它需要专门的接入面，但业务规则、权限和审计必须和人用同一套。这就是「一核多面」：业务和权限只放在能力层，各协议只做适配。

出处：Android AppFunctions 把 App 当作端侧 MCP 服务；Apple App Intents 要求意图复用 App 的业务逻辑；UCP 同时提供 API、A2A、MCP 三种接入方式。

## 2. 结构化优先，界面兜底

能给出结构化能力（API、工具、意图），就不要让 agent 去猜界面。界面仍然要语义化，因为浏览器 agent 和屏幕操作 agent 会退回到读无障碍树和截图。

出处：web.dev《AI agent site UX》；Chrome 文档关于 WebMCP 的说明；Lighthouse 新增的面向 agent 的无障碍审计。

## 3. 以任务为单位设计工具

按用户要完成的事来切分工具，不要把 REST 接口逐个原样包成工具。工具少一点、能力强一点，可以减少选错工具的概率。

出处：Anthropic《Writing effective tools for agents》；Claude 工具定义最佳实践。

## 4. 描述就是提示词

工具的名字、描述、参数说明，决定 agent 能不能选对工具、填对参数。描述要写做什么、何时用、何时不用、参数含义、限制和副作用。

出处：Anthropic 工具定义指南（每个工具至少写 3～4 句描述）；MCP 规范对工具名格式的约定。

## 5. 返回高信号、省 token

返回 agent 决定下一步所需的字段，不要多给。用语义化的稳定 ID，支持分页、过滤和截断；截断时要提示怎样取下一页。

出处：Anthropic（Claude Code 默认把工具返回限制在 25,000 token）；MCP 的 `structuredContent` 与 `outputSchema`；Markdown 内容协商可省约 80% token。

## 6. 错误信息是写给模型看的

输入校验错误要作为工具执行错误返回（不是协议错误），说明错在哪、正确格式是什么、给一个例子，让模型能自己改正后重试。

出处：MCP 2025-11-25 起的明确要求（SEP-1303）；Android AppFunctions 要求抛出具体的异常子类；WebMCP 要求用结构化返回值传递错误。

## 7. 读写分级，写入分两段

只读和写入分开声明。写入先预览或存草稿，再由人确认，最后执行；所有写入都要幂等。不可逆动作默认关闭。

出处：MCP 工具注解（readOnlyHint、destructiveHint、idempotentHint）；WebMCP 的 `consequentialHint`；OWASP ASI02。

## 8. 最小权限，委托可追溯

Agent 有独立身份。令牌只接受签发给本服务的，短期有效，可撤销，按资源细分授权范围。不透传令牌；agent 再调下游时要换发新令牌。

出处：MCP 授权规范（受众校验、禁止令牌透传、RFC 8707）；NIST agent 身份设计原则；OWASP ASI03；国内《智能体应用安全基本要求》的身份标识和权限条款。

## 9. 不可信内容只是数据，不是指令

用户生成内容、第三方返回、网页文本，一律当作不可信数据。设计上要断开「致命三角」：私有数据访问、不可信内容输入、对外通信，这三者不能在同一次执行里无检查点地同时存在。

出处：OWASP ASI01；OWASP MCP Cheat Sheet；Invariant Labs 的 GitHub MCP 攻击案例；WebMCP 的 `untrustedContentHint`。

## 10. 人保留最终控制权

人要能看见 agent 做了什么、在关键处确认、事后撤销、随时关停。Agent 要表明自己是 AI，以及代表谁在做事。

出处：MCP 规范的「用户同意与控制」原则；EU AI Act 第 50 条（2026-08-02 起适用于 agent）；《智能体发展自律公约》；《智能体应用安全基本要求》的高风险操作人工介入、紧急关停条款。

## 11. 用评测说话，看稳定性

验收要用可校验终态的任务集，用多个模型各跑多次，报告 pass^k（k 次全部成功的概率），同时统计不安全动作。只跑一次的演示不能作为验收依据。

出处：τ-bench 提出 pass^k；Anthropic《Demystifying evals for AI agents》区分能力评测和回归评测；OSWorld 可靠性研究。

## 12. 协议会变，业务不该跟着变

MCP 一年内两次大改（2025-11-25 加任务和 URL 采集，2026-07-28 改为无状态、弃用动态客户端注册）；WebMCP 的 API 已经从 `navigator` 迁到 `document`。所以协议细节只放适配层，盯住版本，定期重测。

出处：MCP changelog 与弃用策略（弃用期至少 12 个月）；WebMCP 实现状态页。
