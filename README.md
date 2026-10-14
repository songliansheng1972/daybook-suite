# daybook-suite

**A ledger you can actually open.** Plain text · Zero dependencies · append-only — the truth lives in the volumes.

> **⬇ Download · Quick start**
> **Source — free forever, no signup:** `git clone https://github.com/songliansheng1972/daybook-suite.git`
> **Prebuilt bundle:** [Releases](https://github.com/songliansheng1972/daybook-suite/releases) — or the one-click bundle at **[daybooksuite.com](https://daybooksuite.com)** ($10.99 convenience fee; the source stays free).
> **Run in 10 seconds:** `cd daybook && python3 daybook.py index`

Three independent parts, one foundation, one source of truth:

| Part                  | Box             | Role                                                           | License                 |
| --------------------- | --------------- | -------------------------------------------------------------- | ----------------------- |
| **Daybook** (起居注)     | `daybook/`      | Ledger + records (foundation) · index / query / watch / append | MIT (fully open source) |
| **Daybook MCP** (璇玑)  | `daybook-mcp/`  | Query · exposes the volumes to any MCP client                  | MIT (fully open source) |
| **Daybook Orch** (司南) | `daybook-orch/` | Command · deterministic orchestration for multi-agent systems  | AGPL-3.0 + commercial   |

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

> **This repository licenses each part separately; the root `LICENSE` is a signpost only, not a license text.** The full license texts live inside each package:  
> `daybook/LICENSE` (MIT) · `daybook-mcp/LICENSE` (MIT) · `daybook-orch/LICENSE` (AGPL-3.0-or-later)  
> See `src/LICENSING.md` for the tiered-licensing notes; the source-side originals are `src/LICENSE` and `src/LICENSE.orch`.

- **Daybook · Daybook MCP**: MIT (fully open source).
- **Daybook Orch**: AGPL-3.0-or-later, or a separate commercial license (**closed-source embedding / hosted SaaS without open-sourcing / official support & compliance endorsement** — contact us).
- **$10.99 download** = a convenience fee for the prebuilt bundle; **the source code is forever public, free for anyone to fetch**.
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

- **Version** — a standard **semantic version**, shared by all three packages (one source, released together): currently **v3.0**.
- **Build number** — the sum of the line counts of that package's product `.py` files; a **build fingerprint**, not a version. Auxiliary files (`.sh` / `.c` / `.bas` / `.f` language ports, sentinels) and docs are **not** counted.

| Package | Version | Product `.py` files | Build number |
| --------------- | ------- | ------------------- | ------------ |
| daybook         | v3.0    | 6                   | 1354         |
| daybook-mcp     | v3.0    | 11                  | 2367         |
| daybook-orch    | v3.0    | 9                   | 1746         |

**Code size**: **5,467 lines** across the three packages' product files (1,354 + 2,367 + 1,746).

The **authoritative file list** is `src/pack.py` (each package's `prog` list). Reproduce any time:

```bash
python3 src/pack.py --dry     # prints every counted file's line count and each package's build number
```

## Release tags

Every release tag is **annotated**, and its message states the **version** and **all three build numbers** — the tag alone pins the exact build:

```
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
> **整装包：** [Releases](https://github.com/songliansheng1972/daybook-suite/releases) —— 或到 **[daybooksuite.com](https://daybooksuite.com)** 一键下载整装（$10.99 便利费；源码始终免费）。
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
- **零依赖** —— 只 Python 3 标准库；不联网。拷到任何机器即跑。
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

## 许可

> **本仓按件分层授权，仓根 `LICENSE` 仅为指路牌、非授权文本。** 许可全文在各包内：  
> `daybook/LICENSE`（MIT）· `daybook-mcp/LICENSE`（MIT）· `daybook-orch/LICENSE`（AGPL-3.0-or-later）  
> 分层说明见 `src/LICENSING.md`；源侧原件为 `src/LICENSE` 与 `src/LICENSE.orch`。

- **起居注 · 璇玑**：MIT（全开源）。
- **司南**：AGPL-3.0-or-later，或另购商业许可（**闭源嵌入 / 对外 SaaS 而不开源 / 官方支持与合规背书** 另谈）。
- **$10.99 下载** ＝ 整装包的**便利费**；**源码永远公开，人人可免费自取**。
- 码可开源，**名不可乱用** —— `daybook` / `起居注` / `璇玑` / `司南` 为署名标识。

## 源与包（一源三产物）

```
daybook-suite/            ← 本仓
├── daybook/              ← 起居注（产物 · MIT）
├── daybook-mcp/          ← 璇玑（产物 · MIT）
├── daybook-orch/         ← 司南（产物 · AGPL-3.0 或商业）
└── src/                  ← 唯一源（改先落源，勿改副本）
    └── pack.py           ← 建包器
```

- **只想用**：直接进三个包目录跑，各包自包含、零依赖。
- **想改代码**：改 `src/`，再跑 `python3 src/pack.py` 重打包（`--out` 默认＝本仓根）。
- **纪律**：三包是**产物**；手改产物会被下次打包**静默抹掉**。`pack.py` 自带「**产物 == 源**」一致守卫，失配即非零退出。

## 版本号与构建号（可复现）

- **版本号** —— 标准**语义版本**，三包统一（同源同发）：现为 **v3.0**。
- **构建号** —— 该包「产品 `.py` 件」行数之和，是**构建指纹**，**非版本号**。辅助件（`.sh` / `.c` / `.bas` / `.f` 语言端口、哨兵）与文档**不计入**。

| 包       | 版本号  | 产品 `.py` 件 | 构建号  |
| ------- | ----- | --------- | ---- |
| 起居注     | v3.0  | 6         | 1362 |
| 璇玑      | v3.0  | 11        | 2381 |
| 司南      | v3.0  | 9         | 1746 |

**代码规模**：三包产品件合计 **5,489 行**（1,362 ＋ 2,381 ＋ 1,746）。

> 构建号变动记录：2026-10-14 为 10 个产品件**补齐 SPDX 许可头**（每件 +2 行：`SPDX-License-Identifier` 与
> `Copyright`），起居注 1354→1362、璇玑 2367→2381、司南不变（其产品件原已带头）。**纯注释改动·零逻辑变更**。

**权威件清单**在 `src/pack.py`（各包的 `prog` 列表）。随时复现：

```bash
python3 src/pack.py --dry     # 逐件列出各行数与各包构建号
```

## 发布 Tag

每个发布 tag 均为 **annotated**，且说明里写明**版本号与三包构建号** —— 单看 tag 即可定位到确切构建：

```
v3.0   daybook-suite v3.0 — 起居注 1354 / 璇玑 2367 / 司南 1746
```

核验：`git tag -n99` 列出 tag 及其说明。

## 贡献

外部贡献须先签 **CLA**（`src/CLA.md`；三包内亦各附一份）——**否则本仓无权对含他人版权之代码再授商业许可**，司南的商业路将不可逆地失效。

## 作者

- **纵贯线**：斯坦森、皮特、汤姆、史泰龙
- **手艺人老宋**
- <songliansheng@vip.sina.com>
