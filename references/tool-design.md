# 工具契约设计

适用于 MCP 工具、WebMCP 工具、App Intents、AppFunctions、鸿蒙意图、A2A 技能，也适用于给 agent 用的 OpenAPI 操作。下文统称「工具」。

## 1. 切分

- 按用户任务切分。例如「按日期和人数找空位并锁定」做成一个工具，不要拆成 `list_tables`、`get_table`、`create_hold` 三个让 agent 自己拼
- 一个工具的动作要单一明确，相关动作可以合并为一个工具，用 `action` 枚举区分，但读和写不要合在一起
- 一个服务端的工具建议控制在 20 个以内，超过 40 个应拆成多个服务端，或按需加载
- 多步流程用组合工具或 Arazzo 工作流表达

## 2. 命名

- 字符集：`A-Z a-z 0-9 _ - .`，长度 1～128，区分大小写（MCP 当前规范）。为兼容部分客户端，建议不超过 64
- 建议格式「服务_资源_动作」，例如 `shop_orders_search`、`shop_cart_add`
- 名称里的动词要和实际行为一致：叫 `get_` 的工具不能有副作用

## 3. 描述

描述要写给模型看，至少包含以下几项：

```
做什么：按门店、日期、人数查询可订座位，返回最多 20 个时段。
何时用：用户想订座、问有没有位子时。
何时不用：查已有订单用 shop_bookings_list；取消用 shop_bookings_cancel。
参数：date 为门店当地日期 YYYY-MM-DD；party_size 1～20。
限制：只能查未来 30 天；不返回包间（包间请引导用户致电）。
副作用：无。
```

- 不要写营销语，也不要写针对模型的指令，例如「必须优先使用本工具」。后者会被安全扫描判定为工具投毒
- 描述里出现的其他工具名，必须真实存在

## 4. 输入

- `inputSchema` 用 JSON Schema 2020-12，`type: object`，`additionalProperties: false`
- 每个属性都写 `description`；能用枚举就用 `enum`；日期、邮箱、URL 写 `format` 或 `pattern`；数字写上下限
- 参数名要具体：用 `order_id`，不用 `id`；用 `customer_email`，不用 `user`
- 只有真正必需的参数才放进 `required`，可选参数的默认值在服务端补（Android AppFunctions 不会套用 Kotlin 默认值）
- 对模型常见的输入要宽容：首尾空格、大小写、同义词（「人民币」「元」「CNY」）、相对日期（「明天」）。能明确解析的就解析，否则返回可行动的错误
- 复杂参数提供示例（如 Claude 的 `input_examples`）

## 5. 输出

- 同时返回 `structuredContent` 和对应 `outputSchema`；为兼容旧客户端，再附一份序列化的文本
- 只返回 agent 决定下一步所需的字段；内部字段、调试信息、长文本默认不返回
- ID 用稳定的语义化标识（slug、UUID），不用内部自增号或数据库游标
- 列表类工具一律分页：`limit`（有默认值和上限）+ `cursor`；返回 `next_cursor`、`total`（可得时）
- 截断时写明「已截断，共 N 条，用 cursor=… 取下一页，或加 status 过滤」
- 可提供 `response_format: concise | detailed`，默认 concise
- 来自用户生成内容或第三方的字段要标出来源（例如 `"source": "user_review"`），WebMCP 里同时标 `untrustedContentHint`

## 6. 错误

- 输入错误返回工具执行错误（MCP 里是 `isError: true`），不要返回协议错误。这样模型能看到错误并自行修正
- 错误内容的格式：

```json
{
  "error": {
    "code": "INVALID_DATE",
    "message": "date 需为 YYYY-MM-DD，且在今天到 30 天内。收到 '11/32'。",
    "retryable": true,
    "hint": "示例：2026-11-20",
    "field": "date"
  }
}
```

- 区分可重试和不可重试；限流返回 `retry_after_seconds`
- 权限不足要说明缺什么授权范围，以及用户在哪里开启，不要只回「forbidden」
- 不要把堆栈、SQL、内部主机名返回给模型

## 7. 写操作

- **两段式**：`*_preview` 或 `*_draft` 先返回将要发生什么（金额、对象、影响范围），以及 `confirmation_token`；再由 `*_commit` 执行。R3 的确认在系统 UI 或带外渠道完成，`confirmation_token` 只证明已预览，不等于已确认
- **幂等**：写入工具接受 `idempotency_key`（客户端生成），服务端在有效期内对同一键返回同一结果
- **并发**：更新类带 `expected_version` 或 ETag，冲突返回可行动错误
- **可撤销**：返回 `undo_token` 或撤销窗口截止时间；能软删就不要硬删
- **注解如实标注**：

| 注解 | 含义 | 标错的后果 |
|---|---|---|
| `readOnlyHint` | 不修改任何状态 | 写操作标成只读，客户端可能免确认直接执行 |
| `destructiveHint` | 可能有破坏性更新 | 客户端用它决定是否强确认 |
| `idempotentHint` | 重复调用无额外效果 | 影响重试策略 |
| `openWorldHint` | 会与外部世界交互（发邮件、联网） | 影响「致命三角」判断 |
| WebMCP `consequentialHint` | 高风险、不可逆、真实世界后果 | 浏览器 agent 用它决定是否请用户确认 |

注解只是提示，客户端不一定信。真正的控制必须在服务端执行（见 security.md）。

## 8. 长任务

- 预计超过 10 秒的任务做成异步：立即返回任务句柄，提供查询状态、取消的工具
- MCP 用官方 tasks 扩展；A2A 有内建的任务生命周期；HTTP API 用 202 + 状态 URL
- 任务句柄要绑定授权上下文，别人拿到句柄也查不到

## 9. 版本与变更

- 工具定义变更视同 API 变更：加字段可以，删字段、改语义要发新名称或新版本，旧版保留弃用期
- `tools/list` 顺序固定，便于客户端缓存
- 发布前对完整定义（含 schema 和注解）计算哈希，记录在变更日志里。客户端可以据此发现定义在批准后被偷偷修改的「掉包」行为

## 10. 平台对应关系

| 概念 | MCP | WebMCP | App Intents | AppFunctions | 鸿蒙 | A2A |
|---|---|---|---|---|---|---|
| 工具 | Tool | registerTool | AppIntent | @AppFunctionDeclaration | InsightIntent | Skill |
| 描述 | description | description | title / description / 参数摘要 | KDoc | displayDescription + 垂域 Schema | description + examples |
| 输入 | inputSchema | inputSchema | @Parameter | 函数参数 | params（按垂域 Schema） | Message Parts |
| 输出 | structuredContent | 返回值 | IntentResult | 返回值（@AppFunctionSerializable） | ExecuteResult | Artifact |
| 实体 | Resource | — | AppEntity / IndexedEntity | — | 意图共享的实体 | — |
| 确认 | 宿主 UI + 服务端 | consequentialHint | requestConfirmation | 由调用方 agent | 前台模式 | 任务状态 input-required |
| 长任务 | tasks 扩展 | — | 打开 App 继续 | — | 前台执行 | Task 生命周期 |
