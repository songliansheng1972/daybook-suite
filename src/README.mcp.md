# daybook MCP · 璇玑

**账不变，只换一个面朝外。** 把 daybook 的 append-only 卷，以 MCP 服务器暴露给任意客户端——  
不新建存储、不新协议、不新依赖。纯文本，人机可读。

> 名号「璇玑」：《尚书·舜典》「在璇玑玉衡，以齐七政」——古之观星、换算、读出的器具。  
> **璇玑＝观／换算／读出**，正合 MCP 之职。

## 特点

- **薄接口** —— 真相仍在卷里，它只把卷**读出去、写回来**。
- **零依赖** —— 只 Python 3 标准库；自实现 JSON-RPC，不引 MCP SDK。
- **卷即资源** —— 每一卷都是 `daybook://<卷名>`，支持行范围读、可订阅（mtime 轮询推更新）。
- **写必验签** —— HMAC-SHA256，作者须为已注册 agent（**防冒名**）；审计卷 append-only。

## 十个工具 · 资源 · 提示

- **tools（10）**：`daybook_list` `daybook_query` `daybook_append` `daybook_unread` `daybook_mark_read` `daybook_heartbeat` `daybook_alive` `daybook_index` `cross_ref_make` `cross_ref_verify`
- **resources**：`daybook://<卷名>`（list / read 行范围 / subscribe）
- **prompts（4）**：`daily_journal` `weekly_review` `cross_ref_audit` `agent_handover`

## 怎么跑

```bash
cd daybook-mcp
python3 mcp_server.py        # JSON-RPC 2.0 over stdio
```

把 `mcp_server.py` 配成任意 MCP 客户端的 **stdio server** 即可。`DAYBOOK_ROOT` 可指定卷根（默认脚本所在目录）。

## 边界（诚实）

- 查询是**字段＋子串**匹配，不是语义 / 向量检索。
- stdio 单机；跨主机须另配传输。
- 订阅是**尽力推送**（内存表、重启即清）；**权威永远在卷里**。

## 许可

MIT。见 `LICENSE`。

## 作者

- **纵贯线**：斯坦森、皮特、汤姆、史泰龙
- **手艺人老宋**
- <songliansheng@vip.sina.com>
