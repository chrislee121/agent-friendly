# 支持的 Agent Runtime

基于 [Agent Skills](https://agentskills.io) 协议。

## 推荐安装

```
帮我安装这个 skill：https://github.com/chrislee121/agent-friendly
```

```bash
npx skills add chrislee121/agent-friendly
```

指定 runtime 时加 `-a cursor` / `-a claude-code` / `-a codex` 等。

## 手动安装（用户级）

把本仓库放到对应 `skills/` 目录，目录名保持 `agent-friendly`：

| Runtime | 典型路径 |
|---------|----------|
| Cursor | `~/.cursor/skills/agent-friendly/` |
| Claude Code | `~/.claude/skills/agent-friendly/` |
| Codex | `~/.codex/skills/agent-friendly/` |
| OpenClaw | `~/.openclaw/workspace/skills/agent-friendly/` |
| Gemini CLI | `~/.gemini/skills/agent-friendly/` |
| OpenCode | `~/.config/opencode/skills/agent-friendly/` |

项目级也可放在 `.cursor/skills/`、`.agents/skills/`。

## 依赖

脚本只用 Python 3.9+ 标准库，无需安装第三方包。`scan_site.py` 需要能访问目标网站。
