# 标准地图

按层列出与 agent 友好化相关的标准、协议和约定。**核验时间：2026-11。** 这些标准变化很快，落地前请到「链接」列的官网确认当前版本。

状态说明：**正式** = 已发布的规范或 RFC；**现行** = 被主流平台实际使用但非标准组织发布；**草案** = 标准组织内的草案或实验特性；**预览** = 厂商预览计划。

## 1. 发现层：agent 怎么知道你有什么

| 标准 | 解决什么 | 维护方 | 状态 | 何时用 | 链接 |
|---|---|---|---|---|---|
| robots.txt（RFC 9309） | 抓取许可 | IETF | 正式 | 所有网站 | https://www.rfc-editor.org/rfc/rfc9309 |
| sitemap.xml | 列出规范 URL | sitemaps.org | 现行 | 内容型网站 | https://www.sitemaps.org/protocol.html |
| Link 响应头（RFC 8288） | 在首页响应头里指向 API 描述、文档 | IETF | 正式 | 有 API 或文档的网站 | https://www.rfc-editor.org/rfc/rfc8288 |
| API Catalog（RFC 9727） | `/.well-known/api-catalog`，列出你的 API 和描述文件 | IETF | 正式 | 有公开 API | https://www.rfc-editor.org/rfc/rfc9727 |
| MCP Server Card（SEP-2127） | 连接前描述远程 MCP 服务：名称、端点、协议版本。现行扩展推荐放在 MCP 端点 URL 后加 `/server-card`，再登记到 AI Catalog；早期的 `/.well-known/mcp-server-card` 等固定位置只算兼容 | MCP / AAIF | 正式（扩展） | 提供远程 MCP | https://github.com/modelcontextprotocol/ext-server-card |
| AI Catalog | `/.well-known/ai-catalog.json`，列出一个域名下的 MCP Server Card、Agent Card 等，条目要有 `identifier`、媒体类型，`url` 与 `data` 二选一。MCP Server Card 扩展按这个路径发现 | Agent-Card 社区 | 草案 | 一个域名下有多个 agent 资源，或要让 MCP 客户端发现 Server Card | https://github.com/Agent-Card/ai-catalog |
| ARD | `/.well-known/ard.json` 或首页 `rel="ard"`，条目格式与 AI Catalog 相同，另要求 `urn:air:<域名>:<名称>`、`displayName`，建议 2～5 条 `representativeQueries`。ARD 规范把 ai-catalog.json 称为前代路径，而 MCP 扩展仍读它，所以两个都可以发布 | agenticresourcediscovery.org | 草案（v0.91） | 想被 ARD 注册中心语义检索 | https://github.com/ards-project/ard-spec |
| Personal Agent Protocol | `/.well-known/poppy.json`。`organization.domain` 必须是提供该文件的主机；`agent`、`apis`、`web` 至少有一个 | personalagentprotocol.org | 现行（v1.0，2026-11-14） | 让个人 agent 代表用户用网站、API 或企业 agent | https://personalagentprotocol.org/docs/1.0/spec |
| MCP Registry `server.json` | 登记到官方 MCP 目录，可放 `/.well-known/mcp/server.json` 供自动发现 | MCP | 现行 | 希望被 MCP 客户端检索到 | https://modelcontextprotocol.io/registry/quickstart |
| A2A Agent Card | `/.well-known/agent-card.json`，描述一个 agent 的技能、端点、认证 | Linux Foundation（A2A 项目） | 正式（v1.0） | 你提供的是 agent 而不只是工具 | https://a2a-protocol.org/latest/specification/ |
| Agent Skills 发现索引 | `/.well-known/agent-skills/index.json`，告诉 agent 有哪些技能文档 | Cloudflare 提案 | 草案 | 有面向 agent 的操作指南 | https://github.com/cloudflare/agent-skills-discovery-rfc |
| DNS-AID | `_index._agents.<域名>` 上的 ServiceMode SVCB（type 64）。扫描用 DNS-over-HTTPS 查这一条，HTTPS 记录（type 65）不算；无 AD 只警告，而 AD 取决于解析器是否做 DNSSEC 验证（AliDNS 不做） | IETF 个人草案（draft-02） | 草案 | 你确实有组织级 agent 索引时 | https://datatracker.ietf.org/doc/draft-mozleywilliams-dnsop-dnsaid/ |

## 2. 内容层：agent 怎么读懂你

| 标准 | 解决什么 | 维护方 | 状态 | 何时用 | 链接 |
|---|---|---|---|---|---|
| 语义 HTML + WAI-ARIA + WCAG 2.2 | 浏览器 agent 主要靠无障碍树识别控件的角色、名称、状态 | W3C | 正式 | 所有网页，是兜底层 | https://web.dev/articles/ai-agent-site-ux |
| schema.org JSON-LD | 实体结构化：商品、门店、活动、文章、FAQ | schema.org | 现行 | 内容、电商、本地生活 | https://schema.org |
| Markdown 内容协商 | 请求头 `Accept: text/markdown` 时返回 Markdown，可省约 80% token | Cloudflare 发起 | 现行 | 文档、内容站 | https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/ |
| llms.txt / llms-full.txt | 根目录 Markdown 阅读清单 | 社区提案 | 现行（采用约 12%） | 文档、SaaS。没有证据表明主流 AI 会读，成本低可做 | https://llmstxt.org |
| AGENTS.md | 给编程 agent 的仓库说明 | AAIF（Linux Foundation） | 现行 | 开源仓库、SDK | https://agents.md |

## 3. 政策层：允许 agent 做什么

| 标准 | 解决什么 | 维护方 | 状态 | 何时用 | 链接 |
|---|---|---|---|---|---|
| Content Signals | robots.txt 里写 `Content-Signal: search=yes, ai-input=yes, ai-train=no` | Cloudflare | 现行 | 内容方表态 | https://contentsignals.org |
| AIPREF Content-Usage | robots.txt 规则和 HTTP 头，按路径表态 | IETF AIPREF 工作组 | 草案 | 与 Content Signals 并存，含义要一致 | https://datatracker.ietf.org/doc/draft-ietf-aipref-attach/ |
| Web Bot Auth | agent 用 HTTP 消息签名（RFC 9421）证明身份；`Signature-Agent` 头指向 JWKS 目录 | IETF webbotauth 工作组 | 草案（Cloudflare 已用于已验证 bot） | 你**发出** agent 流量时；网站方用于识别和放行 | https://datatracker.ietf.org/doc/draft-ietf-webbotauth-httpsig-protocol/ |

注意：以上都只是**偏好声明或身份声明**，本身不起阻断作用。真正的访问控制要在服务端做。

## 4. 能力层：agent 怎么办事

| 标准 | 解决什么 | 维护方 | 状态 | 何时用 | 链接 |
|---|---|---|---|---|---|
| **MCP**（当前版本 2026-07-28） | agent 连接工具、资源、提示词的通用协议。2026-07-28 版改为无状态，取消会话和初始化握手，新增 `server/discover`，长任务移入官方扩展，引入多轮往返（MRTR） | AAIF（Linux Foundation） | 正式 | 远程服务给通用助手用的首选 | https://modelcontextprotocol.io/specification/2026-07-28 |
| MCP Apps | MCP 工具返回可交互 UI | MCP 社区（含 OpenAI、Anthropic） | 现行 | 需要在对话里展示表单、卡片 | https://modelcontextprotocol.io |
| **WebMCP** | 网页用 `document.modelContext.registerTool()` 或带注解的表单声明工具，给浏览器 agent 用 | W3C Web 机器学习社区组 | 草案（Chrome 149、Edge 150 源试用） | 有登录态的复杂网页应用 | https://webmachinelearning.github.io/webmcp/ |
| OpenAPI 3.1+ | HTTP API 描述 | OpenAPI Initiative | 正式 | 已有 REST API | https://spec.openapis.org |
| **Arazzo 1.0** | 用多个 API 调用组成工作流，含输入、输出、成功条件 | OpenAPI Initiative | 正式 | 多步任务，比让 agent 自己拼接口可靠 | https://spec.openapis.org/arazzo/v1.0.0 |
| **A2A v1.0** | agent 之间委托任务：任务生命周期、流式、推送、制品 | Linux Foundation | 正式 | 你提供的是 agent，或要把任务交给对方的 agent | https://a2a-protocol.org |
| **Apple App Intents**（iOS 27） | 向 Siri / Apple Intelligence 暴露动作与实体；App Schemas、IndexedEntity 语义索引、View Annotations 屏幕感知、AppIntentsTesting 测试框架 | Apple | 正式 | iOS / macOS App | https://developer.apple.com/wwdc26/guides/apple-intelligence/ |
| **Android AppFunctions** | App 作为端侧 MCP 服务，向 Gemini 等系统 agent 暴露函数；Android 16+，Jetpack `androidx.appfunctions` | Google | 正式 API，Gemini 接入走 Connected Apps 预览 | Android App | https://developer.android.com/ai/appfunctions |
| **HarmonyOS 意图框架**（Intents Kit / InsightIntent） | 通过 `insight_intent.json` 注册意图，供小艺对话、搜索、建议调用；小艺智能体平台支持 A2A 模式接入三方 agent | 华为 | 正式。仅限中国境内、HarmonyOS 5.0+、企业开发者 | 鸿蒙 App | https://developer.huawei.com/consumer/cn/doc/harmonyOS-guides/intents-introduction |

## 5. 身份与授权层

| 标准 | 解决什么 | 状态 | 链接 |
|---|---|---|---|
| OAuth 2.1 | 授权码 + PKCE，去掉隐式流 | 草案（已被 MCP 采用） | https://datatracker.ietf.org/doc/draft-ietf-oauth-v2-1/ |
| RFC 9728 受保护资源元数据 | `/.well-known/oauth-protected-resource`，告诉客户端找哪个授权服务器 | 正式 | https://www.rfc-editor.org/rfc/rfc9728 |
| RFC 8414 / OIDC Discovery | 授权服务器元数据 | 正式 | https://www.rfc-editor.org/rfc/rfc8414 |
| RFC 8707 资源指示 | 令牌绑定目标资源（受众） | 正式 | https://www.rfc-editor.org/rfc/rfc8707 |
| Client ID Metadata Documents | 客户端用一个 HTTPS URL 当 client_id，代替动态注册。MCP 2026-07-28 推荐，动态客户端注册（RFC 7591）已标为弃用 | 草案 | https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/ |
| RFC 9207 `iss` 参数 | 防混淆授权服务器攻击 | 正式 | https://www.rfc-editor.org/rfc/rfc9207 |
| RFC 8693 令牌交换 | 委托链：agent 代表用户再调下游时换发新令牌，不透传 | 正式 | https://www.rfc-editor.org/rfc/rfc8693 |
| auth.md | `/auth.md`（一级标题含 auth.md），加上本域受保护资源元数据，以及本域授权服务器元数据里的 `agent_auth`。扫描不跟随跨域授权服务器 | 现行（WorkOS 提案） | https://github.com/workos/auth.md |

## 6. 交易层：agent 怎么付钱

| 协议 | 回答的问题 | 维护方 | 状态（2026-10 前后） |
|---|---|---|---|
| ACP（Agentic Commerce Protocol） | agent 怎么把一次购买交给商家结账；一次性限额支付令牌 | OpenAI + Stripe | Beta |
| UCP（Universal Commerce Protocol） | agent 怎么使用商家完整的商业系统：目录、购物车、结账、身份关联、订单 | Google + Shopify 等 | 现行，Google AI Mode / Gemini 部分地区已用 |
| AP2（Agent Payments Protocol） | 用签名授权书证明用户授权了什么；不负责付款本身 | Google，已贡献给 FIDO 联盟 | v0.2 |
| x402 | 软件对软件按次付费：资源返回 HTTP 402 和 `PAYMENT-REQUIRED`。发现清单是另一份草案，放 `/.well-known/x402`（`x402Version`、`kind`；facilitator 的 `baseUrl` 必须在本域）。扫描只读清单，不请求付费资源 | x402 基金会（Linux Foundation） | 协议现行；发现为草案 |
| MPP | 402 质询、凭证、收据，支持卡和稳定币。发现用 `/openapi.json` 里的 `x-payment-info`（`intent` 为 `charge` 或 `session`）。发现文档只是提示，运行时以 402 质询为准 | Stripe + Tempo | 现行；发现文档为草案 |
| Visa Trusted Agent Protocol / Intelligent Commerce、Mastercard Agent Pay | 卡组织侧识别可信 agent、令牌化凭证 | Visa、Mastercard | 试点 |

对比参考：https://agent-ready.dev/acp-vs-ucp-vs-ap2-vs-x402

## 7. 安全与治理参考

| 文档 | 用途 | 链接 |
|---|---|---|
| OWASP Top 10 for Agentic Applications 2026（ASI01～ASI10） | agent 应用风险清单 | https://genai.owasp.org |
| OWASP MCP Security Cheat Sheet | MCP 落地控制项 | https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html |
| MCP Security Best Practices | 令牌透传、混淆代理、会话劫持等 | https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices |
| NIST AI Agent Standards Initiative（CAISI，2026-02） | 美国 agent 标准化方向：互操作、身份、安全 | https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure |
| NIST agent 身份管理设计原则 | 独立身份、委托链、短期可撤销授权、防篡改审计 | https://www.nist.gov/blogs/cybersecurity-insights/design-tenets-agent-identity-management-systems |

## 8. 法规与国内标准

见 [compliance.md](compliance.md)。

## 9. 评测参考

| 名称 | 要点 | 链接 |
|---|---|---|
| τ-bench | 多轮对话 + 领域规则；比对终态数据库；提出 pass^k | https://arxiv.org/abs/2406.12045 |
| WebArena | 真实网站长流程任务，功能正确性校验 | https://webarena.dev |
| OSWorld | 桌面 GUI 操作 | https://os-world.github.io |
| Anthropic《Writing effective tools for agents》《Demystifying evals for AI agents》 | 工具设计与评测方法 | https://www.anthropic.com/research/writing-tools-for-agents |
| Cloudflare Agent Readiness | 网站外部就绪度 0～5 级打分，23 项检查 | https://isitagentready.com |

## 采用建议

- **必做**（成熟、成本低）：语义 HTML 与无障碍、robots.txt 表态、结构化数据、OpenAPI（如有 API）、OAuth 元数据
- **优先**（已成主流）：远程 MCP、App Intents / AppFunctions / 鸿蒙意图（有 App 时）、Arazzo（多步流程）
- **按需**：A2A（你提供 agent）、交易协议（你卖东西）、WebMCP（复杂网页应用，且接受草案）、auth.md（agent 自助注册）、AI Catalog / ARD（一个域名多个资源）、Personal Agent Protocol（个人 agent 代用户办事）
- **跟踪**：AIPREF、Web Bot Auth、ARD、DNS-AID、x402 的 well-known 发现草案、CIMD
