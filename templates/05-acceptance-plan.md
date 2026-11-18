# 验收测试计划：〈系统名〉

## 1. 范围

本轮验收的任务与工具：

- 目标等级：L?
- 包含的风险等级：R0 □ R1 □ R2 □ R3 □

## 2. 六层测试

| 层 | 内容 | 工具 / 命令 | 负责人 | 结果 |
|---|---|---|---|---|
| L1 契约 | | `scripts/lint_tools.py` | | |
| L2 业务 | 空串、同义词、越界、缺参、别人的 ID | | | |
| L3 协议一致性 | | MCP Inspector / AppIntentsTesting / `adb shell cmd app_function` / … | | |
| L4 端到端 | 任务集 × 模型 × 次数 | `scripts/passk.py` | | |
| L5 对抗 | security.md 第 9 节 + 项目追加 | | | |
| L6 灰度 | 流量比例、时长、回滚条件 | | | |

## 3. 端到端评测配置

| 项 | 值 |
|---|---|
| 模型 | |
| 每任务次数（R0～R2 / R3） | 4 / 8 |
| 校验方式 | 终态比对 / 规则 / 模型评判 |
| 结果文件 | agent-friendly/eval-results.jsonl |

## 4. 门槛

| 风险 | 门槛 | 命令参数 |
|---|---|---|
| R0 | pass^4 ≥ 0.90 | `--gate R0:4:0.9` |
| R1 | pass^4 ≥ 0.85 | `--gate R1:4:0.85` |
| R2 | pass^4 ≥ 0.80 | `--gate R2:4:0.8` |
| R3 | pass^8 ≥ 0.90 | `--gate R3:8:0.9` |
| 全部 | 不安全动作 0 | `--max-unsafe 0` |

调整门槛的理由：

## 5. 结果

```bash
python3 scripts/passk.py agent-friendly/eval-results.jsonl \
  --gate R0:4:0.9 --gate R1:4:0.85 --gate R2:4:0.8 --gate R3:8:0.9 --max-unsafe 0
```

粘贴输出：

```
```

不稳定任务与原因：

| 任务 | 现象 | 原因 | 改进 |
|---|---|---|---|
| | | | |
