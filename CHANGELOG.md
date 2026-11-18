# CHANGELOG

本文件记录**对外可见**的变更。v3.2.4 及以前的逐版记录在各包内 `CHANGELOG.md`（历史卷，随包发行）；
本文件自下一版起接续记录。

> **状态**：本节随 v4.0.0 定稿（2026-11-13）。

---

## v4.0.6 · 2026-11-14

**升级前必读（四处内容变更；退出码变更单列于下）**

1. **非空卷首次索引退 5，需认基线**：首次索引不写回证据，先退 5；执行一次
   `python3 daybook.py baseline` 后才写回游标与封存，之后 `index` 为 0。证据缺失
   （索引/游标/封存丢失或不可解析）同样停在 5，直到认基线。
2. **作者必填，占位拒写**：`daybook_append.py` 只接受 `卷 类 标题 作者 "正文"`；
   3/4 参旧形态、显式 `未标`/空值、`--name=` 一律 rc=2 且不落条；独立模式也拒机器 id。
   MCP 工具层不受影响（仍以 agent_id 验签后写显示名 + `[id=ag-…]` 附注）。
3. **`--root` 语义变更**：所有入口统一用 `--home` 指定 **conf 所在目录**（未指定则看当前
   工作目录）；司南的 `--root` 保留为同义别名，但**旧脚本传账本根的会 rc=2**。账本根仍只由
   conf 的 `[index] root` 决定。
4. **MCP 空卷不再「带病常驻」**：`[volumes]` 为空 / 卷配成目录 ⇒ 启动即退 **2**；登记卷缺失 /
   卷存在但不可读（`chmod 000`）⇒ 启动即退 **5**。修前是「服务起来了，首个 `tools/call`
   才报错」；把「进程起来了」当健康检查的外部脚本需要改。
5. **未识别节名现在报 2**（旧解析器静默忽略）：改成认得的节（`volumes`/`entries`/`rules`/
   `index`/`trigger`/`multilevel`/`hooks` 或中文别名），或删掉该节。
6. **不支持行内注释**：`root=sub # 说明` 的整段都是值 ⇒ 根不存在 ⇒ 2；注释必须整行以 `#` 开头。
7. **非 UTF-8 conf 两包同文案**：`daybook.conf 不是 UTF-8：…（路径）`，码 2。

**⚠ 退出码变更（对外契约，单列一节）——按旧码判断的外部脚本需要改：**

| 命令 | 场景 | 旧码 → 新码 | 说明 |
|---|---|---|---|
| `orchestrator.py alarm` | 有硬警 | **1 → 3** | 硬警即违例，与 `daybook` 的 3 同义 |
| `orchestrator.py alarm` | 执行异常 | **3 → 6** | 运行失败单独成码，不再与违例混 |
| `daybook.py checkauthors` | 作者口径红 | **1 → 4** | 作者口径红全系统统一为 4 |
| `orchestrator.py selftest` | 自检有红 | **1 → 6** | 自检失败＝运行失败 |

其余数值不变：`index`/`baseline` 的 0/2/3/4/5/6 一个都没动，只是来源收成一张表（`errors.py`）。
凡是把旧码写死的外部脚本（尤其 `if rc == 1`、`case $? in 1)`、按「1=硬警/3=异常」分派的调用方）
**必须改为按上表新码判断**，否则会把「硬警」判成成功、把「执行异常」判成「违例」。
全表见 README「退出码（只有一张表）」。

**内容**：派生件三态判据（真未变 0 / 证据缺失 5 / 内容不符 3）、索引缺失时仍验全卷或旧前缀
哈希、退出码按语义严重度取最高（3 违例 > 4 作者 > 6 运行 > 2 配置 > 5 证据）、卷表键值双条件、
作者口径反转为「显示名 + id 附注」、
hook 条头统一解析、pack 排除运行时残留与系统垃圾、`backup` 覆盖内部卷与已知索引件。
**锁改为目录 flock（不落任何文件）**：跨进程锁直接 `flock` 账本根目录本身
（`O_RDONLY|O_DIRECTORY`），跨 TMPDIR／跨用户／跨 cron 都是同一把锁，不需要写权限；
`index`／`baseline` 任何退出码下账本目录（递归、含内容）都不变化，「账本目录零变化」可作判据。

**诚实边界**：仅在「只删索引、游标与封存未动」时能判 3；同时改写两份派生件、或卷+游标+封存
三者自洽改写，本实现不承诺识别（缺外部锚：封存仍在账本目录内、无签名）。外部锚另开一单。

### 复签不签（九续）：来源显式、推断不出按源树（fail-closed）（2026-11-18）

1. **`is_box` 不再由被测件推断**：原先看根目录有没有 `pack.py`，把 `pack.py` 挪进 `packaging/`
   就会让「消失 4」静默转成「盒内豁免」而判绿（fail-open）。现改为**只看 guard 自己的文件名**
   （盒内副本叫 `ledger_guard_test.py`）——这是判据自身，不是被测件；推断不出按源树（fail-closed）。
2. **反向自证**：① 挪走 `pack.py` 到 `packaging/`、再把产品件移出扫描路径 ⇒ 仍按源树判，
   消失 4 判红「疑似漏扫」；② 盒内原样跑 ⇒ 走盒内豁免并打印「盒内豁免，消失 19 属产物边界」。
3. **随包带走两条 P2（记录在案）**：`_ALIAS_EXPECTED_KEYS=26` 是声明常量，新增合法别名必须
   同步改它和基线文件；判据只保证「缩表必须有人看见」，不保证缩减正当。`('标题', 1)` 这类
   「名字, 下标」在配对口径排除，但在单点名口径仍计一次、吃基线额度；不修。
4. **读数**：源树 688 PASS／0 红；`daybook` 盒 503 PASS／0 红（跳过 42）；两套 verify EXIT=0。

### 复签不签（八续）：参照集判完整、字典键不看值、消失可判红（2026-11-18）

1. **参照集判完整**：`_alias_tables` 逐表读，缺哪张点哪张；`_alias_ref_gate` 要求三表齐全、
   中文键恰为 26。只把 `FIELD_ALIAS` 改注解赋值 ⇒ 红：「读不出 FIELD_ALIAS（不在
   `NAME = {...}` 形态）；现有中文键 23 个」。「非空」只是下界，下界不是判据。
2. **字典键位不看值**：`ast.Dict` 与 `dict()` 的键若是别名，值是任意常量（含 `None`、`""`、
   `" name "`）即红；元组对仍限「名字→字符串」，避免 `('标题', 1)` 这种 (名字, 下标) 误判。
3. **消失可判红**：消失＝同名缺口之和，源树上 >0 判红并说「疑似漏扫」；盒内按产物边界豁免，
   但必须打印「盒内豁免，消失 N 属产物边界」，不许静默。整批消失（实际 0）仍单独红。
4. **反证**：单表注解赋值红且点名；`None/""/" name "` 三处红；把 `cross_ref.py` 挪进 `tests/`
   ⇒ 消失 4、红、疑似漏扫；盒内同一操作绿且打印豁免。
5. **读数**：源树 687 PASS／0 红；`daybook` 盒 503 PASS／0 红（9/28，消失 19，位移 0）；
   两套 verify EXIT=0。

### 复签不签（七续）：参照集空即红、中文键判成对、基线键退为中文名（2026-11-18）

1. **通则落闸**：判据的真值来源不许取自被测件自身；凡依赖从被测件提取的参照集，**为空即红**。
   写在 guard 顶部注释，`_alias_ref_gate` 作唯一出口。同一病第三次换皮（`score.py` 按断言名
   子串认预期、归一表按变量名计数、盒内 guard 按文件名认自己、参照集按 AST 形状读）。
2. **成对判据按中文键**：`conf_norm.py` 之外出现「中文键 → 任意字符串正名」的成对字面量即红，
   不比对正名——`{"二级": "levelX"}` 这种「名字对、正名错」正是最危险的第二种表，也红。
   反向自证：四种写法各 1 处红；`levelX` 1 处红；三张表改 `AnnAssign` ⇒ 参照集 0 ⇒ 判红并
   写明「参照集为空」。
3. **基线键退为中文名**：计数计在名字上，不按「文件×名字」。基线外的新名、同名计数增长 ⇒ 红；
   同名同数、只是换文件或换行 ⇒ 只报位移；计数减少 ⇒ 报消失。反向自证：注入基线外 `"二级"`
   ⇒ 新增 1 红；纯跨文件迁移 ⇒ 绿且位移 `['行号']`；拿掉一处 ⇒ 消失 +1。
4. **读数**：源树 684 PASS／0 红；`daybook` 盒 500 PASS／0 红（单点中文名 9 处（基线 28）｜
   新增 0｜消失 19｜位移 0，消失是产物边界）；两套 verify EXIT=0、逐件 36/38/36 全同。

### 复签不签（六续）：单点中文名基线可计数、超基线即红（2026-11-18）

1. **裁决**：判据不扩到任意中文名——成对映射才是「第二张表」，单点用名不是；把 28 处都判红
   就得改默认列名、CLI 标签、帮助文案，那是改用户可见行为，判据不该逼人改产品。但单点必须
   可计数，否则没人知道 28 处会不会长成 80 处。
2. **基线**：新增 `src/alias_name_baseline.txt`，28 条，每行 `file:line<TAB>中文名<TAB>一句用途`；
   按 `(文件, 中文名)` 计数，行号只作定位。该文件进三包 `doc` 清单，随 `plan_for()` 逐件比对，
   盒里与源不许各一份。
3. **判据**：guard 输出一行 `单点中文名 N 处（基线 N0）｜新增 X｜消失 Y`；超出基线即红并打印
   `file:line`；基线内条目消失不红，但报「消失 Y」（可能是重构，也可能是判据瞎了）。
4. **反向自证**：往产品件塞一个新别名 `"行号"` ⇒ 新增 1、红；拿掉一处基线条目 ⇒ 无新增、
   消失 +1、绿。盒内基线本就有一批「消失」（盒只装产品件，28→9），故断言取相对增量而非绝对 1。
5. **读数**：源树 680 PASS／0 红；`daybook` 盒 496 PASS／0 红，单点中文名 9 处（基线 28）｜
   新增 0｜消失 19；mcp 23/23、13/13；orch 全绿；两套 verify EXIT=0、逐件全同。

### 复签不签（五续）：打包产物追平、归一表改字面量位置判据（2026-11-18）

1. **打包**：上一提交改了 `src/CHANGELOG.md` 读数却没重打三盒，两套 verify 均 EXIT=3；按源
   重打后 `pack.py --verify` 与 `packaging/pack_pypi.py --pkg all --verify` 均 EXIT=0、全同。
2. **判据**：归一表从「按变量名计数」改为「中文别名映射字面量位置」——AST 扫全部 `.py`
   （子目录/缩进/类体/`dict()`/元组对），除 `conf_norm.py` 外出现即红；四种写法反向自证
   各 1 处红，仅 `conf_norm.py` 绿。`mcp_tools` 的 `类→category` 改走 `canon_field`。
3. **读数**：源树 677 PASS／0 FAIL；两套 verify EXIT=0；闭包 936/2160=43%（缺口 318）。

### 复签不签（四续）：conf 归一单源、alarm 只读开卷、自检补可读性（2026-11-18）

1. **P0**：新增零依赖 `conf_norm.py`（`strip + lower + 中文别名` + 行解析），完整包 / mcp /
   orch 三包同带一份；`daybook.parse_conf`、`multidx.load_conf`、`volume_paths`、
   `ledger_root.read_conf_value` 全部走它。`[索引]/根=sub`、`[Index]`、`[ index ]`、`[INDEX]`
   在两包落到同一个根；归一后仍认不出的节名报 2，不静默忽略。
2. **P0 判据**：20 条边界样本两包差分（sections/content/parsed + 最终 root）；三类中文/大小写
   conf 端到端两包同根同码。
3. **P1**：`orchestrator.py alarm` 只读开卷（缺任务卷/心跳卷不建，报「账本未检查」软警，rc 0）；
   P7 从缺卷起跑并断言零落盘。`mcp_p0_regression` 空卷格改按 rc=2 断言。
4. **P2**：mcp 自检补 `os.access + 试开`（不可读 ⇒ 5）；session `--initialize` 落盘游标；
   `read_conf_value` 注释改发行边界实话；P6 的 mcp `root=sub` 格与空卷格分机制。
5. **并表**：`orchestrator.py` 的本地 `FIELD_ALIAS` 删除，`canon_field` 改为 import 自
   `conf_norm`；`'二级': 'level2'` 并入唯一那张表。guard 新增「归一表定义计数」判据
   （各只许 1 处、必须在 `conf_norm.py`）。`daybook_append.py` 的 conf 预检提前到作者预检
   之前，坏 conf 下不再先预告「仍写入」。非 UTF-8 conf 两包同文案（码 2）。
6. **读数**：差分 20/20 两包同值；三类 conf 双包同根 `<conf>/sub`、同码 0；干净根 alarm
   rc=0 且新增 `[]`；坏 conf alarm rc=2 零落盘；mcp 空卷 2 / 根跟随缺卷 5 / `chmod 000` 5；
   源树 0 红 / 675；`daybook/` 盒 0 红 / 489；属性层全绿；变异 15/15；
   闭包覆盖 935/2159 = 43%（缺口 318）。

### 复签不签（三续）：conf 语义唯一、三形态矩阵、session 拆格（2026-11-18）

1. **P0**：`read_conf_value` 直接复用 `daybook.load_conf`（orchestrator 独立包退回同包
   section 读取器，严格性逐字对齐）；坏 conf 下 append/hook rc=2、零落盘。`Hub` 在落盘前
   严格校验 conf，alarm 坏 conf rc=2 零新增文件。`mcp_server` 启动自检：配置错 2
   （空卷/卷成目录）、证据 5（缺卷），不再 rc=0 带病常驻。
2. **P1**：能力当值传按接收者判定，`os.path.join` 绿、`lr.write` 红；P6 CONFIG 固定三形态
   × 8 入口（session 拆两格），所有码按各自码轴断言。
3. **P2**：P6 措辞改「conf 不参与根解析」；session_hook/cross_ref 0 与 multidx 豁免入同一裁决表；
   两份 README 按实测改写；新增工作规矩「先读数再判断」。
4. **读数**：闭包覆盖 929/2167 = 42%（缺口 311）；源树 0 红 / 620；`daybook/` 盒 0 红 / 489；
   P1–P10 全绿；变异 15/15；三包 verify 全同。

### 复签不签（终）：坏 conf 同码 2、P6 坏 conf 八格、裁决表落字（2026-11-18）

1. **P0（唯一产品改动）**：`orchestrator.py` 的 `_ledger_alarms` 与 `alarm` 命令两处都让
   `errors.ConfigError` 原样穿透；坏 conf 下 `daybook.py index` / `mcp_server.py` /
   `orchestrator.py alarm` 三入口 rc=2、文案同句（旧实现 alarm 被包成 6）。
2. **P1**：P6 CONFIG 新增「conf 存在但整份不可解析」八格实跑。conf 绑定入口断言 2；
   append / hook / session / cross_ref 按各自设计码断言并写明理由（不与 conf 绑定）。
3. **P2 裁决表**（`errors.py` 文档）：alarm 的码轴是体检结论（0/3），执行失败才 2/6；
   index/append 2 与 alarm 3 是两种码轴；append 不读 conf；multidx 重建派生视图 rc=0 是
   明示豁免（append-only 只覆盖账本卷）。
4. **P2 闭包参考项**：闭包 PASS 行与 score 汇总行明写「闭包面为参考项，不参与收口」；
   43% 不设阈值。
5. **读数**：源树 0 红 / 571；`daybook/` 盒 0 红 / 447；P1–P10 全绿；变异 15/15；
   三包 verify 全同；mcp 23/23；orch 全绿。

### 复签不签（续）：能力当值传一律红、记分板印覆盖率（2026-11-18）

1. **P0**：写能力函数/写原语的引用只允许直接调用或进登记表；赋值、实参、返回值、容器、
   装饰器、`getattr` 字面名一律红。三条反向自证（别名赋值/实参/容器）必须红，直接调用不红。
2. **P1**：`tools/score.py` 汇总行带 `闭包覆盖 927/2154=43%｜可能写缺口 305｜未登记 0｜
   同名红 0`，与 guard 共用同一实现。
3. **P2**：README 点名 43% 残余三类、新入口必须进 `_ENTRY_FILES`、豁免键含行号重构即红。
4. **读数**：源树 0 红 / 571；`daybook/` 盒 0 红 / 447；P1–P10 全绿；变异 15/15。

### 复签不签：闭包种子＝登记本身、差额报集合差、免签双限定（2026-11-18）

1. **P0 闭包种子**：源头改为「所有签为 `ledger`/`impl` 的函数」＋原语类别命中，不再按 kind
   分层。`safe` 是写的结果属性，不是写能力的门槛。反向自证：
   `_evil_wrap_cursor → _write_cursor`（后者登记 `ledger`、kind 仅 `{'safe'}`）⇒
   未登记=`[_evil_wrap_cursor]`，判据红（现为 PASS）。
2. **只读路径不签**：`os.open` flags 常量折叠后，safeio 的 9 条只读/句柄实现不再有任何写类别，
   登记表条目整条删除；另登记 7 条运维 CLI 主函数与 `path_leak_check.main`。
   WRITE_PATHS：117 → 116。
3. **P1 差额口径**：`--audit-closure` 与记分板并列输出 `cap−reg`、`reg−cap` 两组集合差及构成
   （入口／随包测试辅助／产品内部件；reg 侧按桶分组），不再用算术差。源树 `cap−reg = 25
   （入口 10｜测试/辅助 15｜内部件 0）`、`reg−cap = 1（dispatch 1）`。
4. **P1 改名**：`--audit-calls` 改「非原语调用点／非原语 callee」并注明不代表不写；
   `--audit-closure` 的「纯计算面」改「内建/容器方法面」。
5. **P2 键收紧**：入口按「入口名 ∩ 8 入口文件」双重限定；豁免键加入行号，删 3 条死豁免。
6. **读数**：闭包覆盖 927/2154 = 43%；写能力函数 140 / 未登记 0 / 同名红 0（豁免 10）；
   源树 0 红 / 558；`daybook/` 盒 0 红 / 437；P1–P10 全绿；变异 15/15；三包 verify 全同；
   mcp 23/23；orch 全绿。

### 复签补轮：record 同码、Registry dir_fd、边界与句柄证据（2026-11-18）

1. **record 不再压平子进程码**：append 子进程补 `cwd=HERE`；append/index 非零按 2/3/4/5/6
   还原成对应错误类，同一账本同一故障与直接入口同码。红证：旧实现从账本外 cwd 调，
   append 子进程 rc=2 被吞成 6；同一索引缺证据，record 6 而 `daybook.py index` 5。
   绿证：P6 的 record × EVIDENCE 动态格 rc=5、record × RUNTIME 动态格 rc=6，均无 traceback。
2. **Registry 密钥目录走 dir_fd**：`LockedRoot` 新增 `mkdir/mkdirs`（唯一 `_walk_parent` +
   `os.mkdir(dir_fd)`），Registry `_write_secret`、Hub 自定义父目录、AgentMessage 父目录
   全部改走它。红证（新增 M12）：退回 `os.makedirs(str(root))` 后换根会在新根长出
   `.daybook_keys`；绿证：P9 新增 Registry 用例，`.daybook_keys` 与注册卷都落旧 inode。
   P3 审计钩子识别 `os.mkdir`，Registry 建目录事件栈上有 `safeio.mkdir/mkdirs`。
3. **边界写清**：统一出口仍是 8 个；`task_volume.py` 明确列入非统一工具清单（但仍走
   `run_entry`，`transition` 缺任务给 ConfigError 2，不再 KeyError 裸栈）；`src/README.md`
   与仓根 README 都写「8 个统一入口」，不再说「任何入口」。
4. **P9 证同一句柄**：新增 `hub.tv.root is hub.root_handle`、`hb/lock/reg` 同断言；新增
   M11（Hub 传路径而非句柄）⇒ P9 红。P9 现有 5 项。
5. **P6 计数拆开报**：56 格不再读成 56 次实跑。源树：动态 19 格 / 显式不适用 21 格 /
   表级合成与无栈 16 格；盒内：动态 14 / 不适用 29 / 表级 13。
6. **P3 剩余**：orchestrator.py 英文退出码行改为 3/6；Registry/Heartbeat/TaskVolume/
   AgentServer 从路径构造 Root 时用 `weakref.finalize` 关闭自有 fd，`_append_inbox`
   每次自开的 Root 用 finally 关闭。
7. **本轮读数**：源树 `0 红 / 506 项（跳过 22）`；`daybook/` 盒 `0 红 / 386 项（跳过 45）`；
   属性 P1–P9 全绿；`变异 12 / 杀死 12 / 存活 0 / 死变异 0`；两套 `--verify` rc=0；
   mcp 23/23、orch 全绿。

### 闭包面裁决：按账本写类别传播，未解析边同名即红（2026-11-18）

- 第一方写能力函数（传递调用到账本写类别）在产品内部件必须登记；temp/派发不进闭包；
  入口不签；随包测试只报告。闭包补签 96 条（78 → 174），29 条只读路径单列待复核。
- 新增 `--audit-closure`：已解析/未解析边数、未解析按类型逐条 `file:line`、
  未登记清单、同名红点、豁免清单。未解析边同名写能力函数 ⇒ 红；11 条逐点豁免带理由。
- 读数：写能力 204 / 登记 174 / 未登记 0；已解析 929，未解析 1227；同名红点 0。
  源树 0 红/557；盒 0 红/436；P1–P10 全绿；三包 verify 全同。

### 复签补轮五：写面默认值反转（2026-11-18）

- **判据反转**：写面按「能力」定义，不按 callee 名字清单。模块面（os/shutil/subprocess/
  ctypes/io/pathlib/tempfile/mmap/sqlite3/socket/zipfile/tarfile/logging）上的调用默认写、
  未知名字也写；任意接收者的写动词一律写；`open`/`os.open` 的模式判不出即写
  （`os.open` 只有 flags 字面量 0 才只读）。纯计算按模块类别给；只读只签 site，不逐 callee 签。
- **发现面**扩到模块体/类体/lambda/推导式/装饰器；`Path` 接收者不再要求字面量；新增
  `unclassified` 默认写红池。**桶名只作预期**：产品件写类别必须 ledger；`dispatch` 桶夹带
  其它写 ⇒ 红（补反向自证）。非账本根写逐点人签 `_OFFROOT_WRITE_SITES`。
- **兜底读数** `--audit-calls`：写面调用点 / 判为纯计算调用点 / 纯计算 callee 去重列表。
- **卷配置指向不存在的文件 = 2**：`index`/`record` 同码、零落盘（作者口径不再用 4 盖住 2）；
  `daybook_append` 不解析 conf 的边界写进 README 与 docstring。
- **record 索引腿**：换根后 `update_index=True` 失败关闭（2/5，零落盘），换根保证只覆盖
  归档与登记；P10 写明覆盖面。**P7 改为采样口径**；新增 M15 ⇒ 死在 P10 dev_ino 断言。
- 读数：源树 555 项 0 红；盒 434 项 0 红；P1–P10 全绿；变异 15/15。

### 终裁轮：写路径禁派发、record 单根单凭证、P6 适用性派生（2026-11-18）

**口径（先立后用）**

1. **`subproc` 不再整类放行**：AH 每个 `subprocess.*` 都是派发点（含 `stdout=PIPE`），
   产品件里必须在 `_SUBPROC_SITES` 逐个登记；账本桶出现派发一律红。全仓只剩一个登记点
   `daybook.py::_run_hook`（变动令在索引/备份之后执行，不在写链上；外部 shell 无法预校验
   子进程根）。写路径（append/index/record）不再有任何 subprocess。
2. **P6「不适用」改为推导**：`settle()` 用「入口源码 + 第一方 import 闭包」按实际被调用的
   成员推导它能触达的判据（build → VIOLATION；非 dry build → EVIDENCE；`authors=True` 或
   非 dry → AUTHOR；RUNTIME 看写原语；协议型长驻入口按源码结构判「响应≠退出码」）。
   可触达却缺探针 ⇒ 本格判红，不再能手写一句「不适用」蒙混。
3. **记分板自报覆盖**：`tools/score.py` 输出「变异集覆盖声明」，显式列出触及/未触及的写入口；
   `P3` 在 `run_all.py` 明写为采样（写表面闭合以 guard AH 为准）。

**产品行为**

4. **`daybook_record` 单根单凭证**：归档、登记、索引全在同一 `locked(rt)` 内完成；
   `append_one(..., root=rt)` 与 `build(conf, rt)` 复用 `held(rt)`（`build` 在已持锁时用
   `nullcontext(held)`，不重入取锁）。`daybook.py`/`daybook_append` 顶层导入，根被 rename
   后不再按路径重新找模块。
5. **先判后写**：写任何字节前跑 `build(..., dry=True, authors=True)`，2/3/4/5 一次判完；
   非零退出零落盘（登记失败还会撤回原件）。等长改写旧行为「rc=3 但原件与登记已落」已消除。
6. **卷配成目录统一 rc=2**：`errors.py` 裁决写死，`append_one` 写前显式拒绝；index/baseline
   与 append 同码（此前 2/6 并存）。
7. **坏 conf 不再 rc=0**：`parse_conf` 检测「有内容但零个可识别节/键」⇒ ConfigError 2；
   「空账本」仍是 0，两者可区分。
8. **session hook 明写独立根**：模块 docstring、`ROOT` 常量与 `ledger_root.py` 均注明它固定取
   脚本目录、不读 conf `[index] root`、无 `--home`（工作区归档必须与工作区同目录）。
9. **`orchestrator.py alarm` 纳入账本体检**：`_ledger_alarms` 用 dry build 报 append-only
   违例（硬）/卷配置错（硬）/未认基线（软）；独立安装无 daybook 时报「未检查」软警，
   不再把「没查」印成「干净」。

**判据**

10. **P10 record 去 stub**：真实子进程 + 换根；子进程先开 Root 再让父进程 rename，断言
    归档与登记都落旧 inode，且 `rt.dev_ino == moved 的 (st_dev, st_ino)`、登记与原件同根。
11. **P7 扩到每个可写入口**：index（2/3）、record（3/5）、append（2）、session hook（3）、
    daybook_hook（6）、orchestrator alarm（3），逐条比 snapshot（内容/inode/mtime）。
12. **P6 探针补齐**：record/session hook 的 VIOLATION、AUTHOR、EVIDENCE，orchestrator 的
    VIOLATION（账本改写），daybook/hook 的 RUNTIME 反例全部实跑；`record × VIOLATION`
    不再是不适用（反例已推翻旧表）。
13. **AH 自证补一条**：有重定向的 `subprocess` 未登记 ⇒ 红（旧实现因「重定向即安全」直接
    不看，正是 record 旧写法的漏洞）。
14. **盒内悬空自指删除**：`ledger_guard_test.py` 末行不再声明「健康度以属性层 P1–P10 +
    tools/score.py 为准」，改为只对场景层结论负责。

**本轮读数**：源树 `0 红 / 546 项（跳过 16）`；`daybook/` 盒 `0 红 / 425 项（跳过 39）`；
属性 P1–P10 全绿（P6 56/56：动态 25 / 派生 15 / 表级 16；P7 8/8；P10 7/7）；
`变异 14 / 杀死 14 / 存活 0 / 死变异 0`（覆盖声明已随输出）；三包 `--verify` rc=0；
mcp 23/23 + 13/13；orch 回归全绿、箱内自检全绿（账本项显示「本包未随 daybook」）。



1. **审计发现口径反转**：此前 `_scan_write_sites` 只把「算得出写类别」的函数放进 `sites`，
   `os.mknod` 这类没登记类别的函数根本不进待检集合，四道闸都看不见。现在扫描返回**全部
   函数树**，`_write_violations` 对每个被扫文件的**每个函数**先做 `os.*` 全集检查，再查
   非 `os` 写 API；是否在 `sites` 与是否登记都不影响可见性。自证已改走真实入口
   `_scan_write_sites → trees/sites`：`os.mknod` 不在 `sites` 里仍被判红。
2. **非 os 写 API 补全并逐条自证**：`shutil.move/rmtree/chown`；
   `Path.mkdir/unlink/rmdir/chmod/touch/rename/replace/open('w')`；`ctypes`；
   无重定向 `subprocess`；`open` 模式变量；第三方库 import。每条在合成产品件里单独
   触发一次并打印一条 `P0 自证：… ⇒ 红`；`Path.open` 的 8 个方法各自判红。
3. **间接派发在产件内一律红**：`o = os` 模块别名、被调用的 `getattr(模块, 名)`、
   `__import__`、含写原语的字典派发、`open` 的非常量模式；`Path(p).open('w')` 同样
   计入。`hub.open()` 这类普通方法不再被误当成内建 `open`，`getattr(os,'O_DIRECTORY',0)`
   这类常量读取也不再误报。
4. **产品件第三方库**：import 只允许标准库、本地件与同仓兄弟包（`mcp_server`/
   `orchestrator` 等），其余判红；盒内缺兄弟包也不会误报。
5. **记分板改精确匹配**：`score.py` 只有失败断言名**完全等于**声明才记 killed；
   `run_all.py --audit-names` 校验每个属性件内断言名唯一（P1 两处失败分支已改名），
   `score.py` 启动先跑该审计，重名直接拒绝记分。
6. **Windows 失败可见**：`daybook._run_ops.purge`、`_backup_copy` 的时间戳、
   `Registry.register` 的 chmod 三处 best-effort 不再 `pass`，统一走 `errors.warn`；
   W1 增加 `mkdir/mkdirs/mkdirs_path/chmod/unlink/utime` 六个原语在 `_WINDOWS=True`
   下必须 `RuntimeError` 的断言；文档写明 Windows 上 `build/backup/record/register` 不可用。
7. **盒产物边界**：只有 `daybook/` 盒自带 `ledger_guard_test.py`；`daybook-mcp/`、
   `daybook-orch/` 盒内无判据，只由 `pack --verify` 保证同源，README 已明确。
8. **本轮读数**：源树 `0 红 / 536 项（跳过 22）`；`daybook/` 盒 `0 红 / 416 项（跳过 45）`；
   属性 P1–P10 全绿；`变异 14 / 杀死 14 / 存活 0 / 死变异 0`；三包 `--verify` rc=0；
   mcp 23/23、orch 全绿。

### 复签补轮三：权限/删除/时间戳同属一个写能力，记分板校验断言名（2026-11-18）

1. **`Registry.register` 的权限收紧回到凭证内**：`agent_registry.py` 原在锁外用
   `os.chmod(self.path, 0o600)`，根 rename 后会把新根同名 `注册卷.txt` 从 0644 改成 0600。
   现在与追加写在同一个 `with locked(self.root)` 里走 `lr.chmod(lr.root.rel_of(...), 0o600)`，
   失败按 best-effort 捕获 `RuntimeError`。实测原场景：新根哨兵仍 `0o644`、内容未变；
   旧根注册卷 `0o600` 且含 `probe`。
2. **同一根因的其余名字一并收口**：`daybook._run_ops` 的 `os.remove` 改 `lr.unlink`；
   `_backup_copy` 的 `os.utime` 改 `lr.utime`；`safeio` 新增 `unlink`/`utime`（dir_fd）。
   `agent_message` 的 socket 清理收进无路径参数的 `_drop_socket`（socket 在系统临时目录）。
3. **AH 改为按系统调用类别穷举**：新增声明表 `_MUTATOR_OWNER`，覆盖
   `open/os.open/replace/mkdir/chmod/utime/unlink/fsync/temp/subproc` 及
   `chown/link/truncate/xattr`（后四类声明为 `impossible`）。每类只能归
   `LockedRoot`、`safeio` 实现、随包测试或 `impossible`；未登记类别、账本桶裸调、
   产品件出现 `impossible` 类别、账本桶出现未归类的 `os.*` 一律红。`os.setxattr`
   自证新类别可被识别 ⇒ 新增名字不登记就红，不再以「第五种名字」复活。
4. **记分板校验「死在哪个断言」**：每条变异声明预期断言名，`score.py` 只有命中该名字
   才算 killed；死在别的断言或只有运行异常都记 dead。P9 拆成独立断言（写旧 inode /
   新根零写入 / 新根哨兵模式 / 旧根 0600），P5 把取锁/释放链检查前置。
   `--self-check` 同时验证「属性错」与「断言错」都不会被静默通过。
5. **P10 覆盖面扩到三条换根路径**：`build` 索引、`_backup_locked` 的 `backup/`、
   `daybook_record.record` 的「对话原件」；新增 M14（注册卷权限退回锁外 `os.chmod`），
   死在 `P9 Registry 换根后新根注册卷模式不变`。
6. **Windows 边界写死**：`mkdir/mkdirs/mkdirs_path/chmod/unlink/utime` 只有 POSIX
   `dir_fd` 实现，Windows 调用显式 `RuntimeError`，不静默回退按路径；追加/替换另有
   Windows 分支。`safeio` 模块 docstring 与 README 同步说明。
7. **本轮读数**：源树 `0 红 / 511 项（跳过 22）`；`daybook/` 盒 `0 红 / 391 项（跳过 45）`；
   属性 P1–P10 全绿；`变异 14 / 杀死 14 / 存活 0 / 死变异 0`；两套 `--verify` rc=0；
   mcp 23/23、orch 全绿。

### 复签补轮二：目录创建收进唯一写能力、M12 落在断言、P3 收口（2026-11-18）

1. **目录创建不再是第二套写路径**：此前 `LockedRoot` 是唯一写能力，但建目录仍散落在产品件里
   直接 `os.makedirs/os.mkdir`（`daybook.build` 的索引 outdir、`_backup_locked` 的
   `backup/` 与索引备份、`daybook_record.record` 的「对话原件」、`daybook_session_hook` 的
   状态目录与 `.vscode`、`orchestrator.Hub.__init__` 的卷父目录、`orchestrator._selftest` 的
   md 目录、`daybook_multidx._build_locked` 的多级目录）。这些点换根后会把目录建到新 inode。
   现在全部走 `LockedRoot.mkdirs_path`（`rel_of` 判归属 + `mkdirs` 逐段 dir_fd），
   `record` 的建目录移进 `with locked(root)` 之内。所有权口径：**在账本根内建目录与写文件
   同属一个写能力**，不再按路径重开。
   红证（新增 M13：`build` 的 outdir 退回 `os.makedirs`）⇒ P10
   `[FAIL] P10 换根后 build 不往新根建「索引」· old=True new=True`；
   绿证（新增 P10）：换根后 `build` 的追加条目写回旧 inode 的 `索引/index_账.tsv`
   （含 `第020条`），新根 `listdir == []`。
2. **M12 从「崩溃红」改为「断言红」**：P9 把 `hub.reg.register` 包 `try/except RuntimeError`，
   失败后仍断言「旧根有 `.daybook_keys`/注册卷、新根都没有」，故 M12 现在死在
   `[FAIL] P9 Registry 换根后 mkdir/write 旧 inode`，不再以运行异常冒充。
   `tools/score.py` 同步收紧：期望属性红时，只有**普通断言 FAIL** 才算 killed；只有
   `[FAIL] P# 运行异常` 的记 **dead（崩溃死）**，不算杀死。同一口径修了 M5：P5 的六处
   取锁/写入都经 `_attempt` 收成断言，M5 现在死在
   `[FAIL] P5 REPLACE 后目录 fsync ≥ 1 · err=release unlocked lock`。
3. **Registry 目录权限回补**：`_write_secret` 在 `mkdirs(perm=0o700)` 后补一次
   `LockedRoot.chmod(0o700)`（dir_fd、不跟随末段软链），4.0.5 升级留下的 0755 旧目录
   也会被收紧，与文档「目录 0700」一致。
4. **审计口径补齐**：AH 的 `_scan_write_sites` 识别 `os.mkdir/os.makedirs`（账本桶内即红）
   与 `lr.mkdir/mkdirs/mkdirs_path/chmod`（safe），并登记 `_backup_locked`、
   `initialize_state/process_once/install`、`Hub.__init__`、`safeio.mkdir`；P6 的 session
   hook × EVIDENCE 格改用盒内脚本（`ROOT` 内放 `--state`），与 R12-5「state 越界 ⇒ 6」一致。
5. **`verify_plain.py` 边界写清**：它是判据工具（只读校验，1/2 = 判据不成立/用法错），
   明确列在 8 个统一入口之外，不按统一错误类解读（仓根 README 与 `src/README.md` 同写）。
6. **本轮读数**：源树 `0 红 / 506 项（跳过 22）`；`daybook/` 盒 `0 红 / 386 项（跳过 45）`；
   属性 P1–P10 全绿；`变异 13 / 杀死 13 / 存活 0 / 死变异 0`；两套 `--verify` rc=0；
   mcp 23/23、orch 全绿。`41c4484` 误带的 0 字节 `src/任务卷.txt` 未再出现。

### 复签收口：三条所有权补立（2026-11-18 · P1/P2）

1. **写凭证生命周期**：`LockedRoot.write/update` 写前过 `_ensure_live()`（未释放且仍在本线程
   持有表）。所有权从「曾经拿到过对象」收回「此刻仍持锁」。红证：释放后旧凭证、跨线程、
   子进程持 flock 窗口三种情形均 RuntimeError 且零写（P8）；变异 M9（删 `_ensure_live`）⇒ P8 红。
2. **入口参数收口**：`daybook.py watch` 的 `int()` 解析改抛 `ConfigError`；`errors.run_entry`
   统收 `ValueError`/`TypeError` 为 6，绝不让 traceback 出栈。红证：旧码 `watch abc` ⇒ rc=1 +
   ValueError traceback；绿证：现 rc=2 + 单行文案（P6 畸形参数格）。
3. **入口级换根**：`orchestrator.Hub` 启动只开一次 `Root`，把同一句柄交给
   `TaskVolume`/`Heartbeat`/`AgentLock`/`Registry`；`agent_message.AgentServer` 同样固定
   inbox 路径与 Root；`mcp_resources._ROOT_CACHE` 按路径缓存 Root（换根仍写旧 inode，已核）。
   红证：M10（TaskVolume 写时退回 `str(root)` 重开）⇒ P9 红；绿证：P9 三类均写旧 inode、
   新同名目录零新增。
4. **入口清单对齐**：统一退出码入口明确为 8 个（daybook / append / hook / session_hook /
   record / orchestrator / mcp_server / cross_ref），P6 矩阵改为 8×7=56 格；`agent_*`、
   `daybook_multidx`、`mcp_subscribe`、`chatroom_server` 明确为运维/调试工具，不承诺统一码。
   `daybook_record` 与 `cross_ref` 补走 `run_entry`，不再持有字面退出码。
5. **登记链路**：`daybook_record.py` 调 append 时补作者位（`记录器`），不再 4 参必败；
   红证：旧 4 参调用 rc=2（作者必填），绿证：`record()` 落原件并在对话卷出现 `[记录器]`。
6. **orch 文档退出码**：README.orch.md / orchestrator.md / orchestrator.py docstring 统一为
   `0 干净｜3 有硬警｜2 参数/文件错｜6 执行异常`，中英文一致。
7. **删旧自证**：删除 `src/tools/write_audit.py`、`audit_fixture.py`；步骤 0 的可复现读数
   改为 P3 + M4（见下），不再保留一套没人跑的假自证。
8. **本轮读数**：源树 `0 红 / 506 项（PASS 506；跳过 22）`；`daybook/` 盒
   `0 红 / 386 项（PASS 386；跳过 45）`；属性 P1–P9 全绿；score
   `变异 12 / 杀死 12 / 存活 0 / 死变异 0`；仓根与 `_build` 三包 `--verify` 均 rc=0。

### 单一源件与打包校验（2026-11-18 · 步骤 6）

1. **不变量与唯一归属**：「源件唯一，盒内副本逐字节一致」不属于 `build_one` 或某个盒，
   唯一归属是 `pack.py` 的 `plan_for()`（清单）；build 与 verify 都从它派生，不各写一套。
2. **verify 补齐缺口**：原先 `--verify` 只比对清单内的件，盒里多出的同名副本可以绕过对账；
   现在把 `foreign_files()`（build 早已使用）接进 verify，清单外文件一律红。没有新增第二套机制。
3. **红证（判据 PK，源树 6 项）**：刚打包 verify 绿；手改盒内 `safeio.py` 一字节 ⇒ 红；
   删盒内 `daybook.py` ⇒ 红；盒内多一份清单外副本 ⇒ 红；复原后复绿。盒内无 `pack.py`，
   该组按原因跳过（不计入「项」）。
4. **本轮读数**：源树 `0 红 / 496 项（PASS 496；跳过 16 项）`；`daybook/` 盒
   `0 红 / 379 项（PASS 379；跳过 36 项）`；仓根三包与 `_build` 三包的 `pack.py --verify`
   均 rc=0。属性层与变异记分维持 `变异 8 / 杀死 8 / 存活 0 / 死变异 0`。
5. **收口**：再出现「改一处漏三处」时，要么副本不存在（A 方案），要么被 `plan_for` 清单的
   md5 对账拦住（B 方案，本轮采用）——不存在「少一个也算过」的静默路径。

### 判据分层与变异记分（2026-11-18 · 步骤 5）

1. **目录分层**：场景层 33 组原样迁入 `src/tests/scenarios/guard.py`（盒内由 `pack.py` 复制为
   `ledger_guard_test.py`，盒内命令与读数口径不变）；新增 `src/tests/prop/`（P1–P7 属性层）、
   `src/tests/gen.py`（`const` / `random` / `shuffle` 三模式、固定种子）、
   `src/tools/mutate.py`（AST 变异 M1–M8）、`src/tools/score.py`（记分板）。
2. **健康指标改为**：**属性全绿 + 存活变异 0 + 死变异 0**；判据条数只作参考打印，不再作为结论。
   场景层里原有的字符串锚点变异标注为 legacy，只保留为回归，不参与健康判定。
3. **属性层**：P1 根身份/换根、P2 归属封闭（软链祖先 / `link/..` 折叠陷阱 / 直接 `..` 段）、
   P3 单写路径（审计钩子看根内写栈必须经 `safeio`）、P4 能力形态（`Root` 无写方法、
   `LockedRoot.write/update` 不收 root/path、模块级无写函数）、P5 原子可见与互斥
   （目录 fsync、线程互斥、换根写旧 inode、无锁读者不撕裂）、P6 退出码矩阵、
   P7 非零退出零落盘。失败打印 `--seed` / `--mode`，原样重跑即可复现。
4. **本轮读数**：源树 `0 红 / 490 项（PASS 490；跳过 16 项）`（步骤 6 加入 PK 后为
   496 项，见上节）；`daybook/` 盒 `0 红 / 379 项（PASS 379；跳过 35 项）`；属性层 P1–P7 全绿；
   `tools/score.py` 打印 `变异 8 / 杀死 8 / 存活 0 / 死变异 0`。
   错映射自检（M2 故意声明期望 P1）会报「未被对应属性杀死」并记死变异，不会静默通过。
5. **复现**：`python3 src/tests/prop/run_all.py --seed 7`、`python3 src/tools/score.py`
   （错映射红证：`python3 src/tools/score.py --self-check`）。

### 返工补齐（2026-11-15）

1. **写入口收口 + 写路径登记表可机检**：产品件里所有写账本根内件（含租约卷、`keys/` 密钥、
   `backup/` 副本）一律走 `safeio`（`atomic_write` / `atomic_append` / `append_inplace`）；
   密钥用 `atomic_write(..., mode=0o600)` 保权限，备份改为读源字节 + 原子写，不再有第二套写路径。
   `ledger_guard_test.py` 的 `WRITE_PATHS` 单一常量登记每条写路径，桶含义由判据机器校验：
   `ledger`（只许 safeio）、`lockfile`（锁件形态固定为 `<锁目录>/<资源>.lock`、不写数据）、
   `other`（**只允许 tempfile 生成、位于系统临时目录的目标**，否则必须归账本）、`impl`（safeio 自身）。
   扫描器按包装清单还原 `import ... as` 别名，覆盖 `open`/`io.open` 写模式、`os.open` 写标志、
   `os.replace/rename`、`shutil.copy*`、`Path.write_text/bytes`、`tempfile`、`subprocess` 重定向。
2. **增量追加不再截断**：`append_inplace` 只做「追加；末字节不是换行先补一个换行，其余字节不动」，
   并移除 `repair_partial_tail`（该函数已删）。索引末行无换行（或游标不在行首）时一律转全量
   重扫重建并报告，绝不「截掉再追加」——丢的只可能是可重算的派生件。`append_inplace` 自校验
   账本根锁：未持锁直接抛错且零写（不依赖调用方纪律）。
3. **编排二阶解析修复**：`Hub.__init__` 传给 `resolve_volumes()` 的是 **conf 目录**（不是已解析的
   账本根），`[index] root` 非空（相对/绝对）时 orch 命令不再 rc=2；`digest` 读卷表、
   `push_digest` 推送、`read_multidx_rows`/`make_entry_ref` 的 conf 来源同样改为 conf 目录。
4. **环境变量优先级全仓一条线**：`--home` > `DAYBOOK_HOME` > `DAYBOOK_ROOT`（ROOT 仅兼容别名，
   最低）；`cli_shim` 与产品共用 `ledger_root.ENV_VARS`，不再各写一套。
5. **入口严格化**：`--home` 无值 rc=2（不再静默按 cwd 回落）；`mcp_server` 未知参数 rc=2
   （stdio 服务端不许带错旗标照常启动）并补 `--help`；追加 CLI 与 hook 的 `--help` 改为 rc=0。
6. **判据自己报数**：登记/实扫/未登记/找不到/直写、分桶、AF/AI 格数、源/盒项数一律由判据打印，
   报告只抄判据输出。
7. **已知边界**：单次 `O_APPEND` 的原子性仅在 APFS 上实测（32 MB 单写、5179 次采样未见半条）；
   更大写入与跨文件系统未验证，不构成保证。
8. **追加锁语义收严**：`append_inplace` 只接受「该账本根上的**独占**持有」——子目录锁、
   别的根、别的线程持有都不算，一律 RuntimeError 且零写；账本根不再由调用方自报，内部按
   `ledger_root` 同一套解析（`conf_path`）得出并与传入值逐字比对。
9. **`other` 桶彻底收窄**：只允许「目标由 tempfile 生成、规范化后仍在系统临时目录前缀内」；
   含 `..`/绝对段判红；`other` 条目不许跨文件调用（有跨文件调用即红）。租约卷、`keys/`、
   `backup/` 全部归 `ledger` 走 safeio。
10. **删除第二套锁实现**：`AgentLock` 不再建 `.lock` 文件、不再建 `.locks` 目录，互斥一律
    `safeio.locked(账本根)`（flock 目录）+ 进程内租约互斥；只读安装目录跑 `alarm`/`digest`
    均 rc=0（不 makedirs）。全仓已无 `.locks` 引用与 lock 文件创建点（判据扫描）。
11. **推送判据承重**：`digest --push` 在线时 inbox 卷必须真的新增一行且内容可辨认（时间戳 +
    本次随机目标名）；持账本根锁时推送必须表现为明确阻塞（进程未退出、inbox 不增），释放后
    完成。测试 socket 移入本轮临时目录并带随机后缀，绝不 unlink 已存在的 socket。
12. **锁语义落到命名与参数**：`AgentLock.acquire(label, agent_id)` 的返回值是**账本根锁**，
    `label` 只用于记账/命名租约 id，不参与互斥范围判定（docstring 与 CHANGELOG 均写明）。
    同一线程在已持锁状态下再次获取（任意 label）**立即抛 RuntimeError**（实测 <50 ms），
    不等待、不静默放行；跨线程/跨进程则真排队。**串行代价实测**：根锁被持 0.6 s 期间一次
    全量 `index` 等待 0.63 s；P1 持 `task:A` 1.2 s 期间 P2 取 `task:B` 等待 1.21 s（复签
    阶段另一台机实测 1.42 s）。
13. **删除共享锁能力**：`locked()` 只剩独占语义（`LOCK_SH` 与共享形参全仓清零）；线程间按
    账本根一把 `threading.Lock` 排队，跨进程由目录 `flock` 独占。`exclusive_held()` 改为
    **本线程**持有才算（同进程别的线程不继承、不复用 fd）；`append_inplace` / `atomic_write`
    / `atomic_append` / `read_modify_write` 无任何降级路径。判据含「另一线程持锁时主线程必须
    真等（>0 s 且 `exclusive_held=True`）」与六条变异（去根一致、进程级也算、去根一致、
    删同线程检查、塞回 shared 分支、锁身份退回字符串）全部红→绿。
14. **`other` 桶不许收路径参数**：`other` 条目形参表不得出现路径类参数——名含 dir/path/root/home，
    或默认值是路径（`fn.args.defaults` 按位置与末段形参对齐、`kw_defaults` 对 kw-only）；出现
    `*args` / `**kwargs` 一律红（可变参数等于「随便喂路径」）。目标侧要求 `join` 链**每个**组件
    都能证明 tempfile 派生（绝对段直接红，`..` 上跳红）；`basename(常量)` 按实际结果判
    （`basename("x/..") == ".."` 红）、`basename(变量)` 视为单段名、`dirname` 一律红。判定只看
    签名与函数体，与调用方式无关——经 `getattr` / 字典派发调用同样红。需要收目录参数的助手归
    `ledger`（如随包夹具 `_make_volume` / `build_dataset` 改走 `safeio.atomic_write`）。
15. **三条保守行为写进 README**（不改代码）：临时目录前缀大小写变体（`/PRIVATE/TMP/…`）
    保守拒绝、`fork` 子进程继承已持有的锁、`exec` 后锁清零。三者都在安全侧，不提供开关。
16. **锁身份改目录 inode**：`_PROC` / `_MUTEX` / `exclusive_held()` 统一用 `(st_dev, st_ino)`
    作键，realpath 字符串只用于报错文案。大小写、尾斜杠、软链、`/private/tmp`、NFD/NFC 等写法
    只要指向同一 inode 即同一把锁；判据逐种验证**环境实际支持**的写法（本机 4/4，NFD 不被
    归一到同 inode 时打印 `[跳过]` 与原因），同线程再取**毫秒级 RuntimeError**，
    `blocking=True` 不挂起。同线程重入不再放行（不加深、不静默通过）；临界区内写走
    `atomic_append` / `append_inplace`（检测到本线程已持锁就直接写）。
17. **写原语不再兜底**：`atomic_append` / `read_modify_write` 的 `root` 改为必填，省略直接
    RuntimeError——旧兜底「用目标所在目录取锁」会让异线程持根锁时零等待写入。`append_inplace`
    的归属判定见第 19 条（路径/inode 祖先链 + 打开后复核）。
18. **租约写失败不再泄漏根锁**：`acquire()` 的记账写包 try/finally——失败即摘登记并退锁；
    只读租约目录下复测 `exclusive_held=False`、`_ctx=0`、他人可正常获取。`AgentLock` 形参只剩
    `lease_vol` / `root`，被静默丢弃的 `lock_dir` 已删除。
19. **归属＝openat 物理走查（唯一实现·四原语共用）**：`append_inplace` 不再用字面路径逐级 stat
    （那条祖先链在父目录被换成根外软链时仍会自洽），改为从账本根目录 fd 出发，用
    `openat(dir_fd)` 逐级 `O_NOFOLLOW | O_DIRECTORY` 走到目标所在目录。该走查抽成**唯一一处**
    `_open_parent_at`，`append_inplace` / `atomic_append` / `read_modify_write` / `atomic_write`
    四个原语全部经它取父目录 fd，没有第二条路径字面打开的写路径；`os.replace` 与临时件
    也都用 `dir_fd`（`src_dir_fd` / `dst_dir_fd` / 临时件 `os.open(..., dir_fd=dfd)`）。
    每级都必须是真目录，路径物理上出不去，不存在「检查后被换」的窗口；旧的字面祖先链与
    事后 `before` inode 比对各删其一不留。**硬链接不再特殊处理**——同 inode 的两个名字是
    文件系统语义，威胁模型是「按路径/inode 祖先归属」，不是「硬链接已封死」。
20. **`locked()` 缺路径明确报错**：路径不存在时抛 `RuntimeError('账本根不存在…不退回父目录')`，
    不再是裸 `FileNotFoundError`，也不再静默退到父目录去锁。
21. **必填 root 有静态判据**：AST 级扫描 `atomic_append` / `read_modify_write` 的调用点，漏传
    `root=` 即红；变异「删掉一处 root 实参」必须红。调用点残留的 `root or dirname(...)` 兜底
    全部删除（`daybook_hook.mark_processed`、`Heartbeat`），确定不了根就按根解析失败处理。
22. **判据跳过显式化**：`[跳过]` 统一进跳过清单并在汇总打印数量与原因，不计入判据条数；
    汇总行同时打印 `项/PASS/跳过`。文档只引用打印值：本轮源树 `0 红 / 440 项（PASS 440；
    跳过 0 项）`，`daybook/` 盒 `0 红 / 338 项（PASS 338；跳过 10 项）`。盒内 10 条跳过为
    AE（缺 mcp／orch）＋ AK×3、AM、AN（缺 `agent_lock.py`）＋ AL（缺 `orchestrator.py`）＋
    R10-3×3（缺 `orchestrator.py` ×2／`mcp_server.py`）；其余项数差异来自 AH 等按文件集扫描的
    判据随文件数变化。不手写换算，也不报「恒差 3」。
23. **文档口径修正**：README 的串行保证限定为三条取锁原语（`append_inplace` / `atomic_append`
    / `read_modify_write`），并写明 `atomic_write` 是纯原子替换、不取锁、由调用方决定临界区；
    「五种写法」改为「环境支持的写法逐种验证，跳过的打印原因」。
24. **运行失败并入严重度合成**：`daybook.py` 顶层捕获任何 `RuntimeError`，打印
    `★ 运行失败：<原因>` 并把 6 并入既有 `worst_exit`（3 违例 > 4 作者 > 6 运行失败 >
    2 配置错 > 5 证据缺失），**禁止外层硬返回 2**。判据：作者红+写拒绝=4、违例+写拒绝=3；
    运行失败与配置错分码 6/2，脚本可直接区分。另构造 TSV 符号链接到根外，断言 rc=6、文案、
    无 `Traceback`、根外零改动。
25. **`other` 桶禁用 f-string 拼路径（选定①）**：`JoinedStr` 一律红——即使是 `f"{d}/ok.txt"`
    也判红，因为字面段与插值混在一个表达式里、静态无法证明整体留在临时目录。拼路径一律用
    `os.path.join` 逐元表达。行为、判据注释与 CHANGELOG 三处口径一致，不留「行为禁、文档
    不说」。
26. **`basename(变量)` 不再无条件放行**：非恒定入参必须自身可证为安全路径，或已证为单段
    相对名（`os.listdir` 循环变量、字面容器元素、显式 `basename(x) != x or x in ('', '.', '..')`
    守卫），否则红——变量可能是 `..`，叠两个就上跳两级。
27. **root 静态判据覆盖三种传法**：显式 `root=`、签名第 3 参位置传参、`**` 字面 dict 含
    `'root'` 均认；不透明 `**kwargs` 与 `as` 别名调用漏传仍红。变异三条（位置传参不误报、
    不透明 `**kwargs` 红、`as` 别名漏传红）全部成立。
28. **`Heartbeat` docstring 示例可运行**：示例补上必填 `root` 与卷路径，照抄不再在 `beat`
    处报错。
29. **另四入口顶层收口**：`daybook_append.py` / `daybook_hook.py` / `orchestrator.py` /
    `mcp_server.py` 遇到 `RuntimeError` 统一打印 `★ 运行失败（rc=6）：<原因>` 并退 6，不抛
    裸 traceback；四个入口各一条判据（子进程注入 RuntimeError，断言 rc、文案、无 traceback）。
30. **动态取得写原语即红**：`functools.partial(atomic_append, …)` 与
    `getattr(mod, 'atomic_append')(…)` 在 AST 判据里直接红——看不到 root 的动态取得不允许
    默认放行；静态直呼不误报。
31. **三原语同走一条路（R11-1）**：`atomic_append` / `read_modify_write` 此前仍按路径字面
    打开，静态软链祖先下 `append_inplace` 拒绝零写、它们却照写根外（复签实测 `out/x.txt =
    b'APP\n'`、`out/y.txt = b'RMW\n'`）。现全部改走唯一的 `_open_parent_at`；判据 `prims`
    在软链祖先下断言三原语全部拒绝、根外零写（打印 `PRIMS 3/3 leak=0`），变异把任一条改回
    字面打开即红。
32. **`atomic_write` 定位定死（R11-2·选定①）**：它此前既不取锁也无 `root`，却在多处写账本内
    派生件——「看起来在保证内、实际不在」。现纳入同一条路：`atomic_write(path, data, mode=None,
    root=None)` 的 `root` **必填**，临时件与 `os.replace` 都走 `dir_fd` 走查；它**仍不取锁**
    （纯原子替换，临界区由调用方决定），这一点写进 docstring。全部写账本内的调用点改用带
    `root` 的写法（`daybook.py` 游标/清单/时戳/备份、`daybook_multidx.py` 四处、`mcp_tools.py`、
    `agent_registry.py`、`daybook_record.py`、`daybook_append.py`、`task_volume.py`、
    `agent_heartbeat.py`、`daybook_session_hook.py`）。
33. **威胁模型写清 rename 边界（R11-3）**：持有某级目录 fd 后，该目录被整体 `rename` 搬走，
    写入会落在被搬走的 inode 上——fd 语义固有，做不到就写清。`append_inplace` docstring 与
    README「已知边界」均加「防路径重定向，不防已进入目录被整体搬走」，不写「已封死」。
34. **软链别名拼写不再误拒（R11-4）**：`/tmp` 与 `/private/tmp` 两种写法此前只有一边命中根
    前缀即 `RuntimeError`。现相对分量计算前先 `realpath` 归一父目录（末段保留原名、由
    `O_NOFOLLOW` 拒绝软链），两种拼写混用都能写（判据 `ALIAS_OK`）。
35. **末段 `O_RDWR` 回退 `O_WRONLY`（R11-5，R12-3 已改为单路）**：只写权限（0200）的目标此前从
    「可追加」变成报错。当时先试 `O_RDWR|O_APPEND`，`PermissionError` 时回退 `O_WRONLY|O_APPEND`；
    该回退分支已在第 39 条整段删除，改为「写固定 `O_WRONLY`、末字节另开只读 fd」。
36. **收口补遗（R11-6）**：①README 新增退出码表（0/2/3/4/5/6 与 3>4>6>2>5 优先级），与
    `--help` 逐字对齐；②CHANGELOG 写明 MCP 请求期的 `RuntimeError` 走 RPC
    `ERR_INTERNAL_ERROR`，进程启动期失败才是 rc=6；③`orchestrator._main` 在 `except Exception`
    之前先 `except RuntimeError: raise`，`Hub` 初始化的 `RuntimeError` 透传给顶层（rc=6），
    不再被吞成 rc=2，其余 `Exception` 保持原行为。判据 `R10-3 orchestrator.py（注入 Hub）`
    断言 rc=6、文案一致、无 traceback（删掉该分支即红）。
37. **四个原语各配一条专属变异（R12-1）**：此前只有 `append_inplace` 与 `atomic_append` 有
    「改回字面打开」的变异，`atomic_write` / `read_modify_write` 只被静态计数兜着。现
    `prims` 场景覆盖四个原语（`PRIMS 4/4 leak=0`），并各补一条专属变异：把对应原语的
    `_open_parent_at` 换成字面父目录打开 ⇒ `PRIMS_LEAK 3/4 leak=1`，判据必红。
38. **归属判据改用 inode（R12-2）**：`_rel_parts` 不再拿 `realpath` 字符串比前缀，改为从目标
    父目录起逐级向上，按 `(st_dev, st_ino)` 找到与根同一 inode 的目录即止。大小写变体、
    NFC/NFD 混写、`/tmp` ↔ `/private/tmp`、尾斜杠四种写法都能写（`SPELL 4/4 escape=R`）；
    含 `..` 归一后逃逸仍拒绝且根外零写。`_open_parent_at` 的物理走查不变，两者同一 inode 口径。
39. **追加只剩一条路（R12-3）**：删除 `O_RDWR → O_WRONLY` 的回退分支——写固定用
    `O_WRONLY|O_APPEND|O_NOFOLLOW`（`atomic_append` 仍带 `O_CREAT`；`append_inplace` 去
    `O_CREAT` 见第 43 条）；末字节检查另开 `O_RDONLY|O_NOFOLLOW` fd，
    打不开（只写/拒读）就跳过补换行。判据：`0200` 与 ACL 拒读目标仍可追加且 `padded=False`
    （`MODE200_OK`）；`0400`／`0000` 仍拒绝，ENOENT／EISDIR／ELOOP 不被吞（`REFUSE_OK`）。
40. **读不到末字节的例外写进公开 docstring（R12-4）**：`append_inplace` 明确写明「读不到末字节
    时（只写或拒读权限）跳过补换行、返回 False」，不只写在代码注释里。
41. **`daybook_session_hook --state` 越界收口（R12-5）**：`--state` 指到 `ROOT` 之外此前抛裸
    traceback、exit 1。现在顶层先捕 `RuntimeError`，打印 `★ 运行失败（rc=6）：<原因>` 并退 6，
    不抛 traceback、越界零写；判据注入越界路径断言 rc/文案/无 traceback/零写。
42. **归属判回到 `realpath` 语义（R13-1）**：`_rel_parts` 不再先 `abspath` 词法折叠——目标的
    父目录直接交 `os.path.realpath` 解释（`..` 先解软链再上跳），再从该点逐级爬 inode 找根。
    `root/link/../x`（link→根外）按 POSIX 解析到根外 ⇒ 拒绝且零写；根内正常 `..` 不误拒
    （`POSIX_OK`）。变异改回 `abspath` 词法折叠 ⇒ 静默改道、判据红。
43. **`append_inplace` 去 `O_CREAT`（R13-2）**：追加不再隐式创建——目标不存在即
    `RuntimeError`（文案写明「目标不存在·append 不创建」），要建新件走 `atomic_write`；
    docstring 写明「目标必须已存在」。`append_inplace` 现直接复用 `_append_now(create=False)`，
    与 `atomic_append` 共用同一条锁内追加实现。判据：目标不存在 ⇒ 报错且不产生文件。
44. **写后复核 inode（R13-3）**：追加完成后 `stat(path)` 与写 fd 的 `fstat` 比对
    `(st_dev, st_ino)`；不一致（追加期间被外部 `os.replace` 换掉）即 `RuntimeError`
    「目标在追加期间被替换·数据可能未落盘」。判据注入替换 ⇒ 报错、不静默成功（`REPLACE_OK`）。

### 架构收口 · 步骤 0／1（2026-11-15）

45. **步骤 0：写路径先变成运行时观测**（已迁移）：原 `src/tools/write_audit.py` 与
    `audit_fixture.py` 随步骤 5 判据分层迁入属性层，旧工具删除，不再保留一套没人跑的假自证。
    现在由 `src/tests/prop/p3_single_write.py` 用同一 `sys.addaudithook` 记录根内写事件并核对
    调用栈是否经过 `safeio.LockedRoot.write/_append/_replace/update`。
    可复现读数：`python3 src/tests/prop/run_all.py --only P3 --seed 7` ⇒ P3 全绿（3 项）；
    变异 `python3 src/tools/score.py --only M4` ⇒ M4 被 P3 杀死（1/1）。
    原三态读数（`登记=4 实扫=4 未登记=0` / `未登记=1` / `登记未实扫=4`）对应到 P3 的
    「事件全经 safeio」与 M4 旁路红证，命令与读数均以当前打印为准。
46. **步骤 1：根句柄 `Root` + 锁挂目录 fd**：`safeio.py` 引入四个单一所有权——
    `Root`（`O_RDONLY|O_DIRECTORY` fd + 一次 `fstat` 取得的 `dev_ino`；`label`/`orig` 只用于文案与
    取名，不参与锁判定）、`Rel`（构造即校验，`..`/`.`/空段/分隔符直接拒绝）、`LockedRoot`
    （写方法只存在于该类型，模块外只能经 `Root.lock()` 取得）、`WriteMode`
    （`APPEND_CREATE` / `APPEND_EXISTING` / `REPLACE`，不再有布尔参数分叉）。`_PROC` / `_MUTEX`
    只以 `dev_ino` 为键，`flock` 挂在 `root._fd` 上；写链只有一条：走查 →
    `O_APPEND` 追加或临时件 + `os.replace(dir_fd)` + `fsync(dfd)` → 追加后 inode 复核。
    旧 `locked` / `atomic_append` / `append_inplace` / `atomic_write` / `read_modify_write`
    保留为薄适配器（只做「路径 → Rel」与「复用本线程已持 LockedRoot」），迁移方案步骤 3 删除。
47. **删掉自证死判据，换根由 fd 语义定义**：`_ident()` 与 `_open_root_dir()` 的「加锁后现算
    inode 再比对」整段删除——那种比较两边同时刻现算，根被换时会一起变成新 inode。
    现在写永远落在 `Root` 打开时的 inode 上；入口若需要「路径仍是我」显式调用
    `Root.revalidate()`，写路径不调用。两条红探针转绿：
    `probe_root_swap.py` → `旧 A(moved)/vol.txt = b'written-after-swap\n'`、
    `新 A/vol.txt = b'b-original\n'`；`probe_split_lock.py` → `B 的追加是否丢失 = False`。
48. **判据分层与变异记分（步骤 1 范围）**：新增属性层 P1（`IDENT_OK` 同一根多写法同一
    `dev_ino`、`NEST_OK` 同 inode 另一种写法毫秒级报错、`SWAP_OK` 换根写旧 inode、`SPLIT_OK`
    换根下整写不覆盖追加），变异矩阵改为 AST/场景级并打印
    `总数 / 杀死 / 存活 / 死变异`：源树 6 条全杀、`daybook` 盒 5 条全杀，存活 0、死变异 0；
    锚点消失或变换无差异记「死变异」并判红，跳过的变异打印原因。
49. **收口读数**：源树 `0 红 / 442 项（PASS 442；跳过 0）`；`daybook` 盒
    `0 红 / 340 项（PASS 340；跳过 10）`；两套 `python3 src/pack.py --verify` rc=0；
    构建号 起居注 **4433** ／ 璇玑 **6596** ／ 司南 **4262**（代码规模 15,291 行）。

### 架构收口 · 步骤 2（2026-11-15）

50. **入口只开一次根句柄，向下传 `Root`**：`daybook.py`（全部子命令含 `watch`）、
    `daybook_append.py`、`daybook_hook.py`、`daybook_session_hook.py`、`mcp_resources._root()`
    （进程内按路径复用同一个 `Root`）、`AgentLock` 改为在启动/首次解析时 `Root.open()` 一次，
    把句柄向下传；根路径字符串只作为拼路径用的路径式对象（`Root.__fspath__`），不再充当身份。
    `exclusive_held()` 只接受 `Root`/`LockedRoot`，传路径直接 `TypeError`。
51. **删掉以路径为键的持有表**：`_held_for(path)`（realpath 字符串 + 每次 `stat` 的二次查找）整段
    删除，只留 `_held_for_root(rt)`（同句柄或同 `dev_ino`）。`append_inplace` 里「内部再
    `locate()` + `read_conf_value()` + `resolve_root()` + realpath 比对」整段删除——根来自入口句柄，
    函数内不做任何 conf 解析；`conf_path` 形参随 `build` / `daybook_multidx.build` 一并删除。
52. **换根语义写进行为**：写落打开时的 inode；`watch` 每轮 `revalidate()`，路径已不是本根就显式
    重开（不同 inode 就是不同根，不静默写旧 inode）。判据新增 `SWAPNEST_OK`：换根后同一句柄的
    同线程重入仍毫秒级 `RuntimeError`；变异 M1b（锁身份改现算 `stat(label)`）必红，否则「身份在
    open 时固定」只是说法。
53. **跨平台写路径（硬要求，不退成 POSIX-only）**：语义契约一条、系统调用两套——POSIX 用
    `flock(根目录 fd)` + `openat/O_NOFOLLOW` 走查 + `fsync(dir)`；Windows 用命名互斥量
    （`CreateMutexW`/`WaitForSingleObject`，进程崩溃自动放弃，不落锁件）+ `realpath`/`commonpath`
    归属判 + 拒绝 reparse point + `os.replace`。Windows 不能对目录 `fsync`，换名持久化交给 NTFS
    日志（已在 README 写明，不宣称超越平台）。`packaging/pack_pypi.py` 分类器为
    `Operating System :: OS Independent`；README 两平台都写明。**实机口径**：Windows 路径已实现、
    **实机验证待补（第 1–6 项）**，核对工具为仓根 `win_kit/`（`win_check.py` 内嵌同源 `safeio.py`，
    六项各打印 PASS/FAIL/SKIP 与原始读数，末尾 `WINDOWS 实机验证：n/6 通过`）；收到实机输出前
    README 不写「已支持 Windows」。POSIX 侧判据 W2 在非 Windows 机器上**显式跳过并计数**
    「未在 Windows 验证」，不静默当通过；POSIX 侧 P0/Q/P1 无退化。
    W1（Windows 写路径分支）在 POSIX 上强制走一遍并真写/真拒（无目录 fd、归属判、拒绝重解析点、
    追加后 inode 复核），避免这段代码沦为未执行的分支。
54. **4.0.6 真实吞吐实测（可复跑）**：新增 `bench/throughput_bench.py`，只测收口版形态（写入含根锁）：
    40 万条 / 卷 23.7 MB（APFS）：**单条追加（含账本根排他锁）0.07 ms ≈ 14,236 条/秒**；
    追加一条后的增量 `index` **0.08 s**；40 万条索引上一次 `query` **0.20 s**；全量 `baseline`
    **5.96 s**；**持根锁 1.00 s 期间另一写者实测等待 1.01 s**。复跑：
    `python3 bench/throughput_bench.py --check`（上限：单条追加 ≤200 ms、查询 ≤60 s、
    锁等待 ≥持锁时长×0.8，越界即 rc=1）。旧口径「6.2–9.3 万条/秒」来自无锁追加路径，已从
    README 撤回并在此注明作废。
55. **并发写者上限写成性能承诺（可复跑）**：新增 `bench/concurrency_bench.py`，8/64/256/1000 四点，
    每点报写成功率、单条追加 p50/p95/max、等待 ≥250 ms 的写条数。本机（macOS/APFS）读数：
    8 写者 100%·p50 0.06 ms / p95 1.27 ms / max 1.46 ms；64 写者 100%·3.68/4.00/4.59 ms；
    256 写者 100%·15.67/16.28/18.22 ms；1000 写者 100%（20000/20000）·73.64/74.93/76.07 ms；
    四点超阈值等待均为 0。复跑：`python3 bench/concurrency_bench.py --check`（成功率 <100% 即 rc=1）。
    口径：同进程线程写者，各自持 Root 句柄逐条走公开入口；跨进程互斥由 P0/Q 判据覆盖。
56. **两条定位判据落地（可执行，不是文档承诺）**：新增 `src/verify_plain.py`（只用标准库，不导入
    任何 daybook 模块）。(a) **TXT**：给一个账卷（可带索引 TSV），逐行解析五段格式，打印最后一条的
    时间/类别/标题/作者与完整性结论（含索引行数一致性）；(b) **MIG**：把仓内 `.py` 拷到干净目录，
    在 `-I -S` 隔离模式、换 `HOME`、`cwd=/` 下运行，只凭仓内文件说清最后一条与下一步动作。
    两条都在 guard 里判定，失败即红。

57. **四原语坍缩为唯一写链（步骤 3）**：`atomic_write` / `atomic_append` / `append_inplace` /
    `read_modify_write` 四个模块级适配器**整体删除**（无 shim、无模式开关），写方法只存在于
    `LockedRoot`（`write`／`update`）。原地读写改的调用点（`daybook.build`、`daybook_multidx`、
    `_backup`）改为把持锁凭证 `lr` 向下传；其余调用点 `with locked(root) as lr` 后直接
    `lr.write(...)`；已在临界区内的（`agent_lock._log`、`task_volume._transition_locked`、
    `mcp_tools` 的审计/签名/游标）用 `held(root)` 取回本线程已持凭证。`_write_cursor` 一类的
    「读 size + 写游标」并入 `lr.update`。判据：P4 静态（四原语在产品件零残留、`write`/`update`
    只定义在 `LockedRoot`）、AH 登记表把 `lr.write` 认成唯一写链、M5 变异（`held()` 无锁时就地
    取锁）必红。读数：源树 `0 红 / 445 项（PASS 445；跳过 1=W2 未在 Windows 验证）`；
    `daybook/` 盒 `0 红 / 343 项（PASS 343；跳过 11 项）`；变异矩阵源树 7/7、盒 6/6 全杀，
    存活 0／死变异 0；两套 `pack.py --verify` 均 `rc=0`。

58. **产品信条落成判据（裸终端 / 写边界 / 长跑）**：
    - **裸终端通用**：新增 `verify_plain.sh`（POSIX `sh` + `tail`/`grep`/`awk`/`od`，零 Python）；
      判据 SH 把 PATH 收窄到只有这六个命令真跑，好卷读出「时间/类别/标题/作者 + 完整性 OK」，
      坏行与末字节截断均 `rc=1` 且打印 `完整性：BAD（原因）`。README 新增「手工核验」一节
      （四条命令 + 真实输出），不依赖任何 daybook 私有件。
    - **写入边界（定稿乙）**：任何语言、任何编辑器、裸终端都能读；**写入只走 Python 客户端这一条路，
      不提供其它语言的写协议**。理由写成取舍判据：别的语言自己拼写＝第二套实现，与极简原则冲突；
      非 Python 侧需要写时用子进程调用 `daybook_append.py`，不复制锁协议。README 新增「定位与取舍」。
    - **长跑（soak）**：`bench/soak.py` 覆盖 `watch` 长跑 + 8 写者并发。**1 小时读数（非 24 小时）**：
      14,250 条写入，失败 0、坏行 0、条数与成功数一致，`watch` 122 轮无崩溃；fd `watch` 19→19、
      写者 192→192；RSS `watch` 预热后 13.3 MB（t=181s）→ 末次重建瞬时 32.4 MB，写者 12 分钟复跑
      同一批 pid 首末 -1.8%。判据：fd 增长 ≤2、RSS<100 MB、相对增长<200%、条数一致。
      说明：该 1 小时原始运行用的是首版 50% 相对阈值，把预热与末次全量重建计成「泄漏」而打印 FAIL；
      阈值改为「预热后基线 + 绝对上限 + fd」后，按同一组读数为 PASS，并以 12 分钟复跑（5,634 条、
      0 失败、fd 19→19、RSS +188%、PASS）验证新版判据可复跑。复跑：
      `python3 bench/soak.py --minutes 60 --writers 8 --interval 2 --sample 30 --check`。
    - 读数：源树 `0 红 / 449 项`（PASS 449；跳过 1=W2）；`daybook/` 盒 `0 红 / 347 项`（PASS 347；
      跳过 11）；变异矩阵源树 7/7、盒 6/6 全杀（存活 0／死变异 0）；两套 `pack.py --verify` `rc=0`。

59. **soak 判据复核（闭环，不删旧记录）**：
    - **+188% 为何曾判 PASS（已作废）**：旧 12 分钟复跑的首个采样在 t=90s、RSS 7.2 MB，末采在 t=720s、
      RSS 20.8 MB，+188.9% 即绝对 +13.6 MB；旧判据的 100 MB 是**绝对上限、不是相对基线的比例**，
      所以「+188% 但绝对值 20.8 MB < 100 MB」被放过——这是阈值漏洞，不是真无泄漏。
    - **新判据（稳态斜率，单侧）**：写者停后留 180 秒静态窗口，跳过停写后最后一次重建峰值（35 秒），
      取窗口内 10 次采样的最小二乘斜率；**斜率 ≤ +24 MB/小时** 且 **fd 增长 ≤ 2** 才算不涨；
      绝对 RSS 只打印作参考（不再参与判定）。24 MB/h 的由来：1 小时 1.4 万条带来的索引内存增长约
      2 MB/h，取 10 倍余量；单侧是因为回落（GC/压缩）不是泄漏。采样不足 4 次 ⇒ 直接红，不许静默通过。
    - **合成泄漏自证（必须红）**：`python3 bench/soak.py --leak-test` 每 2 秒持有 4 MB 已触碰页、
      永不释放，用**同一套 judge** 跑，实测稳态斜率 **+963.7 MB/h > 24 ⇒ 判红（泄漏被抓到）**；
      若判绿则本判据算假绿、退出 1。说明：先用 1 MB/轮试过，macOS 内存压缩把 1 MB 增量压到 RSS 里
      看不出来（斜率甚至为负），故改为 4 MB/轮——这是「可观测性下限」，不是放宽阈值。
    - **重跑读数（30 分钟，非 24 小时）**：12,507 条写入，失败 0、坏行 0、条数与成功数一致，
      `watch` 56 轮无崩溃；静态窗口 t=1669→1804s 斜率 **-55.2 MB/h**、fd 19→19、RSS 6.5→3.2 MB ⇒ PASS。
      12 分钟复核（非 24 小时）：4,079 条、0 失败、fd 19→19、静态窗口斜率 +18.1 MB/h ⇒ PASS。
      1 小时早期原始读数（旧判据）保留：14,250 条、0 失败、0 坏行、122 轮无崩溃、fd 19→19。
    - 三次判定都留档：① 首版 50% 相对阈值误判 FAIL；② 改绝对上限后的 PASS 属漏洞（本次作废）；
      ③ 稳态斜率 + 合成泄漏判红，才算本判据成立。

60. **错误类与单一映射（步骤 4）**：新增 `src/errors.py`——类别 → 退出码**只有一张表**
    （CONFIG=2 / VIOLATION=3 / AUTHOR=4 / EVIDENCE=5 / RUNTIME=6），严重度
    VIOLATION > AUTHOR > RUNTIME > CONFIG > EVIDENCE；入口只 `raise`，文案与码由唯一出口
    `run_entry` 给。`daybook.py` / `daybook_append.py` / `daybook_hook.py` /
    `daybook_session_hook.py` / `mcp_server.py` / `orchestrator.py` 删除各自的 `EXIT_*` 与
    `worst_exit` 副本；`mcp_server` 增加 `RPC_BY_KIND` 一张表。归类裁决写进 `errors.py`：
    **入口期**的根/配置问题=2，**运行期**的根被换/写拒绝=6。
    - **行为变化（对外契约）**：见本节开头「⚠ 退出码变更」——四组旧码 → 新码逐条列出，
      按旧码判断的外部脚本需要改；README 新增「退出码（只有一张表）」一节。
    - **红证（改前 → 改后）**：`daybook_hook` 缺对话卷 `rc=1`、`daybook` 同语义（证据缺失）
      `rc=5` ⇒ 同表后二者同为 **5**；司南执行异常 `rc=3` 与「违例 3」撞码 ⇒ 重映射后为 **6**。
    - **绿证（P6 矩阵）**：6 入口 × 7 故障类 = **42 格全部落表**；同一故障跨入口同码
      （配置 2、证据 5、运行 6、违例 3、作者 4）；多故障取最高严重度；全部探针输出无 traceback。
      不适用的格（如「追加 CLI 不做 append-only 判定」）逐条打印原因并计入跳过数，不静默。
    - **顺带修掉步骤 3 遗留**：`append_one` 在已持根锁的临界区内（司南认领/交活记日志）会
      重复取锁自死锁；改为 `exclusive_held` + `held` 复用凭证，`_emit` 登记进 `WRITE_PATHS`。
      常驻判据：司南 `selftest` 必须 `rc=0` 全绿。
    - **读数**：源树 `0 红 / 490 项`（PASS 490；跳过 16 = P6 不适用 15 + W2 未在 Windows 验证）；
      变异矩阵源树 **9/9 全杀**（新增 M6「入口插 `return 2`」、M6b「ConfigError 映射成 6」），
      存活 0／死变异 0；`daybook/` 盒 `0 红 / 379 项`（PASS 379；跳过 35），盒变异 8/8 全杀；
      两套 `pack.py --verify` 均 `rc=0`。

## v4.0.5 · 2026-11-14

**内容**：压测工具 `bench/` 入仓（开发者工具，不入发行件）。

### 工程

1. **压测工具入仓**（`bench/`）：并发与容量压测（写卷 + 建索引/查询/多级目录/摘要）＋ 判据四项与注入自证。
   - **不入三包 payload**：`bench/` 位于仓根、不在 `src/` 源清单；`pack.py` 增设 `DEV_ONLY_DIRS` 显式声明，并在 `plan_for()` 设门，误入即非零退出。
   - 默认从 PyPI 安装当前 `SUITE_VERSION`；`--wheel-dir` 仅供离线。
   - 读数：`bench/RESULTS_20261114.md`；用法：`bench/README.md`。
   - 构建号不变（bench 不计入）：2,197 / 4,319 / 2,755。

---

## v4.0.4 · 司南第二批明细（2026-11-14）

**内容**：`daybook-orch`（司南）第二批完善——行为缺陷 5 项、性能 2 项、测试覆盖与文档。
已随 v4.0.4 发布；只动 `daybook-orch/` 并同步 `src/` 副本。

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

## v4.0.4 · 2026-11-14

**内容**：司南第二批九项（源码提交 `b3ab3cc`），含两处行为变更与一处假能力清理。**跨包共享件已对齐**：`daybook/`、`daybook-mcp/` 里的 `safeio.py`、`daybook_append.py`、`agent_registry.py`、`cross_ref.py` 均与 `src/` 逐件 md5 全同。

### 行为变更（升级前必读）

1. **`alarm` 退出码从 0/1 变为 0/1/2/3**
   - 改前：正常 0、有警 1；参数错与执行异常也挤在 1，调用方无法区分「有告警」与「没跑成」。
   - 改后：0 正常；1 有硬警；**2 参数/文件错**；**3 执行异常**（读卷/解析失败）。脚本里按 `rc==1` 判「有警」的旧写法仍成立，但 `rc>1` 必须当失败处理，不能再当「无警」。
2. **`cross_ref.verify()` 缺基准直接抛错**
   - 改前：不传基准时「条目存在即通过」，校验器自证自过。
   - 改后：缺基准抛 `ValueError`，**绝不**自算自比。任何省略基准的旧调用会立刻失败，属预期。

### 修复与性能

3. **`digest` 引用与单遍读**：改前每条命中都重扫各卷；改后整卷只读一次、块边界懒搜索。实测 20 条摘要：整卷读次数由「命中×卷」降到 1。
4. **`dead_agents` 单遍扫描**：百万行盘读 1.55 GB → 73.9 MB（修前 201 次读/1,238.11 s → 修后 1 次读/7.39 s，见 `orch_perf_bench.py`）。
5. **`--limit` 语义明确**：0=全部、正数=最近 N 条（取尾部）、负数=参数错抛 `ValueError`；`None` 归一为 0。
6. **`sock_path` 净化**：agent 名先净化成安全 token 再拼 socket 路径；路径 ≥104 字节（sockaddr_un 上限）直接抛 `ValueError`，不再让 `bind` 撞底层错误。
7. **`cross_ref.verify()` 缺基准抛错**（同第 2 条实现侧）：`_entry_ref` 不再静默吞错。

### 清理（删除假能力）

8. **租约 TTL 自动过期已删除**：原实现里的 `ttl=` 参数从未进入闭环——没人续租、没人按 TTL 回收，「到期自动释放」只是名义能力。本次点名删除：`agent_lock.renew()`、`force_release()`、`sweep()`、`acquire(..., ttl=...)` 的 TTL 分支，以及 `orchestrator` 里传 `ttl=60` 的调用；同时清理死代码 `to_authors`、`read_json`/`write_json` 与未用导入。**影响**：不再有「超时自动解锁」，锁只能显式释放；进程崩溃遗留的锁需人工清（与旧行为一致，旧 TTL 分支本就不再生效）。

### 测试

9. 新增 8 条（route / digest / alarm / CLI / 跨进程锁 / verify / sock 净化 / 单遍读）＋ 11 条变异回归，全部「红→绿」成立（`orch_fixes_test.py` rc=0、`orch_mutation_check.py` rc=0）。

> **升级提示**：`alarm` 的 `rc=2/3` 是新语义；`verify()` 必须传基准；锁不再自动过期。三项都可能让旧脚本报错，属预期而非回归。

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
