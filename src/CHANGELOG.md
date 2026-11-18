# CHANGELOG

## v4.0.6 · 2026-11-14

> ### ⚠ 升级前必读：三处行为变更 / Read before upgrading: three behaviour changes
>
> 1. **非空卷首次索引退 5，需显式认基线**。首次索引会建立封存证据，但按新裁定**不再自动写回**：
>    先返回 5，执行一次 `python3 daybook.py baseline`（别名 `认基线`）后才写回游标与封存，
>    之后再跑 `index` 为 0。证据缺失（索引/游标/封存丢失、游标不可解析）同样停在 5，直到认基线。
>    **MCP 不认基线**：签名只证明调用者是谁，不证明有人看过这卷。MCP 的 `daybook_index`
>    遇证据缺失原样返回 rc=5 错误、不写不重建，须由人在服务端执行 `baseline`。
>    **MCP never accepts a baseline**: a signature proves who called, not that a human reviewed
>    the volume. `daybook_index` returns rc=5 and writes nothing; a human runs `baseline`.
>    升级路径：4.0.5 → 4.0.6 首次 `index` 为 5（4.0.5 无封存指纹），`baseline` 后为 0；
>    实测记录见 `证据/升级演练_4.0.6_20261114.md`。
>    **The first index of a non-empty volume exits 5 and writes nothing back.** Run
>    `daybook.py baseline` once to accept the baseline; then `index` is 0. Missing evidence
>    likewise stays at 5 until a baseline is accepted.
> 2. **作者必填，占位拒写**。`daybook_append.py` 从此只接受
>    `卷 类 标题 作者 "正文"`；3/4 参旧形态（作者默认「未标」）、显式 `未标`/空值、
>    `--name=` 覆盖入口全部删除，一律 rc=2 且不落条；**独立模式（无注册表）也拒机器 id**。
>    MCP 工具层不受影响（仍以 agent_id 验签后写显示名 + `[id=ag-…]` 附注）。
>    **The author is mandatory.** Legacy 3/4-arg forms, `未标`/empty placeholders and `--name=`
>    are removed and refused with rc=2; standalone mode also refuses machine ids.
>    The MCP tool path is unaffected.
> 3. **MCP 空卷不再「带病常驻」**。`daybook.conf` 的 `[volumes]` 为空、卷配成目录 ⇒ 启动即退
>    **2**；登记卷缺失、卷存在但不可读（`chmod 000` 等）⇒ 启动即退 **5**。修前是「服务起来了，
>    首个 `tools/call` 才报错」；把启动成功当健康检查的外部脚本需要改。
>    **MCP no longer starts sick**: an empty `[volumes]`, a volume pointing at a directory ⇒ exit 2
>    at startup; a missing or unreadable volume ⇒ exit 5. Before, the server started and the first
>    `tools/call` failed.
> 4. **未识别节名现在报 2（相对旧解析器收紧）**。`[other]` 这类既不是认得的节、也不是注释的内容，
>    旧解析器静默忽略，现在 `ConfigError`（2）并点名行号与节名。改法：改成 `volumes` / `entries` /
>    `rules` / `index` / `trigger` / `multilevel` / `hooks`（或其中文别名），或直接删掉该节。
>    **Unknown sections are now a config error (2)**: rename to a known section/alias or delete it.
> 5. **不支持行内注释**。`root=sub  # 说明` 的整段 `sub  # 说明` 都是值，根不存在 ⇒ 2。
>    注释必须整行以 `#` 开头。**Inline comments are not supported**: put `#` comments on their own
>    line.
> 6. **非 UTF-8 conf 两包同文案**：`daybook.conf 不是 UTF-8：…（路径）`，码 2。修前完整包带
>    「配置错」前缀、orch 包直接抛 codec 错误。**A non-UTF-8 conf** now yields the same message and
>    code in both packages instead of a codec error in one of them.
>
> ### ⚠ 退出码变更（对外契约，单列）· Exit-code changes (external contract)
>
> **按旧码判断的外部脚本需要改 / external scripts keyed on the old codes must change.** 逐条旧码 → 新码：
>
> | 命令 | 场景 | 旧码 → 新码 | 说明 |
> |---|---|---|---|
> | `orchestrator.py alarm` | 有硬警 | **1 → 3** | 硬警即违例，与 `daybook` 的 3 同义 |
> | `orchestrator.py alarm` | 执行异常 | **3 → 6** | 运行失败单独成码，不再与违例混 |
> | `daybook.py checkauthors` | 作者口径红 | **1 → 4** | 作者口径红全系统统一为 4 |
> | `orchestrator.py selftest` | 自检有红 | **1 → 6** | 自检失败＝运行失败 |
>
> 其余数值不变：`index`/`baseline` 的 0/2/3/4/5/6 一个都没动，只是来源收成一张表
> （`errors.py`；入口只 `raise`，唯一出口 `run_entry` 给码）。凡是把旧码写死的外部脚本
> （`if rc == 1`、`case $? in 1)`、按「1=硬警/3=异常」分派）**必须改成按上表新码判断**，
> 否则会把「硬警」判成成功、把「执行异常」判成「违例」。
> **Other numbers are unchanged**; only the source is unified into one table. Any wrapper that
> hard-codes the old 1/3 meanings must be updated as above.

### 复签不签（六续）：单点中文名基线可计数、超基线即红（2026-11-18）

- **裁决**：判据不扩到任意中文名——成对映射才是「第二张表」，单点用名不是；把 28 处都判红
  就得改默认列名、CLI 标签、帮助文案，那是改用户可见行为，判据不该逼人改产品。但单点必须
  可计数，否则没人知道 28 处会不会长成 80 处。
- **基线**：新增 `alias_name_baseline.txt`，28 条，每行 `file:line<TAB>中文名<TAB>一句用途`；
  按 `(文件, 中文名)` 计数，行号只作定位。该文件进三包 `doc` 清单，随 `plan_for()` 逐件比对，
  盒里与源不许各一份。
- **判据**：guard 输出一行 `单点中文名 N 处（基线 N0）｜新增 X｜消失 Y`；超出基线即红并打印
  `file:line`；基线内条目消失不红，但报「消失 Y」（可能是重构，也可能是判据瞎了）。
- **反向自证**：往产品件塞一个新别名 `"行号"` ⇒ 新增 1、红；拿掉一处基线条目 ⇒ 无新增、
  消失 +1、绿。盒内基线本就有一批「消失」（盒只装产品件，28→9），故断言取相对增量而非绝对 1。
- **读数**：源树 680 PASS／0 红；`daybook` 盒 496 PASS／0 红，单点中文名 9 处（基线 28）｜
  新增 0｜消失 19；mcp 23/23、13/13；orch 全绿；两套 verify EXIT=0、逐件全同。

### 复签不签（五续）：打包产物追平、归一表改字面量位置判据（2026-11-18）

- **打包产物追平**：上一提交在改动 `src/CHANGELOG.md` 读数后未重打包，三盒仍是旧读数
  （673/932/316），`pack.py --verify` 与 `packaging/pack_pypi.py --pkg all --verify` 双双击
  `产物≠源`、EXIT=3。按源重打三包后两套 verify 均 EXIT=0、逐件全同。
- **归一表判据重写**：`_case_conf_alias_single` 不再按变量名计数（`^(SEC|KEY|FIELD)_ALIAS =`），
  改为「中文别名 → 英文正名」的**映射字面量位置**：AST 扫全部 `.py`（含子目录、缩进、类体、
  `dict()`、元组对），凡出现即红，`conf_norm.py` 除外。按名字计数仍靠声明，改个变量名就穿；
  按字面量位置才是结构。反向自证：顶层/类体/`dict()`/元组对四种写法各 1 处必红，
  只有 `conf_norm.py` 时必绿。
- **顺带并表**：`mcp_tools` 的旧层级名表把 `类→category` 改为 `canon_field('类')`，
  不再自持该项；`部→volume`、`属→entry` 为层级专名，保留。`volume_paths._volume_table`
  删掉对旧段名 `'卷'` 的二次合并（归一后已不可能出现）。
- 读数：源树 677 PASS／0 FAIL；反向自证 4 处红／0 处绿；两套 verify EXIT=0；
  闭包 936/2160=43%（可能写缺口 318）。

### 复签不签（四续）：conf 归一单源、alarm 只读开卷、自检补可读性（2026-11-18）

- **P0 conf 解析只留一套**：新增零依赖 `conf_norm.py`（别名表 + `strip/lower` 归一 + 行解析），
  完整包、`daybook-mcp`、`daybook-orch` 带同一份。`daybook.parse_conf`、
  `daybook_multidx.load_conf`、`volume_paths.read_conf_sections_from` 全部调用它，
  `ledger_root.read_conf_value` 的 fallback 不再自带归一/空判据。分叉（`[索引] 根=sub` 下
  完整包 `root=sub`、orch 包 `root=''`；`[Index]`/`[ index ]` 只有一包认）在结构上去掉。
  三包 `pack.py --verify` 全同。
- **P0 认不出就说真话**：归一后仍不在 `KNOWN_SECTIONS` 的节名、空节名、
  「有非注释内容却零可识别节/键」一律 `ConfigError`（2），不再静默忽略（`[INDEX]` 归一到
  `index` 照常认；`[other]` 报 2 并点名）。
- **P0/P0-4 判据**：新增 20 条边界样本差分（纯注释、空行、BOM、CRLF、`;` 注释、重复节、
  空节名、键无 `=`、行内注释、未知节、缩进键、键前无节、`[索引]+根`、`[index]+根`、
  `[Index]`、`[ index ]`、`[INDEX]`、中英混用、`#` 注释），完整包与 orch 包各跑一次，
  比 `sections/content/parsed` 与最终 root。另加三类 conf（`[索引]/根=sub`、`[Index]`、
  `[ index ]`）端到端：两包各自落到 `<conf>/sub`、同码 0。
- **P1 alarm 不建卷**：`Hub(create=False)` 下 `TaskVolume`/`Heartbeat` 只读开卷；`alarm` 缺
  编排卷时报 `ledger_unchecked`「账本未检查」（软警，rc 0），不把缺卷读成空名册去判幽灵。
  P7 改为从「任务卷/心跳卷不存在」起跑，仍以等长改写取 3，并断言零落盘（含不建卷）。
- **P1 空卷测试改期望**：`mcp_p0_regression.test_empty_volumes_warns` 改按新语义断言
  （rc=2、stdout 空、stderr 点名 `volumes 为空`），不再 `json.loads('')` 崩。
- **P2 自检补可读性**：`mcp_resources.self_check` 在 exists 之后加 `os.access(R_OK)` + 试开
  一次；存在但不可读 ⇒ 证据缺失 5。半吊子自检（只看 exists）与「绝不带病常驻」不能并存。
- **P2 session `--initialize` 游标**：显式从零建游标时**落盘**（即使本轮无可消费事件），
  文案如实写「从零开始，既有事件不跳过」；修前只有「已建立」字样、无状态文件。
- **P2 措辞**：`read_conf_value` 注释改为发行边界的实话（fallback 在，但归一逻辑一行都没有）。
- **P1-3 P6 mcp 格分机制**：`root=sub` 的 mcp 格改用带 `[volumes]` 的 conf、卷不在 `sub/`
  ⇒ 5（证明根跟随 conf），空卷单列一格 ⇒ 2，两种机制不再读成同一种。
- **P0 并表**：`orchestrator.py` 自持的 `FIELD_ALIAS` 删除，`canon_field` 改为
  `from conf_norm import`；`'二级': 'level2'` 并入 `conf_norm.FIELD_ALIAS`（一处生效，
  完整包 / mcp / orch 对同一列只有一种解读）。
- **P1 判据**：guard 新增「归一表定义计数」——`SEC_ALIAS`/`KEY_ALIAS`/`FIELD_ALIAS` 在产物
  目录各只许 1 处定义且必须在 `conf_norm.py`，消费者必须 `from conf_norm import`。
- **P1 append 文案**：根解析（conf）提前到作者预检之前；坏 conf 下不再先预告「仍写入」再 rc=2。
- **P2**：非 UTF-8 conf 两包统一走 `conf_norm.read_text`，同一文案、码 2；未识别节收紧与
  「不支持行内注释」写进 ⚠ 升级前必读与 README。
- **读数**：差分 20/20 两包同值；三类 conf 双包同根（`<conf>/sub`）同码 0；干净根
  `alarm` rc=0 且新增文件 `[]`；坏 conf `alarm` rc=2 零落盘；mcp 空卷 2 / 根跟随缺卷 5 /
  `chmod 000` 5。源树 0 红 / 675 项；`daybook/` 盒 0 红 / 489 项；属性层全绿；变异 15/15；
  闭包覆盖 935/2159 = 43%（可能写缺口 318）；三包 `--verify` 全同。

### 复签不签（三续）：conf 语义唯一、三形态矩阵、session 拆格（2026-11-18）

- **P0 单一 conf 语义**：`ledger_root.read_conf_value` 不再自带轻量解析，直接复用
  `daybook.load_conf`（严格解析）；orchestrator 独立包不带 `daybook.py`，退回同包 section
  读取器，严格性判据与 `parse_conf` 逐字对齐（发行边界，不是第二套语义）。同一份文件只许
  一个结论：有非注释内容却零可识别节/键 ⇒ `ConfigError`（2），不再 fail-open 成空值再回落
  conf 目录写。实测坏 conf 下 append/hook 均 rc=2、新增文件为空；探针确认 append/hook 各有
  `read_conf_value` 调用点，session_hook 无。
- **P0 非零退出零落盘**：`orchestrator.Hub.__init__` 在 `locate` 之后、建根/卷/状态之前严格
  `load_conf`；`Hub` 创建处的 `except` 放行 `ConfigError`。坏 conf 下 `alarm` rc=2 且
  任务卷/心跳卷零新增。
- **P0 服务不带病常驻**：`mcp_resources.self_check` 由「只告警」改为启动失败：volumes 为空 /
  卷指向目录 ⇒ 2；登记卷文件缺失 ⇒ 5。实测坏 conf 2、缺卷 5、卷配成目录 2。
- **P1 别名看接收者**：`Thread(target=os.path.join)` 不再被 orchestrator 的 `join` 误伤
  （接收者 `os`/`sys`/内建类型/纯函数模块 ⇒ 绿）；`Thread(target=lr.write)` 仍红。
  两条自证入 AH。
- **P1 P6 固定三形态**：CONFIG 固定「缺失 / 整份不可解析 / `[index] root=sub`」× 8 入口，
  session 拆无事件/有事件两格（27 格实跑）。读数：
  缺失 2/2/2/0/2/2/2/2/0；不可解析 同；root=sub 0/6/5/0/0/0/0/2/0
  （顺序：daybook / append / hook / session 无事件 / session 有事件 / record / orchestrator /
  mcp_server / cross_ref）。矩阵对账 25 动态 + 17 派生不适用 + 14 表级 = 56。
- **P2 措辞与裁决表**：P6 理由「不读 conf」→「conf 不参与根解析」；session_hook/cross_ref 的 0
  与 multidx 派生视图豁免写进 `errors.py` 同一张裁决表；`src/README.md` 第 79 行「8 入口同码」
  与根 `README.md` 第 297 行「不解析 conf」按实测改写。
- **工作规矩**：凡涉及「读不读 / 写没写」的判断，先给读数（实跑前后快照或进程内探针）再给判断。
- **读数**：闭包覆盖 929/2167 = 42%（可能写缺口 311）；源树 0 红 / 620 项；`daybook/` 盒
  0 红 / 489 项；P1–P10 全绿；变异 15/15；三包 `--verify` 全同。

### 复签不签（终）：坏 conf 同码 2、P6 坏 conf 八格、裁决表落字（2026-11-18）

- **P0（本轮唯一产品改动）`orchestrator.py` 体检吞 `ConfigError`**：`_ledger_alarms` 的
  `except (OSError, ValueError, RuntimeError)` 不含 `ConfigError`（它继承 `DaybookError`，
  不是 `ValueError`），坏 conf 穿出后被 `alarm` 命令的 `except Exception` 包成
  `RuntimeFailure` → 6。现在两处都让 `errors.ConfigError` 原样穿透，顶层按 kind 归 2。
  实测坏 conf 下 `daybook.py index` / `mcp_server.py` / `orchestrator.py alarm` 三入口
  rc 同为 2、文案同句（「整份无法解析…坏 conf 不等于空账本」）。
- **P1 P6 补「conf 存在但整份不可解析」八格实跑**：conf 绑定入口（daybook / record /
  orchestrator / mcp_server）断言 2；不绑定入口按各自码轴断言并写明理由（append 0：
  不与 conf 绑定；hook 0：卷由 `--home` 显式定位；session 0：根固定为脚本目录；
  cross_ref 0：按卷名解析）。原有「无 conf/无根」格保留。
- **P2 裁决表**（`errors.py` 文档）：alarm 的码轴是**体检结论**（0 干净 / 3 有硬警；只有
  体检无法执行才退 2/6）；「卷配成目录」index/append 2 与 alarm 3 是两种码轴，不是同故障
  异码；`daybook_append` 不读 conf（坏 conf 下 0 是设计）；`daybook_multidx` 对已改写卷
  rc=0 重建派生视图是**明示豁免**（append-only 是账本卷级不变量，不覆盖派生视图）。
- **P2 闭包为参考项**：闭包 PASS 行与 `tools/score.py` 汇总行都明写「闭包面为参考项，
  不参与收口」；43% 不设阈值——没有正确阈值，硬编一个就是假精确。
- **读数**：源树 0 红 / 571 项；`daybook/` 盒 0 红 / 447 项；P1–P10 全绿；变异 15/15；
  三包 `--verify` 全同；mcp 23/23；orch 全绿。

### 复签不签（续）：能力当值传一律红、记分板印覆盖率（2026-11-18）

- **P0 别名派发**：写能力函数（登记 `ledger`/`impl` 或原语类别命中）与写原语的引用只允许
  两个位置——**直接调用**、**登记表本身**。赋值（`f = X`、`self.f = X`）、作实参
  （`Thread(target=lr.write)`、`map(_write_cursor, xs)`、回调注册）、作返回值、进容器
  （列表/字典/元组）、当装饰器、`getattr(obj,'write')` 全部判红。反向自证三条
  （别名赋值 / 当实参 / 进容器）必须红，直接调用必须不红。`errors.run_entry(fn)` 按规则
  处理（内部立即 `fn()`，等价直接调用），不是白名单。
- **P1 记分板**：`tools/score.py` 汇总行紧跟 `闭包覆盖 927/2154=43%｜可能写缺口 305｜
  未登记 0｜同名红 0`，与 guard 共用 `_closure_parts`，不写第二套口径。
- **P2 README**：点名 43% 残余三类（属性/实例方法派发、第一方函数别名、新方法名不在写能力
  名集合）；写明新入口必须同时进 `_ENTRY_FILES`；豁免键含行号、重构即红是刻意设计。
- **读数**：源树 0 红 / 571 项；`daybook/` 盒 0 红 / 447 项；P1–P10 全绿；变异 15/15。

### 复签不签：闭包种子＝登记本身、差额报集合差、免签双限定（2026-11-18）

- **P0 闭包种子口径**：源头改为「所有签为 `ledger`/`impl` 的函数」＋原语类别命中，不再按 kind
  分层判断。`safe` 是写的结果属性，不是写能力的门槛：包装一个「已登记但 kind 仅 `safe`」的
  helper，wrapper 自身也必须进写能力面。反向自证（内存树 `a.py`）：
  `_evil_wrap_cursor → _write_cursor`（`_write_cursor` 登记 `ledger`、kind 仅 `{'safe'}`）⇒
  cap=`[_write_cursor, _evil_wrap_cursor]`、未登记=`[_evil_wrap_cursor]`，判据必须红（现为 PASS）。
- **只读路径不签**：`os.open` flags 常量折叠后，safeio 的 9 条只读/句柄实现
  （`_from_dir_path`/`_walk_parent`/`read`/`as_root`/`held`/`locked`/`root_scope`/`open`/
  `read_vol`）不再有任何写类别，登记表里的对应条目整条删除（不签、也不新设「只读实现」桶）。
  另登记 7 条运维/调试 CLI 主函数（`agent_*`、`daybook_multidx`、`task_volume`，均不在 8 入口
  清单内，按产品内部件登记）与 `path_leak_check.main`（盒内无 pack.py 时它按产品件计）。
  WRITE_PATHS：117 → 116（ledger 64 / other 37 / impl 14 / dispatch 1）。
- **P1 差额口径**：`--audit-closure` 与记分板同时输出 `cap−reg`、`reg−cap` 两组集合差及构成
  （入口／随包测试辅助／产品内部件；reg 侧按桶分组），不再用 `|cap|−|reg|` 的算术差冒充。
  源树本轮：`cap−reg = 25（入口 10｜测试/辅助 15｜产品内部件 0）`；`reg−cap = 1（dispatch 1）`。
  盒内：`cap−reg = 5（入口 5）`；`reg−cap = 36（dispatch 1｜other 35）`。
- **P1 字段改名**：`--audit-calls` 的「判为纯计算调用点／纯计算 callee」改为「非原语调用点／
  非原语 callee」，并注明含只读/纯计算/外部，**不代表不写**（`uninstall` 经 `atomic_json`
  写 `.vscode/tasks.json`、`write_message` 写协议流仍在这一侧）；`--audit-closure` 的
  「纯计算面」改为「内建/容器方法面」。本轮读数：写面调用点 91 / 非原语调用点 3806 /
  非原语 callee 去重 533。
- **P2 免签与豁免键**：入口改为「入口名 ∩ 8 入口文件」双重限定（`_is_entry`）；未解析同名红判
  的写能力名集也按「非入口」逐函数过滤，同名内部函数不再免签。`_CLOSURE_EXEMPT` 键加入行号
  `(文件, 函数, callee, 行号)`，同函数第二处同名调用不会被前一行顺带放行；删除 3 条已无对应
  边的死豁免，现 10 条（命中 0）。
- **读数**：闭包覆盖 927/2154 = 43%（未解析 1227：内建/容器方法面 922、可能写缺口 305）；
  写能力函数 140 / 未登记 0 / 同名红 0（豁免 10）。源树 0 红 / 558 项；`daybook/` 盒
  0 红 / 437 项；P1–P10 全绿；变异 15/15；三包 `--verify` 全同；mcp 23/23；orch 全绿。

### 复签补轮：record 同码、Registry dir_fd、边界与句柄证据（2026-11-18）

- `daybook_record` 的 append 子进程补 `cwd=HERE`；append/index 非零按 2/3/4/5/6 还原成
  对应错误类，不再一律压成 6。P6 的 record × EVIDENCE / RUNTIME 改为动态注入（5/6）。
- `LockedRoot` 新增 `mkdir/mkdirs`（dir_fd 走查）；Registry 密钥目录、Hub 自定义父目录、
  AgentMessage 父目录全部改走它。新增 M12（退回 os.makedirs 路径）⇒ P9 红；P3 审计钩子
  识别 mkdir 并验证栈经过 safeio。
- 边界：8 个统一入口不变；`task_volume.py` 列入非统一工具清单（走 run_entry，不再裸栈）；
  `src/README.md` 与仓根 README 统一写「8 个统一入口」。
- P9 增加同一句柄断言（tv/hb/lock/reg is hub.root_handle）与 Registry 换根用例；
  新增 M11（Hub 传路径）⇒ P9 红。
- P6 格数拆开报告：源树动态 19 / 不适用 21 / 表级 16；盒内动态 14 / 不适用 29 / 表级 13。
- orchestrator.py 英文退出码 3/6；从路径构造的 Root 用 weakref.finalize 关闭，_append_inbox
  自开 Root 用 finally 关闭。
- 读数：源树 `0 红 / 506 项（跳过 22）`；`daybook/` 盒 `0 红 / 386 项（跳过 45）`；
  属性 P1–P9 全绿；`变异 12 / 杀死 12 / 存活 0 / 死变异 0`；两套 verify rc=0。

### 闭包面裁决：按账本写类别传播，未解析边同名即红（2026-11-18）

- **闸只落一处**：第一方函数若传递地调用到账本写类别（`_LEDGER_KINDS`），自身即「写能力函数」，
  产品内部件必须登记。temp 与派发不进闭包（不改根内状态，各有各的闸）。
  入口（`main`/`_main`/`__init__`/`dispatch`/`serve`）不签，归 8 入口清单；随包测试只报告不签。
- **闭包补签 96 条**（产品内部件，逐条写理由）；其中 29 条是属性类型/局部类型解析后新增的
  只读路径（`other` 桶、自身无直接写类别），已在注释与报告里单列，供复核改判。
  WRITE_PATHS：78 → 174 条。
- **`--audit-closure`**：已解析边数 / 未解析边数；未解析按 `from-import`/`instance-method`/
  `getattr`/`dispatch`/`other` 分类，逐条列 `file:line`；另列未登记写能力函数、同名红点、已签豁免。
- **未解析边的 callee 与本仓写能力函数同名 ⇒ 红**（宁红勿漏）。写能力名集按桶判：
  `ledger`/`impl` 才算，闭包补签的只读路径（`other`）不算，避免 `read/get/list` 同名淹没信号。
  11 条逐点豁免（LockedRoot 凭证释放、Root 根内读取、线程互斥量、协议输出流），逐条带理由。
- 下界声明：实例方法按局部/属性类型解析到首方类；`from x import f` 裸名、`getattr`、字典派发
  仍然计为未解析并在读数里逐条出现，不静默丢弃。
- **读数**：写能力函数 204 / 已登记 174 / 未登记 0；已解析边 929，未解析边 1227
  （实例方法 1107、字典派发 1、裸名 119）；同名红点 0（豁免 11）。
  源树 0 红 / 557（跳过 16）；盒 0 红 / 436（跳过 39）；P1–P10 全绿；三包 verify 全同。

### 复签补轮五：写面默认值反转（2026-11-18）

- **判据反转**：写面按「能力」定义，不按 callee 名字清单。模块面（os/shutil/subprocess/
  ctypes/io/pathlib/tempfile/mmap/sqlite3/socket/zipfile/tarfile/logging）上的调用默认写、
  未知名字也写；任意接收者的写动词（write/mkdir/unlink/rename/replace/chmod/chown/utime/
  truncate/symlink/link/touch/write_text/write_bytes）一律写；`open` 与 `os.open` 的模式
  判不出即写（`os.open` 只有 flags 字面量 0 才只读）。纯计算按模块类别给；只读只签 site
  （文件/函数/callee 三元组），不逐 callee 签。
- **发现面**：扩到模块体/类体/lambda/推导式/装饰器；`Path` 接收者不再要求字面量
  （形参注解、`Path(p)/'x'`、变量都算）；新增 `unclassified` 默认写红池。
- **桶名只作预期**：产品件写类别必须是 ledger（safeio 自身 impl），`dispatch` 桶只能带
  subproc/temp，夹带其它写 ⇒ 红。新增自证：dispatch 桶夹带 chmod 必须红。
- **非账本根写逐点人签**：`_OFFROOT_WRITE_SITES` 只覆盖列出的 (文件, 函数, 类别)，签名目标
  由 tempfile 生成；同函数新增写类别仍红。
- **兜底读数**：`guard.py --audit-calls` 打印写面调用点 / 判为纯计算调用点 / 纯计算 callee
  去重列表（只报告，不当绿证）。
- **卷配置指向不存在的文件 = 配置错 2**：`index` 与 `record` 同码且零落盘；作者口径检查
  跳过该卷，避免 4 盖掉 2。`daybook_append.py` 不解析 conf 的边界写进 README 与模块 docstring。
- **record 索引腿声明收窄**：换根后 `update_index=True` 失败关闭（2/5，零落盘），换根保证
  只覆盖归档与登记；P10 docstring 写明覆盖面。
- **P7 口径改为采样**：列出已采样/未采样入口（orchestrator join/open/log、daybook_multidx、
  mcp_server 未采样及理由）；新增 M15（record 锁退回 `str(rt)` 路径重开）⇒ 死在 P10 dev_ino。
- 删除盒内 `tools/score.py` 悬空自指与 `_unclassified_os` 死代码。
- **读数**：源树 0 红 / 555（跳过 16）；盒 0 红 / 434（跳过 39）；P1–P10 全绿；
  变异 15/15；三包 verify rc=0；mcp 23/23 + 13/13；orch 自检与 fixes 全绿。

### 终裁轮：写路径禁派发、record 单根单凭证、P6 适用性派生（2026-11-18）

1. **写路径禁止 subprocess**：AH 把每个 `subprocess.*`（含 `stdout=PIPE`）都当派发点，产品件
   必须在 `_SUBPROC_SITES` 逐个登记，账本桶一律红；全仓只剩 `_run_hook` 一个登记点。
2. **record 单根单凭证 + 先判后写**：归档/登记/索引同一 `locked(rt)`；写前
   `build(dry=True, authors=True)` 判 2/3/4/5，非零退出零落盘（登记失败撤回原件）。
3. **同码与可区分**：卷配成目录统一 2（`errors.py` 裁决）；坏 conf（有内容却无可识别节/键）
   rc=2，不再打印「合计 0 条」写空索引；空账本仍为 0。
4. **独立根明写**：`daybook_session_hook.py` 固定取脚本目录，不读 conf `[index] root`、无
   `--home`（模块 docstring 与 `ledger_root.py` 均已写明）。
5. **alarm 纳入账本体检**：append-only 违例/卷配置错为硬警，未认基线为软警；独立安装无
   daybook 时报「未检查」，不再印成「干净」。
6. **判据**：P10 record 改真实子进程 + 换根 + 同一 `dev_ino`；P7 扩到每个可写入口
   （含 daybook_hook，8 项）；P6「不适用」改由代码路径推导（record × VIOLATION 已实跑）；
   记分板输出变异集覆盖声明；删除盒内「健康度以属性层/score 为准」的悬空自指。
7. **读数**：源树 0 红 / 546（跳过 16）；盒 0 红 / 425（跳过 39）；P1–P10 全绿；变异 14/14。

### 复签补轮四：发现先于归类（2026-11-18）

- AH 扫描返回全部函数树；`os.*` 全集与非 os 写 API 逐函数检查，不再依赖 `sites`。
- 补 `shutil.move/rmtree/chown`、Path 八个写方法、ctypes、无重定向 subprocess、
  `open` 模式变量、第三方库；产品件禁模块别名/被调 getattr/`__import__`/字典派发。
- 自证改走真实 `_scan_write_sites` 入口，逐条打印；`os.mknod` 无类别仍在 `sites` 外判红。
- score 精确匹配断言名；`--audit-names` 校验唯一；P1 失败分支改名。
- 三处 best-effort 失败改 `errors.warn`；W1 六原语 Windows 拒绝；文档写明 Windows 上
  build/backup/record/register 不可用。
- 只有 daybook 盒自带判据，mcp/orch 盒仅由 pack --verify 保证同源。
- 读数：源树 536/22、盒 416/45、P1–P10 全绿、14/14、verify 0、mcp 23/23、orch 全绿。

### 复签补轮三：权限/删除/时间戳同属一个写能力（2026-11-18）

- `Registry.register` 的 `os.chmod(self.path, 0o600)` 移进 `with locked(self.root)`，
  改 `lr.chmod(lr.root.rel_of(...))`：换根后不会再改新根同名 `注册卷.txt`（实测新根
  哨兵仍 0644、旧根 0600）。
- `_run_ops` 的 `os.remove` → `lr.unlink`；`_backup_copy` 的 `os.utime` → `lr.utime`；
  safeio 新增 `unlink`/`utime`（dir_fd）。socket 清理收进无路径参数的 `_drop_socket`。
- AH 增加系统调用类别声明表：mkdir/chmod/utime/unlink/chown/link/truncate/xattr 等
  必须有唯一归属；未登记类别、账本桶裸调、产品件 impossible 类别、未归类 `os.*` 均红。
- 记分板校验预期断言名，死于别的断言/崩溃不算 killed；P9 独立断言、P5 释放链前置；
  P10 扩到 build/backup/record；新增 M14。`--self-check` 同时验属性错与断言错。
- Windows：目录/权限/删除/时间戳原语仅 POSIX dir_fd，调用显式 RuntimeError，不回退。
- 读数：源树 511/22、盒 391/45、P1–P10 全绿、14/14、verify 0、mcp 23/23、orch 全绿。

### 复签补轮二：目录创建收进唯一写能力（2026-11-18）

- 产品件里剩余 9 处 `os.makedirs/os.mkdir` 全部改走 `LockedRoot.mkdirs_path`：
  `daybook.build` 的 outdir、`_backup_locked` 的 `backup/`/索引备份、`daybook_record.record`
  的「对话原件」（移进取锁区）、`daybook_session_hook` 三处、`orchestrator.Hub.__init__`
  与 `_selftest`、`daybook_multidx._build_locked`。账本根内建目录与写文件同属一个写能力。
- 新增 P10（build 换根：追加条目写回旧 inode、新根零目录）与 M13（outdir 退回
  `os.makedirs`）⇒ M13 死在 `[FAIL] P10 换根后 build 不往新根建「索引」`。
- M12 改死断言：P9 捕获 `RuntimeError` 后仍断言旧根有密钥目录/注册卷、新根没有；
  `score.py` 只有普通断言红才算 killed，纯崩溃记 dead。M5 同口径，死在
  `[FAIL] P5 REPLACE 后目录 fsync ≥ 1 · err=release unlocked lock`。
- Registry 补 `LockedRoot.chmod(0o700)`，已存在的 0755 旧目录也收紧。
- AH 识别 `os.mkdir/os.makedirs` 与 `lr.mkdir*`，登记 `_backup_locked`、session hook 三处、
  `Hub.__init__`、`safeio.mkdir`；P6 session × EVIDENCE 改在盒内 ROOT 内放 state。
- `verify_plain.py` 明确为判据工具，不在 8 统一入口表内。
- 读数：源树 `0 红 / 506 项（跳过 22）`；盒 `0 红 / 386 项（跳过 45）`；P1–P10 全绿；
  `变异 13 / 杀死 13 / 存活 0 / 死变异 0`；两套 verify rc=0；mcp 23/23、orch 全绿。

### 复签收口：三条所有权补立（P1/P2 · 2026-11-18）

- **写凭证生命周期**：`LockedRoot.write/update` 写前过 `_ensure_live()`（未释放且仍在本线程
  持有表）。红证：释放后旧凭证 / 跨线程 / 子进程持锁窗口均 RuntimeError 且零写（P8）；
  变异 M9（删校验）⇒ P8 红。
- **入口参数收口**：`daybook.py watch` 的 `int()` 改抛 `ConfigError`；`errors.run_entry`
  统收 `ValueError`/`TypeError` 为 6。旧码 `watch abc` ⇒ rc=1 + traceback；现 rc=2 + 单行文案。
- **入口级换根**：`orchestrator.Hub` 启动只开一次 `Root`，交给 TaskVolume / Heartbeat /
  AgentLock / Registry；`agent_message.AgentServer` 固定 inbox 与 Root；`_ROOT_CACHE`
  按路径缓存 Root（换根写旧 inode，已核）。M10（写时按路径重开）⇒ P9 红。
- **8 个统一退出码入口**：daybook / append / hook / session_hook / record / orchestrator /
  mcp_server / cross_ref；P6 改为 8×7=56 格。`agent_*`、`daybook_multidx`、`mcp_subscribe`、
  `chatroom_server` 明确为运维/调试工具，不承诺统一码。
- `daybook_record.py` 调 append 补作者位（`记录器`），并在对话卷可查；orch 三份文档退出码
  统一为 3/6；删除 `tools/write_audit.py`、`audit_fixture.py`，步骤 0 读数改由 P3 + M4 复现。
- 读数：源树 `0 红 / 506 项（跳过 22）`；`daybook/` 盒 `0 红 / 386 项（跳过 45）`；
  属性 P1–P9 全绿；`变异 12 / 杀死 12 / 存活 0 / 死变异 0`；两套 `--verify` rc=0。

### 单一源件与打包校验（步骤 6 · 2026-11-18）

- 不变量「源件唯一，盒内副本逐字节一致」唯一归属 `pack.py` 的 `plan_for()` 清单：
  build 与 verify 都从同一清单派生，不各写一套。
- `--verify` 原先只比对清单内的件；现在把 build 已在用的 `foreign_files()` 接进 verify，
  盒内多出的清单外副本也判红。没有新增第二套机制。
- 新增判据 PK（源树）：刚打包 verify 绿；手改盒内 `safeio.py` 一字节 ⇒ 红；
  删盒内 `daybook.py` ⇒ 红；盒内多一份清单外副本 ⇒ 红；复原后复绿。盒内无 `pack.py` 时
  打印原因跳过。
- 读数：源树 `0 红 / 496 项（PASS 496；跳过 16 项）`；`daybook/` 盒
  `0 红 / 379 项（PASS 379；跳过 36 项）`；仓根与 `_build` 三包 `--verify` 均 rc=0。
  The packaging invariant is owned by one manifest (`plan_for`); verify now also rejects
  unlisted in-box files, so a hand edit, a deletion or a duplicate copy all fail.

### 判据分层与变异记分（步骤 5 · 2026-11-18）

- 场景层 33 组原样迁入 `tests/scenarios/guard.py`；盒内仍由 `pack.py` 复制为
  `ledger_guard_test.py`，盒内命令与读数口径不变。
- 新增属性层 `tests/prop/`（P1–P7）、种子化生成器 `tests/gen.py`（`const` / `random` /
  `shuffle`）、AST 变异器 `tools/mutate.py`（M1–M8）与记分板 `tools/score.py`。
- **健康指标改为「属性全绿 + 存活变异 0 + 死变异 0」**；判据条数只作参考打印。
  场景层原有的字符串锚点变异标注为 legacy，仅保留为回归，不参与健康判定。
- 本轮读数：源树 `0 红 / 490 项（PASS 490；跳过 16 项）`（步骤 6 加入 PK 后为 496 项）；
  `daybook/` 盒 `0 红 / 379 项（PASS 379；跳过 35 项）`；属性层 P1–P7 全绿；
  `python3 tools/score.py` 打印 `变异 8 / 杀死 8 / 存活 0 / 死变异 0`。
- 错映射自检：`python3 tools/score.py --self-check`（M2 故意声明期望 P1）会报
  「未被对应属性杀死」并记死变异，不会静默通过。
  Health is now "properties green + 0 survivors + 0 dead mutations"; the scoreboard,
  not the check count, is the release gate.

### 复核 P0（海东青四项）

- **索引缺失时仍验哈希（范围如实）**：当**只删索引、游标与封存未动**时，同长按全卷哈希、
  变长按旧前缀哈希比对，不符退 3。**不承诺**识别「同时改写两份派生件」或「卷+游标+封存
  三者自洽改写」——本实现没有外部锚（封存仍在账本目录内、无签名），这类改写与真实写入
  不可区分。外部锚（移出目录/加密签名）另开一单，不在 4.0.6。
  **Hashes are still verified when only the index is deleted**; a mismatch exits 3. Rewriting
  two derived artifacts together, or a self-consistent rewrite of volume+cursor+seal, is
  **not** claimed to be detectable without an external anchor.
- **证据缺失不再自动重建**：退 5 后不写回索引/游标/封存，状态保持 5，直到显式
  `baseline`（认基线）。首次建立同样走这条。
- **认基线遇违例一律拒**：`baseline` 先只验不写；有 append-only 违例或配置错即退 3/2，
  不写任何派生件——不把「账本被改过」替人认成新基线。作者口径红只报不拦。
- **判拒只有一个聚合**：CLI 与 MCP 的 `daybook_index` 共用 `errors.worst`（2/3/4/5 全部上报，
  屏幕/审计记违例）；违例卷在落笔前再次收紧，一次调用不能把篡改重建为新基线。
- **证据缺失路径不再崩溃**：正常追加后删索引会走「卷变大」分支数不存在的索引文件
  （`FileNotFoundError` rc=1）；现于分支前判「索引不存在」，直接退 5。
- **版本锚**：`SUITE_VERSION`、三包 `version.txt`、仓根与包内 README、CHANGELOG 统一 4.0.6。

### 复核 P1

- 退出码「不互掩」的口径写进 `--help`：屏幕全打，退出码取语义严重度最高
  （违例 3 > 作者 4 > 运行 6 > 配置错 2 > 证据缺失 5）；3 不被 2 掩盖，也不被 5 洗掉。
- `backup` 在默认 `out_dir` 为空时备份根目录下的已知索引件，不再直接返回。
- CLI 收掉「作者默认未标」的 4/2 参形态与 `--name=` 后门：作者必填，占位值拒写。

> **【口径归一 · 2026-10-14 · 老宋令】** 历史条目中的「承重墙」一词，对外统称改从新版——即「**N 条特点**」（2026-10-14 起产品线统一为「**八目**」八轴）；「5 条工程优势」亦改称「5 条**工程**优势」（不宣称企业级）。**仅改称谓·条目事实未改**（不静默改）。

## v3.2.4 · 2026-10-30

### 商标补记：发行名写进商标申请范围（老宋 2026-10-30 裁「同意」）

- **裁定**：三个 PyPI 发行名 `daybook-suite`／`daybook-mcp`／`daybook-orch`
  **一并写进商标申请范围**（与产品名 `daybook`／起居注／璇玑／司南 同列）。
- **为什么要两条腿**：PyPI 的**包名占位归 PyPI 管**，**商标归商标局管**。
  只有占位，别人仍可在别的渠道、以别的名义用同名做生意；**两条都走，名才站得住**。
- **新增 `TRADEMARK.md`（名之正本·随三包）**：
  - §二 标识清单（四个产品名 ＋ **三个发行名** ＋ 域名服务标识，含首次使用与状态）；
  - §三 **申请范围**：法域（CNIPA 优先／USPTO 拟／EUIPO 视需要）× 类别（**第 9 类·可下载软件**；
    **第 42 类·软件开发与平台服务**）× 覆盖标识成表；
  - §四 使用规则（可／不可各四条，含禁近似注册）、§五 ™／® 标记纪律、§六 与许可之分野。
- **为什么单独立件**：「名」的口径不与「码」的口径混写（**一字段两义必拆字段**）。
  `LICENSING.md` §五 改为指针（不另立一套）、§七 加「两条腿」说明、§九 第 1 条标识清单同步扩列。
- **PyPI 长描述**（`packaging/README_template.md`）新增「商标（名不可乱用）」段 ⇒ pip 页直接可见。
- ⚠️ **状态如实**：当前为**拟申请范围，尚未提交、尚未核准**；保护力自核准之日起算，
  `TRADEMARK.md` 与本文**均不构成核准证明**（**占位不声明＝声明不落字；声明不提交＝声明不生效**）。
  实际提交动作须由掌印人办理。
- **未动**：代码零变更（`daybook.py`／`mcp_tools.py`／`orchestrator.py` 等**逐件 sha 与 v3.2.3 全同**）；
  账形三条、append-only、零依赖、产物==源守卫；v3.2.2 的口径闸与「秒可选」全部照旧。

**版本号**：升 **v3.2.4**（三包同源同发）。

## v3.2.3 · 2026-10-30

### 许可补记：发行名归属写进许可（老宋 2026-10-30 裁「写进许可」）

- **为什么单发一版**：v3.2.2 把 `daybook-mcp`／`daybook-orch` 两个 PyPI 名**首次发布**出去。
  名发出去了，但**许可文本里没写这个名归谁、怎么判官方**——占位不声明＝声明不落字。
  而 **PyPI 同版本号不可重传**，v3.2.2 的 payload 已无法再改 ⇒ 只有新版本号能把许可文本
  真正落到 PyPI 项目页上。**故发 v3.2.3（纯许可文档版，代码零变更）。**
- **新增 `LICENSING.md` §七「发行渠道与发行名归属」**：三渠道（PyPI 三发行名／GitHub 仓／官网）
  的**对应件、许可、首发日与首发版本**成表留痕；并给出「如何判官方」三条
  （Homepage 指 daybooksuite.com ＋ Repository 指本仓 ＋ Release tag 与 CHANGELOG 版本号对得上）。
  原 §七、§八 顺次为 §八、§九；§五（商标）加指针「发行名同属此列，见 §七」。
- **PyPI 长描述同步**：`packaging/README_template.md` 新增「发行名归属（官方渠道声明）」段
  ⇒ `pip` 页面上直接可见，不必解包。
- **未动**：代码零变更（`daybook.py`／`mcp_tools.py` 等**逐件 md5 与 v3.2.2 全同**）；
  账形三条、append-only、零依赖、产物==源守卫；v3.2.2 的口径闸与「秒可选」全部照旧。

**版本号**：升 **v3.2.3**（三包同源同发）。

## v3.2.2 · 2026-10-30

### 条目头秒精度 ⇄ 索引口径（病：写入器写秒，索引器只认到分钟）

**一、默认口径放宽为「秒可选」**
- **病**：`daybook_append.py` 写 `[YYYY-MM-DD HH:MM:SS]`（W-75 修⑥ 为心跳 alive 判定改的秒级），
  而**出厂** `head_regex` 只到分钟 ⇒ 追加条目**一条都进不了索引**；且增量游标已越过该行，
  **改正则也不回补**，必须删 `index/` ＋游标全量重建。
- **独立复现（v3.2.1）**：默认口径下写 3 条 → 索引 **0 条**；把口径改宽、不删档 → 仍 **0 条**；
  删档重建 → **3 条**。⇒ 坑在出厂默认，不在个别 conf。
- **药**：`head_regex` 放宽为 `(?::\d{2})?`（秒可选）。理由不是「更宽松」，而是
  **两种精度在本套件里都是合法写法**——append／心跳／锁／消息／MCP 写秒，`task_volume.py` 写分；
  **任何「只认一种精度」的默认值，必然吞掉另一半条目**。
- **面**：`src/daybook.py` 新增 `DEFAULT_HEAD_REGEX` 作唯一真源（两处内建缺省改为引用它）
  ＋ `daybook.conf`／`daybook.dist.conf`／`daybook.sample.conf` ＋ `volume_format_spec.md` ＋ `README.en.md`。

**二、口径漂移闸（把纪律变成判据）**
- 建索引时把 `head_regex／extra_head_regex／tag_regex／fields` 算 sha256，写 `index/.head_stamp.json`
  （与 TSV／游标同临界区，沿用 W-75 修② 目录锁）。
- 下轮建索引比对：**一致 ⇒ 增量照旧**；**不一致 ⇒ 删该卷 TSV／TXT／游标全量重扫**，
  `volumes.md` 记「★ 口径已改（旧→新）：增量不回补，已清索引与游标·全量重扫」；
  **无戳**（存量索引升级首轮）⇒ 放行并补戳，记「口径未溯源」，不冤枉人。
- 三组自检：阳（漂移被咬住 0→3）／阴（口径不变不误删）／豁（无戳放行补戳）。

**三、缺省口径归一（同一问题不再两个答案）**
- **病**：`mcp_tools.py` 缺省 `^\[`（宽松）、`daybook.py` 缺省分钟级（严格）⇒ 走 MCP 写能进索引、
  走命令行写进不去。
- **药**：`mcp_tools.py` 缺省改用 `daybook.DEFAULT_HEAD_REGEX`（它本就 `import daybook as _db`）。

**四、自测件自己挂住（自检件挂＝没人跑自检）**
- **病**：`src/test/run.sh` 的 Fortran 一步跑 `daybook_f` 时吃 stdin；本机装了 gfortran
  （Homebrew GCC 15.2.0）⇒ **整条自测无限挂住**（2026-10-30 实测卡死 11 分钟，无输出、无超时）。
  v3.2.1 的回归说明里已记「Fortran 编译挂起·非阻塞」，实为**等 stdin**，非编译慢。
- **药**：`"$OUT/daybook_f" < /dev/null`。改后 `bash test/run.sh` 一次跑完 **PASS 4 / FAIL 0**。

**版本号**：升 **v3.2.2**（三包同源同发）。**未动**：账形三条、append-only 纪律、零依赖、
产物==源守卫；索引／查询逻辑零变更（仅缺省值与新增闸）。
**复现**：`python3 src/pack.py --dry`（产物==源）；口径三幕与三组验证见
`DAYBOOK补件/W302_秒头口径闸/`（`W302_口径闸_验证.py`、`W302_闸三组验证.py`）。
**回归**：`bash src/test/run.sh` PASS 4/FAIL 0（py/sh/C 三实现 + 编码检测）；
跨包口径三幕（`daybook`／`daybook-mcp`）与闸三组（阳／阴／豁）全绿；
`python3 packaging/pack_pypi.py --pkg all --version 3.2.2 --build` 六件 twine check 全 PASSED。

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
