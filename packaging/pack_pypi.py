#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""pack_pypi.py —— 三包的 **pip 发行版**建包器（承 pack.py 之后一步）

与 `src/pack.py` 的分工
-----------------------
  `src/pack.py`  ：把 `src/` 打成三个**整装目录**（`daybook/` `daybook-mcp/` `daybook-orch/`）
                   —— 解压即用形态，随仓提交，是 GitHub Release 的料。
  本件           ：把上述整装目录**再包一层薄壳**，产出可 `pip install` 的发行版
                   —— pip 形态，**生成物不提交**（在 `packaging/_build/`）。

壳要做的事（详见 `packaging/cli_shim.py` 抬头）：把「代码目录」与「运行目录」分开，
让 pip 装完之后的 conf／账本／数据卷落在**用户自己的目录**，而不是 site-packages。

版本映射（**重要**）
--------------------
仓内语义版本为 `v3.1`（`src/pack.py` 的 `SUITE_VERSION`）。PyPI 版本号补成三段：
  `3.1` → `3.1.0`；预发布传 `--version 3.1.0rc1`。
（PEP 440 下 `3.0` 与 `3.0.0` 数值相等，但**文件名不同**，同版号不可重传 —— 故统一补三段，避免踩坑。）

用法
----
  python3 packaging/pack_pypi.py --pkg all                 # 生成三包树到 packaging/_build/
  python3 packaging/pack_pypi.py --pkg daybook --verify    # 只核 payload == 整装目录（md5）
  python3 packaging/pack_pypi.py --pkg all --build         # 生成 + python -m build 出 dist
  python3 packaging/pack_pypi.py --version 3.0.0rc1 --pkg daybook --build
退出码：0 正常；2 缺件；3 一致校验失配。
"""

import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHIM = os.path.join(HERE, "cli_shim.py")
README_TPL = os.path.join(HERE, "README_template.md")

# ── 三件定义 ────────────────────────────────────────────────
# dist    : PyPI 发行名
# box     : 仓内整装目录（pack.py 的产物）
# module  : 顶层包名（独立命名空间·三件互不冲突）
# cmd     : 控制台命令名
# entry   : 运行目录里的入口件（HERE 锚定件）
# license : SPDX 字符串
# layer   : 授权分层说明（进长描述）
PKGS = {
    "daybook": {
        "dist": "daybook-suite",
        "box": "daybook",
        "module": "daybook_suite",
        "cmd": "daybook",
        "entry": "daybook.py",
        "license": "MIT",
        "layer": "本包**全件 MIT**（起居注＝账本体：基座 `daybook.py`／`daybook_append.py`／`safeio.py`／"
                 "`daybook_record.py`／`daybook_hook.py`／`daybook_session_hook.py`）。",
        "summary": "DAYBOOK 起居注：纯文本、零依赖、只增不改的长期记忆账本（pip 发行版）",
        "keywords": ["daybook", "append-only", "plain-text", "long-term-memory", "llm-memory",
                     "journal", "zero-dependency"],
        "usage": "daybook index                      # 生成/刷新索引\n"
                 "daybook query 类=实验 时间=2026-10   # 按字段精确查条目原文\n"
                 "daybook backup                     # 手动备份\n"
                 "daybook watch 30                   # 监视各卷，变动即重算索引 + 自动备份",
    },
    "mcp": {
        "dist": "daybook-mcp",
        "box": "daybook-mcp",
        "module": "daybook_mcp",
        "cmd": "daybook-mcp",
        "entry": "mcp_server.py",
        "license": "MIT",
        "layer": "本包**全件 MIT**（璇玑＝MCP 接口：`mcp_{server,tools,resources,prompts,subscribe,transport}.py`，"
                 "连同共享原语 `agent_registry.py`／`cross_ref.py` 与基座件）。",
        "summary": "DAYBOOK 璇玑：把纯文本账本暴露成 MCP 服务（resources / tools / prompts）",
        "keywords": ["daybook", "mcp", "model-context-protocol", "llm-memory", "agent-memory",
                     "zero-dependency"],
        "usage": "daybook-mcp                        # 以 stdio 起 MCP 服务（JSON-RPC 2.0）\n"
                 "# 供支持 MCP 的客户端挂载：resources=各卷·tools=query/append/cross_ref·prompts=4 模板",
    },
    "orch": {
        "dist": "daybook-orch",
        "box": "daybook-orch",
        "module": "daybook_orch",
        "cmd": "daybook-orch",
        "entry": "orchestrator.py",
        "license": "AGPL-3.0-or-later",
        "layer": "本包**混装**：编排件（`orchestrator.py`／`agent_lock.py`／`agent_heartbeat.py`／"
                 "`agent_message.py`／`task_volume.py`）为 **AGPL-3.0-or-later**（或另购商业许可）；"
                 "其余共享件（`agent_registry.py`／`cross_ref.py`／`daybook_append.py`／`safeio.py`）**仍为 MIT**。"
                 "逐件标注见各件文件头的 `SPDX-License-Identifier`，分层说明见随包 `LICENSING.md`。",
        "summary": "DAYBOOK 司南：把账本底座上的身份/任务/锁/心跳/路由焊成一个可跑闭环的智能体编排中心",
        "keywords": ["daybook", "orchestration", "agent", "multi-agent", "append-only",
                     "zero-dependency"],
        "usage": "daybook-orch selftest               # 自检（应全绿）\n"
                 "daybook-orch --help                 # 列出可用命令",
    },
}

PYPROJECT = """[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "@@DIST@@"
version = "@@VERSION@@"
description = "@@SUMMARY@@"
readme = "README.md"
requires-python = ">=3.8"
license = "@@LICENSE@@"
license-files = ["LICENSE"]
authors = [{ name = "手艺人老宋", email = "songliansheng@vip.sina.com" }]
keywords = [@@KEYWORDS@@]
classifiers = [
    "Programming Language :: Python :: 3",
    "Operating System :: OS Independent",
    "Topic :: Office/Business",
]

[project.urls]
Homepage = "https://daybooksuite.com"
Repository = "https://github.com/songliansheng1972/daybook-suite"

[project.scripts]
@@CMD@@ = "@@MODULE@@.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
@@MODULE@@ = ["payload/*", "payload/sample/*"]
"""

INIT_PY = '''"""@@SUMMARY@@"""

__version__ = "@@VERSION@@"

__all__ = ["__version__"]
'''


def read_text(p):
    with io.open(p, encoding="utf-8") as fh:
        return fh.read()


def write_text(p, s):
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write(s)


def md5_of(path):
    h = hashlib.md5()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_if_changed(sp, dp):
    """内容变了才写（md5 比对）；返回是否发生写入。

    刻意**不用「删光重建」**：一次性 rmtree 几十件会撞批量删除安全闸，
    且每次重写全部文件既慢又噪。改为幂等增量：变了才写、源已删才逐件清。
    """
    if os.path.exists(dp) and md5_of(sp) == md5_of(dp):
        return False
    d = os.path.dirname(dp)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    shutil.copy2(sp, dp)
    return True


def write_if_changed(p, s):
    if os.path.exists(p):
        try:
            if read_text(p) == s:
                return False
        except OSError:
            pass
    write_text(p, s)
    return True


def suite_version():
    """从 pack.py 取语义版本（单一真相源），失败回退 '3.0'。"""
    p = os.path.join(REPO, "src", "pack.py")
    try:
        for line in read_text(p).splitlines():
            s = line.strip()
            if s.startswith("SUITE_VERSION"):
                return s.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return "3.0"


def pep440(v):
    """'3.0' → '3.0.0'；已含三段/预发布后缀的原样返回。"""
    base = v
    tail = ""
    for tag in ("rc", "a", "b", "dev", "post"):
        i = v.find(tag)
        if i > 0 and v[i - 1].isdigit():
            base, tail = v[:i], v[i:]
            break
    parts = base.split(".")
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts) + tail


def tree_paths(dist):
    root = os.path.join(HERE, "_build", dist)
    return root, os.path.join(root, "src")


def gen_one(key, version):
    spec = PKGS[key]
    box = os.path.join(REPO, spec["box"])
    if not os.path.isdir(box):
        print("缺整装目录：%s（先跑 python3 src/pack.py）" % box, file=sys.stderr)
        return 2
    root, srcroot = tree_paths(spec["dist"])
    moddir = os.path.join(srcroot, spec["module"])
    payload = os.path.join(moddir, "payload")
    if not os.path.isdir(moddir):
        os.makedirs(moddir)

    # ── payload：增量拷贝 + 逐件清陈旧（不批量删）──
    n = 0
    want = set()
    for dirpath, _dirs, files in os.walk(box):
        for f in files:
            sp = os.path.join(dirpath, f)
            rel = os.path.relpath(sp, box)
            want.add(rel)
            if copy_if_changed(sp, os.path.join(payload, rel)):
                n += 1
    if os.path.isdir(payload):
        for dirpath, _dirs, files in os.walk(payload):
            for f in files:
                dp = os.path.join(dirpath, f)
                if os.path.relpath(dp, payload) not in want:
                    os.remove(dp)
                    n += 1

    sub = {
        "@@DIST@@": spec["dist"],
        "@@VERSION@@": version,
        "@@SUMMARY@@": spec["summary"],
        "@@LICENSE@@": spec["license"],
        "@@MODULE@@": spec["module"],
        "@@CMD@@": spec["cmd"],
        "@@ENTRY@@": spec["entry"],
        "@@KEYWORDS@@": ", ".join('"%s"' % k for k in spec["keywords"]),
        "@@USAGE@@": spec["usage"],
        "@@LAYER@@": spec["layer"],
    }
    tpl_py = _sub(read_text(SHIM), sub)
    if write_if_changed(os.path.join(moddir, "cli.py"), tpl_py):
        n += 1
    if write_if_changed(os.path.join(moddir, "__init__.py"), _sub(INIT_PY, sub)):
        n += 1
    if write_if_changed(os.path.join(root, "pyproject.toml"), _sub(PYPROJECT, sub)):
        n += 1
    if write_if_changed(os.path.join(root, "README.md"),
                        _sub(read_text(README_TPL), sub)):
        n += 1
    sp = os.path.join(box, "LICENSE")
    if os.path.exists(sp) and copy_if_changed(sp, os.path.join(root, "LICENSE")):
        n += 1
    print("已就绪：%s（%s %s·本次改写 %d 件）" % (root, spec["dist"], version, n))
    return 0


def _sub(text, sub):
    for k, v in sub.items():
        text = text.replace(k, v)
    return text


def verify_one(key):
    """payload == 整装目录 逐件 md5 比对。"""
    spec = PKGS[key]
    box = os.path.join(REPO, spec["box"])
    root, srcroot = tree_paths(spec["dist"])
    payload = os.path.join(srcroot, spec["module"], "payload")
    if not os.path.isdir(payload):
        print("  ✗ %s payload 不存在（先 --pkg %s 生成）" % (spec["dist"], key), file=sys.stderr)
        return [spec["dist"] + "/<payload 缺>"]
    bad = []
    for dirpath, _dirs, files in os.walk(box):
        for f in files:
            sp = os.path.join(dirpath, f)
            rel = os.path.relpath(sp, box)
            dp = os.path.join(payload, rel)
            if not os.path.exists(dp):
                bad.append("%s/payload/%s 缺" % (spec["dist"], rel))
            elif md5_of(sp) != md5_of(dp):
                bad.append("%s/payload/%s ≠ 整装目录" % (spec["dist"], rel))
    return bad


def build_one(key):
    spec = PKGS[key]
    root, _ = tree_paths(spec["dist"])
    py = sys.executable
    print("== 构建 %s ==" % spec["dist"])
    rc = subprocess.call([py, "-m", "build", "--no-isolation", "--outdir",
                          os.path.join(root, "dist")], cwd=root)
    return rc


def main():
    ap = argparse.ArgumentParser(description="DAYBOOK 三包 pip 发行版建包器")
    ap.add_argument("--pkg", choices=list(PKGS) + ["all"], default="all")
    ap.add_argument("--version", default=None,
                    help="PyPI 版本号（默认取 src/pack.py 的 SUITE_VERSION 并补成三段）")
    ap.add_argument("--verify", action="store_true", help="只核 payload == 整装目录（md5）")
    ap.add_argument("--build", action="store_true", help="生成后再 python -m build 出 dist")
    args = ap.parse_args()

    targets = list(PKGS) if args.pkg == "all" else [args.pkg]
    version = args.version or pep440(suite_version())
    print("PyPI 版本号：%s（仓内语义版本 %s）" % (version, suite_version()))

    if args.verify:
        print("== 一致校验：payload == 整装目录 ==")
        bad = []
        for k in targets:
            bad += verify_one(k)
        if bad:
            for b in bad:
                print("  ✗ " + b, file=sys.stderr)
            return 3
        print("  全同 ✓（%d 包逐件比对通过）" % len(targets))
        return 0

    rc = 0
    for k in targets:
        r = gen_one(k, version)
        if r:
            rc = r
    if rc == 0 and args.verify is False:
        bad = []
        for k in targets:
            bad += verify_one(k)
        if bad:
            print("一致校验失配：", file=sys.stderr)
            for b in bad:
                print("  ✗ " + b, file=sys.stderr)
            return 3
        print("一致校验：payload == 整装目录 ✓")
    if rc == 0 and args.build:
        for k in targets:
            r = build_one(k)
            rc = rc or r
    return rc


if __name__ == "__main__":
    sys.exit(main())
