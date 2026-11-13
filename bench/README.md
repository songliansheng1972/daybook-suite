# bench/ · daybook 并发与容量压测

开发者工具目录，**不进任何包的 payload**（见 `src/pack.py` 的 `DEV_ONLY_DIRS` 声明）。
测的是**发布件**（pip 安装的三件），不是仓内工作树；读数写进 `bench/RESULTS_20261114.md`。

## 前置

- macOS，`python3` ≥ 3.9
- 磁盘：`--quick` 约 1 GB；全档约 5 GB（脚本预检，不够直接拒绝）
- 1000 并发档：先 `ulimit -n 8192`
- 默认要能访问 PyPI；离线见下文「离线跑法」

## 快速开始

```bash
bench/run.sh --quick                 # 自证 + 10 万×64，约 10–20 秒（首次含装包）
bench/run.sh                         # 全档：自证 + 10 万×64 + 100 万×256 + 1000 并发
bench/run.sh --only 1m               # 单档（selfcheck|100k|1m|1000）
bench/run.sh --clean                 # 跑完删临时数据（读数先归档到 ~/daybook-bench-results/）
```

默认安装 `src/pack.py` 的 `SUITE_VERSION`；可覆盖：

```bash
bench/run.sh --version 4.0.4 --only 100k
```

## 参数

| 参数 | 含义 |
|---|---|
| `--only selfcheck\|100k\|1m\|1000` | 只跑一档（可逗号分隔）；任何档都会先跑自证 |
| `--quick` | 自证 + 10 万×64 |
| `--clean` | 成功后删临时数据；读数与日志先归档到 `~/daybook-bench-results/<时间戳>/` |
| `--version X` | 指定 pip 版本，默认 `SUITE_VERSION` |
| `--wheel-dir DIR` | 离线：只从本地目录装 wheel，不访问网络 |
| `--data-dir DIR` | 指定数据目录（默认 `mktemp -d`） |

## 各档含义与参考耗时

| 档 | 条数 × 并发 | 含义 | 4.0.3 实跑参考（M2/8 GB） |
|---|---|---|---|
| selfcheck | 1 万 × 8 | 判据自证：先注入交错必须红，再正常写必须绿 | <1 s |
| 100k | 10 万 × 64 | 判据与稳定性 | 写卷 1.07 s |
| 1m | 100 万 × 256 | 容量档，并测索引/查询/多级目录/摘要 | 写卷 15.9 s；单档约 92 s（含装包） |
| 1000 | 20 万 × 1000 | 千并发（仅台式机/服务器跑） | 未在本机跑；外推 5–10 s |

完整读数与瓶颈见 `bench/RESULTS_20261114.md`。

## 判据（四项）与自证

1. **总条数**：按 `\n\n` 流式切条，条数 == N。
2. **逐行 sha256**：按独立规格预生成清单，逐条 sha256 + 长度，按多重集比对。
3. **无交错**：每条必须是单个物理行，整行匹配结构正则，无空块、无尾残。
4. **无缺号重号**：`SEQ` 位图覆盖 1..N 各一次。

自证：0 号写者把一条拆成两段写，并与 1 号写者握手，让另一条记录插进两段之间。
**预期红**：sha256 / 无交错 / 长度三项；总条数仍绿。若注入后仍全绿，脚本立即中止并打印
「判据失效，本次读数作废」，后续档不跑。

## 失败时看哪里

- 数据目录（运行结束会打印）：
  - `results.md`：机器表、分档表、性能表、降档记录
  - `logs/stage_*.json`、`logs/judge_*.json`、`logs/writer_*.log`、`logs/perf_*.log`、`logs/machine.json`
- 失败即停、保留现场；只有显式 `--clean` 才删。
- 判据红时先看 `logs/judge_<档>.json` 的 `checks`，再对该档 `writer_<档>.log`。

## 离线跑法

在有网机器上取 wheel：

```bash
pip download --no-deps -d /path/to/wheels \
  daybook-suite==4.0.4 daybook-mcp==4.0.4 daybook-orch==4.0.4
```

拷到目标机后：

```bash
bench/run.sh --wheel-dir /path/to/wheels --quick
```

`--wheel-dir` 会强制 `pip --no-index`，不访问网络。

## 边界

- 只测：写卷（`daybook_append.append_one`）、`daybook` 建索引/查询/多级目录、`orch digest`。
- 不测：NFS/网络盘、fsync 策略、MCP 传输层、orch 其他子命令。
- 记录字节数决定磁盘与吞吐口径；跨版本/跨负载比较时必须同时看「条/秒」与「B/条」。
