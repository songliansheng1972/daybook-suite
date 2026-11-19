# DAYBOOK MCP 接入说明（DEEPSEEK HARNESS / WORKBUDDY / TRAE）

本目录给三个客户端各留一份 stdio 配置模板。4.0.7 起推荐用随包安装器
`setup/daybook-setup install`：一条命令完成运行副本、本机密钥、签名代理与三家客户端配置，
用户不需要手写 HMAC，也不需要看密钥。

## 1. 基本信息 / Basics

| 项 | 值 |
|---|---|
| 启动命令 | `~/.daybook-mailroom/signer/daybook-signer <label>`（安装器写入；label = trae / workbuddy / deepseek-harness） |
| 传输 | stdio（换行分隔 JSON-RPC 2.0） |
| 协议版本 | `2024-11-05` |
| conf 目录 | `DAYBOOK_ROOT=/path/to/daybook-ledger`（放 `daybook.conf` 的目录；账本根由 conf 的 `[index] root` 决定） |
| 身份 | 代理按注册卷自动把 `label → agent_id` 映射；客户端不需要填 `DAYBOOK_AGENT_ID` |
| 工具面 | **4 个**：`daybook_query` / `daybook_list` / `daybook_append` / `cross_ref_verify` |
| 写权限 | **本机同 uid 可信 + 本机签名代理留痕**（见第 2 节）；不是「持有密钥才能写」 |

## 2. 写权限的真实边界 / The real boundary

4.0.6 底本原文（`daybook-mcp/mcp-clients/README.md:20`）写的是：
`| 写权限 | **不提供**。开写前置是密钥轮换，方案另出，未获批准前不开放 |`。
4.0.7 按实际形态改口径，**这是有边界的降级，不是等价替代**：

1. **本机同 uid 可信**：同一 OS 用户下的进程可读取 `.daybook_keys/<agent_id>.key`（600）并代签；
   签名代理挡不住同 uid 的本地进程。密钥是签名材料，不是访问控制。
2. **签名留痕**：每次写都有 `agent_id`、时间、HMAC-SHA256、审计行（`audit/sign_audit.jsonl`，
   prev/self 哈希链）与账本行锚点；`signer/verify_audit.py` 可独立回边车与账本行核对。

签名代理的职责与边界：

- 只对写工具 `daybook_append` 补 `agent_id + ts + signature`，其余 JSON-RPC 原样透传；
- 密钥只从账本根 `.daybook_keys/` 读取，权限必须恰好 600；不写入日志、审计或命令行；
- 密钥不可用时只拒写，只读调用继续可用；
- **非同 uid / 远程 / 第三方客户端不适用**；本版没有密钥轮换。

### 六条撤回条件（照抄 `#84111`，不重写）

1. 密钥内容或完整密钥文件出现在报告、日志、命令行、审计行、聊天记录或仓库中；
2. verify_audit.py 报哈希链断裂、head 不符、边车/账本锚点不符或 HMAC 验签失败；
3. 不经代理的未签名写被服务端接受；
4. 代理被绕过、替换或崩溃后仍产生成功写，或出现无法归属的写行；
5. 需要把写权限提供给非同 uid、远程或第三方客户端；
6. 密钥轮换完成或发布方给出正式开写方案。

出处：`#84111`；本地底稿 `纵贯线条文_MCP写权限边界降级_20261118.r2.txt:19-24`。

## 3. 两个接入方 / The clients

- **DEEPSEEK HARNESS**：用 `deepseek-harness.json`。
- **WORKBUDDY**：用 `workbuddy.json`。
- 两份模板的 `command` 指向安装器生成的签名代理；`args` 的 label 与注册身份一致。
- 生产 conf 用真实 `daybook.conf`；发布包内 `daybook-mcp/daybook.conf` 是空卷样板。

## 4. 自检方法 / Self-check

接入后先做这一步，**拿到 `daybook://2026`、资源数非零、工具数 = 4 才算接上**：

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"resources/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/list"}' \
| DAYBOOK_ROOT=/path/to/daybook-ledger \
  /path/to/daybook-suite/daybook-mcp/daybook-mcp
```

判据：

1. `resources/list` 里有 `daybook://2026`；
2. 资源数为 **1**（不是 0）；
3. `tools/list` 里工具数为 **4**，且不含 `daybook_unread` / `daybook_mark_read` /
   `daybook_heartbeat` / `daybook_alive` / `daybook_index` / `cross_ref_make` /
   `daybook_multi_query`。

> 若显式加 `MCP_READ_ONLY=1`，工具数是 **3**（唯一写工具 `daybook_append` 被隐藏），
> 这是只读模式的预期值，不是故障。

失败时：stderr 出现 `WARN 自检：volumes 为空` 或 `FATAL 启动自检失败`，按提示检查 conf 与
`DAYBOOK_ROOT`——**服务不会静默返回 0 个资源**。

## 5. 调度语义的出口（4.0.7 移出 MCP）

收件与在场语义没有删，移到司南 CLI：

```sh
python3 daybook-orch/orchestrator.py --home /path/to/ledger unread  <agent_id> <卷>
python3 daybook-orch/orchestrator.py --home /path/to/ledger mark_read <agent_id> <卷>
python3 daybook-orch/orchestrator.py --home /path/to/ledger heartbeat <agent_id> [--load 0.3]
python3 daybook-orch/orchestrator.py --home /path/to/ledger alive <agent_id> [--timeout 120]
```

维护面：`python3 daybook.py index`、`python3 daybook.py multiindex`、`python3 cross_ref.py make <卷> <行号>`。

## 6. 边界 / Boundaries

- 本版写权限只覆盖本机同 uid；非同 uid / 远程 / 第三方不适用。
- 不承诺唤醒：`digest --push` 仍是尽力推送，MCP 客户端没有 server→client 主动唤醒通道。
- 不修改 `<你的开源版目录>` 下任何文件。
