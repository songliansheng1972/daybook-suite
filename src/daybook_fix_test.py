#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook 出厂件回归：conf 卷表白名单 + 作者口径单一来源
daybook factory regressions: volume-table whitelist + single-source author convention
================================================
覆盖两条真机缺陷：
Covers two field defects:
  ③ [volumes] 段里的 locks/audit 等非卷键被当卷读 ⇒ 目录 ⇒ IsADirectoryError
     Non-volume keys (locks/audit) in [volumes] treated as volumes ⇒ directory ⇒ IsADirectoryError
  ④ CLI 与 MCP 写出的条目 author 口径不一致（显示名顶 id 位）
     CLI and MCP disagree on the author convention (display name taking the id slot)

每条都带变异验证：把旧行为放回去，检查必须报红。
Each check carries a mutation: restore the old behaviour and the check must go red.

跑法 / Run: python3 daybook_fix_test.py
退出码 / Exit: 0 = PASS, 1 = FAIL
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import daybook                      # noqa: E402
import daybook_append as dba        # noqa: E402

FAILS = []
CHECKS = [0]

AID = 'ag-0123456789abcdef'

CONF = r"""[volumes]
协作=协作卷.txt
locks=.locks
audit=审计卷.txt
registry=注册卷.txt

[entries]
head_regex=^(?:\[#\d+\][ ]*)?\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)\]
tag_regex=^(?:\[#\d+\][ ]*)?\[\d{4}[^\]]*\][ ]*\[([^\]]+)\][ ]*\[([^\]]*)\](?:[ ]*\[([^\]]*)\])?
fields=volume,line,time,category,title,author

[rules]
category=tag:1
title=tag:2
author=tag:3

[index]
root=
out_dir=idx
index_prefix=index_
manifest=volumes.md

[trigger]
incremental=是
"""

REGISTRY = '[2026-11-01 09:00] [注册] [%s] [汤姆] [密钥文件=.daybook_keys/%s.key]\n' % (AID, AID)


def _ok(name, cond, detail=''):
    CHECKS[0] += 1
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name,
                          (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    if not cond:
        FAILS.append(name)
    return bool(cond)


def _write(path, text):
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _head_tokens(line):
    """取行首连续 [..] 段 · leading bracket tokens."""
    tokens, rest = [], line
    while rest.startswith('['):
        end = rest.find(']')
        if end < 0:
            break
        tokens.append(rest[1:end])
        rest = rest[end + 1:].lstrip(' ')
    return tokens


def _stage_cli(tmp):
    """把被测 daybook.py/safeio.py/daybook_append.py 拷进隔离目录。
    Copy the daybook.py/safeio.py/daybook_append.py under test into an isolated directory."""
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py'):
        shutil.copy2(os.path.join(HERE, name), os.path.join(tmp, name))


# ── ③ 卷表白名单 / 目录型条目 ─────────────────────────────────
def test_volume_whitelist(tmp):
    conf_path = os.path.join(tmp, 'daybook.conf')
    _write(conf_path, CONF)
    conf = daybook.load_conf(conf_path)
    _ok('③1 [volumes] 只留内容卷', set(conf['volumes']) == {'协作'}, str(conf['volumes']))
    _ok('③2 locks/audit/registry 显式跳过并留痕',
        {'locks', 'audit', 'registry'} <= set(conf.get('volumes_skipped', {})),
        str(conf.get('volumes_skipped', {})))

    # 变异：关掉白名单 ⇒ 旧行为复现（locks 被当卷）· mutation: disable the whitelist
    saved = daybook.NON_VOLUME_KEYS
    daybook.NON_VOLUME_KEYS = frozenset()
    try:
        old = daybook.load_conf(conf_path)
        reproduced = 'locks' in old['volumes']
    finally:
        daybook.NON_VOLUME_KEYS = saved
    _ok('③3 变异：无白名单 ⇒ locks 被当卷（旧行为必红）', reproduced)


def test_directory_volume(tmp):
    """目录型条目：build 不得抛 IsADirectoryError，须明确报错。
    A directory entry must not raise IsADirectoryError; it must be reported explicitly."""
    root = os.path.join(tmp, 'work')
    os.makedirs(os.path.join(root, '.locks'))
    conf = {'volumes': {'坏卷': '.locks'},
            'entries': {}, 'rules': {},
            'index': {'out_dir': 'idx', 'index_prefix': 'index_', 'manifest': 'volumes.md'},
            'trigger': {'incremental': '是'}, 'volumes_skipped': {}}
    raised = None
    try:
        per, total, rep = daybook.build(conf, root)
    except Exception as exc:                     # noqa: BLE001 · 这里就是要抓崩溃
        raised = exc
        per, total, rep = {}, 0, []
    _ok('③4 目录型条目不再崩溃', raised is None, repr(raised))
    _ok('③5 明确登记卷配置错误',
        len(daybook.CONFIG_ERRORS) == 1 and '目录' in daybook.CONFIG_ERRORS[0][1],
        str(daybook.CONFIG_ERRORS))

    # CLI 层：rc=2、明确报错、无 traceback
    cli = os.path.join(tmp, 'cli')
    os.makedirs(os.path.join(cli, '.locks'))
    _stage_cli(cli)
    _write(os.path.join(cli, 'daybook.conf'), CONF.replace('协作=协作卷.txt', '坏卷=.locks'))
    r = subprocess.run([sys.executable, 'daybook.py', 'index'], cwd=cli,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    text = (r.stdout or '') + (r.stderr or '')
    _ok('③6 CLI 目录条目 rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
    _ok('③7 CLI 明确报目录·无 Traceback',
        '目录' in text and 'Traceback' not in text, text.splitlines()[-1] if text else '')


# ── ④ 作者口径单一来源 ───────────────────────────────────────
def test_author_source(tmp):
    work = os.path.join(tmp, 'auth')
    os.makedirs(work)
    vol = os.path.join(work, '协作卷.txt')
    _write(vol, '')
    _write(os.path.join(work, '注册卷.txt'), REGISTRY)
    cli = os.path.join(HERE, 'daybook_append.py')

    # CLI 用显示名 ⇒ 落盘必须是注册表 id，显示名只作 [名=…] 附注
    r = subprocess.run([sys.executable, cli, vol, '聊', '第一条', '汤姆', '正文一'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    lines = [l for l in io.open(vol, encoding='utf-8').read().splitlines() if l.startswith('[')]
    tok = _head_tokens(lines[0]) if lines else []
    _ok('④1 CLI 显示名解析为注册表 id', r.returncode == 0 and tok[3:4] == [AID], str(tok))
    _ok('④2 显示名只作 [名=…] 附注', '[名=汤姆]' in (lines[0] if lines else ''))

    # 未注册作者 ⇒ 拒写（不许顶 id 位）
    r = subprocess.run([sys.executable, cli, vol, '聊', '坏作者', '未注册人', '正文'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('④3 未注册作者被拒（rc=2）', r.returncode == 2 and '注册表 id' in (r.stderr or ''),
        'rc=%d' % r.returncode)

    # 同一落盘入口：CLI 与 MCP 两条路径写出的条目头形状一致
    _ok('④4 MCP 侧调用同一入口 append_one',
        '_dba.append_one(' in io.open(os.path.join(HERE, 'mcp_tools.py'),
                                      encoding='utf-8').read())
    mcp_vol = os.path.join(work, 'MCP卷.txt')
    _write(mcp_vol, '')
    dba.append_one(vol, 'MCP', '_', '正文二', author=AID)
    dba.append_one(mcp_vol, 'MCP', '_', '正文二', author=AID)
    shape = r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[[^\]]+\] \[[^\]]*\] \[ag-[0-9a-f]{16}\] '
    import re as _re
    ok_shape = all(_re.match(shape, l) for l in
                   [ll for ll in io.open(vol, encoding='utf-8').read().splitlines() if ll.startswith('[')]
                   + [ll for ll in io.open(mcp_vol, encoding='utf-8').read().splitlines() if ll.startswith('[')])
    _ok('④5 CLI/MCP 条目头同一形状（author=id）', ok_shape)

    ok, detail = dba.check_author_consistency(vol)
    _ok('④6 单一 id 口径 ⇒ 绿', ok, str(detail.get('kinds')))

    # 变异：把旧行为放回去（显示名直接顶作者位）⇒ 机检必红
    with io.open(vol, 'a', encoding='utf-8') as f:
        f.write('[2026-11-14 02:00:00] [聊] [旧口径] [汤姆] 手写旧条目\n\n')
    ok, detail = dba.check_author_consistency(vol)
    _ok('④7 变异：显示名顶 id 位 ⇒ 机检必红',
        (not ok) and set(detail.get('kinds', [])) == {'id', '显示名'}, str(detail.get('kinds')))

    # 机检确实由分类器驱动（把它阉掉，红转绿 ⇒ 证明判据不是摆设）
    saved = dba.classify_author
    dba.classify_author = lambda a: 'id'
    try:
        neutered, _detail = dba.check_author_consistency(vol)
    finally:
        dba.classify_author = saved
    _ok('④8 变异：阉掉分类器 ⇒ 红消失（判据可被反证）', neutered)

    # index 集成：口径混用 ⇒ 报红退出 4
    cli_dir = os.path.join(tmp, 'auth_cli')
    os.makedirs(cli_dir)
    _stage_cli(cli_dir)
    _write(os.path.join(cli_dir, 'daybook.conf'), CONF)
    shutil.copy2(vol, os.path.join(cli_dir, '协作卷.txt'))
    r = subprocess.run([sys.executable, 'daybook.py', 'index'], cwd=cli_dir,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('④9 index 集成：作者口径混用 rc=4', r.returncode == 4, 'rc=%d' % r.returncode)


def main():
    tmp = tempfile.mkdtemp(prefix='daybook_fix_')
    try:
        print('=== daybook 出厂件回归（conf 白名单 / 作者口径）· factory regressions ===')
        test_volume_whitelist(tmp)
        test_directory_volume(tmp)
        test_author_source(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('  共 %d 项，FAIL %d 项' % (CHECKS[0], len(FAILS)))
    if FAILS:
        print('  FAIL: %s' % '、'.join(FAILS))
        return 1
    print('  PASS: 白名单与作者口径回归全绿 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
