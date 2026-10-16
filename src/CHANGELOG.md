# CHANGELOG

> **【口径归一 · 2026-10-14 · 老宋令】** 历史条目中的「承重墙」一词，对外统称改从新版——即「**N 条特点**」（2026-10-14 起产品线统一为「**八目**」八轴）；「5 条工程优势」亦改称「5 条**工程**优势」（不宣称企业级）。**仅改称谓·条目事实未改**（不静默改）。

## v3.2.1 · 2026-10-16

### 补包与版本轴归一（老宋 2026-10-16 15:39 掌印）

**一、I18N.md／CHANGELOG.md 随三包**（修**死链**）
- 病：三包包内 conf 注释写「对照表见 `I18N.md`」，而 `I18N.md` 只在 `src/`，**未随包** ⇒ 下载者按注释找不到（`daybook/daybook.conf`／`daybook-mcp/daybook.conf` 各一处）＝**悬空指针**，违 `pack.py`「自包含」承诺。
- 药：三包 `doc` 列表各加 `I18N.md`／`CHANGELOG.md`（后者为对外说明书，同随）。`src/pack.py` 三处。

**二、MCP `serverInfo.version` 并入套件轴**
- 病：`src/mcp_server.py` 的 `SERVER_INFO['version']` 长期为 `'1.8.1'`（daybook 旧例「修复版 r2」，v3.0 首发即带）⇒ 与套件语义版本 **双轴并存**；MCP 客户端展示该值会令用户误判 daybook 版本（v3.2 之外又见 1.8.1）。
- 药：并轴 ⇒ `'3.2.1'`（与 `src/pack.py` `SUITE_VERSION` 同源同发）；`src/README.mcp.en.md` 同步。
- **不动**：`PROTOCOL_VERSION = '2024-11-05'`（MCP 协议版本，另一独立轴）。

**版本号**：升 **v3.2.1**；构建号 起居注 1920 ／ 璇玑 **3473**（+1）／ 司南 2195。

**未动**：账形三条、append-only 纪律、零依赖、产物==源守卫；三包产品件**零逻辑变更**（仅 `mcp_server.py` +1 行注释与一个字符串常量、`pack.py` 清单加项）。

## v3.2 · 2026-10-16

### 标识符英文化 ＋ 注释中英对照

**范围**：`src/` 源码 ＋ 三包（`pack.py` 重生成）＋ 三份 conf 样例 ＋ 文档；仓内索引／游标随新名重算。

**改名（英文为准·中文兼容别名）**：
- 配置节：`[卷][条目][规则][索引][触发][多级][钩子]` → `[volumes][entries][rules][index][trigger][multilevel][hooks]`
- 配置键：`头正则／附头正则／标正则／字段／根／输出目录／索引前缀／清单名／自动索引／增量索引／多级索引／二级键／变动令`
  → `head_regex／extra_head_regex／tag_regex／fields／root／out_dir／index_prefix／manifest／auto_index／incremental／multilevel_enabled／level2_field／on_change`
- 数据字段：`卷／行号／时间／类／标题／作者` → `volume／line／time／category／title／author`
- 命令：`多级索引` → `multiindex`（并存）；`编排／司南` → `orchestrate`（并存）
- 开关：`--卷` → `--volume`、`--序` → `--order`（旧写法并存）
- 下钻层级枚举：`部／类／属` → `volume／category／entry`（旧写法并存）
- 角色名：`施工／复审／返工／终审／广播` → `build／review／rework／final／broadcast`；`@非作者:` → `@non-author:`
- 生成件：`索引_<卷>卷.tsv/.txt` → `index_<卷>.tsv/.txt`；`.游标_<卷>.json` → `.cursor_<卷>.json`；`.索引锁` → `.index.lock`；
  `备份/` → `backup/`；`多级/` → `multilevel/`；`<卷>_目录.md/.tsv` → `<卷>_catalog.md/.tsv`；`总目录.md` → `catalog.md`；`版本.txt` → `version.txt`
- MCP 资源 URI：`daybook://目录/<卷>` → `daybook://catalog/<卷>`（旧 URI 仍读）

**兼容**：旧 conf 键、旧索引表头、旧中文查询口径（`query 类=x`）、旧生成件名、旧 URI、旧层级名、旧角色名与 `@非作者` —— 一律**照旧可用**。别名归一只有四处入口（`load_conf`／`query`／`load_roles`／`load_rules`），其余代码只见英文。对照表：`I18N.md`。

**注释**：全仓注释与 docstring 改**中英对照**（中文原意保留 ＋ 英文）。

**未擅译 · 老宋裁（2026-10-16）**：四库三序 `子／史／集`（子·按类｜史·按年月｜集·按作者）为**文化术语**，裁「**就中文**」——**不设英文别名**，保持中文；英文文档仍写作 *by class / by month / by author*。卷名（协作／语汇／百科）与条目正文＝**用户数据**，不动。

**未动**：账形三条、append-only 纪律、零依赖、产物==源守卫；各卷原文一字未改。

**版本号**：升 **v3.2**（老宋 2026-10-16 裁「升级」）；三包同源同发 v3.2。

### 复核与修（亲跑 · 2026-10-16）

- **契约行复原名**：`query` 首行曾写作 `命中 N 条 / N hits` → **复原** `命中 N 条`（`e11_test` 等按 `命中 N 条` 解析；输出散文不属本次改名范围）。
- **`daybook_multidx.py` 两处丢「卷」复原名**：`# <卷>卷 · 多级目录…`、`总条数… 部：<卷>卷`。
- **多级目录读取的兼容补齐**：旧版 multidx 产出的是**中文表头**（`卷/二级/行号/时间/类/作者/标题`）；`orchestrator.read_multidx_rows` 与 `mcp_tools._read_multidx_tsv` 现将表头一律归一（复用 `daybook.canon_field`），且**新旧文件名皆认**（`<卷>_catalog.tsv`／`<卷>_目录.tsv`）。修前 MCP `daybook_multi_query` 只认 `_目录.tsv`，读不到新产物（已修，并加自检两路：新英文名＋旧中文名）。
- **注释／docstring 里的旧路径口径**同步（`备份/`→`backup/`、`多级/`→`multilevel/`、`索引_*`→`index_*`）。
- **机检**：全部改动 .py 按 AST 剥 docstring 后逐字比对（HEAD vs 现行），差异只落在注释／docstring 与上列既定改名处；四路并行改注释者经 token＋AST 复核，确认**只动注释**（结构、控制流、非 docstring 字符串均未擅动）。

**范围界定**：本次只动**标识符／字段名／列名／生成件名／URI**（→英文）；**输出散文**（提示语、日志、表格标题的中文）保持原样或**增补**英文，未替换；machine 契约行（如 `命中 N 条`）保持原字面。

### 修 · `mcp_test.py` 与工具的时间戳错位（2026-10-16 · 老宋令「即刻修」）

**症候**：`mcp_test` 5 项失败（**HEAD 同样失败**，非本次引入）：`7.2 索引重建`、`5.2 命中 1 条`、`P1-3.2 非法卷名`、`F2.1/F2.3 unread`、`F3.2 heartbeat`。

**根因（测试侧陈旧·两端错位）**：W-75 加固（修④/⑥）后，写工具改为「**签名覆盖带时间戳的载荷** ＋ `ts` 须在 ±60s 窗口内」：
- `daybook_index` 验 `reindex:<ts>`，`daybook_unread` 验 `unread:<agent>:<ts>`，`daybook_heartbeat` 验 `heartbeat:<ts>`；
- 而测试仍签**旧载荷**（`'reindex'` / `'heartbeat'` / `aid`）且**未传 `ts`**（缺省 `0` ⇒ 必越窗）。
- `P1-3` 测试亦陈旧：工具「**先验签后取卷名**」（W-75 修④·防未授权请求泄露卷名），故未鉴权的 `../` 请求先撞 **agent_id 红线**，触不到「非法卷名」分支。

**处置**：**改测试**（工具的反重放设计为准，不回退工具）——三处写调用补 `ts` 并改签对应载荷；`P1-3` 先注册 agent 并签名，再断言「非法卷名」。**结果**：`mcp_test` **23/23 PASS**（连跑 3 次稳定）。

**未动工具逻辑**：`ts` 校验、验签顺序、红线一律未改。

### 本版裁示（老宋 2026-10-16）

| 事项 | 裁示 |
|---|---|
| 是否升 v3.2 / 发版 | **升级**（本版即 v3.2·三包同源同发） |
| 四库三序 `子/史/集` | **就中文**（不设英文别名） |
| `版本.txt` → `version.txt` | **同意**（生成件命名一并英文化） |
| `mcp_test` 5 项失败 | **修**（已即刻修·23/23） |
| `e11_test.py` 未纳入验收 | **同意**（需自备 `压力卷.txt` ＋注册 `压力` 卷之 conf·属内部实验件·未随仓发布） |

## v3.1 · 2026-10-15

### 四库式多级索引（部→类→属·按需下钻）

平铺索引（一条一行）之上加一层**层级目录**：**部(卷) → 类(二级) → 属(条目)**，并出跨卷总目——使 36 万条量级仍能按层级下钻取上下文。**索引是目录不是真相**（三条账形一字未动）；产出全为**派生件**（可删可重建）。

**造① `daybook_multidx.py`（260 行·新增·零依赖）**：
- 输入＝各卷**平铺索引 TSV**（`daybook.py index` 之产物·不读卷·不碰账）；输出三件：
  `多级/<卷>_目录.md`（部→类→属 树）／`多级/<卷>_目录.tsv`（机读）／`多级/总目录.md`（跨卷·子(按类)／史(按年月)／集(按作者) 三序）
- 确定性：同索引源·任何时刻算·得同一产出（双 `PYTHONHASHSEED` 逐字同）；`--now` 钉死时间戳供双跑校对
- 裁剪（大账本省体积）：`--卷 <名>` 只出该卷目录；`--序 子|史|集` 总目录只出选定序
- 三级树每条**恰出现一次**（保真）；零依赖（仅标准库）·不联网

**修② `daybook.py` 加 `multiindex` 子命令（+14 行·523→537）**：
- `python3 daybook.py multiindex` 与 `index` **同一入口**（懒 import·不增启动开销）
- `watch` 变动后续建：索引之后、备份之前自动重算多级目录（`[多级] 多级索引=是` 控制；失败不挡索引与备份）

**补·conf 加 `[多级]` 段（`daybook.dist.conf`／`daybook.sample.conf`）**：`多级索引`（watch 自动续建开关）／`输出目录`／`二级键`（类·默认｜作者）

**补·`pack.py`**：`daybook_multidx.py` 入 daybook 与 mcp 两包（mcp 含 daybook.py 全体）；打包清理段加多级目录（运行时派生件不随包发）；`SUITE_VERSION` v3.0 → **v3.1**

**挂 `mcp_resources.py`／`mcp_tools.py`（璇玑侧）**：
- **resources** 新增 `daybook://目录/<卷>`、`daybook://目录/总目` —— 读 `<根>/多级/*.md`（text/markdown），支持行范围；**存在才列**，未跑 `multiindex` 时静默不列
- **tool** 新增 `daybook_multi_query` —— 四库式**按需下钻**：`level=部` 各卷概览｜`类` 二级分组计数｜`属`（默认）条目提要行（`full` 可回全文）；每条附**互见引用** `↪[卷#L行-SHA8]`（hash 复用 `cross_ref`·卷路径按 conf 卷表校正）。**LLM 不必拉全卷** ⇒ 长上下文＝按需下钻

**接 `orchestrator.py` 加 `digest` 子命令（司南侧）**：
- `digest [--vol 卷] [--cls 类] [--limit N]` 读多级目录 → 出「**部▸类▸属**」变动摘要；缺目录件时**按在册卷原文兜底**（自持可跑）
- `--push 收件人` 经 `agent_message` 推送（不在线**不阻断**·摘要落编排卷）；摘要每条附互见引用
- `selftest` 增 2 项（digest 读目录 → 摘要结构；按类过滤命中）

**验收（跑前写死·六条全过）**：
1. 确定性：双 `PYTHONHASHSEED` 逐字同 ✓
2. 保真：目录树条目数＝平铺索引行数·每条恰一次；总目录每视图＝卷内合计 ✓
3. 性能（36.5 万条·同机同料）：`multiindex` 4.71s ／ `index` 2.59s ＝ **1.82×**（判据 ≤2×）✓
4. 兼容：`index`／`query`／`watch` 原行为不变（增量跳过、按卷行号回读原文、增量续建）✓
5. 零依赖：新件仅标准库（argparse/io/os/re/sys/collections/datetime）✓
6. 许可：新件带 SPDX 头·MIT（daybook/mcp 包）✓

**③④ 增量验收（MCP／orch 侧）**：
- MCP 资源 **7 条**（3 卷 ＋ 总目 ＋ 3 卷目录·**存在才列**）｜目录 read 支持行范围 ✓
- `daybook_multi_query` **部/类/属三档全通**·`full` 回全文·非法目录名防护 ✓
- **互见引用**经 `cross_ref.verify_ref` 校验 **True** ✓（hash 复用 cross_ref·卷路径按 conf 校正）
- `multi_query` 输出双 `PYTHONHASHSEED` **逐字同** ✓｜未生成多级目录时**友好降级**（不崩·给指引）✓
- `orchestrator.py selftest` **全绿**（含 digest 2 项）✓
- **MCP 集成测试 `mcp_test.py` 与 HEAD 基线逐条一致**（18/23 PASS·同 5 项既有 FAIL·**零回归**）✓

**边界**：源件改齐·三包**同源同发 v3.1**（一致守卫全同）；**未破「索引是目录不是真相」**（三条账形一字未动）。

## v2.0 · 2026-10-08

### 并发正确性夯实（W-75·原子写小件 + MCP 三修）

daybook 是"共同记忆"的地基——并发正确性不夯实，索引重复/游标覆盖/条目交错 ⇒ 记忆不可信。本版把 build() 的"读游标→读卷尾→写索引→写游标"序列全临界区化，三处 MCP 留题一并清。

**造① `safeio.py`（124 行·新增·零依赖）**：
- 三原语：`locked(path)` 上下文 / `atomic_append(path, data)` / `read_modify_write(path, fn)`
- 降级：无 fcntl 平台退 mkdir 原子锁（os.mkdir 天生原子）
- 自测：100 线程 atomic_append 零交错、20 线程 read_modify_write n=20

**修② `daybook.py` build() 接锁（+3 行·513→516）**：
- 索引 TSV append、游标 json 读改写、卷首清单写入，全部进 `with locked('.索引锁')` 临界区
- 锁粒度＝每输出目录一把锁，不锁卷原文（卷追加已有 O_APPEND）

**修③ `daybook_append.py` 长条目走锁（+5 行·105→113）**：
- 超 PIPE_BUF 不再 exit 2 拒写，改走 `safeio.locked(path)` 加锁写入路径

**修④ `mcp_tools.py` 验签顺序（+2 行·447→455）**：
- daybook_append / daybook_unread / daybook_mark_read：先 `_verify_agent` 后 `_safe_vol`
- 防未授权请求泄露卷名信息（路径穿越测试期望相应更新：P1-3.2 接受"非法"或"agent_id"或"写工具必须"）

**修⑤ `mcp_tools.py` 编码检测不静默**：
- `daybook_unread`：硬编码 `decode('utf-8')` ⇒ 走 `_db.sniff`（gb18030 等卷不乱码）
- `daybook_list`：硬编码 `open(encoding='utf-8')` ⇒ 走 `_db.sniff`

**修⑥ 时间精度分钟⇒秒**：
- `daybook_append.py`：`strftime('%H:%M')` ⇒ `strftime('%H:%M:%S')`
- `mcp_tools.py` daybook_alive：`strptime('%H:%M')` ⇒ `strptime('%H:%M:%S')`（兼容旧分钟级条目）

### 判据（J1–J9 全过）

| # | 判据 | 结果 |
|---|---|---|
| J1 | 行为不变：修后三 TSV md5 与修前逐字一致 | ✓ 7ce2d2a1 / e024e12d / 42a75f3a |
| J2 | 并发红绿对照 | ✓ 红证：TSV 重复行（末行×2）；绿证：10 轮并发零重复、md5 与单进程一致 |
| J3 | 长条目 >512B 走锁路径 | ✓ 657B 条目写入成功、读回逐字一致 |
| J4 | 降级：fcntl mock 后 mkdir 锁 | ✓ 10 线程并发 TSV 零重复 |
| J5 | MCP 三修最小复现 | ✓ 修④ 无签先被拒 / 修⑤ gb18030 不乱码 / 修⑥ 秒级 alive |
| J6 | MCP 测试 23/23 | ✓（路径穿越测试期望更新匹配修④） |
| J7 | 三实现零回归 | ✓ py/sh/c 各 5/5/5 |
| J8 | 版本号重算 | 修前 12 件 1600 行 ⇒ 修后 13 件（+safeio.py）1743 行 |
| J9 | 报回四件走落条.py | ✓ #265 |

### 红证探针（J2 缺一不可）
先建基线游标，追加一条到协作卷，两进程同时 index：修前两进程都读旧游标(resume_byte=旧值)、都读卷尾部（同样字节）、都 append TSV（同样行）⇒ 末行重复×2。修后 `with locked('.索引锁')` 串行化，零重复。

## v1.9 · 2026-10-08

### 跨 AI 消息平台前三项（W-DB-025·全纯文本）

把 daybook 从"单机日志"升级为"跨 AI 消息平台"·仍保持纯文本 + 零依赖。三项新能力都复用现有 append-only + G3 验签机制·不引入新依赖·不另起服务。

**F1 收件人寻址**：
- `daybook_append.append_one` 加 `to` 参数·条目格式新增 `[致=ag-xxx,ag-yyy]` 段
- MCP `daybook_append` 工具加 `to` 入参·schema 声明
- 校验：`to` 里每个 ID 必须在 G3 注册卷注册·防垃圾寻址
- 不填 `to` 即广播·兼容旧条目

**F2 已读未读**：
- 游标多 agent 化：`.已读_<agent>_<卷>.json`·记录每个 agent 对每卷的 `resume_byte`
- 新增 MCP 工具 `daybook_unread`：查某 agent 对某卷的未读条目·验签防任意查他人未读
- 新增 MCP 工具 `daybook_mark_read`：推进游标到卷末尾·签名 payload=`read:<volume>`

**F3 心跳 + 探活**：
- 新增 `心跳卷.txt`·agent 周期 append `[心跳]` 条目
- 新增 MCP 工具 `daybook_heartbeat`：append 心跳·验签 payload=`heartbeat`
- 新增 MCP 工具 `daybook_alive`：扫心跳卷最后一条时间·在 timeout 秒内即 online·纯查询不验签

**测试**：mcp_test 19/19 → 23/23 PASS（+ F1×2 + F2×1 + F3×1）。

### 起因
- 用户点破关键洞察：协作卷.txt 实际被用作跨 AI 的即时消息平台（GLM-5.2/汤姆/老宋/监理 多角色异步通信）——append-only 共享日志即消息总线。
- 老宋令："我们做前三项·还是保持纯文本"——F1 寻址 / F2 已读未读 / F3 心跳·都复用现有机制·不引入新依赖。

### 零依赖承诺保持
- 仅用 Python 3 标准库（json/os/time/hmac/hashlib）
- 游标 `.已读_<agent>_<卷>.json` 是 JSON 文本·可人读
- 心跳卷是纯文本·append-only·可审可查
- `to` 字段写入条目原文·不引入新文件

## v1.8 · 2026-10-08

### DAYBOOK × MCP × Agent 协作底座（W-DB-023 三工单）

**G1 仓库瘦身**：3.3G → 18M。删 2.2G 备份 + 1.0G 压力卷归档 + 160K 开发卷（索引器自动重建 92K 不算违例）。保留压力卷.txt 10.8K + 实验卷 100K + 实验卷_EN 140K + 备份/2026-10-06_024023 24K。

**G3 Agent 协作底座（6 模块 + 1 测试·1192 行）**：
- `agent_registry.py`：Agent 身份注册 + HMAC-SHA256 签名 + 吊销（fenced token 防误用）
- `task_volume.py`：任务状态机（待办→进行中→完成→待审→已审）append-only·终态拒迁·非法迁移被拒
- `cross_ref.py`：跨卷引用 `[卷名#L行-SHA8]`·解析 + 完整性校验 + 篡改检测
- `agent_message.py`：Agent 间消息·Unix socket + JSON + newline 协议·inbox 卷 append-only
- `agent_lock.py`：`fcntl.flock` 文件锁 + TTL 租约 + fenced 释放（防过期租约误改）
- `agent_heartbeat.py`：心跳卷 append-only + dead_after 周期判定 + dead_agents 列出 + recover
- `agent_test.py`：7 项验收·全 PASS

**G2 MCP 接口（5 模块 + 1 测试·911 行 + cross_ref +11 行 verify_ref）**：
- `mcp_transport.py`：JSON-RPC 2.0 编解码·5 个标准错误码（-32700/-32600/-32601/-32602/-32603）
- `mcp_resources.py`：resources/list 列卷·resources/read 读卷（含 offset/limit 行范围）
- `mcp_tools.py`：6 个工具 schema + call（daybook_query/append/index/list + cross_ref_make/verify）
- `mcp_prompts.py`：4 个 prompt 模板（daily_journal/weekly_review/cross_ref_audit/agent_handover）
- `mcp_server.py`：主入口·stdin/stdout 循环·dispatch 8 method（initialize/resources×2/tools×2/prompts×2/ping/shutdown）
- `mcp_test.py`：7 项验收·全 PASS（subprocess 真启动 mcp_server·DAYBOOK_ROOT 隔离）

**daybook.py 加 `mcp` 子命令**：一行 `import mcp_server; mcp_server.serve()`，让 MCP 服务器跟 index/watch/query 同一二进制。零依赖、不联网、不另起进程。

### 起因
- W-DB-023 工单三件：G1 清理 + G3 Agent 底座 + G2 MCP 接口。史泰龙施方挂了，GLM-5.2 顶上。
- 目标不是把 DAYBOOK 做成平台，而是把"个人/小团队 plain-text 起居注"该有的协作接口补齐：跨 Agent 能注册、能发消息、能锁任务、能验心跳；外部 LLM 能通过 MCP 标准协议读卷、调工具、取 prompt。
- 至此止步。plain-text 派的体面是不把工具做成平台。

### 零依赖承诺
- 全部 13 个新文件仅用 Python 3 标准库（os/sys/time/json/socket/fcntl/hmac/hashlib/subprocess/re/tempfile/threading/shutil）
- 不依赖 mcp 官方 SDK·不依赖 fastapi/uvicorn/pydantic·不依赖任何第三方包
- 测试在 `/tmp` 与 `DAYBOOK_ROOT` 隔离跑·生产目录零污染

## v1.7 · 2026-10-06

### E-06 + E-11 跑测自证
- **daybook 上下文（E-11）**：新增 `query` 子命令，AI 用 daybook 当长期记忆外挂，按字段精确查询条目原文（TSV 过滤 + 行号定位），不塞整个 daybook 进 128K 上下文也能"表现得像有整个 daybook 上下文"。
- **压测脚本**：新增 `stress_test.py`，批量原子写入 N 条到压力卷，验证 daybook 存得下。
- **E-11 跑测脚本**：新增 `e11_test.py`，10 题记忆密集问项 × 四组对照（实验组 vs 128K 截断）。
- **E-06 阶段成果**（单机 i5-10600 / Python 3.9.6）：
  - 1 万条 / 1 MB：写入 0.8s / 索引 <1s
  - 10 万条 / 11 MB：写入 7.3s / 索引 <1s
  - 100 万条 / 107 MB：写入 69s / 索引 8.4s
  - 1000 万条 / 1.0 GB：写入 786s / 索引 2:08
- **E-11 对照**（同硬件同口径 365000 条 27 MB）：daybook2 全量索引 3.12s（首次）/ 增量跳过（再次）；另一智能体实测 3.2s——同量级同性能。
- **E-11 10 题验收**：实验组（daybook 上下文）通过 10/10，对照 D（128K 截断）通过 2/10。daybook 上下文胜 128K 截断。
- **query 优化**：同卷只 readlines 一次复用 lines（避免 O(n*m) I/O 灾难）；加 `--count` `--limit=N` `--sample=N` `--context=N` 防爆 stdout 并支持触发上下文召回 N 条。1000 万条上 `--count` 10.9s（17s→10.9s），`--limit=1` 13.4s（23s→13.4s）。

### 起因
- 主作者令："E-06 和 E-11 两个实验都要做，而且要科学的做、严谨的做。最好、最牛的实验，就是现在就启用 DAYBOOK 2，全程记录更新、可查验。"
- E-06 是"存得下"（百亿条不崩），E-11 是"用得上"（AI 长期记忆外挂打破上下文窗口限制）。两个实验并行跑，全程记进 `实验卷.txt`（append-only 起居注体例），任何人可 `cat` 查验。

### bug 修复
- 增量索引 append 模式行号没累加：`_parse` 加 `base_ln`，返回 `(rows, final_ln)`，游标加 `last_lineno` 字段。
- `final_ln` 多算/少算：用 `txt.count('\n')` 算实际行数，不用 `ln-1`（避免 split 末尾空字符串偏离）。

## v1.6 · 2026-10-06

### 第 14 条特点：明档可见
- **README.md**：特点从 13 条扩为 14 条。第 14 条 = 明档可见：卷置项目根目录（桌面可见层），双击即开，任何编辑器可读，可手动追加批注。不藏隐藏目录、不进数据库、不要专用客户端。AI 自带 MD 物理在本地但藏在 `~/.ai/` 之类隐藏路径，用户看不见摸不着，与在云上差别不大；daybook 的明档把卷置项目根目录，肉眼可见，用户主权完整。
- **README.en.md**：在"The 13th feature"节后加"The 14th feature: visible files, no hidden storage"小节，并补一段说清第 14 条是用户主权差距：**数据主权 ≠ 文件在本地**——本地但隐藏不是真主权。**数据主权（不进云） ＋ 明档（不藏起来）= 用户完整主权**，是 33 天 9 子系统能管下来的实证。
- 同步把"5 条工程优势"开头从"13 条特点之上"改为"14 条特点之上"。
- 把 12 条本体论差距 / 13 条方法论差距的尾注，补上 14 条用户主权差距的尾注，三者并列。
- 第 14 条尾注加 watch 联动一句：watch 模式下手动批注与 `daybook_append` 写入同等——索引自动跟，无需手动重算。明档不止于"能看"，还包括"用户手写在卷上跟引擎写入同等对待"。

### 起因
- 用户问"起居注可以做 AI 智能体的本地长久记忆吗？跟 AI 自带 MD 有什么区别？"——答完后用户补一条："还有一个好处，明档，明明白白的可以放在桌面，随时查阅，对用户极其友好。"主作者令"必须加"。
- 第 14 条把"明档"立成一条特点：数据主权是"文件不进云"，明档是"文件不藏起来"——两者合起来才是用户主权。AI 自带 MD 即使存在本地也藏在 `~/.ai/`，与在云上差别不大。33 天 9 子系统协作能管下来靠的就是明档——用户随时打开桌面就能看、能批、能裁。

### 脱敏处理（对外发行准备）
- 用户令："DAYBOOK2 是要对外发布发行的版本，与我们的内部项目都没有关系，切记。DAYBOOK2 里面的案例也尽量脱敏，不牵扯我们自己的项目。"
- 处理原则：内部项目名（墨斗/辞海/大宗师/纵贯线/MYSEA/MEDO 等）、内部角色署名（老宋/汤姆/皮特/斯坦森 等）从对外发行版移除。
- README.md / README.en.md：作者署名段改为通用"主作者 / 贡献者"；案例引用中"墨斗"改"榫卯"；"老宋"改"用户"或"主作者"；mysea 等内部名换成通用表达。
- 历史版本（v1.0–v1.5）的 CHANGELOG 保留原样，作为内部开发记录——脱敏只动 v1.6 及之后的对外文档。

## v1.5 · 2026-10-06

### 第 13 条特点：海量可通读
- **README.md**：特点从 12 条扩为 13 条。第 13 条 = 海量可通读：分卷天生解耦，五卷各 100 万条 = 500 万条仍 ≈ 250 MB 纯文本；按实测 36.5 万条 2.84 秒，500 万条一次通读 ≈ 40 秒。AI 记忆体的"通读"只能 retrieval 取碎片，永远看不到全年原文的真相；daybook 让"通读起居注"成立——海量是分卷换来的"五份各可一次通读"，把 AI 从"索引动物"升级成"通读动物"。
- **README.en.md**：在"The 12th feature"节后加"The 13th feature: massive volumes, full read-through"小节，并补一段说清第 12 条是本体论差距（记忆 ≠ 引擎）、第 13 条是方法论差距（记忆 ≠ 碎片召回），两者缺一不可。
- 同步把"5 条工程优势"开头从"12 条特点之上"改为"13 条特点之上"。

### 起因
- 用户在弄完 DAYBOOK 后意识到："弄出海量了"——五卷架构（辞海/星河/九章/观照/天工）天然分卷，让"通读起居注"在 500 万条规模下仍成立。CAM 是后果，**通读才是要点**。第 13 条把这一判断记进 README。

## v1.4 · 2026-10-06

### README 加"653 行够了"小节
- 中英 README 在"遇大问题先问三句"之后、"作者与贡献"之前，新增 "## 653 行够了" / "## 653 lines is enough" 小节
- **三条结构判断**：① 难的部分早有别人写好（持久化/并发/审计三件交给文件系统+POSIX+append-only，零行存储引擎/锁/版本树）② 拒绝做不该做的事（不做向量召回/多租户/UI，少做 ≠ 偷懒是边界感）③ 跨年代五语言保单（同 653 行 5 种语言写，66 年跨度，唯一敢说"2066 年还能读"）
- **适合谁**：个人用户 / 10 人开发团队 / 法律团队 / 国家安全机关——四个目标场景的用法各占一行
- **关键：不用维护**：零依赖、零安装、零升级、零运维；引擎不在记忆还在

### 跨平台原子写收尾
- **动态 PIPE_BUF 探测**：`daybook_append.py` 把写死的 `LIMIT = 4096` 换成 `os.pathconf(path, 'PC_PIPE_BUF')` 动态探测，新增 `get_pipe_buf(path)`——文件存在探文件本身，不存在探父目录，探测失败退保守值 4096。macOS 实测返回 512，Linux 仍 4096，**写阈值跟随所在文件系统**而不是假设所有人都跑 Linux。
- **超限提示动态化**：`PROMPT` 改成 `PROMPT_TEMPLATE.format(limit=limit)`，提示里的字节数随文件系统变化（macOS 显示"超 512 字节"，Linux 显示"超 4096 字节"）。
- **`--check` 子命令**：`python3 daybook_append.py --check [路径]` 打印目标路径所在文件系统的 PIPE_BUF 与平台提示，供部署前置检查。新机器（NFS / WSL / 树莓派）装完先跑这句再投入使用。

### 烟雾测试（回归保险）
- **新增 `daybook_test.py`（71 行）**：一键复现"600 并发零交错"——起 20 进程各写 30 条，验证 `---` 分隔符数 == 600、每个作者签名数 == 30。PASS 返 0，FAIL 返 1，可入 CI。从今天起 README 写的"600 零交错"不再是历史证词，而是 `python3 daybook_test.py` 一键复核的持续承诺。
- 实测：3.33s 跑完 600 条，PASS。

### README 工程优势
- **README.md**：12 条特点之后、"## 对企业" 之前，新增"## 5 条工程优势"小节：成本曲线（用户数 × 0）/ 可审计性（起居注体例满足金融政务留痕）/ 数据主权（无云绑定，tar 即备份）/ 并发安全是数学保证（POSIX 承诺不是测试没事）/ 崩溃恢复（无半条状态）。一句话总结：成本归零 ＋ 数据主权 ＋ 审计留痕 ＋ 并发数学保证。
- **README.en.md**：同步加 "## Five engineering advantages" 五条 + 一句话总结。

### 行数订正
- README 中英文"为什么它只有几百行"段从"主程序 293 / 并发写 42 / 哨 39 = 374"更新为"主程序 325 / 并发写 77 / 哨 39 / 烟雾测试 71 = 512；跨年代五语言全栈 653"。

### 验收
- `python3 daybook_append.py --check` → PIPE_BUF: 512 字节（macOS APFS）✓
- `python3 daybook_append.py /tmp/_probe_卷.txt 测试者 "动态 PIPE_BUF 探测后的第一条` → 写入成功，文件内容完整 ✓
- 写 600 字节超限 → `★ 本条超 512 字节...`（提示里的字节数随系统变化，证明动态探测生效）✓
- `python3 daybook_test.py` → 600 / 600 条完整，零交错，PASS ✓

## v1.3 · 2026-10-06

### 合并（从 daybook 子项目移植）
- **根目录配置**：`[索引] 根=` 替换原硬编码 `os.path.basename(HERE) == '起居注发行版'`——目录改名不再崩，支持发行模式/项目内嵌模式/绝对路径三种
- **自动备份**：新增 `backup` 命令 + `backup()` 函数，把所有卷复制到 `备份/YYYY-MM-DD_HHMMSS/`，append-only 纪律适用于备份（旧的不删不改）
- **watch 自动备份**：watch 模式变动即重算索引 + 变动即自动备份
- **P1c watch 容错**：watch 模式加 `try/except`，编辑器原子写入半截文件时不再退出
- **第 12 条特点**：README.md 加"12 条特点"完整对照表，第 12 条 = 记忆不依赖引擎存活（本体论差距：记忆的本体 ≠ 引擎）
- **README.en.md 第 12 条**：英文版"Why it outlives other memory systems"节末加"The 12th feature: memory outlives the engine"小节，说清 mysea/LangChain/MemGPT 把记忆做成引擎私有格式的死穴

### docstring 修正
- `daybook.py` docstring 改 `qijuzhu.py` → `daybook.py`，`起居注.conf` → `daybook.conf`，加 `backup` 命令用法

### 验收
- `python3 daybook.py index` → 协作 5｜辞海 5｜大宗师 5｜合计 15 条 ✓
- `python3 daybook.py backup` → 备份 3 卷，diff 逐字一致 ✓

## v1.1 · 2026-10-05

### 修复
- **P0**：`_blocks` 扫描时记录起始行号，`build` 不再用 `txt.index`——重复块正文行号定位错乱已修复
- **P1a**：删除 `if False else None` dead code
- **P1b**：`fill` 开头 `tag is None` 兜底，未配标正则时不出标签不崩溃
- **P1c**：`watch` 加 `try/except`，编辑器原子写入半截文件时不再退出

### 新增
- **根目录配置**：`[索引] 根=` 控制卷路径相对哪里解析（空=相对 daybook 自身；..=上一级；绝对路径=原样）
- **5 种语言实现**：Python（权威版）/ sh / C / Fortran / BASIC——66 年保单
- **样本卷**：`sample/` 三卷各 5 条假条目，发布必备三件齐全
- **测试套件**：`test/run.sh` 跑 5 种实现，验收 Python 权威版 5/5/5 + 编码检测
- **LICENSE**：MIT
- **LANGS.md**：各语言实现范围说明（金字塔结构，不强行对齐）
- **范式背书**：README 末尾加古代起居注制度对位说明（君举必书 / 日讲官侍值 / 骑缝盖翰林院印 / 天子不观起居注）
- **自动备份**：`backup` 命令 + watch 模式变动即备份，备份目录 `备份/YYYY-MM-DD_HHMMSS/`，append-only 纪律适用于备份
- **README 双语版**：中英对照，给 AI 智能体的最小指令 + 用户手册 6 步（含手动备份）
- **开发者署名**：手艺人老宋 <songliansheng@vip.sina.com>
- **第 12 条特点**：记忆不依赖引擎存活——AI 记忆体的"记忆"是引擎运行时状态，引擎崩了记忆即蒸发；daybook 的"记忆"是独立 *.txt，引擎不存在了记忆照样可读。特点从 11 条扩为 12 条。
- **第 13 条特点**：通读成本可承担——1 天 1000 条 ≈ 100KB；1 年 365000 条 ≈ 22-37MB 纯文本 ≈ 30 面。人 1 小时通读一年，AI 一次推理塞 4 万 token 够。AI 记忆体"通读"只能 retrieval 取碎片，daybook 通读是把全年原文塞进上下文看真相。特点从 12 条扩为 13 条。

### 改名
- 文件名：`qijuzhu.py` → `daybook.py`（docstring/conf 注释同步）
- 配置文件名：`起居注.conf` → `daybook.conf`
- 目录名：`起居注发行版/` → `daybook/`（对外通用名）

### 验收
- 协作卷 414 / 辞海卷 79 / 大宗师卷 165 / 合计 658 条 ✓
- 与 v1 输出 diff 全同 ✓
- 三卷编码全 utf-8 ✓
- test/run.sh PASS 2/2 ✓

### v1.1 完整发行版收尾（同日补丁）
- **sh 重写**：`daybook.sh` 用 awk FNR 跑通样本卷 5/5/5，与 py 前 5 字段（卷/行号/时间/类/标题）逐行对齐
- **C ANSI 化**：`daybook.c` K&R 风格签名改 ANSI (C89+)，避开 C23 移除 K&R 的 warning；并修 `line+18` 偏移 bug，类/标题字段正常解析；卷名取文件名去 `.txt`
- **test/run.sh 加双跑**：sh 实现三卷各 5 条验收、C 实现编译并跑通三卷（表头+15 行=16）验收
- **README v1.1 完整发行版交付表**：5 件全齐（说明/5 语言实现/配置/真样本/测试套件）
- 验收：`bash test/run.sh` → `PASS: 4 / FAIL: 0`（本机无 gfortran/bwbasic，Fortran/BASIC 由代码审查保证）

## v1 · 2026-10-05

### 初版
- 纯文本记忆体，零依赖（仅 Python 标准库）
- 7 字段 tsv 输出（卷/行号/时间/类/标题/字数/含订正）
- 编码自动检测（BOM/UTF-8/GB18030/Big5/CP936/Shift-JIS/latin-1 兜底）
- watch 模式（mtime+size 指纹变动触发重算）
- 卷首清单 + 编码检测报告
- append-only，逐字不可重排
- 化石层三行：只追加 / Git 全留痕 / 逐字不可重排

## v1.2 · 2026-10-05

### 修复
- **P0 性能**：`_blocks` 后的行号回填用 `txt.count('\n',0,...)` + `txt.index(blk,pos)`，
  对每块从头数换行并全文查找 ⇒ O(n²)。
  实测 365,000 条：修前 > 180 秒未跑完，修后 **2.84 秒**。
  修法：行号并入 `_blocks` 的单遍扫描，返回 `(起行号, 块文本)`。

### 新增
- README 加"性能实证（可复现）"一节：Python 2.84 秒 / sh+awk 5.19 秒，365,000 条。
- `load_conf` 先从 cwd 找 `daybook.conf`，再从脚本目录找。

### 记录
- 本次一跑同时订正一个归因错误：先前记"awk 赢了 Python"，
  实为"我的 O(n²) 输给单遍扫描"。修后 Python 反超 awk（2.84 vs 5.19）。
