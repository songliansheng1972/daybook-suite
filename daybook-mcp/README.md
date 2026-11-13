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

## 十一个工具 · 资源 · 提示

- **tools（11）**：`daybook_list` `daybook_query` `daybook_append` `daybook_unread` `daybook_mark_read` `daybook_heartbeat` `daybook_alive` `daybook_index` `cross_ref_make` `cross_ref_verify` **`daybook_multi_query`**
- **resources**：`daybook://<卷名>`（list / read 行范围 / subscribe）＋ **`daybook://catalog/<卷>`、`daybook://catalog/catalog`**（四库式多级目录·text/markdown）
- **prompts（4）**：`daily_journal` `weekly_review` `cross_ref_audit` `agent_handover`

### 多级目录 · 按需下钻（v3.1）

账本侧 `python3 daybook.py multiindex` 生成**部(卷)→类→属(条目)** 的层级目录（派生件·可删可重建）后，
本包即可把它**当资源读**、**按下钻查**：

```
daybook_multi_query(level='部')                  # 各卷概览（条数／二级组数）
daybook_multi_query(volume='协作', level='类')    # 该卷二级分组计数
daybook_multi_query(cls='核', limit=20)          # 命中条目提要行（每条附互见引用 ↪[卷#L行-SHA8]）
daybook_multi_query(volume='协作', full=True)     # 需要时取全文
```

⇒ **LLM 不必拉全卷**：上下文限制转成「按需查询」。未生成目录时，资源不列、工具给友好指引（不崩）。

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
