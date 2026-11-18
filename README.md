# daybook-suite

**A ledger you can actually open.** Plain text · Zero dependencies · append-only — the truth lives in the volumes.

> **⬇ Download · Quick start**  
> **Source — free forever, no signup:** `git clone https://github.com/songliansheng1972/daybook-suite.git`  
> **Download — free:** [Releases](https://github.com/songliansheng1972/daybook-suite/releases) · **[daybooksuite.com](https://daybooksuite.com)** · `pip install daybook-suite daybook-mcp daybook-orch` — no account, no payment. A paid one-click bundle may come later — not now.  
> **Run in 10 seconds:** `cd daybook && python3 daybook.py index`

Three independent parts, one foundation, one source of truth:

| Part                  | Box             | Role                                                           | License                 |
| --------------------- | --------------- | -------------------------------------------------------------- | ----------------------- |
| **Daybook** (起居注)     | `daybook/`      | Ledger + records (foundation) · index / query / watch / append | MIT (fully open source) |
| **Daybook MCP** (璇玑)  | `daybook-mcp/`  | Query · exposes the volumes to any MCP client                  | MIT (fully open source) |
| **Daybook Orch** (司南) | `daybook-orch/` | Command · deterministic orchestration for multi-agent systems  | AGPL-3.0 + commercial   |

## Daybook's Eight Facets

Named after the *Eight Entries* of the Great Learning — **from within, outward: wisdom grown out of memory.** Eight axes, one meaning each, each aimed at a known weakness of today's AI-memory stacks.

| #  | Facet            | What it means                                                                                                                                                                                                                    | vs. mainstream AI memory / vector stores                                             |
| :- | :--------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------- |
| 1  | **Textuality**   | Plain text (TXT/UTF-8), not binary — human- and machine-readable, auditable, verifiable, traceable                                                                                                                               | A vector DB is a float32 matrix; step outside the framework and it is noise          |
| 2  | **Transparency** | A white box — double-click and you see code + index + source                                                                                                                                                                     | Embeddings cannot be read, and cannot be traced back                                 |
| 3  | **Formality**    | A strict entry format (type / title / author / time / recipient), validated by 2,000 years of *qijuzhu* practice                                                                                                                 | Chat history appended ad hoc, no schema                                              |
| 4  | **Append-only**  | Append-only: no rewriting, no deletion; corrections are new entries; the whole archive reversible and verifiable                                                                                                                 | Update/delete allowed; silent tampering goes undetected                              |
| 5  | **Queryability** | Milliseconds on a single machine — grep / awk / sqlite straight through; still milliseconds at five million entries                                                                                                              | Needs an index server or GPU, and returns "similar" rather than "confirmed"          |
| 6  | **Density**      | Small entries, small files — millions of entries ≈ a few hundred megabytes                                                                                                                                                       | A hundred million embeddings = several GB to tens of GB                              |
| 7  | **Locality**     | Fully local: standard library only, no network, no upload, no version-compatibility treadmill                                                                                                                                    | Framework dependencies, cloud hosting, SDK-version hell, data leaving the machine    |
| 8  | **Persistence**  | It does not parasitize the AI — if the model crashes, is swapped out, or shuts down, the memory loses not one character; it moves with the project, any agent can pick it up and go to work, and it outlives machine generations | Memory lives in model weights or a cloud account — swap or shut down, and it forgets |

**Daybook's Eight Facets — a drop-in replacement for the context window. Permanent memory for agents.**

## Why "Daybook" (起居注, Qǐjūzhù)

For nearly two thousand years, Chinese court historians kept the **qijuzhu** — the day-by-day record of the emperor's own words and deeds. **The name goes back to the Han dynasty (1st century AD); as a full institution it was formalized in the Tang, and such records were kept, on and off, until 1910.**

It ran on four iron rules:

- **Append-only** — an entry, once written, was never altered.
- **Independent recorder** — the Tang ideal was that *even the emperor did not get to read it*. (That is the classical ideal, not a practice every dynasty kept — later courts did ask to look.)
- **Chronological** — "以事系日，以日系月，以月系时，以时系年": day by day, never reshuffled.
- **Source of record** — every later official history was compiled from it.

The recorder was separate from the recorded, and a written record could not be rewritten. Two thousand years of practice settled one point: **records that matter must be append-only, and independent of the one being recorded.**

The other two parts also carry old names: **璇玑 (xuánjī)**, an ancient astronomical instrument for *observation*; **司南 (sīnán)**, the early south-pointing compass, for *direction*.

We invented nothing. We just hung that two-thousand-year-old ledger on your AI.

## Highlights

- **Ledger = plain text** — readable with `cat`; no runtime requirements, no model requirements.
- **Zero dependencies** — Python 3 standard library only; no network. Copy to any machine and it runs.
- **Append-only** — writes never corrupt history; the index is just a catalog, rebuildable from the source text at any time.
- **One foundation for all three** — the same volumes, the same truth; **others can build compliant ledgers on their own — we don't need to be present**.

> **The full feature list lives in the Daybook package README** — [`daybook/README.md`](daybook/README.md) (§ 特点, thirteen items). This root README stays a *pointer*, never a second copy, so the two cannot drift apart.

## Quick start

```bash
cd daybook       && python3 daybook.py index          # Daybook: index
cd daybook-mcp   && python3 mcp_server.py             # Daybook MCP: start MCP server
cd daybook-orch  && python3 orchestrator.py selftest  # Daybook Orch: end-to-end self-test 9/9
```

Each package is self-contained; `daybook.conf` lets you change volume paths.

## License

> **The root `LICENSE` is the standard MIT full text, covering `src/` and `daybook-mcp/` (and the generated `daybook/` package).**  
> **Daybook Orch (`daybook-orch/` and its source files) is NOT MIT** — it is licensed under **AGPL-3.0-or-later**, or a separate commercial license. Its full text lives at `daybook-orch/LICENSE` (also `LICENSES/AGPL-3.0-or-later.txt`); per-part attribution is in `NOTICE`; tiered-licensing notes are in `src/LICENSING.md`.

- **Daybook · Daybook MCP**: MIT (fully open source).
- **Daybook Orch**: **AGPL-3.0-or-later**, or a separate commercial license (**closed-source embedding / hosted SaaS without open-sourcing / official support & compliance endorsement** — contact **songliansheng@vip.sina.com**).
- **Everything is free right now** — source, [Releases](https://github.com/songliansheng1972/daybook-suite/releases), and the site; no account, no payment. A paid one-click bundle may come later — not now. **The source code stays public and free for anyone to fetch.**
- The code is open, **but the name is not free to reuse** — `daybook` / `起居注` / `璇玑` / `司南` are attribution marks.

## Source & packages (one source, three artifacts)

```
daybook-suite/            ← this repo
├── daybook/              ← Daybook (artifact · MIT)
├── daybook-mcp/          ← Daybook MCP (artifact · MIT)
├── daybook-orch/         ← Daybook Orch (artifact · AGPL-3.0 or commercial)
└── src/                  ← the single source (change the source first, never the copies)
    └── pack.py           ← packager
```

- **Just want to use it**: run directly inside the three package directories — each is self-contained with zero dependencies.
- **Want to change the code**: edit `src/`, then run `python3 src/pack.py` to repack (`--out` defaults to this repo root).
- **Discipline**: the three packages are **artifacts**; hand-edits to artifacts are **silently wiped** by the next pack. `pack.py` ships with an "**artifacts == source**" consistency guard; any mismatch exits non-zero.

## Version & build number (reproducible)

- **Version** — a standard **semantic version**, shared by all three packages (one source, released together): currently **v4.0.6**.
- **Build number** — the sum of the line counts of that package's product `.py` files; a **build fingerprint**, not a version. Auxiliary files (`.sh` / `.c` / `.bas` / `.f` language ports, sentinels, launcher, test scripts) and docs are **not** counted.

| Package      | Version | Product `.py` files | Build number |
| ------------ | ------- | ------------------- | ------------ |
| daybook      | v4.0.6  | 8                   | 3849         |
| daybook-mcp  | v4.0.6  | 13                  | 6017         |
| daybook-orch | v4.0.6  | 11                  | 3695         |

**Code size**: **15,291 lines** across the three packages' product files (4,433 + 6,596 + 4,262).

The **authoritative file list** is `src/pack.py` (each package's `prog` list). Reproduce any time:

```bash
python3 src/pack.py --dry     # prints every counted file's line count and each package's build number
```

## Release tags

Every release tag is **annotated**, and its message states the **version** and **all three build numbers** — the tag alone pins the exact build:


```
v3.2.1 daybook-suite v3.2.1 — 起居注 1920 / 璇玑 3473 / 司南 2195
v3.2   daybook-suite v3.2 — 起居注 1920 / 璇玑 3472 / 司南 2195
v3.1   daybook-suite v3.1 — 起居注 1653 / 璇玑 2962 / 司南 1926
v3.0   daybook-suite v3.0 — 起居注 1354 / 璇玑 2367 / 司南 1746
```

Check: `git tag -n99` lists each tag together with its message.

## Contributing

External contributions require signing the **CLA** first (`src/CLA.md`; also bundled in each of the three packages) — **otherwise this repository has no right to re-license code containing others' copyright under a commercial license**, and the commercial path for Daybook Orch would be irreversibly broken.

## Authors

- **纵贯线 (Zongguanxian)**: 斯坦森 (Statham), 皮特 (Pitt), 汤姆 (Tom), 史泰龙 (Stallone)
- **手艺人老宋 (Artisan Lao Song)**
- <songliansheng@vip.sina.com>

---

# daybook-suite（中文）

**一叠你能翻的账。** 纯文本 · 零依赖 · append-only —— 真相在卷里。

> **⬇ 下载 · 快速开始**  
> **源码（永远免费·无需注册）：** `git clone https://github.com/songliansheng1972/daybook-suite.git`  
> **下载（当前全部免费）：** [Releases](https://github.com/songliansheng1972/daybook-suite/releases) · **[daybooksuite.com](https://daybooksuite.com)** · `pip install daybook-suite daybook-mcp daybook-orch` —— 无需账号、无需付款。将来可能有一键包，但不是现在。  
> **十秒跑起来：** `cd daybook && python3 daybook.py index`

三件分立，同一底座，同一份真相：

| 件       | 盒名              | 职                          | 许可              |
| ------- | --------------- | -------------------------- | --------------- |
| **起居注** | `daybook/`      | 账＋录（基座）· 索引 / 查询 / 监视 / 落条 | MIT（全开源）        |
| **璇玑**  | `daybook-mcp/`  | 查 · 把卷暴露给任意 MCP 客户端        | MIT（全开源）        |
| **司南**  | `daybook-orch/` | 令 · 多智能体的确定性编排             | AGPL-3.0 ＋ 商业许可 |

## 名字的由来 —— 起居注

近两千年前，中国的史官就在做一件事：**逐日记录帝王的一言一行**，写成的档册叫「**起居注**」。**其名起于汉代（公元一世纪），到唐代成为定制，此后断断续续一直写到 1910 年。**

它立过四条铁律：

- **只增不改** —— 写定的记录，不许删改。
- **记录者独立** —— 唐代定制：连皇帝本人也不得调阅。（**这是制度理想，并非历代皆然** —— 宋以后即有君主索阅之例。）
- **编年为序** —— 「以事系日，以日系月」，逐日逐条，不许重排。
- **修史底本** —— 后世国史、实录皆由它编成。

记录的人与被记录的人，分开；写过的事，不能重写。两千年实践验证的只有一句：**重要的记录，必须只增不改、独立于被记录者。**

另两件亦取古名：**璇玑**，上古观测天象之器 —— 主「查」；**司南**，最早的定向之器 —— 主「令」。

我们没发明什么 —— 只是把这叠两千年的账，挂给了 AI。

## 卖点

- **账本＝纯文本** —— `cat` 就能读；不挑环境、不挑模型。
- **零依赖 · 跨平台** —— 只 Python 3 标准库；不联网。macOS / Linux / 树莓派拷到即跑；Windows 走命名互斥量 + `realpath` 归属判的真实写路径（语义契约与 POSIX 相同）。
- **只增不改** —— append-only，写不坏历史；索引是目录，可随时从原文重算。
- **三件同底座** —— 同一批卷、同一份真相；**别人可自造合规之账，我们不必在场**。

> **完整特点见旗舰包 README** —— [`daybook/README.md`](daybook/README.md)（「## 特点」段·十三条）。本仓根 README 只作**指路**，不复制正文 —— 两处不各自漂移。

## 怎么跑

```bash
cd daybook       && python3 daybook.py index          # 起居注：索引
cd daybook-mcp   && python3 mcp_server.py             # 璇玑：启 MCP 服务器
cd daybook-orch  && python3 orchestrator.py selftest  # 司南：端到端自检 9/9
```

各包自包含，`daybook.conf` 可改卷路径。

## 并发模型：唯一写链在同一账本根下串行

写入口只有一个：**持锁凭证 `LockedRoot`**。文件写是 `write` / `update`，目录是
`mkdir` / `mkdirs` / `mkdirs_path`，权限/删除/时间戳是 `chmod` / `unlink` / `utime`；
它们都只长在同一个凭证上。取锁即拿到该凭证（`with locked(root) as lr:`），已在临界区内的
调用点用 `held(root)` 取回本线程持有的同一凭证；没有任何模块级写原语，也没有「不取锁的
原子替换」这种旁路。追加（可创建 / 必须已存在）与原子替换是同一个 `write` 的三种
`WriteMode`，不再各有一套实现。目录/权限/删除/时间戳只有 POSIX `dir_fd` 实现：Windows
调用会显式 `RuntimeError`，不提供按路径回退（追加/替换在 Windows 有独立分支）。因此
**Windows 上 `build` / `backup` / `record` / `register` 不可用**；这三处 best-effort 失败
（`purge`/备份时间戳/注册卷 chmod）改为 `errors.warn`，不再静默吞掉。

互斥范围是**整个账本根**，不是卷、不是任务、也不是 `AgentLock.acquire()` 的那个标签字符串。
锁的身份是账本根目录的 **inode**（`st_dev, st_ino`），不是路径字符串——大小写、尾斜杠、软链、
`/private/tmp`、NFD/NFC 等写法只要指向同一 inode 就是同一把锁（判据按环境实际支持的写法逐种
验证，不支持的打印跳过与原因）。线程之间在进程内排队（每个账本根一把 `threading.Lock`），
进程之间由账本根目录的独占 `flock` 排队；没有任何共享锁模式，也不建锁件。

- `AgentLock.acquire(label, agent_id)` 拿到的就是这把根锁：`label` 只用于记账/命名租约 id，
  不参与互斥范围的判定。同一线程在已持锁状态下再次获取（任意 label）会**立即抛错**，不等待。
- **实测代价读数**（源树判据 AM 每次实测）：根锁被持 0.6s 期间，一次全量 `index` 实际等待
  **0.63s**；P1 持 `task:A` 1.2s 期间，P2 取 `task:B` 实际等待 **1.21s**（复签阶段另一台机
  上测得 1.42s）。也就是说：**同一账本根上的取锁写只会排队，不会并行**；写入越重，后来者
  等得越久。
- **判据计数**只引用判据打印的「项」值（=PASS+FAIL 行数），条数只作参考。本轮实测：
  源树 `0 红 / 536 项（PASS 536；跳过 22 项）`；`daybook/` 盒 `0 红 / 416 项（PASS 416；
  跳过 45 项）`。盒内项数较少不是漏跑：盒只收起居注产品件与随包测试，缺 mcp／orch 两包、
  `agent_lock.py`、`pack.py` 等，依赖它们的判据逐条打印 `[跳过]` 与原因、不进「项」计数；
  其余少掉的项来自按文件集扫描的判据（如 AH 登记条目）随文件数变化。所有场合只报打印值，
  不手写换算。
- **只有 `daybook/` 盒自带判据**（`ledger_guard_test.py`）。`daybook-mcp/`、`daybook-orch/`
  盒内没有自带判据，它们与源树同源只由 `pack --verify` 逐字节保证；不要把「盒内可自证」
  读成三包都成立。
- **判据健康度**不看条数：属性层 P1–P10 全绿（`python3 src/tests/prop/run_all.py --seed 7`），
  变异记分 `python3 src/tools/score.py` 打印 `变异 14 / 杀死 14 / 存活 0 / 死变异 0`。杀死的判据不是「有 FAIL 就算」，而是**命中该变异声明的预期断言名**；
  死在别的断言、或只有运行异常，都记死变异，不算杀死。
  健康＝**属性全绿 + 存活变异 0 + 死变异 0**；三者缺一即未收口。场景层源件在
  `src/tests/scenarios/guard.py`（盒内仍叫 `ledger_guard_test.py`，命令不变）。
- **写原语按系统调用类别穷举**（AH），且**发现先于归类**：先对每个被扫文件的**每个函数**
  扫 `os.*` 全集与全部非 `os` 写 API（`shutil.move/rmtree/chown`、`Path.mkdir/unlink/rmdir/
  chmod/touch/rename/replace/open`、`ctypes`、无重定向 `subprocess`），再判定类别。算不出
  类别的函数不会因为「没进 sites」而消失。所有类别在 `_MUTATOR_OWNER` 里有唯一归属：
  `LockedRoot`、`safeio` 实现内、随包测试、或 `impossible`。未登记类别、账本桶裸调、
  产品件出现 `impossible` 类别、未知 `os.*`、产品件的间接派发（`getattr` 调用派发、
  `__import__`、含写原语的字典派发、`o = os` 别名）与 `open` 模式变量，AH 一律判红。
  产品件还禁止第三方库 import。新增一种名字而不登记，下一次跑判据就会红。P10 同时覆盖
  `build`、`backup`、`record` 三条换根路径。
- **统一退出码入口只有 8 个**：`daybook.py`、`daybook_append.py`、`daybook_hook.py`、
  `daybook_session_hook.py`、`daybook_record.py`、`orchestrator.py`、`mcp_server.py`、
  `cross_ref.py`；P6 的 8×7 矩阵只对这张清单负责。`agent_*`、`task_volume.py`、
  `daybook_multidx.py`、`mcp_subscribe.py`、`chatroom_server.py` 是运维/调试工具，
  不承诺统一码，也不得拿来宣称「任何入口同码」。`verify_plain.py` 是**判据工具**（只读校验，
  退出码 1/2 表示「判据不成立/用法错」），不在这张入口表内，也不要按统一错误类解读。

## 退出码（CLI）

`index` 与各子命令共用同一套退出码，多类同现时屏幕每类都打印，退出码取语义严重度最高的一类。
与 `python3 daybook.py --help` 的输出逐字一致：

| 码 | 含义 | 说明 |
| --- | --- | --- |
| 0 | 干净 | 含「未变」；本轮正常落盘 |
| 2 | 卷配置错 | 目录型条目、配置指向不存在的文件等；解析层不崩，CLI 报错非零退出，**零落盘** |
| 3 | append-only 违例 | 账本被改写 |
| 4 | 作者口径 | 作者位出现机器 id 或两种形态混用 |
| 5 | 派生件证据缺失 | 索引/游标/封存丢失或不可解析；**不写回**，用 `baseline` 认基线 |
| 6 | 运行失败 | 写/锁被拒等运行期 `RuntimeError`；**不写回** |

优先级：**3 违例 > 4 作者 > 6 运行失败 > 2 配置错 > 5 证据缺失**。「检测到篡改」不会被 2 掩盖，
也不会被 5 洗掉；运行失败（6）与配置错（2）分属两码，脚本可直接区分，两者同现取 6。
MCP 请求期的 `RuntimeError` 走 RPC 的 `ERR_INTERNAL_ERROR`，不映射为进程退出码；启动期失败才是 rc=6。

## 已知边界（不构成保证）

- **写路径防重定向，不防「已进入目录被整体搬走」**：所有写原语从账本根目录 fd 起逐级
  `openat(O_NOFOLLOW|O_DIRECTORY)` 走查，截断软链祖先与 `..` 重定向；但一旦持有某级目录 fd，
  该目录被 `rename` 整体搬走后再写入，数据会落在**被搬走的那个目录**里（fd 语义固有）。
- **单次追加的原子性只在 APFS 上实测过**：一次 `O_APPEND` 写入 32 MB、5179 次采样，未观察到半条。
  更大的单次写入、以及跨文件系统（NFS/SMB/exFAT/网络盘等）**未验证**；这些场景下的落盘一致性
  不作保证。增量追加型派生件另有兜底：末行无换行一律转全量重扫重建，不截断丢行。
- **锁的三条保守行为**（有意如此，不视为缺陷）：①临时目录前缀大小写变体（如 `/PRIVATE/TMP/…`）
  一律按「可能不在系统临时目录内」拒绝，宁可判红；②`fork` 出的子进程**继承**父进程已持有的
  锁（内核 fd 语义），子进程不得再取同一把锁；③`exec` 后锁随 fd 关闭自动清零，新程序必须
  重新取锁。三者都是安全侧行为，不提供开关改变。
- **`daybook_append.py` 不解析 conf（设计边界）**：它只认账本根与目标卷文件，因此 `daybook.conf`
  写坏时它仍可能 rc=0 并追加成功。这不代表「conf 坏了也能写」——`daybook.py index` 与
  `daybook_record.py` 都会按配置错（2）拒绝并零落盘；append 是单条落盘的唯一入口，不承担配置体检。
  `daybook_append.py` does not parse conf (by design): it only knows the ledger root and the target
  volume, so a broken conf does not stop it. That never means "broken conf is writable": `index` and
  `record` refuse with code 2 and land nothing; append is the single-entry writer, not a conf checker.

## 许可

> **仓根 `LICENSE` 是标准 MIT 全文，覆盖 `src/` 与 `daybook-mcp/`（以及由其生成的 `daybook/` 包）。**  
> **司南（`daybook-orch/` 及其源码件）不是 MIT** —— 适用 **AGPL-3.0-or-later**，或另购商业许可。全文见 `daybook-orch/LICENSE`（另见 `LICENSES/AGPL-3.0-or-later.txt`）；逐件归属见 `NOTICE`；分层说明见 `src/LICENSING.md`。

- **起居注 · 璇玑**：MIT（全开源）。
- **司南**：**AGPL-3.0-or-later**，或另购商业许可（**闭源嵌入 / 对外 SaaS 而不开源 / 官方支持与合规背书** 另谈，联系 **songliansheng@vip.sina.com**）。
- **当前全部免费**：源码、[Releases](https://github.com/songliansheng1972/daybook-suite/releases)、站点，三处皆无账号、无付款。将来**可能**出一键包（便利费），但**不是现在**。**源码永远公开，人人可免费自取。**
- 码可开源，**名不可乱用** —— `daybook` / `起居注` / `璇玑` / `司南` 为署名标识。

## 源与包（一源三产物）

```
daybook-suite/            ← 本仓
├── daybook/              ← 起居注（产物 · MIT）
├── daybook-mcp/          ← 璇玑（产物 · MIT）
├── daybook-orch/         ← 司南（产物 · AGPL-3.0 或商业）
└── src/                  ← 唯一源（改先落源，勿改副本）
    ├── pack.py           ← 建包器
    ├── tests/scenarios/  ← 33 组场景判据（盒内复制为 ledger_guard_test.py）
    ├── tests/prop/       ← P1–P10 属性层（seed 化生成，失败可一键复现）
    └── tools/            ← mutate.py（AST 变异 M1–M14）+ score.py（记分板）
```

- **只想用**：直接进三个包目录跑，各包自包含、零依赖。
- **想改代码**：改 `src/`，再跑 `python3 src/pack.py` 重打包（`--out` 默认＝本仓根）。
- **纪律**：三包是**产物**；手改产物会被下次打包**静默抹掉**。`pack.py` 自带「**产物 == 源**」一致守卫，失配即非零退出。

## 压测（`bench/`）

- **复现**：`bench/run.sh --quick`（判据自证 + 10 万×64）；全档 `bench/run.sh`（1000 并发档先 `ulimit -n 8192`）。
- **读数**：[bench/RESULTS_20261114.md](bench/RESULTS_20261114.md)；用法、判据与离线跑法见 [bench/README.md](bench/README.md)。
- **边界**：`bench/` 是开发者工具，**不入三包 payload**；wheel、临时数据、日志不入 git。默认从 PyPI 安装当前 `SUITE_VERSION`，`--wheel-dir` 仅供离线。

## 版本号与构建号（可复现）

- **版本号** —— 标准**语义版本**，三包统一（同源同发）：现为 **v4.0.6**。
- **构建号** —— 该包「产品 `.py` 件」行数之和，是**构建指纹**，**非版本号**。辅助件（`.sh` / `.c` / `.bas` / `.f` 语言端口、哨兵、启动器、测试脚本）与文档**不计入**。

| 包   | 版本号    | 产品 `.py` 件 | 构建号  |
| --- | ------ | ---------- | ---- |
| 起居注 | v4.0.6 | 8          | 4433         |
| 璇玑  | v4.0.6 | 13         | 6596         |
| 司南  | v4.0.6 | 11         | 4262         |

**代码规模**：三包产品件合计 **15,291 行**（4,433 ＋ 6,596 ＋ 4,262）。

> 构建号变动记录：2026-10-14 为 10 个产品件**补齐 SPDX 许可头**（每件 +2 行：`SPDX-License-Identifier` 与  
> `Copyright`），起居注 1354→1362、璇玑 2367→2381、司南不变（其产品件原已带头）。**纯注释改动·零逻辑变更**。  
> 2026-10-15 **v3.1**：新增 `daybook_multidx.py`（四库式多级索引）⇒ 起居注 1362→1653（6→7 件）、璇玑 2381→2962（11→12 件）；  
> 司南加 `digest` 子命令 ⇒ 1746→1926。  
> 2026-10-16 **v3.2**：全仓标识符英文化 ＋ **注释改中英对照**（注释行数增加）⇒ 起居注 1653→**1920**、璇玑 2962→**3472**、司南 1926→**2195**。  
> **纯注释＋改名改动·零逻辑变更**；另修 `mcp_test.py` 与工具的时间戳错位（测试侧陈旧·工具未动）。  
> 2026-10-16 **v3.2.1**：**I18N.md／CHANGELOG.md 随三包**（修包内 conf 注释「对照表见 I18N.md」之死链）＋ **MCP `serverInfo.version` 并入套件轴**（`1.8.1`→`3.2.1`）⇒ 璇玑 3472→**3473**（`mcp_server.py` +1 行注释）；起居注／司南构建号不变。

**权威件清单**在 `src/pack.py`（各包的 `prog` 列表）。随时复现：

```bash
python3 src/pack.py --dry     # 逐件列出各行数与各包构建号
```

## 发布 Tag

每个发布 tag 均为 **annotated**，且说明里写明**版本号与三包构建号** —— 单看 tag 即可定位到确切构建：

```
v3.2.1 daybook-suite v3.2.1 — 起居注 1920 / 璇玑 3473 / 司南 2195
v3.2   daybook-suite v3.2 — 起居注 1920 / 璇玑 3472 / 司南 2195
v3.1   daybook-suite v3.1 — 起居注 1653 / 璇玑 2962 / 司南 1926
v3.0   daybook-suite v3.0 — 起居注 1354 / 璇玑 2367 / 司南 1746
```

核验：`git tag -n99` 列出 tag 及其说明。

## 贡献

外部贡献须先签 **CLA**（`src/CLA.md`；三包内亦各附一份）——**否则本仓无权对含他人版权之代码再授商业许可**，司南的商业路将不可逆地失效。

## 作者

- **纵贯线**：斯坦森、皮特、汤姆、史泰龙
- **手艺人老宋**
- <songliansheng@vip.sina.com>
