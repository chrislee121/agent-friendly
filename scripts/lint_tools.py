#!/usr/bin/env python3
"""检查给 agent 用的工具契约。

输入可以是：
  - MCP tools/list 的结果：{"tools": [...]} 或 {"result": {"tools": [...]}}
  - 工具数组：[{"name": ..., "description": ..., "inputSchema": ...}, ...]
  - OpenAPI 3.x 文档（JSON）：每个操作按一个工具检查

有 error 时 exit 1。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
WRITE_VERBS = (
    "create", "add", "insert", "update", "edit", "set", "patch", "delete", "remove",
    "cancel", "send", "publish", "pay", "charge", "transfer", "refund", "reserve",
    "submit", "approve", "invite", "upload", "write", "commit", "purchase",
    "checkout", "rename", "archive", "revoke", "grant",
)
READ_VERBS = ("get", "list", "search", "find", "query", "read", "fetch", "lookup", "describe", "count")
LIST_VERBS = ("list", "search", "find", "query")
VAGUE_PARAMS = {"id", "data", "params", "obj", "object", "info", "value", "input", "payload", "args", "user", "item", "body"}
IDEMPOTENCY_PARAMS = {"idempotency_key", "idempotencykey", "request_id", "requestid", "client_request_id", "dedupe_key", "dedup_key"}
PAGINATION_PARAMS = {"limit", "page_size", "pagesize", "per_page", "cursor", "page", "offset", "page_token", "pagetoken", "max_results"}
DATE_HINT = re.compile(r"(date|time|_at$|_on$|deadline|birthday)", re.I)
USAGE_HINT = re.compile(r"(用于|当|适用|不要|不适用|何时|use when|use this|when the user|do not|don't|instead)", re.I)
INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)",
    r"忽略(之前|以上|上面|先前)的",
    r"<\s*important\s*>",
    r"do not (tell|mention|inform|reveal)[^.]{0,40}user",
    r"不要(告诉|告知|透露给)用户",
    r"system prompt",
    r"系统提示词",
    r"before (using|calling) (any )?(other )?tools?",
    r"(~/\.ssh|id_rsa|\.env\b|/etc/passwd)",
    r"you must (always )?(call|use) this tool",
]


@dataclass
class Finding:
    level: str
    rule: str
    tool: str
    message: str


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict | None
    output_schema: dict | None = None
    annotations: dict = field(default_factory=dict)
    origin: str = "mcp"
    http_method: str | None = None
    extra: dict = field(default_factory=dict)


def load_tools(data) -> list[Tool]:
    if isinstance(data, dict) and "openapi" in data:
        return tools_from_openapi(data)
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        data = data["result"]
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]
    if not isinstance(data, list):
        raise ValueError("无法识别的输入：需要 MCP tools/list 结果、工具数组或 OpenAPI 3.x 文档")
    tools = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        tools.append(Tool(
            name=str(raw.get("name", "")),
            description=str(raw.get("description") or ""),
            input_schema=raw.get("inputSchema"),
            output_schema=raw.get("outputSchema"),
            annotations=raw.get("annotations") or {},
        ))
    return tools


def tools_from_openapi(doc: dict) -> list[Tool]:
    tools = []
    global_security = doc.get("security")
    for path, item in (doc.get("paths") or {}).items():
        shared_params = item.get("parameters", []) if isinstance(item, dict) else []
        for method, op in (item or {}).items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head"}:
                continue
            props, required = {}, []
            for p in shared_params + op.get("parameters", []):
                if "$ref" in p:
                    continue
                props[p.get("name", "")] = {**(p.get("schema") or {}), "description": p.get("description", "")}
                if p.get("required"):
                    required.append(p.get("name", ""))
            body = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema") or {}
            if body.get("type") == "object":
                props.update(body.get("properties") or {})
                required.extend(body.get("required") or [])
            schema = {"type": "object", "properties": props}
            if required:
                schema["required"] = required
            if body.get("additionalProperties") is False:
                schema["additionalProperties"] = False
            m = method.lower()
            ann = {"readOnlyHint": m in {"get", "head"}}
            if m in {"put", "delete"}:
                ann["idempotentHint"] = True
            if m == "delete":
                ann["destructiveHint"] = True
            responses = op.get("responses") or {}
            tools.append(Tool(
                name=op.get("operationId") or "",
                description=" ".join(x for x in [op.get("summary", ""), op.get("description", "")] if x),
                input_schema=schema,
                output_schema=None,
                annotations=ann,
                origin="openapi",
                http_method=m.upper(),
                extra={
                    "path": path,
                    "has_4xx": any(str(code).startswith("4") for code in responses),
                    "has_security": op.get("security", global_security) not in (None, []),
                },
            ))
    return tools


def words(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return [w for w in re.split(r"[_.\-]+", spaced.lower()) if w]


def implies_write(name: str) -> bool:
    return any(w in WRITE_VERBS for w in words(name))


def implies_read(name: str) -> bool:
    ws = words(name)
    return bool(ws) and any(w in READ_VERBS for w in ws) and not implies_write(name)


def all_descriptions(tool: Tool) -> list[str]:
    texts = [tool.description]
    for prop in ((tool.input_schema or {}).get("properties") or {}).values():
        if isinstance(prop, dict):
            texts.append(str(prop.get("description") or ""))
    return texts


def lint(tools: list[Tool]) -> list[Finding]:
    out: list[Finding] = []
    add = lambda level, rule, tool, msg: out.append(Finding(level, rule, tool, msg))

    if len(tools) > 40:
        add("warn", "T060", "*", f"工具数量 {len(tools)} 个，超过 40。建议拆分服务端或按需加载")
    elif len(tools) > 20:
        add("info", "T060", "*", f"工具数量 {len(tools)} 个，超过 20。确认每个都必要")

    seen: dict[str, int] = {}
    for t in tools:
        seen[t.name] = seen.get(t.name, 0) + 1

    for t in tools:
        n = t.name or "<无名>"
        if not NAME_RE.match(t.name):
            add("error", "T001", n, "名称须为 1～128 个字符，只能包含 A-Z a-z 0-9 _ - .")
        elif len(t.name) > 64:
            add("warn", "T001", n, "名称超过 64 个字符，部分客户端可能截断")
        if t.name and (t.name[0] in "-." or t.name[-1] in "-."):
            add("warn", "T001", n, "名称以 - 或 . 开头或结尾，部分客户端解析会出问题")
        if seen.get(t.name, 0) > 1:
            add("error", "T002", n, "名称重复")
        if len(tools) > 10 and len(words(t.name)) < 2:
            add("info", "T003", n, "工具较多时建议用「服务_资源_动作」命名，减少与其他服务冲突")

        d = t.description.strip()
        if not d:
            add("error", "T010", n, "缺少描述")
        elif len(d) < 60:
            add("warn", "T011", n, f"描述只有 {len(d)} 个字符。写清做什么、何时用、何时不用、参数、限制、副作用")
        elif not USAGE_HINT.search(d):
            add("info", "T012", n, "描述里没有说明何时用 / 何时不用")

        for text in all_descriptions(t):
            for pat in INJECTION_PATTERNS:
                if re.search(pat, text, re.I):
                    add("error", "T050", n, f"描述中出现疑似注入或投毒语句：/{pat}/")
                    break

        s = t.input_schema
        if not isinstance(s, dict):
            add("error", "T020", n, "缺少 inputSchema")
            props = {}
        else:
            if s.get("type") != "object":
                add("error", "T020", n, "inputSchema 的 type 须为 object")
            props = s.get("properties") or {}
            if t.origin == "mcp" and s.get("additionalProperties") is not False:
                add("warn", "T021", n, "建议设置 additionalProperties: false，只接受已声明的参数")
            for req in s.get("required") or []:
                if req not in props:
                    add("error", "T024", n, f"required 里的 {req} 没有在 properties 中定义")
            for pname, pdef in props.items():
                pdef = pdef if isinstance(pdef, dict) else {}
                if not str(pdef.get("description") or "").strip():
                    add("warn", "T022", n, f"参数 {pname} 缺少描述")
                if pname.lower() in VAGUE_PARAMS:
                    add("warn", "T023", n, f"参数名 {pname} 太笼统，建议写成 order_id、customer_email 这类具体名称")
                if (pdef.get("type") == "string" and DATE_HINT.search(pname)
                        and not (pdef.get("format") or pdef.get("pattern") or pdef.get("enum"))):
                    add("info", "T025", n, f"参数 {pname} 看起来是日期或时间，建议写 format 或 pattern")

        prop_keys = {k.lower() for k in props}
        a = t.annotations or {}
        ro = a.get("readOnlyHint")
        is_write = implies_write(t.name) or ro is False

        if "readOnlyHint" not in a:
            add("warn", "T030", n, "未声明 readOnlyHint")
        if implies_write(t.name) and ro is True:
            add("error", "T031", n, "名称表明是写操作，却标了 readOnlyHint: true。客户端可能免确认直接执行")
        if is_write and ro is not True:
            if "destructiveHint" not in a or "idempotentHint" not in a:
                add("warn", "T032", n, "写操作要同时声明 destructiveHint 和 idempotentHint")
            if a.get("idempotentHint") is not True and not (prop_keys & IDEMPOTENCY_PARAMS):
                add("warn", "T033", n, "非幂等写操作建议接受 idempotency_key，防止重试重复执行")
            if a.get("destructiveHint") is True:
                add("info", "T034", n, "破坏性工具：确认必须在服务端强制执行，不能只依赖注解")
        if ro is True and t.origin == "mcp" and not t.output_schema:
            add("info", "T040", n, "只读工具建议提供 outputSchema 并返回 structuredContent")
        if any(w in LIST_VERBS for w in words(t.name)) and not (prop_keys & PAGINATION_PARAMS):
            add("warn", "T041", n, "列表或搜索类工具缺少分页参数（limit / cursor）")

        if t.origin == "openapi":
            if not t.extra.get("has_4xx"):
                add("warn", "T070", n, f"{t.http_method} {t.extra.get('path')} 没有定义 4xx 响应，agent 拿不到可行动的错误")
            if not t.extra.get("has_security"):
                add("info", "T071", n, f"{t.http_method} {t.extra.get('path')} 没有声明 security，确认是否本应公开")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="检查给 agent 用的工具契约")
    ap.add_argument("file", help="MCP tools/list JSON、工具数组 JSON 或 OpenAPI 3.x JSON")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quiet-info", action="store_true", help="不显示 info")
    args = ap.parse_args()

    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        tools = load_tools(data)
    except (OSError, ValueError) as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 2

    findings = lint(tools)
    if args.quiet_info:
        findings = [f for f in findings if f.level != "info"]
    counts = {lvl: sum(f.level == lvl for f in findings) for lvl in ("error", "warn", "info")}

    if args.json:
        print(json.dumps({
            "tools": len(tools),
            "counts": counts,
            "findings": [f.__dict__ for f in findings],
        }, ensure_ascii=False, indent=2))
    else:
        order = {"error": 0, "warn": 1, "info": 2}
        for f in sorted(findings, key=lambda f: (order[f.level], f.tool, f.rule)):
            print(f"[{f.level:5}] {f.rule} {f.tool}: {f.message}")
        print(f"\n共 {len(tools)} 个工具：error {counts['error']}，warn {counts['warn']}，info {counts['info']}")
        print("FAIL" if counts["error"] else "PASS")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
