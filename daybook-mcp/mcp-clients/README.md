# DAYBOOK MCP 只读接入说明（DEEPSEEK HARNESS / WORKBUDDY）
# DAYBOOK MCP read-only integration (DEEPSEEK HARNESS / WORKBUDDY)

本目录给两个待接入方各留一份 stdio 配置模板。**一律只读**：`MCP_READ_ONLY=1`，
四个写工具（`daybook_append` / `daybook_mark_read` / `daybook_heartbeat` / `daybook_index`）
在 `tools/list` 中不出现，直呼也返回 `isError:true`。

Templates for the two pending clients, stdio only. Read-only is mandatory: with
`MCP_READ_ONLY=1` the four write tools are hidden from `tools/list` and rejected when called.

## 1. 基本信息 / Basics

| 项 | 值 |
|---|---|
| 启动命令 | `/Users/song/Desktop/daybook-suite/daybook-mcp/daybook-mcp` |
| 传输 | stdio（换行分隔 JSON-RPC 2.0） |
| 协议版本 | `2024-11-05` |
| 账本根 | `DAYBOOK_ROOT=/Users/song/Desktop/小数学家/daybook-ledger`（示例值，换成自己的账本根）。**发布版内置 conf 是空卷样板，必须显式给 `DAYBOOK_ROOT` 或改 conf，否则启动告警 `volumes 为空`** |
| 身份 | `DAYBOOK_AGENT_ID`（模板里是占位值，改成实际 agent_id；也可在请求 `_meta.agentId` 里逐条携带） |
| 写权限 | **不提供**。开写前置是密钥轮换，方案另出，未获批准前不开放 |

## 2. 两个接入方 / The two clients

- **DEEPSEEK HARNESS**：用 `deepseek-harness.json`。把 `mcpServers.daybook` 并入其 MCP 配置
  （若其配置键为 `servers`，把外层键名改掉即可，内层字段不变）。
- **WORKBUDDY**：用 `workbuddy.json`，同上。
- `DAYBOOK_AGENT_ID` 分别留了 `DEEPSEEK_HARNESS` / `WORKBUDDY` 作为占位，按实际 agent_id 替换。
- 两份模板都写入了显式 `DAYBOOK_ROOT`（示例账本根，按实际替换）；发布版包内
  `daybook-mcp/daybook.conf` 是空卷样板，不设 `DAYBOOK_ROOT` 会按 `[index] root` 解析并告警 0 卷。
  生产接入请用真实 conf，或始终显式传 `DAYBOOK_ROOT`。

## 3. 自检方法 / Self-check

接入后先做这一步，**拿到 `daybook://2026` 且资源数非零才算接上**：

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"resources/list"}' \
| MCP_READ_ONLY=1 DAYBOOK_ROOT=/Users/song/Desktop/小数学家/daybook-ledger \
  /Users/song/Desktop/daybook-suite/daybook-mcp/daybook-mcp
```

期望（stderr 一行 + stdout 两行）：

```
[daybook-mcp] root=/Users/song/Desktop/小数学家/daybook-ledger volumes=1
{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", ...}}
{"jsonrpc": "2.0", "id": 2, "result": {"resources": [{"uri": "daybook://2026", "size": 1502, ...}]}}
```

判据：
1. `resources/list` 里有 `daybook://2026`；
2. 资源数为 **1**（不是 0）；
3. `tools/list` 里没有四个写工具。

失败时：stderr 出现 `WARN 自检：volumes 为空` 或 `FATAL 启动自检失败`，按提示检查 conf 与
`DAYBOOK_ROOT`——**服务不会静默返回 0 个资源**。

## 4. 边界 / Boundaries

- 本轮只开只读；写工具不开放。
- 开写的前置是密钥轮换（影响面、旧内联明文处置、轮换后各 agent 重发），方案另出，未批准前不动手。
- 不修改 `/Users/song/Desktop/小数学家/开源版/` 下任何文件。
