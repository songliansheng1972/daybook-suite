#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""卷路径解析（orch）· conf 驱动 + 单一根
Volume path resolution (orch) · conf-driven + a single root
================================================
本件只做一件事：把「根目录 + daybook.conf」解析成**全部卷的绝对路径**。
This module does one thing: resolve "root + daybook.conf" into **absolute paths for every volume**.

为什么单独成件：orchestrator 与 agent_message 都要用同一套路径，
放一起会循环引用；放两份会重新长出「两套根解析」。
Why a separate module: both orchestrator and agent_message need the same paths.
Putting it in either one creates a circular import; duplicating it grows a second root resolver.

conf 写法（`[volumes]` 段·键为内部卷角色；不写则用默认文件名）：
conf format (`[volumes]` section · keys are internal volume roles; defaults apply when absent):
    [volumes]
    registry=注册卷.txt
    tasks=任务卷.txt
    heartbeat=心跳卷.txt
    leases=租约卷.txt
    ledger=编排卷.txt
    inbox=消息卷.txt
中文/旧写法（注册卷=…、任务卷=… 等）作为别名照读。
Chinese/legacy forms (注册卷=…, 任务卷=… etc.) are accepted as aliases.
同段里其它键仍视为 daybook 内容卷（供 digest 兜底扫描），不会被当成内部卷。
Other keys in the same section remain daybook content volumes (for the digest fallback),
and are never mistaken for internal volumes.
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# 内部卷角色的默认文件名 · default filenames for the internal volume roles
DEFAULT_VOLUMES = {
    'registry': '注册卷.txt',
    'tasks': '任务卷.txt',
    'heartbeat': '心跳卷.txt',
    'leases': '租约卷.txt',
    'ledger': '编排卷.txt',
    'inbox': '消息卷.txt',
}

# 角色别名（英文为准·中文/旧写法兼容） · role aliases (English canonical; Chinese/legacy accepted)
VOLUME_ALIASES = {
    'registry': ('registry', '注册卷', '注册卷.txt'),
    'tasks': ('tasks', 'task', '任务卷', '任务卷.txt'),
    'heartbeat': ('heartbeat', '心跳卷', '心跳卷.txt'),
    'leases': ('leases', 'lease', '租约卷', '租约卷.txt'),
    'ledger': ('ledger', '编排卷', '编排卷.txt'),
    'inbox': ('inbox', '消息卷', '消息卷.txt'),
    'locks': ('locks', 'lock', '锁目录'),
}

# 保留键：这些键不是内容卷，digest 兜底扫描须跳过 · reserved keys: not content volumes, skipped by the digest fallback
RESERVED_KEYS = {alias for aliases in VOLUME_ALIASES.values() for alias in aliases}


def resolve_root(root=None):
    """账本根：与 daybook / MCP / 追加 CLI / 钩子 同源（唯一实现 ledger_root）。
    `root` 只用于定位 conf 目录，绝不直接当根；conf 的 [index] root 说了算。
    Ledger root: the same resolver as daybook / MCP / the append CLI / the hook (the only
    implementation is ledger_root). `root` only locates the conf dir — never the root itself;
    conf's [index] root decides."""
    from ledger_root import locate, not_found_message, read_conf_value, resolve_root as _resolve
    cd, cp = locate(override=root)
    if cp is None:
        raise ValueError(not_found_message(cd))
    return _resolve(cd, {'index': {'root': read_conf_value(cp, 'index', 'root')}})


def read_conf_sections_from(path):
    """读指定 conf 文件，返回 {段名小写: {键小写: 值}}。缺文件返 {}。
    Read the given conf file → {lowercased section: {lowercased key: value}}. {} when absent."""
    sections = {}
    if not path or not os.path.exists(path):
        return sections
    sec = None
    for line in io.open(path, encoding='utf-8'):
        raw = line.rstrip('\n')
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        m = re.match(r'^\[(.+)\]$', stripped)
        if m:
            sec = m.group(1).strip().lower()
            sections.setdefault(sec, {})
            continue
        if sec is not None and '=' in raw:
            k, v = raw.split('=', 1)
            k = k.strip().lower()
            if k:
                sections[sec][k] = v.strip()
    return sections


def read_conf_sections(root=None):
    """读 conf（默认 <root>/daybook.conf）。conf 目录与根不同时由调用方直接给路径。
    Read conf (defaults to <root>/daybook.conf). When the conf dir differs from the root the
    caller passes the path directly."""
    from ledger_root import locate
    _cd, cp = locate(override=root)
    if cp is None:
        return {}
    return read_conf_sections_from(cp)


def _volume_table(root=None, conf_path=None):
    """合并 [volumes] 与旧段名 [卷]；给了 conf_path 就直接读那一份。
    Merge [volumes] with the legacy section [卷]; an explicit conf_path is read as-is."""
    sections = (read_conf_sections_from(conf_path) if conf_path
                else read_conf_sections(root))
    table = {}
    for name in ('volumes', '卷'):
        table.update(sections.get(name, {}))
    return table


def content_volumes(root=None):
    """内容卷表（过滤 orch 内部保留键）→ {卷名: 相对/绝对路径}。
    Content volume table (internal reserved keys filtered out) → {name: relative/absolute path}."""
    return {k: v for k, v in _volume_table(root).items()
            if k not in RESERVED_KEYS and v}


def content_volumes_from(conf_path, root=None):
    """按指定 conf 文件取内容卷表（conf 目录可与账本根不同）。
    Content volume table from an explicit conf file (its dir may differ from the root)."""
    return {k: v for k, v in _volume_table(root, conf_path=conf_path).items()
            if k not in RESERVED_KEYS and v}


def resolve_volumes(root=None, conf_path=None):
    """解析内部七卷的绝对路径。返回 {角色: 绝对路径, 'root': 绝对根}。
    Resolve absolute paths for the seven internal volumes. Returns {role: abs path, 'root': abs root}."""
    root = resolve_root(root)
    table = _volume_table(root, conf_path=conf_path)
    out = {}
    for role, default in DEFAULT_VOLUMES.items():
        rel = None
        for key in VOLUME_ALIASES[role]:
            if table.get(key):
                rel = table[key]
                break
        if not rel:
            rel = default
        rel = os.path.expanduser(rel)
        out[role] = rel if os.path.isabs(rel) else os.path.join(root, rel)
    out['root'] = root
    return out
