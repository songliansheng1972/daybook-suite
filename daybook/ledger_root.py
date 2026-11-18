#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""LedgerRoot · 账本根的唯一解析（daybook / MCP / 追加 CLI / 钩子 / 司南 五处同源）
LedgerRoot · the single ledger-root resolver (shared by daybook / MCP / append CLI / hook / orch)
================================================
唯一口径（两级，猜不到就停 / two levels only — stop when unknown）：
  1) conf 目录：显式指定优先（--home/--root 参数 > DAYBOOK_ROOT > DAYBOOK_HOME）；
     未显式指定 ⇒ **当前工作目录**。显式指定但该目录没有 conf ⇒ 立刻报错，
     绝不静默换下一个候选，也绝不以「本件所在目录」兜底。
     conf dir: an explicit location wins (--home/--root argument > DAYBOOK_ROOT >
     DAYBOOK_HOME); with none given, the **current working directory** is used. An explicit
     location without a conf fails immediately — no silent fall-through to the next candidate,
     no "script directory" fallback.
  2) 账本根 = conf 的 [index] root：空 → conf 所在目录；'..' → 上一级；
     绝对 → 原样；相对 → join(conf 目录)。
     Ledger root = conf [index] root: empty → conf dir; '..' → parent; absolute → as-is;
     relative → join(conf dir).
  3) 全部 realpath 归一（锁的身份是目录 inode）。
     Everything is realpath-normalised (the lock identity is the directory inode).
  4) 例外（明写的独立根）：`daybook_session_hook.py` 的根固定为脚本所在目录，不读本
     文件的解析结果——它随工作区安装，归档物必须与工作区同目录（见该件 docstring）。
     Exception (documented independent root): `daybook_session_hook.py` uses its own script
     directory and does not use this resolver — it is installed inside the workspace and its
     archive must land there (see that module's docstring).
"""
import os

CONF_NAME = 'daybook.conf'
# 显式指定的环境变量（优先级从高到低）：HOME 优先，ROOT 仅兼容别名。
# Explicit env vars (highest first): HOME wins; ROOT is a compatibility alias with the lowest
# priority. The shim reads this same constant (no second copy of the rule).
ENV_VARS = ('DAYBOOK_HOME', 'DAYBOOK_ROOT')


def take_home(argv):
    """从参数表里剥出 `--home DIR` / `--home=DIR`（统一旗标，所有入口共用）。
    Strip `--home DIR` / `--home=DIR` from an argv list (the one flag every entry accepts).
    返回 (剩余参数, home|None, 错误文案)。`--home` 没带值 ⇒ 错误文案非空（调用方 rc=2），
    绝不静默回落。
    Returns (rest, home|None, error). A valueless `--home` yields an error (the caller exits 2)
    and is never silently ignored."""
    rest, home, i = [], None, 0
    while i < len(argv):
        a = argv[i]
        if a == '--home':
            if i + 1 >= len(argv):
                return rest, None, '--home 需要一个目录参数（conf 所在目录）'
            home = argv[i + 1]
            i += 2
            continue
        if a.startswith('--home='):
            home = a.split('=', 1)[1]
            if not home.strip():
                return rest, None, '--home 需要一个目录参数（conf 所在目录）'
            i += 1
            continue
        rest.append(a)
        i += 1
    return rest, home, ''


def not_found_message(conf_dir):
    """五处入口共用的「找不到 conf」文案（逐字一致）。
    The one "conf not found" wording shared verbatim by all five entries."""
    return ('★ 未找到 daybook.conf：%s（请用 --home 或 DAYBOOK_HOME 指定 conf 所在目录）'
            % conf_dir)


def _explicit(override=None):
    if override is not None and str(override).strip():
        return str(override).strip()
    for name in ENV_VARS:
        v = (os.environ.get(name) or '').strip()
        if v:
            return v
    return ''


def locate(override=None):
    """定位 conf：显式指定优先，否则当前工作目录；只查这一个候选。
    Locate conf: an explicit location, else the current working directory; one candidate only.
    返回 (conf_dir_realpath, conf_path|None)。无 conf 时 conf_dir 仍是该候选目录。
    Returns (conf_dir_realpath, conf_path|None); with no conf, conf_dir is still that candidate."""
    raw = _explicit(override)
    d = os.path.realpath(os.path.expanduser(raw if raw else os.getcwd()))
    p = os.path.join(d, CONF_NAME)
    return d, (p if os.path.isfile(p) else None)


def read_conf_value(conf_path, section, key):
    """只读 conf 的某一段某一键（供不带 daybook.py 完整解析器的包使用）。
    Read one section/key from a conf (for packages that ship no full daybook parser).
    根规则不在这里：返回值一律交给 resolve_root。
    The root rule is not here: the raw value goes straight to resolve_root."""
    sec, val = None, ''
    with open(conf_path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            if s.startswith('[') and s.endswith(']'):
                sec = s[1:-1].strip()
                continue
            if sec is not None and sec.lower() == section.lower() and '=' in s:
                k, v = s.split('=', 1)
                if k.strip().lower() == key.lower():
                    val = v.strip()
    return val


def resolve_root(conf_dir_path, conf):
    """conf [index] root → 绝对账本根（realpath 归一·必须存在）。
    conf [index] root → absolute ledger root (realpath-normalised, must exist).
    目录不存在或不是目录 → ValueError（调用方按配置错处理，绝不静默换根）。
    A missing directory raises ValueError (the caller treats it as a config error and never
    silently switches roots)."""
    rc = str((conf.get('index') or {}).get('root', '') or '').strip()
    if not rc:
        root = conf_dir_path
    elif rc == '..':
        root = os.path.dirname(conf_dir_path)
    elif os.path.isabs(rc):
        root = rc
    else:
        root = os.path.join(conf_dir_path, rc)
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        raise ValueError('账本根目录不存在或不是目录：%s（conf=%s，index.root=%r）'
                         % (root, os.path.join(conf_dir_path, CONF_NAME), rc))
    return root


def ledger_root(override=None):
    """一步到位：定位 conf → 解析 [index] root。找不到 conf / 根不存在都抛 ValueError。
    One call: locate conf → resolve [index] root. Raises ValueError when conf is missing or
    the root does not exist."""
    cd, cp = locate(override)
    if cp is None:
        raise ValueError(not_found_message(cd))
    return resolve_root(cd, {'index': {'root': read_conf_value(cp, 'index', 'root')}})


def conf_root_from_path(conf_path):
    """已知 conf 路径时：返回 (conf 目录, 账本根)。供已自带 conf 解析器的调用方使用。
    With a known conf path: return (conf dir, ledger root). For callers that already parsed conf."""
    cd = os.path.realpath(os.path.dirname(os.path.abspath(conf_path)))
    return cd, resolve_root(cd, {'index': {'root': read_conf_value(conf_path, 'index', 'root')}})
