# daybook ORCH · Sinan (司南)

**Orchestrate.** Turn daybook's append-only volumes into an operating system for multiple agents —
**not by building a scheduler, but by deterministic table lookup.**

> Name "Sinan" (司南) comes from the *Han Feizi · Having Standards*: "the ancient kings set up the
> **Sinan** to fix dawn and dusk" — an instrument that fixes direction, **the same for every asker**.
> **For one and the same entry, any moment, any asker, gets the same next hand.**
> That is precisely the divide between this and "let the LLM guess the next hand":
> **the orchestrator contributes no intelligence — only direction.**

---

## In one line

**No new storage, no new protocol, no new dependency.** Orchestration is just a **deterministic
table lookup** for "who should act, and up to which step"; truth stays in the volumes.

---

## Feature highlights

### 1. Eleven verbs

| Verb | Effect |
|---|---|
| `join` | Enlist (issues an `agent_id` + secret) |
| `leave` | Depart |
| `who` | Presence (registry × heartbeat) |
| `open` | Open a task (appends `[工]`) |
| `claim` | Claim a task (**locked** · todo → in-progress · no double-claim) |
| `submit` | Submit work (appends `[报·致=复审]`) |
| `review` | Adjudicate (appends `[审]`; **pass / reject**) |
| `pull` | Pull your queue (**table lookup** for the next hand = non-author) |
| `board` | Board (by state) |
| `alarm` | Health check (lost / orphaned / stalled) |
| `selftest` | End-to-end self-test (**9/9**) |

### 2. Six primitives (welded into one loop)

| Primitive | Module | Office |
|---|---|---|
| Identity | `agent_registry.py` | HMAC-SHA256 · unforgeable · revocable · append-only registry |
| Task | `task_volume.py` | Five-state machine (below) · append-only · **never rewrites history** |
| Lock | `agent_lock.py` | `fcntl.flock` + **TTL lease** (60 s default · renew / release / force-release · fenced token) |
| Presence | `agent_heartbeat.py` | Heartbeat volume · dead if missing ≥3 cycles |
| Message | `agent_message.py` | Unix socket (TCP loopback fallback) · `notify/request/response/broadcast` · append-only inbox volume |
| Reference | `cross_ref.py` | `[volume#Lline-SHA8]` · **tamper-proof** · reverse-lookup |
| **Routing** | **`orchestrator.py`** | **class → role → person (deterministic table lookup)** |

### 3. State machine (five states · terminal refuses to move)

```
todo ─▶ in-progress ─▶ done ─▶ in-review ─▶ reviewed(terminal)
                 ▲              │
                 └── rejected ──┘
any ─▶ cancelled (append-only, leaves a trace)
```

### 4. Two tables (plain text · human-readable and editable · **never buried in code**)

- **`orchestration_routing.conf`**: `class[:keyword] = role`
  (e.g. `报=复审` · `报:驳回=返工` · `审=终审` · `裁=广播`)
- **`orchestration_roles.conf`**: `role = person list`, including **`@非作者:角色`** (implements "**no self-review**")

### 5. Three commandments

1. **Read only header fields** (class / to / author) + keyword substring match — **never infer from body semantics** (reading semantics degrades back to LLM guessing).
2. **Never write shadow state** — everything lands in append-only volumes; boards / inboxes are **derived artifacts, deletable and rebuildable**.
3. **Tables are human-readable and editable** — change a rule → re-run → it is reborn.

> Essence: **settled by lookup, not by inference.**

### 6. The loop

```
join ─▶ open[工] ─▶ claim(locked · todo→in-progress)
                        │
                        ▼
             submit[报·致=复审] (→done→in-review)
                        │
                        ▼
             pull(lookup = non-author) ─▶ review[审]
                        │                    ├─ pass → reviewed (terminal)
                        └────────────────────┴─ reject → in-progress (rework)
```

---

## Run it

```bash
cd daybook-orch
python3 orchestrator.py selftest        # end-to-end self-test 9/9
python3 orchestrator.py join 汤姆         # enlist
python3 orchestrator.py open "implement X" --by 汤姆
python3 orchestrator.py claim T001 ag-xxxx
python3 orchestrator.py pull 皮特         # pull the queue (routing projection)
python3 orchestrator.py board            # board
python3 orchestrator.py alarm            # health check
```

- `--root DIR` sets the volume root (defaults to this directory); `--rule / --roles` swap the routing / roles tables.
- Also reachable via the `daybook` entry point: `python3 daybook.py 编排 <verb>` (alias `python3 daybook.py 司南 <verb>`).

## Boundaries (honest)

- Routing is deterministic **only for known classes**; unmatched entries fall to "broadcast" — **no guessing**.
- `@非作者` needs **≥2 candidates**; a single candidate falls to "pending" — **no guessing**.
- `flock` is **process-level** mutual exclusion; cross-host requires a shared filesystem or higher-level coordination (consistent with daybook's "one ledger per person" stance).
- The socket push in `agent_message.py` is **optional/attachable** (not hard-bound here, to avoid pulling in a service).

## Relation to the other two

| Product | Box | Office |
|---|---|---|
| Journal | `daybook` | ledger + recording (base) |
| Xuanji | `daybook-mcp` | query |
| **Sinan** | **`daybook-orch`** | **orchestrate** |

All three share **one base** (append-only volumes), **one promise** (zero dependency), **one truth**;
Sinan **adds no storage at all** — it only replaces "manually opening tickets and manually dispatching"
with **deterministic table lookup**.

## Version

`版本.txt`: a package's version = **the sum of lines of its product `.py` files** (daybook's old rule; recomputable).

## License

**AGPL-3.0-or-later**, or a separate **commercial license**.
The packages may be used and modified freely, **including internal commercial use**.
For **closed-source embedding / external SaaS without open-sourcing / official support
and compliance endorsement**, a commercial license is available separately.

See [`LICENSE`](LICENSE). The three packages share one **per-file** licensing scheme;
see [`LICENSING.md`](LICENSING.md).

## Authors

- **纵贯线**：斯坦森、皮特、汤姆、史泰龙
- **手艺人老宋**
- <songliansheng@vip.sina.com>

---

daybook-suite · daybook-orch (Sinan · 司南)
