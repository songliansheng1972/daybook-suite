#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: @@LICENSE@@
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""@@DIST@@ · 薄入口（pip 发行版）

本件由 `packaging/pack_pypi.py` 生成，**请勿手改**：要改就改仓内模板
`packaging/cli_shim.py` 再重生成。

设计缘由（为什么要这一层壳）
----------------------------
DAYBOOK 的产品件只认两级定位：显式 `--home`／`DAYBOOK_HOME`／`DAYBOOK_ROOT`，
否则**当前工作目录**；账本根只由 conf 的 `[index] root` 决定，代码装在哪都不影响。
装进 site-packages 后，壳把「代码目录」与「conf 所在目录」分开，并把这些旗标/环境变量
统一交给产品侧，保证两边解析到同一个 conf。

故本壳把「代码目录」与「运行目录」分开：
  · 代码目录 = 包内 `payload/`（随 pip 升级自动生效）
  · 运行目录 = 见 `resolve_home()`
  · 首次在该目录就位：`daybook.conf` 与 `sample/` **各复制一份**（用户可改），
    其余件（产品 `.py`、配置、文档）**一律建软链**指回 `payload/`
  · 随后 `runpy` 跑「运行目录里的 @@ENTRY@@」，并把运行目录写进 `DAYBOOK_ROOT`
    ⇒ conf / 账本 / 索引 / 备份 / 各数据卷 **全部落在用户自己的目录**
"""

import os
import runpy
import shutil
import sys
import tempfile

__all__ = ["main", "resolve_home"]

_DIST = "@@DIST@@"
_CMD = "@@CMD@@"
_ENTRY = "@@ENTRY@@"
_CONF = "daybook.conf"
_SAMPLE = "sample"
# 同套件三件的顶层模块名（#83447：统一入口 `daybook mcp` / `daybook orchestrate` 需要另两包的 payload）
# Top-level module names of the three suite packages (#83447: the unified entry `daybook mcp` /
# `daybook orchestrate` needs the payloads of the other two packages)
_SIBLINGS = ("daybook_suite", "daybook_mcp", "daybook_orch")


def payload_dir():
    """包内产品件目录。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload")


def sibling_payloads():
    """已安装的同套件各件的 payload 目录（按模块名排序；未装的跳过）。
    Payload dirs of the installed suite packages (sorted by module name; uninstalled ones are skipped)."""
    import importlib.util
    out = []
    for mod in _SIBLINGS:
        try:
            spec = importlib.util.find_spec(mod)
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.origin:
            continue
        p = os.path.join(os.path.dirname(spec.origin), "payload")
        if os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def resolve_home(argv):
    """挑运行目录，并把 `--home` 从参数里摘掉。

    优先次序：`--home=X` > `DAYBOOK_HOME` > `DAYBOOK_ROOT` > **当前目录**（仅当它已含
    `daybook.conf`，即「用我自己那本账」）。都没有 conf ⇒ 报错：绝不隐式改 `~/.daybook`
    （曾因默认落到家目录软链而误改真实账本）。
    Priority: --home=X > DAYBOOK_HOME > DAYBOOK_ROOT > cwd containing daybook.conf. With no
    conf anywhere, refuse: never implicitly touch ~/.daybook (a default that landed on a
    home-directory symlink once mutated a real ledger).
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
    # 显式指定：DAYBOOK_HOME 优先，其次 DAYBOOK_ROOT（两者都只指向 conf 所在目录）。
    # Explicit: DAYBOOK_HOME first, then DAYBOOK_ROOT (both point at the conf directory only).
    env = (os.environ.get("DAYBOOK_HOME", "").strip()
           or os.environ.get("DAYBOOK_ROOT", "").strip())
    if env:
        return os.path.abspath(os.path.expanduser(env)), rest
    if os.path.isfile(os.path.join(os.getcwd(), _CONF)):
        return os.getcwd(), rest
    # 与产品侧逐字一致的一句（与入口无关）· the same entry-independent sentence the products use
    sys.stderr.write(
        "★ 未找到 daybook.conf：%s（请用 --home 或 DAYBOOK_HOME 指定 conf 所在目录）\n"
        % os.path.realpath(os.getcwd()))
    raise SystemExit(2)


def _link_payload(home, payload, made, reassign):
    """把一个 payload 内的件链进运行目录。

    reassign=True 时，已有软链指错目标会被改指（本包 payload 优先）；
    False 时只补缺，不动已有链接（避免兄弟包覆盖本包的同名件）。
    Link one payload's files into the run directory.
    With reassign=True an existing link pointing elsewhere is repointed (own payload wins);
    with False only missing ones are created (so sibling packages never hijack same-named files).
    """
    for name in sorted(os.listdir(payload)):
        if name in (_CONF, _SAMPLE):
            continue
        link = os.path.join(home, name)
        target = os.path.join(payload, name)
        if os.path.islink(link):
            if reassign and os.path.realpath(link) != os.path.realpath(target):
                # 改指走「临时名 + os.replace」：原子、幂等、无「先删后建」空窗；
                # 并发改指最多是最后一个赢，任何时刻 runpy 都看得到完整链。
                # Repoint via temp name + os.replace: atomic, idempotent, no remove→symlink
                # window. Concurrent repoints just let the last one win; runpy always sees
                # a complete link.
                tmp = link + '.daybook-link.%d' % os.getpid()
                try:
                    os.remove(tmp)
                except FileNotFoundError:
                    pass
                os.symlink(target, tmp)
                os.replace(tmp, link)
                made.append(name)
            continue
        if os.path.exists(link):
            continue  # 用户自留的实体件：不动 / a real file kept by the user: leave it alone
        try:
            os.symlink(target, link)
        except FileExistsError:
            # 并发首次启动：另一个进程已建同名链。产品要能扛住，不许 rc=1。
            # Concurrent first run: another process already created it. The product must
            # survive this — never rc=1.
            continue
        made.append(name)


def _ensure_home(home, payload):
    """在运行目录就位：conf/sample 缺失才复制；其余件一律软链指回 payload。

    已装的兄弟包 payload 一并链入（#83447）：统一入口 `daybook mcp` / `daybook orchestrate`
    裸 import mcp_server / orchestrator，靠的正是这些链接。
    Set up the run directory: copy conf/sample only when absent; symlink everything else back to the payload.
    Payloads of the other installed suite packages are linked in too (#83447): the unified entry
    `daybook mcp` / `daybook orchestrate` does a bare import of mcp_server / orchestrator, which relies on those links.
    """
    os.makedirs(home, exist_ok=True)
    fresh = not os.path.exists(os.path.join(home, _CONF))
    if fresh:
        # 同目录临时件 + os.replace：并发首启时两个进程写同一个 conf 也只会有一个完整版本
        # temp + os.replace: concurrent first runs writing the same conf still land one complete copy
        fd, tmp = tempfile.mkstemp(prefix='.daybook.conf.', dir=home)
        try:
            with os.fdopen(fd, 'wb') as f:
                with open(os.path.join(payload, _CONF), 'rb') as src:
                    f.write(src.read())
            os.replace(tmp, os.path.join(home, _CONF))
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    if fresh and not os.path.exists(os.path.join(home, _SAMPLE)):
        # 先拷到本进程独占的临时目录，再整目录 rename：并发首启不会互相踩半成品
        # Copy into a process-private temp dir first, then rename the directory: concurrent
        # first runs never observe each other's half-copied tree.
        tmpd = tempfile.mkdtemp(prefix='.daybook.sample.', dir=home)
        try:
            shutil.copytree(os.path.join(payload, _SAMPLE), os.path.join(tmpd, _SAMPLE))
            try:
                os.rename(os.path.join(tmpd, _SAMPLE), os.path.join(home, _SAMPLE))
            except OSError:
                if not os.path.exists(os.path.join(home, _SAMPLE)):
                    raise
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)
    made = []
    _link_payload(home, payload, made, reassign=True)
    for p in sibling_payloads():
        if os.path.abspath(p) == os.path.abspath(payload):
            continue
        _link_payload(home, p, made, reassign=False)
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
    # 兄弟包 payload 也进 sys.path（#83447）：软链之外再兜一层，防平台不支持软链
    # Sibling payloads also join sys.path (#83447): a second layer in case the platform lacks symlink support
    for p in reversed(sibling_payloads()):
        if p not in sys.path:
            sys.path.insert(0, p)
    # 运行目录就是 conf 目录：覆盖 DAYBOOK_ROOT，使产品侧与壳的解析完全一致
    # （--home 优先于环境变量时，不能让旧的 DAYBOOK_ROOT 把壳的选择覆盖掉）。
    # The run directory is the conf directory: overwrite DAYBOOK_ROOT so the product side
    # resolves exactly what the shell resolved (--home must win over a stale env value).
    os.environ["DAYBOOK_ROOT"] = home
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
