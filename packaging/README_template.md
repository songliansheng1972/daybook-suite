# @@DIST@@

@@SUMMARY@@

## 安装

```bash
pip install @@DIST@@
```

## 用法

```bash
@@USAGE@@
```

## 你的数据放在哪（重要）

第一次运行会在**运行目录**就位 `daybook.conf` 与 `sample/`（示例三卷），
账本、索引、备份、各数据卷**全部落在该目录**，不会写进 Python 安装目录。

运行目录的挑选次序：

1. `--home=/path`（当次指定）
2. 环境变量 `DAYBOOK_HOME`
3. **当前目录**（仅当它已含 `daybook.conf` —— 即"用我自己那本账"）
4. 默认 `~/.daybook`（首次自动创建）

产品代码留在包内（以软链接入运行目录），`pip install -U` 升级代码时**不会动你的数据**。
要用自己的账本：把 `daybook.conf` 里 `[卷]` 的路径改成你自己的纯文本卷即可（相对该目录或绝对路径都行）。

## 八件要紧的事

1. **纯文本** —— 卷是纯文本，任何编辑器、任何年代都能打开。
2. **零依赖** —— 只用 Python 标准库，不装任何第三方包。
3. **只增不改** —— 追加写，旧的条目不删不改（append-only 纪律）。
4. **多写者安全** —— 带锁写入，多人/多进程同时记不会互相踩。
5. **图是引用** —— 结构以引用表达，不复制正文。
6. **可挂长期记忆** —— 可作为 AI 智能体的可读长期记忆底座。
7. **够快** —— 索引随取随算，日常规模下即时完成。
8. **跨年代** —— 不依赖特定工具链，十年后仍读得出。

## 三件套

| 件 | 名 | 作用 | 许可 |
|---|---|---|---|
| `daybook-suite` | 起居注 | 账本体：索引 / 查询 / 备份 / 监视 | MIT |
| `daybook-mcp` | 璇玑 | MCP 接口（resources / tools / prompts） | MIT |
| `daybook-orch` | 司南 | 智能体编排中心 | AGPL-3.0-or-later（共享件仍 MIT） |

## 授权分层

@@LAYER@@

逐件以文件头 `SPDX-License-Identifier` 为准；包内另附 `LICENSING.md`（分层说明）。

## 链接

- 官网：<https://daybooksuite.com>
- 仓库：<https://github.com/songliansheng1972/daybook-suite>
