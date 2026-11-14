#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""LedgerRoot · 账本根的唯一解析（daybook / MCP / 追加 CLI 同源）
LedgerRoot · the single ledger-root resolver (shared by daybook / MCP / the append CLI)
================================================
口径（三处必须完全一致，否则不同进程会锁到不同目录）：
Rule (identical everywhere, or different processes lock different directories):
  conf 目录 = DAYBOOK_ROOT（显式覆盖）> 调用方给的默认目录
  conf dir = DAYBOOK_ROOT (explicit override) > the caller's default dir
  [index] root：空 = conf 目录；'..' = 上一级；绝对 = 原样；相对 = join(conf 目录)
  [index] root: empty = conf dir; '..' = parent; absolute = as-is; relative = join(conf dir)
  结果一律 realpath 归一，且必须是已存在的目录（否则 raise ValueError，不静默降级）
  The result is always realpath-normalised and must exist (otherwise ValueError; never a
  silent fallback).
锁的身份是目录 inode，所以「同一个账本根」必须解析成同一个字符串/inode。
The lock identity is the directory inode, so one ledger root must resolve to one path/inode.
"""
import os

CONF_NAME = 'daybook.conf'


def conf_dir(fallback):
    """conf 所在目录：DAYBOOK_ROOT 显式覆盖，否则 fallback（通常是脚本所在目录）。
    Directory holding daybook.conf: explicit DAYBOOK_ROOT override, else `fallback`
    (normally the script's own directory)."""
    return (os.environ.get('DAYBOOK_ROOT') or '').strip() or fallback


def read_index_root(conf_path):
    """只读 conf 的 [index] root（供不带 daybook.py 的包使用：orch 包只发追加器）。
    Read only [index] root from a conf (for packages that ship no full daybook parser: the
    orch package ships the appender only).
    根规则不在这里：返回原值后一律交给 resolve_root，保证三处同源。
    The root rule is not here: the raw value goes straight to resolve_root, so all callers
    share one implementation."""
    sec, val = None, ''
    with open(conf_path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            if s.startswith('[') and s.endswith(']'):
                sec = s[1:-1].strip()
                continue
            if sec in ('index', '索引') and '=' in s:
                k, v = s.split('=', 1)
                if k.strip() in ('root', '根'):
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
