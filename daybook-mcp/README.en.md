# daybook MCP · Xuanji (璇玑)

**Query.** Expose daybook's append-only volumes to any MCP client as an MCP server —
**no new storage, no new protocol, no new dependency.**

> Name "Xuanji" (璇玑) comes from the *Book of Documents · Canon of Shun*: "he examined the
> Xuanji and Yuheng, thereby regulating the seven luminaries" — an ancient instrument for
> observing, converting, and reading out. **Observe / convert / read out** is exactly the
> office of MCP: **reach out, translate, read back.**

---

## In one line

**The ledger does not change; only its outward face does.** Xuanji is a thin interface over
the same volumes: truth stays in the volumes — it only **reads them out and writes them back**.

---

## Feature highlights

### 1. Ten tools

| Tool | Purpose | Requires signature |
|---|---|---|
| `daybook_list` | List every volume registered in `daybook.conf [卷]` (path / lines / bytes) | no |
| `daybook_query` | Query entry text by field (volume / lineno / time / tag / title / author; substring match) | no |
| `daybook_append` | **Append** one entry · append-only · atomic · **author-ID red line** (`author ≡ agent_id` + signature) | **yes** |
| `daybook_unread` | Unread entries for an agent on a volume (after its cursor) | **yes** |
| `daybook_mark_read` | Advance the read cursor to the end of the volume | **yes** |
| `daybook_heartbeat` | Register a heartbeat (appends a `[心跳]` entry) | **yes** |
| `daybook_alive` | Is an agent online? (within 120 s by default) | no |
| `daybook_index` | Rebuild all volume indexes | **yes** |
| `cross_ref_make` | Create a cross-volume reference `[volume#Lline-SHA8]` | no |
| `cross_ref_verify` | Verify a cross-volume reference | no |

### 2. Volumes as resources + subscription

- **`resources/list`**: exposes **every volume** registered in `daybook.conf [卷]` as
  `daybook://<volume>` with size / lines / mtime.
- **`resources/read`**: `daybook://<volume>` supports **line ranges** (offset / limit); reads are
  **written to the audit volume**.
- **`resources/subscribe` / `unsubscribe`**: subscribe to a volume → **mtime polling** → on change,
  push `notifications/resources/updated`. Zero dependency (no watchdog); the subscription table is
  **in-memory** and cleared on restart (per the MCP spec).

### 3. Four prompts

`daily_journal` (daily template) · `weekly_review` (weekly roundup) · `cross_ref_audit` (audit cross-refs) ·
`agent_handover` (handover template).

### 4. Five security pillars

1. **Writes require a signature**: HMAC-SHA256; `author ≡ registered agent_id` (**anti-impersonation**).
2. **Volume-name allowlist + traversal guard**: rejects `..`, `/`, `\`, and absolute paths.
3. **Append-only audit volume**: every `tools/call` and `resources/read` is recorded (white box).
4. **Anti-junk addressing**: `to` must be a **registered** agent.
5. **Failures return `isError:true`** (not swallowed as an internal JSON-RPC error) so the model **sees** them.

### 5. Server / protocol surface

| Item | Value |
|---|---|
| Transport | JSON-RPC 2.0 over newline-delimited **stdio** |
| Protocol version | MCP `2024-11-05` |
| Server name | `daybook-mcp` (`1.8.1`) |
| Capabilities | `resources` (listChanged, **subscribe**) · `tools` · `prompts` |
| Dependencies | **Zero** (Python 3 standard library only; hand-rolled JSON-RPC, no MCP SDK) |

---

## Run it

```bash
cd daybook-mcp
python3 mcp_server.py          # serve over stdio; clients talk JSON-RPC
```

Plug into any MCP client: configure `mcp_server.py` as a **stdio server**.
The `DAYBOOK_ROOT` environment variable sets the volume root (defaults to the script's directory).

## What you can change

- **Volume table**: edit `daybook.conf [卷]` (one volume per line: `name = path`).
- **Audit**: read `MCP审计卷.txt` (append-only).

## Boundaries (honest)

- **No semantic search**: `daybook_query` is **field + substring** matching, not vector / semantic search.
- **stdio, single-machine**: cross-host requires another transport.
- **Subscription is best-effort push**: in-memory table, mtime polling, cleared on restart; **the volume is always the authority**.

## Relation to the other two

| Product | Box | Office |
|---|---|---|
| Journal | `daybook` | ledger + recording (base) |
| **Xuanji** | **`daybook-mcp`** | **query** |
| Sinan | `daybook-orch` | orchestrate |

All three share **one base** (append-only volumes), **one promise** (zero dependency), **one truth**.

## Version

`版本.txt`: a package's version = **the sum of lines of its product `.py` files** (daybook's old rule; recomputable).

## License

MIT. See [`LICENSE`](LICENSE).

The three packages share one **per-file** licensing scheme; see [`LICENSING.md`](LICENSING.md).

## Authors

- **纵贯线**：斯坦森、皮特、汤姆、史泰龙
- **手艺人老宋**
- <songliansheng@vip.sina.com>

---

daybook-suite · daybook-mcp (Xuanji · 璇玑)
