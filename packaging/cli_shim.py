#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: @@LICENSE@@
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""@@DIST@@ · 薄入口（pip 发行版）

本件由 `packaging/pack_pypi.py` 生成，**请勿手改**：要改就改仓内模板
`packaging/cli_shim.py` 再重生成。

设计缘由（为什么要这一层壳）
----------------------------
DAYBOOK 的产品件是「进目录直接跑」的形态：`daybook.py` 用
`HERE = dirname(abspath(__file__))` 锚定 `daybook.conf` 与「账本根」，mcp/orch 各件亦用
`HERE` 取数据卷（任务卷/注册卷/租约卷/心跳卷/消息卷）。这在解压即用的整装包里很干净；
但一装进 site-packages 就出问题：conf 不在脚本旁会直接报错；就算把 conf 随包装进去，
账本与各类数据卷也会写进**程序安装目录** —— 用户无处安放自己的东西。

故本壳把「代码目录」与「运行目录」分开：
  · 代码目录 = 包内 `payload/`（随 pip 升级自动生效）
  · 运行目录 = 见 `resolve_home()`
  · 首次在该目录就位：`daybook.conf` 与 `sample/` **各复制一份**（用户可改），
    其余件（产品 `.py`、配置、文档）**一律建软链**指回 `payload/`
  · 随后 `runpy` 跑「运行目录里的 @@ENTRY@@」⇒ `HERE` = 运行目录
    ⇒ conf / 账本 / 索引 / 备份 / 各数据卷 **全部落在用户自己的目录**

前提（已探针实测）：`os.path.abspath` **不解析软链**，故经软链执行时 `HERE` 等于软链所在目录。
"""

import os
import runpy
import shutil
import sys

__all__ = ["main", "resolve_home"]

_DIST = "@@DIST@@"
_CMD = "@@CMD@@"
_ENTRY = "@@ENTRY@@"
_CONF = "daybook.conf"
_SAMPLE = "sample"


def payload_dir():
    """包内产品件目录。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload")


def resolve_home(argv):
    """挑运行目录，并把 `--home` 从参数里摘掉。

    优先次序：`--home=X` > 环境变量 `DAYBOOK_HOME` > **当前目录**（仅当它已含 `daybook.conf`，
    即「用我自己那本账」）> `~/.daybook`
    """
    rest = []
    home = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--home":
            i += 1
            if i < len(argv):
                home = argv[i]
        elif a.startswith("--home="):
            home = a.split("=", 1)[1]
        else:
            rest.append(a)
        i += 1
    if home:
        return os.path.abspath(os.path.expanduser(home)), rest
    env = os.environ.get("DAYBOOK_HOME", "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env)), rest
    if os.path.isfile(os.path.join(os.getcwd(), _CONF)):
        return os.getcwd(), rest
    return os.path.join(os.path.expanduser("~"), ".daybook"), rest


def _ensure_home(home, payload):
    """在运行目录就位：conf/sample 缺失才复制；其余件一律软链指回 payload。"""
    os.makedirs(home, exist_ok=True)
    fresh = not os.path.exists(os.path.join(home, _CONF))
    if fresh:
        shutil.copyfile(os.path.join(payload, _CONF), os.path.join(home, _CONF))
    if fresh and not os.path.exists(os.path.join(home, _SAMPLE)):
        shutil.copytree(os.path.join(payload, _SAMPLE), os.path.join(home, _SAMPLE))
    made = []
    for name in sorted(os.listdir(payload)):
        if name in (_CONF, _SAMPLE):
            continue
        link = os.path.join(home, name)
        target = os.path.join(payload, name)
        if os.path.islink(link):
            if os.path.realpath(link) != os.path.realpath(target):
                os.remove(link)
                os.symlink(target, link)
                made.append(name)
            continue
        if os.path.exists(link):
            continue  # 用户自留的实体件：不动
        os.symlink(target, link)
        made.append(name)
    return made, fresh


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    payload = payload_dir()
    home, rest = resolve_home(argv)
    made, fresh = _ensure_home(home, payload)
    runner = os.path.join(home, _ENTRY)
    if not os.path.exists(runner):
        sys.stderr.write("%s: 运行目录内缺 %s：%s\n" % (_CMD, _ENTRY, runner))
        return 2
    sys.path.insert(0, home)
    sys.path.insert(0, payload)
    # mcp/orch 各件支持 DAYBOOK_ROOT 覆盖（其自带测试逃生门）·一并设上以求一致
    os.environ.setdefault("DAYBOOK_ROOT", home)
    if made or fresh:
        sys.stderr.write(
            "%s: 运行目录 = %s%s（%s）\n"
            % (_CMD, home, "，已初始化" if fresh else "",
               "新建链接 %d 条" % len(made) if made else "无需新建链接")
        )
    sys.argv = [runner] + rest
    try:
        runpy.run_path(runner, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
