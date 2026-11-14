#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""LedgerRoot · 账本根的唯一解析（daybook / MCP / 追加 CLI / 钩子 / 司南 五处同源）
LedgerRoot · the single ledger-root resolver (shared by daybook / MCP / append CLI / hook / orch)
================================================
唯一口径（五处调用点必须传同一组输入，结果才可能同一个 inode）：
One rule only (the five call sites must pass the same inputs for the same inode):
  1) conf 目录：显式 override（--root/--home）> DAYBOOK_ROOT > DAYBOOK_HOME > 本件所在目录；
     取第一个**存在 daybook.conf** 的目录；都没有 conf 时退回本件所在目录（调用方按配置错处理）。
     conf dir: explicit override > DAYBOOK_ROOT > DAYBOOK_HOME > this file's dir; the first
     directory that actually holds daybook.conf wins; with no conf anywhere it falls back to
     this file's dir (the caller reports a config error).
  2) 账本根 = conf 的 [index] root：空 → conf 所在目录；'..' → 上一级；
     绝对 → 原样；相对 → join(conf 目录)。
     Ledger root = conf [index] root: empty → conf dir; '..' → parent; absolute → as-is;
     relative → join(conf dir).
  3) 环境变量只用来**找 conf**，绝不直接当账本根，也绝不覆盖 conf 的 root。
     Environment variables only locate conf — never the root itself, never an override of
     conf's root.
  4) 全部 realpath 归一（锁的身份是目录 inode）。
     Everything is realpath-normalised (the lock identity is the directory inode).
"""
import os

CONF_NAME = 'daybook.conf'
ENV_VARS = ('DAYBOOK_ROOT', 'DAYBOOK_HOME')


def locate(default_dir, override=None):
    """定位 conf：override > DAYBOOK_ROOT > DAYBOOK_HOME > default_dir，取第一个有 conf 的。
    Locate conf: override > DAYBOOK_ROOT > DAYBOOK_HOME > default_dir, first one holding conf.
    返回 (conf_dir_realpath, conf_path|None)。
    Returns (conf_dir_realpath, conf_path|None)."""
    cands = []
    if override:
        cands.append(override)
    for name in ENV_VARS:
        v = (os.environ.get(name) or '').strip()
        if v:
            cands.append(v)
    cands.append(default_dir)
    first = None
    for c in cands:
        d = os.path.realpath(os.path.expanduser(str(c).strip()))
        if first is None:
            first = d
        p = os.path.join(d, CONF_NAME)
        if os.path.isfile(p):
            return d, p
    return (first or os.path.realpath(default_dir)), None


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


def ledger_root(default_dir, override=None):
    """一步到位：定位 conf → 解析 [index] root。找不到 conf / 根不存在都抛 ValueError。
    One call: locate conf → resolve [index] root. Raises ValueError when conf is missing or
    the root does not exist."""
    cd, cp = locate(default_dir, override)
    if cp is None:
        raise ValueError('找不到 daybook.conf：%s（可用 DAYBOOK_ROOT 指向 conf 所在目录）'
                         % os.path.join(cd, CONF_NAME))
    return resolve_root(cd, {'index': {'root': read_conf_value(cp, 'index', 'root')}})


def conf_root_from_path(conf_path):
    """已知 conf 路径时：返回 (conf 目录, 账本根)。供已自带 conf 解析器的调用方使用。
    With a known conf path: return (conf dir, ledger root). For callers that already parsed conf."""
    cd = os.path.realpath(os.path.dirname(os.path.abspath(conf_path)))
    return cd, resolve_root(cd, {'index': {'root': read_conf_value(conf_path, 'index', 'root')}})
