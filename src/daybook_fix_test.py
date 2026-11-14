#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook 出厂件回归：conf 卷表键值双条件 + 作者口径（显示名/id 附注）
daybook factory regressions: volume-table key+value criterion + author convention (display name / id annotation)
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
task=我的任务.txt
locks=.locks
audit=.audit
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


def _stage_cli(tmp):
    """把被测 daybook.py/safeio.py/daybook_append.py 拷进隔离目录。
    Copy the daybook.py/safeio.py/daybook_append.py under test into an isolated directory."""
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py'):
        shutil.copy2(os.path.join(HERE, name), os.path.join(tmp, name))


# ── ③ 卷表键值双条件 / 目录型条目 ─────────────────────────────
def test_volume_whitelist(tmp):
    # 真实布局：内容卷是真文件（哪怕键名叫 task/registry），锁/审计是目录
    # Real layout: content volumes are real files (even keyed task/registry); locks/audit are dirs
    root = os.path.join(tmp, 'confroot')
    os.makedirs(root)
    for name in ('协作卷.txt', '我的任务.txt', '注册卷.txt'):
        _write(os.path.join(root, name), '')
    os.makedirs(os.path.join(root, '.locks'))
    os.makedirs(os.path.join(root, '.audit'))
    conf_path = os.path.join(root, 'daybook.conf')
    _write(conf_path, CONF)
    conf = daybook.load_conf(conf_path)
    _ok('③1 合法内容卷不因键名被吞（task 指向用户自己的文件）',
        set(conf['volumes']) == {'协作', 'task'}, str(conf['volumes']))
    _ok('③2 内部卷/目录型非卷键不进索引面，且留痕',
        set(conf.get('volumes_skipped', {})) == {'locks', 'audit', 'registry'},
        str(conf.get('volumes_skipped', {})))
    _ok('③2b 跳过理由写明「内部卷」或「目录」',
        all(('内部卷' in v.get('reason', '')) or ('目录' in v.get('reason', ''))
            for v in conf['volumes_skipped'].values()))
    _ok('③2c 内部卷仍在 _files 备份面',
        set(conf.get('_files', {})) == {'协作', 'task', 'registry'}, str(conf.get('_files')))

    # 变异：退回「只按键名」的旧白名单 ⇒ 合法卷 task 被吞（旧行为必红）
    # Mutation: restore name-only skipping ⇒ the legitimate `task` volume is swallowed
    saved = daybook._skip_non_volume
    daybook._skip_non_volume = lambda k, v, b: ('旧键名白名单' if k in daybook.NON_VOLUME_KEYS else None)
    try:
        old = daybook.load_conf(conf_path)
        reproduced = 'task' not in old['volumes']
    finally:
        daybook._skip_non_volume = saved
    _ok('③3 变异：只按键名 ⇒ task 被吞（旧行为必红）', reproduced, str(old['volumes']))


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
    _write(os.path.join(cli, 'daybook.conf'),
           CONF.replace('协作=协作卷.txt', '坏卷=.locks')
               .replace('task=我的任务.txt\n', '')
               .replace('registry=注册卷.txt\n', ''))
    r = subprocess.run([sys.executable, 'daybook.py', 'index'], cwd=cli,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    text = (r.stdout or '') + (r.stderr or '')
    _ok('③6 CLI 目录条目 rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
    _ok('③7 CLI 明确报目录·无 Traceback',
        '目录' in text and 'Traceback' not in text, text.splitlines()[-1] if text else '')


# ── ⑤ 无 conf 时的用法/未知子命令（不得 traceback）────────────
def test_help_without_conf(tmp):
    d = os.path.join(tmp, 'noconf')
    os.makedirs(d)
    _stage_cli(d)                      # 故意不放 daybook.conf · deliberately no daybook.conf

    r = subprocess.run([sys.executable, 'daybook.py', '--help'], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    text = (r.stdout or '') + (r.stderr or '')
    _ok('⑤1 无 conf 跑 --help ⇒ rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
    _ok('⑤2 无 conf 跑 --help 无 Traceback', 'Traceback' not in text and 'FileNotFoundError' not in text)

    r = subprocess.run([sys.executable, 'daybook.py', '不存在的子命令'], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    text = (r.stdout or '') + (r.stderr or '')
    _ok('⑤3 未知子命令 ⇒ rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
    _ok('⑤4 未知子命令无 Traceback', 'Traceback' not in text and '未知子命令' in text)

    # 变异：旧顺序（先 load_conf 再分派）在同一目录必红——证明本用例挡得住旧实现
    # Mutation: the old order (load_conf before dispatch) must go red here, proving this case bites
    r = subprocess.run([sys.executable, '-c', 'import daybook; daybook.load_conf()'], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('⑤5 变异：先 load_conf 的旧顺序必红',
        r.returncode != 0 and 'Error' in (r.stderr or ''), 'rc=%d' % r.returncode)


# ── ⑥ backup：out_dir 为空时不得把整根复制进备份 ────────────────
def test_backup_empty_outdir(tmp):
    root = os.path.join(tmp, 'bk')
    os.makedirs(root)
    _write(os.path.join(root, '账卷.txt'), '[2026-11-14 03:00:00] [聊] [一] [汤姆] 正文\n\n')
    _write(os.path.join(root, '旁件.txt'), '不该被备份的根目录文件\n')
    _write(os.path.join(root, 'index_账.tsv'), 'volume\tline\n')
    _write(os.path.join(root, '.cursor_账.json'), '{"fmt":2}\n')
    conf = {'volumes': {'账': '账卷.txt'}, 'entries': {}, 'rules': {},
            'index': {'out_dir': '', 'index_prefix': 'index_', 'manifest': 'volumes.md'},
            'trigger': {}, 'volumes_skipped': {}}
    bdir, n = daybook.backup(conf, root)
    names = set()
    for d, _dirs, files in os.walk(bdir):
        for f in files:
            names.add(os.path.relpath(os.path.join(d, f), bdir))
    _ok('⑥1 out_dir 为空：卷被备份', '账卷.txt' in names, str(names))
    _ok('⑥2 out_dir 为空：整根未被复制', '旁件.txt' not in names and n == 1, str(names))
    _ok('⑥3 out_dir 为空：已知索引件一并备份',
        'index_账.tsv' in names and '.cursor_账.json' in names, str(names))


# ── ⑦ 无 --home 时不得隐式改 ~/.daybook ──────────────────────
def test_no_implicit_home(tmp):
    shim = os.path.join(os.path.dirname(HERE), 'packaging', 'cli_shim.py')
    if not os.path.exists(shim):
        _ok('⑦0 packaging/cli_shim.py 存在', False, shim)
        return
    d = os.path.join(tmp, 'nohome')
    os.makedirs(d)
    env = {k: v for k, v in os.environ.items() if k != 'DAYBOOK_HOME'}
    r = subprocess.run([sys.executable, shim, 'index'], cwd=d, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    text = (r.stdout or '') + (r.stderr or '')
    _ok('⑦1 无 --home/无 DAYBOOK_HOME ⇒ rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
    _ok('⑦2 明确要求显式指定，不静默落 ~/.daybook',
        '--home' in text and '~/.daybook' in text, text.strip()[:120])


# ── ⑧ 索引面 vs 备份面：内部卷只备份不索引 ─────────────────────
def test_backup_surface(tmp):
    root = os.path.join(tmp, 'surface')
    os.makedirs(root)
    for name in ('协作卷.txt', '注册卷.txt', '编排卷.txt'):
        _write(os.path.join(root, name), '')
    _write(os.path.join(root, 'daybook.conf'),
           '[volumes]\n协作=协作卷.txt\nregistry=注册卷.txt\nledger=编排卷.txt\n')
    conf = daybook.load_conf(os.path.join(root, 'daybook.conf'))
    _ok('⑧1 索引面只认内容卷', set(conf['volumes']) == {'协作'}, str(conf['volumes']))
    _ok('⑧2 备份面含内部卷', set(conf['_files']) == {'协作', 'registry', 'ledger'},
        str(conf['_files']))
    bdir, n = daybook.backup(conf, root)
    got = sorted(os.listdir(bdir))
    _ok('⑧3 backup 实备 3 卷', n == 3 and got == ['协作卷.txt', '注册卷.txt', '编排卷.txt'], str(got))


# ── ⑨ pack：运行时残留/系统垃圾不进扫描面，陌生文件仍硬拒 ────────
def test_pack_residue(tmp):
    import pack as _pack
    dest = os.path.join(tmp, 'box')
    os.makedirs(os.path.join(dest, 'sub'))
    for name in ('任务卷.txt', '心跳卷.txt', '.DS_Store'):
        _write(os.path.join(dest, name), '')
    _write(os.path.join(dest, 'sub', '.DS_Store'), '')
    _write(os.path.join(dest, '陌生.txt'), '不该被放过\n')
    extra = _pack.foreign_files(dest, [(os.path.join(HERE, 'pack.py'), 'pack.py')])
    _ok('⑨1 运行时残留/系统垃圾不进扫描面', '任务卷.txt' not in extra and '.DS_Store' not in extra,
        str(extra))
    _ok('⑨2 陌生文件仍硬拒', extra == ['陌生.txt'], str(extra))


# ── ⑩ hook：条头附注段不得让整条静默跳过 ───────────────────────
def test_hook_parse(tmp):
    import daybook_hook
    d = os.path.join(tmp, 'hook')
    os.makedirs(d)
    dialog = os.path.join(d, '对话卷.txt')
    line = ('[2026-11-14 05:00:00] [对话] [标题甲] [汤姆] [id=%s] [未注册] '
            '对话原件/x.txt\nSHA256: abc\n' % AID)
    _write(dialog, line)
    blocks = daybook_hook.parse_dialog(dialog, d)
    _ok('⑩1 带 [id=…] 附注的条目仍被解析', len(blocks) == 1 and blocks[0][2] is not None,
        str(blocks[0][2] if blocks else None))
    meta = blocks[0][2] if blocks else ('', '', '', '')
    _ok('⑩2 类/标题/作者/原件路径均不错位',
        meta[0] == '对话' and meta[1] == '标题甲' and meta[2] == '汤姆' and meta[3] == '对话原件/x.txt',
        str(meta))
    # 变异：旧正则（作者后只能紧跟原件路径）在同一行必不匹配 —— 证明旧实现会静默丢条
    import re as _re
    old_re = _re.compile(r'^\[[^\]]+\]\s*\[([^\]]+)\]\s*\[([^\]]*)\](?:\s*\[([^\]]*)\])?\s*(对话原件/[^\s]+\.txt)')
    _ok('⑩3 变异：旧正则必不匹配（静默丢条可复现）', old_re.match(line) is None)
    # ⑩4/⑩5 端到端：钩子追更必须把源条目的 [id=ag-…] 附注带到目标卷（作者位仍只写显示名）
    # End to end: the hook must carry the source [id=ag-…] annotation into the target volume,
    # while the author slot keeps the display name.
    os.makedirs(os.path.join(d, '对话原件'))
    _write(os.path.join(d, '对话原件', 'x.txt'), '这条要 决定 一件事。')
    kw = os.path.join(d, 'kw.txt')
    _write(kw, '[目标] [追更] 决定\n')
    daybook_hook.run(dialog, kw, root=d)
    target = io.open(os.path.join(d, '目标卷.txt'), encoding='utf-8').read()
    _ok('⑩4 钩子追更条目带 [id=] 附注', '[汤姆]' in target and ('[id=%s]' % AID) in target,
        target[:160])
    _ok('⑩5 作者位仍是显示名（机器 id 只在附注）',
        ('[%s]' % AID) not in target.replace('[id=%s]' % AID, ''), target[:160])
    _ok('⑩6 [未注册] 标记原样传播（不得洗成确定作者）', '[未注册]' in target, target[:160])


# ── ⑪ 退出码口径写进 --help ──────────────────────────────────
def test_help_exit_codes(tmp):
    d = os.path.join(tmp, 'helpdoc')
    os.makedirs(d)
    _stage_cli(d)
    r = subprocess.run([sys.executable, 'daybook.py', '--help'], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    text = (r.stdout or '') + (r.stderr or '')
    _ok('⑪1 --help 写明退出码 0/2/3/4/5',
        all(('\n  %s ' % c) in text or ('  %s ' % c) in text for c in ('0', '2', '3', '4', '5'))
        and '退出码' in text, text[:80])
    _ok('⑪2 --help 写明「取最严重」而非位掩码',
        '严重度' in text and '违例' in text, '')


# ── ⑫ CLI 后门收口：作者必填、无 --name= ─────────────────────
def test_author_cli_backdoor(tmp):
    d = os.path.join(tmp, 'backdoor')
    os.makedirs(d)
    vol = os.path.join(d, '卷.txt')
    _write(vol, '')
    cli = os.path.join(HERE, 'daybook_append.py')
    r = subprocess.run([sys.executable, cli, vol, '聊', '标题', '正文四参'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('⑫1 4 参形态（默认未标）被拒 rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
    r = subprocess.run([sys.executable, cli, vol, '聊', '标题', '未标', '正文'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('⑫2 显式「未标」占位被拒 rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
    r = subprocess.run([sys.executable, cli, vol, '聊', '标题', '汤姆', '正文', '--name=别人'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('⑫3 --name= 后门被拒 rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
    _ok('⑫4 三次拒写都没落条目', io.open(vol, encoding='utf-8').read().strip() == '')
    # 独立模式（无注册表）也拒机器 id：作者位只许显示名
    # Standalone mode (no registry) also refuses a machine id: the author slot is a display name only
    iso = os.path.join(d, '独立')
    os.makedirs(iso)
    ivol = os.path.join(iso, '卷.txt')
    _write(ivol, '')
    r = subprocess.run([sys.executable, cli, ivol, '聊', '标题', AID, '正文'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('⑫5 独立模式拒机器 id（rc=2）', r.returncode == 2, 'rc=%d' % r.returncode)


# ── ④ 作者口径（作者位＝显示名·id 只作附注）────────────────────
def test_author_source(tmp):
    work = os.path.join(tmp, 'auth')
    os.makedirs(work)
    vol = os.path.join(work, '协作卷.txt')
    _write(vol, '')
    _write(os.path.join(work, '注册卷.txt'), REGISTRY)
    cli = os.path.join(HERE, 'daybook_append.py')

    # 注册过的显示名 ⇒ 作者位仍是显示名，id 只作 [id=ag-…] 附注
    r = subprocess.run([sys.executable, cli, vol, '聊', '第一条', '汤姆', '正文一'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    lines = [l for l in io.open(vol, encoding='utf-8').read().splitlines() if l.startswith('[')]
    tok = dba._head_tokens(lines[0]) if lines else []
    _ok('④1 作者位写显示名', r.returncode == 0 and tok[3:4] == ['汤姆'], str(tok))
    _ok('④2 注册表 id 降为 [id=…] 附注', '[id=%s]' % AID in (lines[0] if lines else ''))
    _ok('④2b 不再出现 [名=…]', '[名=' not in (lines[0] if lines else ''))

    # 未注册作者 ⇒ 允许写入，stderr 警告，附注 [未注册]
    r = subprocess.run([sys.executable, cli, vol, '聊', '未注册', '未注册人', '正文'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    lines = [l for l in io.open(vol, encoding='utf-8').read().splitlines() if l.startswith('[')]
    tok = dba._head_tokens(lines[-1]) if lines else []
    _ok('④3 未注册名允许写入（rc=0）', r.returncode == 0, 'rc=%d' % r.returncode)
    _ok('④3b stderr 有未注册警告', '未注册' in (r.stderr or ''))
    _ok('④3c 附注标 [未注册]', '[未注册]' in (lines[-1] if lines else ''))
    _ok('④3d 作者位是未注册名', tok[3:4] == ['未注册人'], str(tok))

    # 未注册的机器 id ⇒ 拒写（作者位不许出现 id，且无法反查显示名）
    r = subprocess.run([sys.executable, cli, vol, '聊', '坏id', 'ag-ffffffffffffffff', '正文'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('④3e 未注册机器 id 被拒（rc=2）', r.returncode == 2, 'rc=%d' % r.returncode)

    # 同一落盘入口：CLI 与 MCP 两条路径写出的条目头形状一致
    _ok('④4 MCP 侧调用同一入口 append_one',
        '_dba.append_one(' in io.open(os.path.join(HERE, 'mcp_tools.py'),
                                      encoding='utf-8').read())
    mcp_vol = os.path.join(work, 'MCP卷.txt')
    _write(mcp_vol, '')
    dba.append_one(vol, 'MCP', '_', '正文二', author='汤姆', author_id=AID)
    dba.append_one(mcp_vol, 'MCP', '_', '正文二', author='汤姆', author_id=AID)
    shape = r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[[^\]]+\] \[[^\]]*\] \[汤姆\] \[id=ag-[0-9a-f]{16}\] '
    import re as _re
    ok_shape = all(_re.match(shape, l) for l in
                   [ll for ll in io.open(vol, encoding='utf-8').read().splitlines()
                    if ll.startswith('[') and '[MCP]' in ll]
                   + [ll for ll in io.open(mcp_vol, encoding='utf-8').read().splitlines() if ll.startswith('[')])
    _ok('④5 CLI/MCP 条目头同一形状（作者=显示名·id 附注）', ok_shape)

    ok, detail = dba.check_author_consistency(vol)
    _ok('④6 显示名口径 ⇒ 绿', ok, str(detail.get('kinds')))

    # 正文行里的 [注][甲][乙][老宋] 不是条目（head_regex 锚定）
    with io.open(vol, 'a', encoding='utf-8') as f:
        f.write('[注] [甲] [乙] [老宋] 这是正文里的一行，不是条目\n\n')
    ok, detail = dba.check_author_consistency(vol)
    _ok('④6b 正文假条目不得被算进去', ok and '老宋' not in str(detail.get('samples')),
        str(detail.get('kinds')))

    # 旧三段条目 + 正文 [致=…] 不得被当成作者位
    with io.open(vol, 'a', encoding='utf-8') as f:
        f.write('[2026-11-14 01:00:00] [聊] [旧三段] [致=汤姆] 旧格式正文\n\n')
    ok, detail = dba.check_author_consistency(vol)
    _ok('④6c 旧三段 [致=…] 不被当作者', ok, str(detail.get('kinds')))

    # 变异：作者位放机器 id ⇒ 必红（判据与上一轮相反）
    red_vol = os.path.join(work, '机器id卷.txt')
    _write(red_vol, '[2026-11-14 02:00:00] [聊] [旧口径] [%s] 手写旧条目\n\n' % AID)
    ok, detail = dba.check_author_consistency(red_vol)
    _ok('④7 变异：作者位出现 ag-… ⇒ 必红',
        (not ok) and '机器id' in detail.get('kinds', []), str(detail.get('kinds')))

    # 机检确实由分类器驱动（把它阉掉，红转绿 ⇒ 证明判据不是摆设）
    saved = dba.classify_author
    dba.classify_author = lambda a: '显示名'
    try:
        neutered, _detail = dba.check_author_consistency(red_vol)
    finally:
        dba.classify_author = saved
    _ok('④8 变异：阉掉分类器 ⇒ 红消失（判据可被反证）', neutered)

    # 配置卷不存在 ⇒ 不得报「无条目」全绿
    conf_missing = {'volumes': {'不在': '不存在的卷.txt'}, 'entries': {}, 'rules': {},
                    'index': {}, 'trigger': {}, 'volumes_skipped': {}}
    rows = daybook.check_authors(conf_missing, work)
    _ok('④9 配置卷不存在 ⇒ 报红', rows and not rows[0][2] and '卷缺失' in rows[0][3]['kinds'],
        str(rows[0][3].get('kinds') if rows else rows))

    # index 集成：机器 id 混入 ⇒ 报红退出 4
    cli_dir = os.path.join(tmp, 'auth_cli')
    os.makedirs(cli_dir)
    _stage_cli(cli_dir)
    _write(os.path.join(cli_dir, 'daybook.conf'), CONF)
    shutil.copy2(red_vol, os.path.join(cli_dir, '协作卷.txt'))
    r = subprocess.run([sys.executable, 'daybook.py', 'index'], cwd=cli_dir,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('④10 index 集成：作者位机器 id ⇒ rc=4', r.returncode == 4, 'rc=%d' % r.returncode)


# ── ⑬ 入口壳并发补链：6 进程同时对空运行目录首启，必须全 rc=0 ──
def test_entry_shell_concurrency(tmp):
    import time
    src_shim = os.path.join(os.path.dirname(HERE), 'packaging', 'cli_shim.py')
    if not os.path.exists(src_shim):
        _ok('⑬0 packaging/cli_shim.py 存在', False, src_shim)
        return
    base = os.path.join(tmp, 'shell')
    text = io.open(src_shim, encoding='utf-8').read()
    text = text.replace('@@DIST@@', 'daybook').replace('@@CMD@@', 'daybook').replace('@@ENTRY@@', 'entry.py')

    def mk_payload(tag, content):
        d = os.path.join(base, tag)
        payload = os.path.join(d, 'payload')
        os.makedirs(os.path.join(payload, 'sample'))
        _write(os.path.join(payload, 'daybook.conf'), '[index]\nroot=\n')
        _write(os.path.join(payload, 'sample', 'x.txt'), 'x\n')
        _write(os.path.join(payload, 'entry.py'), "print('ok')\n")
        for i in range(400):
            _write(os.path.join(payload, 'mod%03d.py' % i), content)
        shim = os.path.join(d, 'shim.py')
        _write(shim, text)
        return shim, payload

    shim_mcp, payload_mcp = mk_payload('mcp', '# MCP\n')
    shim_cli, payload_cli = mk_payload('cli', '# CLI\n')
    launcher = os.path.join(base, 'launch.py')
    _write(launcher, (
        "import os, sys, time, runpy\n"
        "shim, home, barrier = sys.argv[1], sys.argv[2], sys.argv[3]\n"
        "mod = runpy.run_path(shim, run_name='shimmod')\n"
        "while not os.path.exists(barrier):\n"
        "    time.sleep(0.001)\n"
        "sys.argv = [shim, '--home=' + home]\n"
        "sys.exit(mod['main']())\n"))
    # 真实次序：先跑一次 mcp 入口（home 里已有一整套指向 mcp payload 的链），
    # 再并发多个 CLI 入口——reassign 分支会改指；旧实现 os.remove 撞上别人已删即 rc=1。
    # The real sequence: run the mcp entry once (the home already links the mcp payload),
    # then start several CLI entries concurrently — reassign repoints them, and the old
    # implementation's os.remove hit a link another process had already removed ⇒ rc=1.
    all_rcs, all_outs = [], []
    home = os.path.join(base, 'home')
    for rnd in range(2):
        home = os.path.join(base, 'home%d' % rnd)
        flag0 = os.path.join(base, 'mcp.flag%d' % rnd)
        p0 = subprocess.Popen([sys.executable, '-B', launcher, shim_mcp, home, flag0],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
        time.sleep(0.05)
        io.open(flag0, 'w').write('1')
        o0, e0 = p0.communicate()
        all_outs.append((o0 or '', e0 or ''))
        all_rcs.append(p0.returncode)
        barrier = os.path.join(base, 'go%d.flag' % rnd)
        procs = [subprocess.Popen([sys.executable, '-B', launcher, shim_cli, home, barrier],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True) for _ in range(8)]
        time.sleep(0.2)
        io.open(barrier, 'w').write('1')
        outs = [p.communicate() for p in procs]
        all_outs.extend(outs)
        all_rcs.extend(p.returncode for p in procs)
    # 第三轮：home 内预置指向 /nowhere 的错误软链，8 进程并发改指（无旧链可删的路径不走，
    # 这条专门打「先删后建」的空窗与 FileNotFoundError）。
    # Third round: pre-place broken links to /nowhere, then 8 concurrent repoints — this kills
    # the remove→symlink window and the FileNotFoundError branch.
    home = os.path.join(base, 'home_bad')
    os.makedirs(home)
    for i in range(400):
        os.symlink('/nowhere', os.path.join(home, 'mod%03d.py' % i))
    os.symlink('/nowhere', os.path.join(home, 'entry.py'))
    barrier = os.path.join(base, 'go_bad.flag')
    procs = [subprocess.Popen([sys.executable, '-B', launcher, shim_cli, home, barrier],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True) for _ in range(8)]
    time.sleep(0.2)
    io.open(barrier, 'w').write('1')
    outs = [p.communicate() for p in procs]
    all_outs.extend(outs)
    all_rcs.extend(p.returncode for p in procs)
    bad = [(rc, (o + e).strip().splitlines()[-1:] or [''])
           for (o, e), rc in zip(all_outs, all_rcs) if rc != 0]
    _ok('⑬1 先 mcp 后 8 进程×2 轮并发 CLI 全 rc=0（改指不互相踩）', not bad,
        '非零=%s' % bad[:4])
    _ok('⑬2 无 Traceback', not any('Traceback' in (o + e) for o, e in all_outs))
    _ok('⑬3 conf/sample 就位', os.path.isfile(os.path.join(home, 'daybook.conf'))
        and os.path.isdir(os.path.join(home, 'sample')))
    _ok('⑬4 产品件已改指到 CLI payload',
        os.path.islink(os.path.join(home, 'mod000.py'))
        and os.path.realpath(os.path.join(home, 'mod000.py')).startswith(
            os.path.realpath(payload_cli)))
    _ok('⑬5 无残留临时件',
        not [n for n in os.listdir(home) if n.startswith('.daybook.')])


def main():
    tmp = tempfile.mkdtemp(prefix='daybook_fix_')
    try:
        print('=== daybook 出厂件回归（conf 白名单 / 作者口径）· factory regressions ===')
        test_volume_whitelist(tmp)
        test_directory_volume(tmp)
        test_help_without_conf(tmp)
        test_backup_empty_outdir(tmp)
        test_no_implicit_home(tmp)
        test_backup_surface(tmp)
        test_pack_residue(tmp)
        test_hook_parse(tmp)
        test_help_exit_codes(tmp)
        test_author_cli_backdoor(tmp)
        test_author_source(tmp)
        test_entry_shell_concurrency(tmp)
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
