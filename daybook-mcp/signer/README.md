# daybook-signer（4.0.7 随包）

stdio 签名代理，版本 `0.2.0`，协议 `mcp-stdio-signer/1`。

- 客户端仍按标准 MCP 说话；代理只对写调用 `daybook_append` 补
  `agent_id + ts + signature`，其余 JSON-RPC 原样透传。
- 密钥只从账本根 `.daybook_keys/<agent_id>.key` 读取，权限必须恰好 `600`；
  不写入日志、审计、命令行。审计只记密钥 SHA-256 指纹前 8 位。
- 密钥不可用时只拒写，只读调用继续可用。
- 审计落在 `<base>/audit/sign_audit.jsonl`，每行 prev/self 哈希链；
  外部核对器 `verify_audit.py` 会回产品边车与账本行逐条验 sha 与 HMAC。

启动：

```sh
DAYBOOK_ROOT=/path/to/ledger DAYBOOK_SERVER=/path/to/mcp_server.py \
  ./daybook-signer <label>
```

`<label>` 由 `daybook-setup install` 注册；启动器从注册卷自动映射 `label → agent_id`。
