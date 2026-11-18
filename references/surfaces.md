# 接入面选型

## 1. 先判断两件事

**系统形态**：内容站、电商、SaaS / API 平台、移动 App、企业内部系统、设备 / IoT、本身就是 agent 的服务、开发者工具。

**对象 agent**：

| 对象 | 它怎么接入 | 你要提供 |
|---|---|---|
| 外部通用助手（ChatGPT、Claude、Gemini、Grok、豆包等） | 远程 MCP 连接器、搜索抓取、浏览器 | 远程 MCP + OAuth；网页可读 |
| 系统级 agent（Siri、Gemini on Android、小艺） | 系统意图框架 | App Intents / AppFunctions / 鸿蒙意图 |
| 浏览器 agent（浏览器内置 agent、扩展、屏幕操作 agent） | 无障碍树、截图、WebMCP | 语义 HTML；WebMCP（可选） |
| 自家 agent | 直接调能力层 | 内部工具定义，复用同一套契约 |
| 合作方 agent | A2A、MCP、API | A2A Agent Card 或 MCP + 机构级授权 |
| 编程 agent（开发者用户） | 读文档和仓库 | OpenAPI、llms.txt、AGENTS.md、SDK |

## 2. 决策表

✅ 必做　⭐ 推荐　○ 按需　— 一般不需要

| 接入面 | 内容站 | 电商 | SaaS / API | 移动 App | 企业内部 | 设备 / IoT | Agent 服务 | 开发者工具 |
|---|---|---|---|---|---|---|---|---|
| 语义 HTML + 无障碍 | ✅ | ✅ | ✅ | ○（Web 端） | ✅ | ○ | ○ | ✅ |
| robots.txt + 内容偏好 | ✅ | ✅ | ✅ | ○ | —（内网） | — | ✅ | ✅ |
| schema.org 结构化数据 | ✅ | ✅ | ○ | — | — | — | — | ○ |
| Markdown 协商 / llms.txt | ⭐ | ○ | ⭐ | — | ○ | — | ○ | ✅ |
| OpenAPI + Arazzo | ○ | ⭐ | ✅ | ○（有后端时） | ⭐ | ⭐ | ○ | ✅ |
| OAuth 元数据（RFC 9728/8414） | — | ✅ | ✅ | ○ | ✅ | ⭐ | ✅ | ⭐ |
| 远程 MCP | ○ | ⭐ | ✅ | ○（有云同步时） | ⭐ | ⭐ | ⭐ | ✅ |
| WebMCP | — | ○ | ⭐ | — | ○ | — | — | ○ |
| App Intents / AppFunctions / 鸿蒙意图 | — | ⭐（有 App） | ⭐（有 App） | ✅ | ○ | ⭐ | — | — |
| A2A Agent Card | — | ○ | ○ | — | ○ | — | ✅ | — |
| 交易协议（UCP / ACP / AP2 / x402） | ○（付费内容） | ⭐ | ○（按量计费） | ○ | — | — | ○ | ○ |
| Web Bot Auth 签名 | — | — | — | — | — | — | ✅（你发流量） | — |

## 3. 判断数据在哪

| 数据位置 | 远程 agent 能否访问 | 做法 |
|---|---|---|
| 只在端上（本地数据库、端到端加密） | 不能，除非新增同步 | 先做系统意图；远程 MCP 要等有服务端同步，且由用户自愿开启 |
| 在你的服务端 | 能 | 远程 MCP / API，按用户授权 |
| 在第三方平台（如 iCloud 私有库） | 一般不能直接访问 | 不要让服务端代持用户的平台凭据；改为用户主动同步一份到你的服务端，或只做端侧接入 |

## 4. 各接入面要点

### 语义 HTML（所有网页的兜底）

- 能点的用 `<button>`、`<a>`，不用带 onclick 的 `<div>`
- 每个输入框都用 `<label for>` 关联标签，不要只用 placeholder
- 纯图标按钮要有可访问名称
- 用 `aria-expanded`、`aria-selected`、`disabled` 暴露状态
- 不要用透明遮罩盖住控件；交互元素不小于 8×8 像素；布局稳定
- 关键内容、导航和表单要出现在服务端渲染的 HTML 里
- 验证：Chrome DevTools 无障碍面板、Lighthouse 面向 agent 的无障碍审计、Playwright 无障碍快照

### 远程 MCP

- 传输用 Streamable HTTP，遵守当前协议版本（2026-07-28：无状态，每个请求在 `_meta` 里带协议版本，必须实现 `server/discover`）
- 跨调用状态用服务端签发的句柄作为普通参数传递，不要依赖会话
- 授权：OAuth 2.1 + PKCE；发布 `/.well-known/oauth-protected-resource`；客户端注册优先支持 Client ID Metadata Documents，动态注册只作兼容；回调地址按注册值精确比对
- 校验 `Origin` 头，不合法时返回 403
- 发现：Server Card（端点下的 `/server-card`）、域名级 AI Catalog、MCP Registry 登记
- 长任务用官方 tasks 扩展；需要用户补充输入时用多轮往返返回 `input_required`
- 验证：MCP Inspector（`npx @modelcontextprotocol/inspector`），并在至少两个真实客户端里连接测试

### WebMCP（草案）

- 命令式：`document.modelContext.registerTool({ name, description, inputSchema, execute, annotations })`
- 声明式：给现有 `<form>` 加 `toolname`、`tooldescription` 注解
- 注解：`readOnlyHint`；高风险动作标 `consequentialHint`；返回第三方内容时标 `untrustedContentHint`
- `execute` 抛出的异常信息不会传给 agent，错误要用结构化返回值传递
- 只能在 HTTPS 下使用；跨源 iframe 需要 `allow="tools"` 和 `exposedTo`
- 草案状态，必须保证不支持 WebMCP 的 agent 仍能靠语义 HTML 完成任务
- 验证：开启 `chrome://flags/#enable-webmcp-testing`

### Apple App Intents（iOS 27）

- 动作用 `AppIntent`，内容用 `AppEntity`；优先采用系统 App Schemas，Siri 能直接理解
- 能建索引的实体实现 `IndexedEntity` 并设置 `indexingKey`，进入 Spotlight 语义索引；数据大或在服务端的用 `EntityStringQuery`
- 屏幕上的内容用 View Annotations 映射到实体，支持「这个」「刚才那个」这类说法
- 写操作要求确认（`requestConfirmation`），高风险操作打开 App 在前台完成
- 验证顺序：AppIntentsTesting（XCUITest 进程外执行）→ 快捷指令 → Spotlight → 真机 Siri

### Android AppFunctions

- 依赖 `androidx.appfunctions`（KSP 编译），用 `@AppFunctionDeclaration` 标注函数，KDoc 就是描述
- 要求 compileSdk 37+、AGP 9.1+，设备 Android 16+
- 可选参数的 Kotlin 默认值不生效，省略时会收到 null / 0 / false，要在函数体里补默认值
- 平台在主线程发起调用，数据库、网络、磁盘 I/O 要切到 `Dispatchers.IO`
- 失败时抛具体的 `AppFunctionException` 子类
- 给 Gemini 用要在 Google Connected Console 创建连接应用（预览计划）
- 验证：`adb shell cmd app_function`、官方开源测试 agent

### 鸿蒙意图框架

- `resources/base/profile/insight_intent.json` 注册意图，继承 `InsightIntentExecutor` 实现
- 任务执行类场景只支持预置的垂域意图，不能自定义；要按垂域 Schema 对齐参数
- 限制：中国境内、HarmonyOS 5.0+、企业开发者
- 小艺智能体平台：端插件的工具名、版本与 `intentName`、`intentVersion` 对应；有云侧 agent 的可用 A2A 模式接入

### OpenAPI + Arazzo

- 每个操作都要有 `operationId`、描述、参数说明、4xx 响应 schema、`security`
- 多步流程用 Arazzo 写成工作流（输入、步骤、成功条件、输出），可以直接生成 MCP 工具和端到端测试
- 发布 `/.well-known/api-catalog` 并在首页加 `Link` 头

### A2A

- 发布 `/.well-known/agent-card.json`：名称、描述、版本、`supportedInterfaces`（含协议版本）、技能、认证方式
- 敏感信息放在需认证的扩展卡片里，公开卡片不放密钥
- 卡片可以用 JWS 签名（RFC 8785 规范化）

### 交易协议

- 先确认商户角色（是否为记账商户）、拒付责任归谁、平台覆盖哪些地区
- 支付金额和收款方由服务端定，模型和对方 agent 传来的值都不可信
- 限额在付款组件里强制执行（不在模型上下文里），未结算的按上限预占，扣减要原子化
- 签名授权书（AP2）连同展示给用户的说明一起保存
