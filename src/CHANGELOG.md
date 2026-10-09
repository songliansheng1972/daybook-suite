# CHANGELOG

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

### 第 14 条承重墙：明档可见
- **README.md**：承重墙从 13 条扩为 14 条。第 14 条 = 明档可见：卷置项目根目录（桌面可见层），双击即开，任何编辑器可读，可手动追加批注。不藏隐藏目录、不进数据库、不要专用客户端。AI 自带 MD 物理在本地但藏在 `~/.ai/` 之类隐藏路径，用户看不见摸不着，与在云上差别不大；daybook 的明档把卷置项目根目录，肉眼可见，用户主权完整。
- **README.en.md**：在"The 13th load-bearing wall"节后加"The 14th load-bearing wall: visible files, no hidden storage"小节，并补一段说清第 14 条是用户主权差距：**数据主权 ≠ 文件在本地**——本地但隐藏不是真主权。**数据主权（不进云） ＋ 明档（不藏起来）= 用户完整主权**，是 33 天 9 子系统能管下来的实证。
- 同步把"5 条企业级优势"开头从"13 条承重墙之上"改为"14 条承重墙之上"。
- 把 12 条本体论差距 / 13 条方法论差距的尾注，补上 14 条用户主权差距的尾注，三者并列。
- 第 14 条尾注加 watch 联动一句：watch 模式下手动批注与 `daybook_append` 写入同等——索引自动跟，无需手动重算。明档不止于"能看"，还包括"用户手写在卷上跟引擎写入同等对待"。

### 起因
- 用户问"起居注可以做 AI 智能体的本地长久记忆吗？跟 AI 自带 MD 有什么区别？"——答完后用户补一条："还有一个好处，明档，明明白白的可以放在桌面，随时查阅，对用户极其友好。"主作者令"必须加"。
- 第 14 条把"明档"立成承重墙：数据主权是"文件不进云"，明档是"文件不藏起来"——两者合起来才是用户主权。AI 自带 MD 即使存在本地也藏在 `~/.ai/`，与在云上差别不大。33 天 9 子系统协作能管下来靠的就是明档——用户随时打开桌面就能看、能批、能裁。

### 脱敏处理（对外发行准备）
- 用户令："DAYBOOK2 是要对外发布发行的版本，与我们的内部项目都没有关系，切记。DAYBOOK2 里面的案例也尽量脱敏，不牵扯我们自己的项目。"
- 处理原则：内部项目名（墨斗/辞海/大宗师/纵贯线/MYSEA/MEDO 等）、内部角色署名（老宋/汤姆/皮特/斯坦森 等）从对外发行版移除。
- README.md / README.en.md：作者署名段改为通用"主作者 / 贡献者"；案例引用中"墨斗"改"榫卯"；"老宋"改"用户"或"主作者"；mysea 等内部名换成通用表达。
- 历史版本（v1.0–v1.5）的 CHANGELOG 保留原样，作为内部开发记录——脱敏只动 v1.6 及之后的对外文档。

## v1.5 · 2026-10-06

### 第 13 条承重墙：海量可通读
- **README.md**：承重墙从 12 条扩为 13 条。第 13 条 = 海量可通读：分卷天生解耦，五卷各 100 万条 = 500 万条仍 ≈ 250 MB 纯文本；按实测 36.5 万条 2.84 秒，500 万条一次通读 ≈ 40 秒。AI 记忆体的"通读"只能 retrieval 取碎片，永远看不到全年原文的真相；daybook 让"通读起居注"成立——海量是分卷换来的"五份各可一次通读"，把 AI 从"索引动物"升级成"通读动物"。
- **README.en.md**：在"The 12th load-bearing wall"节后加"The 13th load-bearing wall: massive volumes, full read-through"小节，并补一段说清第 12 条是本体论差距（记忆 ≠ 引擎）、第 13 条是方法论差距（记忆 ≠ 碎片召回），两者缺一不可。
- 同步把"5 条企业级优势"开头从"12 条承重墙之上"改为"13 条承重墙之上"。

### 起因
- 用户在弄完 DAYBOOK 后意识到："弄出海量了"——五卷架构（辞海/星河/九章/观照/天工）天然分卷，让"通读起居注"在 500 万条规模下仍成立。CAM 是后果，**通读才是承重墙**。第 13 条把这一判断记进 README。

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

### README 企业级优势
- **README.md**：12 条承重墙之后、"## 对企业" 之前，新增"## 5 条企业级优势"小节：成本曲线（用户数 × 0）/ 可审计性（起居注体例满足金融政务留痕）/ 数据主权（无云绑定，tar 即备份）/ 并发安全是数学保证（POSIX 承诺不是测试没事）/ 崩溃恢复（无半条状态）。一句话总结：成本归零 ＋ 数据主权 ＋ 审计留痕 ＋ 并发数学保证。
- **README.en.md**：同步加 "## Five enterprise-grade advantages" 五条 + 一句话总结。

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
- **第 12 条承重墙**：README.md 加"12 条承重墙"完整对照表，第 12 条 = 记忆不依赖引擎存活（本体论差距：记忆的本体 ≠ 引擎）
- **README.en.md 第 12 条**：英文版"Why it outlives other memory systems"节末加"The 12th load-bearing wall: memory outlives the engine"小节，说清 mysea/LangChain/MemGPT 把记忆做成引擎私有格式的死穴

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
- **第 12 条承重墙**：记忆不依赖引擎存活——AI 记忆体的"记忆"是引擎运行时状态，引擎崩了记忆即蒸发；daybook 的"记忆"是独立 *.txt，引擎不存在了记忆照样可读。承重墙从 11 条扩为 12 条。
- **第 13 条承重墙**：通读成本可承担——1 天 1000 条 ≈ 100KB；1 年 365000 条 ≈ 22-37MB 纯文本 ≈ 30 面。人 1 小时通读一年，AI 一次推理塞 4 万 token 够。AI 记忆体"通读"只能 retrieval 取碎片，daybook 通读是把全年原文塞进上下文看真相。承重墙从 12 条扩为 13 条。

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
