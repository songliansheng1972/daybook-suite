# CHANGELOG

本文件记录**对外可见**的变更。v3.2.4 及以前的逐版记录在各包内 `CHANGELOG.md`（历史卷，随包发行）；
本文件自下一版起接续记录。

> **状态**：本节随 v4.0.0 定稿（2026-11-13）。

---

## 未发布 · 2026-11-14

**内容**：`daybook-orch`（司南）第二批完善——行为缺陷 5 项、性能 2 项、测试覆盖与文档。
版本号未改、未打包、未上传、未 push；只动 `daybook-orch/` 并同步 `src/` 副本。

### 修复（改前 → 改后）

1. **`digest` 兜底恒 0 / 跨卷引用静默返回空 → 失败可见**
   - 改前：`make_entry_ref` 一律 `except Exception: return ''`；卷表为空或读失败时安静返回 0 条，看着像「没有新条」。
   - 改后：引用失败返回原因并在**输出**标 `↪[互见失败:…]`、**stderr** 留痕；卷表为空报 `src=no-volumes` 并双告警；卷不存在/读失败逐条列出；摘要末尾汇总失败条数。`make_entry_ref` 现返回 `(ref, err)`。

2. **`alarm` 自产中文字串当判据 → 结构字段判据 + 退出码拆分**
   - 改前：`any('失联' in it …)` 判硬警，幽灵负责人也判「干净」。
   - 改后：`alarm()` 返回 `Alarm(code, hard, msg)`。硬警只看结构字段：心跳**时间戳+阈值**（`dead_agents`）、**注册表成员**（`ghost_owner`）、**状态机位置**（`orphan_task`）；`stalled_done` 为软警。
   - 退出码：0 干净｜1 有硬警｜2 参数/文件错｜**3 体检执行异常**（读卷/解析失败）。异常不再与硬警共用 1。

3. **`cross_ref.verify()` 无前缀自比自过 → 必须给基准**
   - 改前：不传 `sha_prefix` 时「条目存在即通过」，对外宣称可校验是硬伤。
   - 改后：缺基准抛 `ValueError`；基准须 8 位小写 hex；CLI 缺基准 rc=2。顺带修掉 `cross_ref.py` CLI 顶层缺 `import sys` 导致的 `NameError`（此前 CLI 实际跑不通）。

4. **`--limit 0` 全量 / `--limit -1` 少一条 → 统一语义**
   - 改前：`limit` 为假值即全量，负数走 `rows[1:]`。
   - 改后：`0`=全部（显式）；正数=最近 N 条；**负数非法**（`ValueError` / CLI rc=2）。帮助文本写明「0=全部；负数非法」。

5. **`sock_path` 未净化 / conf 抬头照抄 mcp / 死开关死代码**
   - `sock_path()` 先净化 agent 名：去路径分隔符与控制字符（中文名照用），拒绝空/`.`/`..`/超长（≥104 字节）；`send` 捕获并返回失败原因，`serve` 非法名 rc=2。
   - `daybook.conf` 改为**司南专用样板**，抬头不再写「daybook-mcp 包内置样板」；新增 `src/daybook.orch.conf` 并在 `pack.py` 的 `conf_rename` 中优先取用。
   - 删除（点名）：`Agent.to_authors`、`safeio.read_json` / `write_json`、`AgentLock.renew` / `force_release` / `sweep`（连同 TTL/`expires` 与 CLI `renew`/`sweep`）、未用导入 `agent_registry.json`、`agent_message.threading`、`agent_lock.json`、`safeio.io`、`daybook_append.io`。
   - **误报保留**：工作单称 `import time` 未用；实测 `orchestrator.py` 的 `_log` 使用 `time.strftime`，未删。

### 性能（同一批数据·修前 → 修后）

脚本 `daybook-orch/orch_perf_bench.py`；HEAD `d9c4225`；起跑 `2026-11-14 01:05:29`（百万行 `01:05:31`）。

| 场景 | 数据 | 修前 | 修后 |
|---|---|---|---|
| `digest`（20 行） | 1 卷 / 24 条 / 22,800 B | 卷读 21 次 / 478,800 B / 6.20 ms | 卷读 1 次 / 22,800 B / 0.75 ms |
| `dead_agents` | 200 agent × 5 心跳 / 46,000 B | 卷读 201 次 / 9,246,000 B / 1495.19 ms | 卷读 1 次 / 46,000 B / 10.00 ms |
| `digest` 百万行 | 1 卷 / 1,000,000 条 / 73,888,900 B | 卷读 21 次 / 1,551,666,900 B / 9493.11 ms | 卷读 1 次 / 73,888,900 B / 6704.80 ms |

- 修法（算法级，非调常数）：`digest` 新增 `VolumeIndex`，**整卷读一次**、条目块按行号懒搜索（`O(块长)`）；不再「每条摘要整卷重读 + 每次重解析 conf」。`dead_agents` 改**单遍**收集最后心跳，再按阈值比较，不再每个 agent 重扫全卷。
- 百万量级：盘读从 **1.55 GB → 73.9 MB（21×）**。剩余耗时来自兜底直扫 + 全量排序（修前修后同样存在，不属本次回归）；有 `multilevel` 目录件时走目录，不直扫原卷。页缓存会掩盖重复读的 I/O 成本，故以**盘读字节**为硬指标。

### 测试

- `orch_fixes_test.py` 新增 5-12：`route` 确定性查表、`digest` 可见性/`--limit`、`alarm` 结构与退出码（含仅幽灵负责人场景）、CLI `--limit`、**真跨进程锁**（6 进程同刻抢锁恰好 1 个成功）、`verify` 缺基准、`sock_path`/死代码、单遍读性能。
- `orch_mutation_check.py` 新增 7 条变异（6-12）：静默 0 条、字串硬警、旧 `limit`、不 `flock`、自比自过、不净化、逐条重读 + 逐 agent 重扫。
- 结果：**11/11 红→绿**（批次一 4 + 批次二 7），两遍读数均留。

### 压测脚本（如实）

- 仓内可查：`src/test/benchmark_365k.py`（36.5 万条全量读/索引）、`src/daybook_test.py`（600 并发追加、逐条完整且仅一次）；历史 CHANGELOG v1.7 E-06 记有 100 万条（107 MB，写入 69 s / 索引 8.4 s）等读数。
- **「100 万条记录 + 1000 并发」单一压测脚本/日志：待补**（仓内未找到，不编造读数）。找到后须同时写明零错判据：总行数对账 + 逐条内容校验。

### 文件

- 新增：`daybook-orch/orch_perf_bench.py`、`src/daybook.orch.conf`（均登记 `pack.py`）。
- 同步：`daybook-orch/*` → `src/`（md5 全同）。
- `daybook/`、`daybook-mcp/` 本轮不动；共享件（`safeio.py` 等）待发布步统一对齐。

---

## v4.0.3 · 2026-11-14

**内容**：司南消息总线四条缺陷修复（源码提交 `99b858b`），新增 `volume_paths.py` 与两条回归脚本。

### 修复（改前 → 改后）

1. **回应关系按位置判 → 只认显式 `[re=<条号>]`**
   - 改前：`pull` 把「任意更晚的条目」当作已回复，不校验作者、不校验关联单号。
   - 改后：只认 `[re=<条号>]`；相邻、同作者、时间先后一律不作数。
   - 兼容：旧条目没有 `id=`/`re=`，判 `unknown` 并告警，不按新语义猜。

2. **消息条目无签名 → 条目头带 `[id=]`/`[sig=]` 并在读取时验签**
   - 改前：条目只有 `[致=]`，日志写裸 aid，无法验真伪。
   - 改后：落盘即带显式条号与 HMAC-SHA256 签名（`[id=…] [sig=…]`；签名覆盖落盘时间），读取时验签；密钥 0600/0700，环境变量只用于选钥。
   - 兼容：旧条目判 `unsigned`、验签失败判 `invalid`，均**明确告警**，不静默放行。

3. **两套根解析 → `volume_paths.py` 单根解析**
   - 改前：六个数据卷写死在模块旁不读 conf，消息卷不随 `--root`。
   - 改后：七卷（registry/tasks/heartbeat/leases/ledger/inbox/locks）统一由 `<root>/daybook.conf` 的 `[volumes]` 解析，缺省用默认文件名，`--root` 一处生效。
   - 兼容：不写 `[volumes]` 时行为与旧默认文件名一致，无需迁移。

4. **读卷无锁 → 共享锁读（同线程可重入）**
   - 改前：`read_vol` 裸读，长条目并发追加时可能读到半行。
   - 改后：读侧取共享锁（`locked(shared=True)`），写侧仍独占；同线程在持锁区内再读不死锁（重入检测，不做 shared→exclusive 升级）。
   - 兼容：无接口变化。

### 新增

- `volume_paths.py`：卷路径唯一解析器（两个模块共用，避免循环引用与第二套根）。
- `orch_fixes_test.py`、`orch_mutation_check.py`：四条修复的正向回归＋变异体（改回旧行为必须红）。

> **升级提示**：旧消息条目会被判 `unsigned`/`unknown` 并告警，属预期；新写入条目自动带 `[id=]`/`[sig=]`。若 `--root` 指向的目录里没有 `daybook.conf`，七卷使用 `<root>` 下的默认文件名。

---

## v4.0.2 · 2026-11-13

**内容**：索引与校验的 P0 修复（源码提交 `d48231a`）。

- **「未变」判据改为全卷 sha256**：不再只看 `size + mtime`；等长改写后把 mtime 改回去，旧判据会静默漏检，现在必被发现。纯追加仍走已知前缀哈希＋尾部续读的快路径。
- **索引格式升代（fmt=2）**：代次写入 `.head_stamp.json` 与卷首清单；**旧索引与旧清单首次运行会判过期并自动重建**，不静默沿用。
- **append-only 违例退出码 `rc=3`**：等长改写、变短、前缀不符均报违例；`daybook index` 以 3 退出，便于脚本与 CI 拦截。
- **watch 变动判定纳入卷内容指纹**：不再只依赖大小与时间。
- **`query` 收集端有界**：`--count` 只数不攒、`--limit` 边扫边截、`--sample` 两遍抽样。
- **坏 `tag:N` 规则进清单**：解析失败不再静默，列入告警清单。
- **兜底编码标注替换处数**：`gb18030` 替换兜底时写明替换了多少处，不再无声。
- **随包新增 `ledger_guard_test.py`（变异回归，修必配变异）**：等长替换＋`utime` 恢复 mtime **必须 rc=3**；把判据临时退回 `size+mtime` 的变异体下**必须红**。挡的是「判据被改回去而并发烟雾仍全绿」的静默回退 —— `daybook_test.py` 是 600 并发烟雾，验不出这一层。

> **升级提示**：从 4.0.1 升到 4.0.2 后，**首次运行会重建索引**（索引格式升代），耗时随卷大小而定；属预期行为，不是数据损坏。

---

## v4.0.1 · 2026-11-13

**内容**：仅发布面文案修正（源码提交 `1cff6cf`），**不加功能、不改行为**。

- 司南文档与代码抬头：删除「HMAC-SHA256·不可伪造」，改为「自述身份、尚无签名校验」。
- 包元数据：`Operating System :: OS Independent` 改为 `POSIX`（代码 `import fcntl` 无兜底）。
- 消息层说明：删除「TCP 回环兜底」与「按 to 分发到 inbox 卷」，改为「仅 AF_UNIX」「所有消息同一卷」。
- 构建号不变：起居注 2002 ／ 璇玑 4101 ／ 司南 2271。

---

## v4.0.0 · 2026-11-13

### 破坏性变更

1. **`daybook_append` 新增必填 `ts`**
   - 改了什么：工具 schema 的 `required` 加入 `ts`（Unix 秒）；服务端在验签**之后**校验时间窗 ±60s。
   - 对使用者的影响：任何调用 `daybook_append` 的客户端都必须带 `ts` 并用 v2 载荷重签；不带 `ts` 的调用直接失败（参数缺失），带旧签名则验签失败。

2. **签名载荷升级 v2**
   - 改了什么：验签载荷由「仅 `content`」改为
     `append|v2|volume=<卷>|tag=<主>|subtag=<子或_>|to=<收件人>|ts=<时间戳>|content=<正文>`。
   - 对使用者的影响：客户端签名实现须照此拼接（空 `subtag` 用 `_`，空 `to` 留空）；v1 签名不再被接受。换来的是签名绑定卷/标签/收件人/时间戳，**跨卷重放与改标重放不可行**。

3. **修复前生成的 `cross_ref` 旧引用验签失败**
   - 改了什么：修复前块边界多算「下一条条目头行」，哈希覆盖「本条 + 下一条头行」；修复后只覆盖本条。
   - 对使用者的影响：升级前已落盘的 `[卷#L行-SHA8]` 互见引用，`verify` 会报不符；这是**纠正，不是回归**。需要重新生成引用，**新旧引用不可混用**。纯无编号旧卷、逐条生成过的引用同样受影响。

4. **只读模式下四个写工具从 `tools/list` 消失**
   - 改了什么：`MCP_READ_ONLY=1` 时 `daybook_append`／`daybook_mark_read`／`daybook_heartbeat`／`daybook_index` 不再出现在 `tools/list`，直接调用亦被拒绝（审计走 stderr）。
   - 对使用者的影响：只在显式开启只读模式时发生；缓存工具清单或按固定清单做能力探测的客户端需处理清单变化。默认（不设该变量）清单不变。

### 修复

1. **`cross_ref`：`[#N]` 编号前缀与块边界 off-by-one**
   - 条目头正则改为 `^(?:\[#\d+\][ ]*)?\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?\]`，带编号与旧式无编号都认；块边界修到「下一个条目头」，不再吞下一条头行；末条到文末并显式标注「（末条·至文末：其后无条目头）」。
   - 影响：带编号条目（账本绝大多数）从此能生成/校验引用；`make_ref`、`verify`、索引路径三处 SHA8 口径一致。

2. **`_entry_ref` 不再静默吞错**
   - 失败改为抛异常：`multi_query` 捕获后写 stderr `WARN 互见引用失败 …`，并在输出行标 `↪[互见失败]`。
   - 影响：互见失败不再伪装成「没有引用」，可定位、可统计。

3. **`_root()` 解析 conf**
   - 解析顺序：`DAYBOOK_ROOT`（显式覆盖）> conf `[index] root`（空=conf 所在目录；`..`=上级；相对=拼 conf 目录；绝对=原样）。
   - conf 缺失/不可读、根目录不存在 → 抛 `RootError`，**不再静默当空账本**；MCP 启动自检把 root 与卷数写到 stderr，根无效直接退出（退出码 2）。

4. **`resources/subscribe` 校验 URI**
   - 订阅前校验资源真实存在，不存在报 `-32602`，不再返回假的 `subscribed:true`；目录派生件与卷共用同一 `uri → 路径` 映射，订阅的 mtime 监视也同源。

5. **`_multidx_dir` 与 `daybook_multidx` 同源**
   - 改按 conf 的 `index.out_dir` + `multilevel.out_dir` 解析（生产为 `<根>/索引/multilevel`）；`multi_query` 的「目录未生成」提示会打印实际查找路径；旧 `<根>/多级` 仍可读。

6. **HMAC 密钥移出注册卷（0600）＋签名边车**
   - 新注册写独立密钥文件 `.daybook_keys/<agent_id>.key`（文件 0600、目录 0700，显式 `os.open`/`chmod`，不依赖 umask），注册卷只记 `[密钥文件=.daybook_keys/<id>.key]`，并把注册卷本身收紧到 0600；旧内联密钥格式仍可读（**建议轮换**，见发布清单）。
   - 新增 `MCP签名边车.jsonl`（append-only）：每次写工具调用记录 `agent_id / signature / payload / ts` 等，供事后验签；边车写失败则**不动卷**。

7. **统一入口首次必断（#83447）**
   - 改了什么：`cli.py` 启动时探测已安装的 `daybook_suite`／`daybook_mcp`／`daybook_orch`，把各包 `payload/` 一并链入运行目录并加入 `sys.path`；未安装对应包时，`daybook mcp`／`daybook orchestrate` 给出明确提示（`pip install daybook-mcp` / `daybook-orch`）并以退出码 2 结束，不再抛 `ModuleNotFoundError`。
   - 对使用者的影响：三包齐装后，`daybook mcp`／`daybook orchestrate` **首跑即可用**，无需先各自跑一次独立入口。

### 新增

1. **`MCP_READ_ONLY=1`**：只读模式——隐藏并拒绝四个写工具，审计与告警走 stderr，零写盘。取值 `1/true/yes/on` 均生效。
2. **启动器 `daybook-mcp`**：零依赖 shell 启动器，固定 `PYTHONDONTWRITEBYTECODE=1`（不在账本/包内生成 `__pycache__`），支持 `DAYBOOK_ROOT`、`PYTHON`、`MCP_READ_ONLY`。
3. **`mcp-clients/` 三件**：`deepseek-harness.json`、`workbuddy.json`、`README.md`——常见 MCP 客户端的挂载配置样例。
4. **`mcp_p0_regression.py`**：13 项 P0 回归（initialize、只读隐藏写工具、四写工具被拒、`cross_ref` 秒级头、编号前缀与末条、生产 `索引/multilevel` 路径、`resources/read` offset/limit、subscribe 存在性、只读零写盘、密钥 0600、根由 conf 解析、启动零 `__pycache__`、空卷告警）。
5. **发行物补齐**：`daybook-mcp` 的 wheel/sdist 现实际包含启动器 `daybook-mcp`、`mcp-clients/` 三件、`mcp_p0_regression.py` 与 `mcp_test.py`（此前 `package-data` 未覆盖 `payload/mcp-clients/*`，命中 0）。

### 性能

1. **`multi_query` 整卷读取次数：命中数 ×1／×2 → 1**
   - 单次调用内建整卷索引（键 = path + mtime_ns + size），互见引用与全文共用；**跨调用不复用**，账本变动即重读。
   - 本机核验（8.25 MB / 6,000 条合成卷，500 条）：`reads=1`、0.375 s；旧路径实测 ≈0.124 s/条，500 条约 62 s。
   - 任务书读数（14.95 MB 真实卷）：`full=true limit=500` 由 **129.0 s → 1.07 s**。
   - ⚠️ 仓内《发布版缺口与收敛_20261113.md》记同配置为 3.292 s。**三处读数口径未统一**，发布前须在同一卷上复测一次再定稿本节数字。

### 版本号：4.0.0

- 依据：破坏性变更 **4 条**，其中两条会让**已在用的第三方客户端当天报错**（`ts` 必填、v2 载荷），一条会让**已落盘数据验签失败**（旧 `cross_ref` 引用）。按语义化版本，这是主版本号变更。
- 不取 3.3.0：3.x 内做会静默破坏调用方，`pip install -U` 的人无从预期。
- 单一真相源：`src/pack.py` 的 `SUITE_VERSION = '4.0.0'`；三包同版同发。

---

## 已知未修（不阻塞发版，但应知会）

- `mark_read` 游标写入非原子、无锁；签名载荷仍为 `read:<volume>`（可重放）。
- `DAYBOOK_AGENT_ID` 可兜底审计署名（只影响「谁干的」的记录，不越权）。
- 可写模式的审计卷无轮转。
- `daily_journal` prompt 缺 `subtag` 参数。
- `initialize` 仍声明 `resources.listChanged=true` 但不发通知。
- `push()` 吞异常（含 BrokenPipe），死订阅不会自清。
- 单卷不可读时仅汇总告警，不逐卷报错。

---

## 已知问题（4.0.1 待修）

> 4.0.0 发布面文案已按实际代码改正；以下行为缺陷**不在 4.0.0 修复**，登记待下一版处理。

1. ~~**根解析两套并存**：六个数据卷的位置写死在模块旁（不读 conf），消息卷不随 `--root` 走 —— 换根时部分卷仍落在旧处。~~ **v4.0.3 已修**（`volume_paths.py` 单根解析）。
2. **`digest` 兜底恒 0**：多级目录件缺失时的「原文兜底」路径统计恒为 0 条。
3. **跨卷引用失败静默返回空**：跨卷生成互见引用失败时返回空串，不告警、不标记。
4. **`alarm` 判据脆弱**：拿自产的中文字串当状态判据；异常与硬警同样都以退出码 1 结束，调用方无法区分。
5. **`cross_ref.verify()` 无前缀自比自过**：不带 `[#N]` 前缀的条目，校验时自己和自己比，恒通过。
6. ~~**`pull` 把任意后条算已回**：只要存在更晚的条目就判为「已回复」，不校验作者与关联单号。~~ **v4.0.3 已修**（只认 `[re=]`）。
7. ~~**`read_vol` 无锁读**：并发追加时可能读到半行。~~ **v4.0.3 已修**（共享锁读）。
8. **`digest` 复杂度 O(命中×卷)**：每条命中都重扫各卷，卷多时线性放大。

> 另：本次修的四条里，「消息条目验签 / 显式回应引用」原不在本清单，属清单外新增修复（v4.0.3）。
