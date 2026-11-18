#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook.conf 归一与解析的唯一实现（零依赖）
The single implementation of daybook.conf normalisation and parsing (zero dependencies)
================================================
**本件不许 import 本仓任何模块**：完整包（daybook）与独立包（daybook-orch）原样带同一份。
归一表、归一函数、行解析都只在这里；两个包的结构性分叉因此不可能发生。
This module imports nothing from this repo: the full package and the standalone daybook-orch
package ship this very file. One alias table, one parser — structural divergence is impossible.

归一（认对）：节名/键名 `strip()` + `lower()` + 中文别名表（`[volumes]` 的键是卷名，
保留大小写，只 `strip()`）。所以 `[索引]`、`[Index]`、`[ index ]`、`[INDEX]` 都是 `index`。
Normalisation (recognise correctly): section/key names are `strip()` + `lower()` + Chinese alias
table (keys under `[volumes]` are volume names and keep their case; only `strip()` is applied).
So `[索引]`, `[Index]`, `[ index ]` and `[INDEX]` all become `index`.

报错（认错时说真话）：归一后仍不是认得的节名 ⇒ `ConfError`（调用方转 rc=2）；
文件里有非注释内容却零可识别节/键 ⇒ `ConfError`。
Errors (tell the truth when unrecognised): a section still unknown after normalisation raises
`ConfError` (callers map it to rc=2); content with no recognisable section/key raises too.

坏 conf 不等于空账本：绝不把「配置写错了」降级成「没配置」。
A bad conf is never an empty ledger: "misconfigured" must not degrade into "unconfigured".
"""

# ── 别名表（英文为准·中文兼容）· the one alias table ──
SEC_ALIAS = {
    '卷': 'volumes', '条目': 'entries', '规则': 'rules', '索引': 'index',
    '触发': 'trigger', '多级': 'multilevel', '钩子': 'hooks',
}
KEY_ALIAS = {
    '头正则': 'head_regex', '附头正则': 'extra_head_regex', '标正则': 'tag_regex',
    '字段': 'fields', '根': 'root', '输出目录': 'out_dir', '索引前缀': 'index_prefix',
    '清单名': 'manifest', '自动索引': 'auto_index', '增量索引': 'incremental',
    '多级索引': 'multilevel_enabled', '二级键': 'level2_field', '变动令': 'on_change',
    '类': 'category', '标题': 'title', '作者': 'author',
}
FIELD_ALIAS = {
    '卷': 'volume', '行号': 'line', '时间': 'time',
    '类': 'category', '标题': 'title', '作者': 'author',
}

# 认得的节名（归一后）。归一负责认对；这里负责「认不出就报」。
# Recognised section names (post-normalisation). Normalisation recognises; this set reports.
KNOWN_SECTIONS = frozenset((
    'volumes', 'entries', 'rules', 'index', 'trigger', 'multilevel', 'hooks',
))


class ConfError(Exception):
    """conf 归一/解析失败（零依赖异常；调用方转成自己的 ConfigError）。
    Conf normalisation/parse failure (zero-dependency; callers translate it to their ConfigError)."""


def canon_sec(name):
    """节名归一：strip + lower + 中文别名。Canonical section name."""
    s = str(name).strip().lower()
    return SEC_ALIAS.get(s, s)


def canon_key(name):
    """键名归一：strip + lower + 中文别名。Canonical key name."""
    s = str(name).strip().lower()
    return KEY_ALIAS.get(s, s)


def canon_field(name):
    """字段名归一：strip + lower + 中文别名（含内置三字段）。Canonical field name."""
    s = str(name).strip().lower()
    return FIELD_ALIAS.get(s, s)


def parse_text(text):
    """conf 文本 → (sections, content, parsed)。认不出就抛 ConfError。
    Parse conf text → (sections, content, parsed). Raise ConfError when unrecognisable.

    `content` = 非空且非 `#` 注释的行数；`parsed` = 被认作 `[节]` 或 `键=值` 的行数。
    content = lines that are neither blank nor `#` comments; parsed = lines understood as a
    `[section]` or `key=value`."""
    sections = {}
    sec = None
    content = 0
    parsed = 0
    for no, line in enumerate(text.splitlines(), 1):
        if no == 1:
            line = line.lstrip('\ufeff')      # BOM 不是内容 / a BOM is not content
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        content += 1
        if stripped.startswith('[') and stripped.endswith(']'):
            inner = stripped[1:-1].strip()
            if not inner:
                raise ConfError('daybook.conf 第 %d 行：空节名 []；节名不能留空' % no)
            name = canon_sec(inner)
            if name not in KNOWN_SECTIONS:
                raise ConfError(
                    'daybook.conf 第 %d 行：无法识别的节名 [%s]（归一后 %r）；认得的节：%s'
                    % (no, inner, name, ', '.join(sorted(KNOWN_SECTIONS))))
            sec = name
            sections.setdefault(sec, {})
            parsed += 1
            continue
        if sec and '=' in line:
            k, v = line.split('=', 1)
            # 卷名是用户标识符（大小写敏感）：只 strip，不 lower/别名。
            # Volume names are user identifiers (case-sensitive): strip only, no lower/alias.
            k = k.strip() if sec == 'volumes' else canon_key(k)
            if not k:
                continue                       # 空键认不出，不计入 parsed
            v = v.strip()
            if k == 'fields':
                v = ','.join(canon_field(x) for x in v.split(','))
            sections[sec][k] = v
            parsed += 1
    if content and not parsed:
        raise ConfError(
            'daybook.conf 整份无法解析：有 %d 行非注释内容，却没有可识别的 [节] 或 键=值；'
            '坏 conf 不等于空账本' % content)
    return sections, content, parsed
