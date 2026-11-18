# 评分卡：〈系统名〉

依据 references/scorecard.md。每个分数都要有证据，没有证据按 0 分。

| 维度 | 分（0～4） | 证据 |
|---|---|---|
| D1 可发现 | | |
| D2 可理解 | | |
| D3 可操作 | | |
| D4 身份与授权 | | |
| D5 人的控制 | | |
| D6 可靠性 | | |
| D7 安全 | | |
| D8 可追溯与合规 | | |
| D9 评测与运营 | | |

| 红线 | pass / fail / na | 证据 |
|---|---|---|
| H1 | | |
| H2 | | |
| H3 | | |
| H4 | | |
| H5 | | |
| H6 | | |
| H7 | | |
| H8 | | |

填好后转成 JSON（格式见 references/scorecard.md 第 4 节或 `examples/scorecard.sample.json`）：

```bash
python3 scripts/score.py agent-friendly/scorecard.json --gate L3
```

结论：

- 等级：
- 加权分：
- 是否达到目标等级：
- 阻塞项：
