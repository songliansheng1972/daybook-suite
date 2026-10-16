# packaging/ —— pip 发行版（PyPI）建包

本目录是 **DAYBOOK 三件的 pip 发行版**建包链：把仓内整装目录再包一层薄壳，
产出可 `pip install` 的 sdist/wheel。

## 与 `src/pack.py` 的分工

| 步骤 | 工具 | 产物 | 是否提交 |
|---|---|---|---|
| 1 | `python3 src/pack.py` | 三个**整装目录** `daybook/` `daybook-mcp/` `daybook-orch/`（解压即用） | **提交**（GitHub Release 的料） |
| 2 | `python3 packaging/pack_pypi.py` | `packaging/_build/<dist>/` 三棵 pip 包树 | **不提交**（生成物） |
| 3 | `python3 -m build`（由 `--build` 代跑） | `packaging/_build/<dist>/dist/*.whl` `*.tar.gz` | 不提交 |
| 4 | `twine upload` | PyPI 上的发行版 | — |

**源只此一份**：产品件在 `src/`；整装目录是 `pack.py` 的产物；pip 树是 `pack_pypi.py` 的产物。
`packaging/cli_shim.py` 与 `packaging/README_template.md` 是**模板**（要改改这里），
`pack_pypi.py` 负责把模板 + 整装目录组装成包树。

## 为什么需要一层壳（`cli_shim.py`）

产品件是「进目录直接跑」形态：`daybook.py`／`mcp_*.py`／`orchestrator.py` 等都用
`HERE = dirname(abspath(__file__))` 锚定 conf 与各类数据卷。装进 `site-packages` 后，
conf 不在脚本旁会直接报错；即便随包带上 conf，**账本与数据卷也会写进程序安装目录**。

壳把「代码目录」与「运行目录」分开：

```
分包内  <mod>/payload/          ← 代码在此（随 pip 升级生效）
运行目录  $DAYBOOK_HOME|~/.daybook|当前目录(若已有 conf)|--home=
          ├─ daybook.conf       ← 复制一份（用户可改）
          ├─ sample/            ← 复制一份
          └─ daybook.py, *.py … ← 软链，指回 payload
```

**载荷前提（已探针实测）**：`os.path.abspath` **不解析软链**，故经软链执行时 `HERE`＝软链所在目录
⇒ 数据落运行目录、代码随包升级，两头都不误。

## 用法

```bash
cd <仓根>
python3 src/pack.py                          # 1) 先出整装目录（源改了必须先重打）
python3 packaging/pack_pypi.py --pkg all     # 2) 生成三棵 pip 包树（自带一致校验）
python3 packaging/pack_pypi.py --pkg all --build   # 3) 顺带 python -m build 出 dist
python3 packaging/pack_pypi.py --pkg mcp --verify  #    只核 payload == 整装目录（md5）
python3 packaging/pack_pypi.py --version 3.2.0rc1 --pkg daybook --build  # 指定版本
```

依赖（**不入仓、装在本机隔离环境**）：`build`、`twine`、`setuptools>=77`。

## 版本号口径

仓内语义版本（`src/pack.py` 的 `SUITE_VERSION`，现为 `v3.2`）→ PyPI 版本号**补成三段**：`3.2` → `3.2.0`。
预发布显式传 `--version 3.2.0rc1`。

> 为何补三段：PEP 440 下 `3.0` 与 `3.0.0` 数值相等，但**文件名不同**；而**正式 PyPI 同一文件名不可覆盖、不可重传**。
> 若一会儿发 `3.0`、一会儿发 `3.0.0`，等于白白烧掉一个版号。统一补三段即免此坑。

**不可逆提醒**：正式 PyPI 上，一旦上传，该「版本号+文件名」永久占用。**首发务必用预发布**
（如 `3.0.0rc1`：占自己的名，不吃掉 `3.0.0`）当演练靶。

## 许可分层（按件·不按包）

三件的 `license` 字段不是一刀切：

- `daybook-suite`（起居注）：**全件 MIT** → `license = "MIT"`
- `daybook-mcp`（璇玑）：**全件 MIT** → `license = "MIT"`
- `daybook-orch`（司南）：**混装**（编排件 AGPL-3.0-or-later ＋ 共享件 MIT）→
  发行版层写 `license = "AGPL-3.0-or-later"`（取最严者），随包带 `LICENSING.md`，
  长描述里明示"包内 MIT 件仍为 MIT"；逐件以文件头 `SPDX-License-Identifier` 为准。

## 已发布记录

| 版本 | 件 | 日期 | 备注 |
|---|---|---|---|
| `3.0.0rc1` | `daybook-suite` | 2026-10-14 | 首发·通道演练（rc 不吃正式版号） |
