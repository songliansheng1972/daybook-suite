#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P7 · 非零退出零落盘（属性层·**采样**）
P7 · zero writes on a non-zero exit (property layer, **sampling**)
================================================
rc=2（配置错）、3（违例）、5（证据缺失）都不得改动账本目录：递归内容、inode、mtime
全不变。本层是**采样**，不是「每个可写入口各测一次」的全覆盖声明：
  已采样：daybook.py index（2/3）、daybook_record.record（3/5）、
          daybook_append.append_one（2）、daybook_session_hook watch（3）、
          daybook_hook（6）、orchestrator alarm（3）
  未采样：orchestrator join/open/log、daybook_multidx、mcp_server。
          join/open 的失败面是参数/锁而非账本判据；multidx 是从卷重算的派生视图，
          不跑 append-only 闸（同一份被改写卷它仍 rc=0 重建 multilevel/），本层不替它声明；
          mcp_server 是协议型长驻入口（单次故障映射为响应），由 P6 的代码路径推导。
The layer **samples**; it does not claim "one test per writable entry". It covers index (2/3),
record (3/5), append (2), session-hook (3), daybook_hook (6), orchestrator alarm (3). It does not
sample orchestrator join/open/log (their failure surface is args/locks, not the ledger predicate),
daybook_multidx (a derived-view rebuild that does not run the append-only gate), or mcp_server
(protocol server; P6 derives its mapping). `cross_ref.py` has no write primitive.
"""
import io
import json
import os
import shutil
import subprocess
import sys

import common
from common import check

PY = sys.executable


def _same(name, tmp, before, r, expect):
    after = common.snapshot(tmp)
    check(name, r.returncode == expect and before == after,
          'rc=%d 期望=%d diff=%r' % (r.returncode, expect,
                                     common.diff_snap(before, after)[:5]))


def run(seed=7, mode='const'):
    print('  -- P7 非零退出零落盘（采样·seed=%d mode=%s） --' % (seed, mode))
    # 1) daybook.py index：rc=2（卷配成目录）
    with common.tmpdir('p7a_') as tmp:
        common.make_ledger(tmp)
        common.run_entry(tmp, ['baseline'])
        common.run_entry(tmp, ['index'])
        os.makedirs(os.path.join(tmp, '坏卷目录'))
        conf = os.path.join(tmp, 'daybook.conf')
        text = io.open(conf, encoding='utf-8').read()
        io.open(conf, 'w', encoding='utf-8').write(
            text.replace('账=账卷.txt', '账=坏卷目录'))
        before = common.snapshot(tmp)
        _same('P7 daybook index rc=2：账本目录零变化（内容/inode/mtime）',
              tmp, before, common.run_entry(tmp, ['index']), 2)

    # 2) daybook.py index：rc=3（等长改写）
    with common.tmpdir('p7b_') as tmp:
        common.make_ledger(tmp)
        common.run_entry(tmp, ['baseline'])
        common.run_entry(tmp, ['index'])
        common.tamper_mid(os.path.join(tmp, '账卷.txt'))
        before = common.snapshot(tmp)
        _same('P7 daybook index rc=3：账本目录零变化（内容/inode/mtime）',
              tmp, before, common.run_entry(tmp, ['index']), 3)

    # 3) record：rc=3（违例）——旧实现先落原件与登记，再让 index 子进程报 3
    with common.tmpdir('p7c_') as tmp:
        common.make_ledger(tmp)
        common.run_entry(tmp, ['baseline'])
        common.run_entry(tmp, ['index'])
        common.tamper_mid(os.path.join(tmp, '账卷.txt'))
        before = common.snapshot(tmp)
        r = subprocess.run([PY, '-B', 'daybook_record.py', '--role', '用户'],
                           cwd=tmp, input='不得落盘\n', stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
        _same('P7 record rc=3：先判后写·账本目录零变化', tmp, before, r, 3)

    # 4) record：rc=5（证据缺失）——同样零落盘
    with common.tmpdir('p7d_') as tmp:
        common.make_ledger(tmp)
        before = common.snapshot(tmp)
        r = subprocess.run([PY, '-B', 'daybook_record.py', '--role', '用户'],
                           cwd=tmp, input='不得落盘\n', stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
        _same('P7 record rc=5：证据缺失·账本目录零变化', tmp, before, r, 5)

    # 5) append_one：rc=2（卷配成目录）
    with common.tmpdir('p7e_') as tmp:
        common.make_ledger(tmp)
        os.makedirs(os.path.join(tmp, '目录卷.txt'))
        before = common.snapshot(tmp)
        r = subprocess.run([PY, '-B', 'daybook_append.py', '--home', tmp,
                            '目录卷.txt', '测试', '标题', '皮特', '正文'],
                           cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        _same('P7 append rc=2（卷配成目录）：账本目录零变化', tmp, before, r, 2)

    # 6) session hook：rc=3（经由 record 的违例）——state 也不得写
    with common.tmpdir('p7f_') as tmp:
        common.make_ledger(tmp)
        common.run_entry(tmp, ['baseline'])
        common.run_entry(tmp, ['index'])
        common.tamper_mid(os.path.join(tmp, '账卷.txt'))
        shutil.copy2(os.path.join(common.SRC, 'daybook_session_hook.py'), tmp)
        ev = os.path.join(os.path.dirname(tmp), os.path.basename(tmp) + '_ev')
        os.makedirs(os.path.join(ev, 's1'))
        with io.open(os.path.join(ev, 's1', 'events.jsonl'), 'w',
                     encoding='utf-8') as f:
            f.write(json.dumps({'type': 'session.start',
                                'data': {'context': {'cwd': tmp}}}) + '\n')
            f.write(json.dumps({'type': 'user.message', 'id': 'm1',
                                'timestamp': '2026-11-13T10:00:00Z',
                                'data': {'content': '不得落盘'}}) + '\n')
        before = common.snapshot(tmp)
        r = subprocess.run([PY, '-B', 'daybook_session_hook.py', 'watch', '--once',
                            '--initialize', '--events-root', ev,
                            '--state', os.path.join(tmp, 'state.json'),
                            '--workspace', tmp],
                           cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        try:
            _same('P7 session hook rc=3：账本目录零变化（state 不写）', tmp, before, r, 3)
        finally:
            shutil.rmtree(ev, ignore_errors=True)

    # 7) daybook_hook：rc=6（根只读，已处理卷写不出）——同样零落盘
    with common.tmpdir('p7h_') as tmp:
        common.make_ledger(tmp)
        shutil.copy2(os.path.join(common.SRC, 'daybook_hook.py'), tmp)
        with io.open(os.path.join(tmp, '对话卷.txt'), 'w', encoding='utf-8') as f:
            f.write('[2026-11-13 10:00:00] [对话] [t] [皮特] 正文\n')
        with io.open(os.path.join(tmp, 'hook_a_关键词.txt'), 'w', encoding='utf-8') as f:
            f.write('[账] [测试] 正文\n')
        os.chmod(tmp, 0o555)
        try:
            before = common.snapshot(tmp)
            r = subprocess.run([PY, '-B', 'daybook_hook.py', '--home', tmp],
                               cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)
            _same('P7 daybook_hook rc=6（根只读）：账本目录零变化', tmp, before, r, 6)
        finally:
            os.chmod(tmp, 0o755)

    # 8) orchestrator alarm：rc=3（账本被等长改写）——体检不得写回任何字节
    with common.tmpdir('p7g_') as tmp:
        common.make_ledger(tmp)
        common.run_entry(tmp, ['baseline'])
        common.run_entry(tmp, ['index'])
        orch = os.path.join(common.SRC, 'orchestrator.py')
        subprocess.run([PY, '-B', orch, '--home', tmp, 'join', '汤姆'],
                       cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
        common.tamper_mid(os.path.join(tmp, '账卷.txt'))
        before = common.snapshot(tmp)
        r = subprocess.run([PY, '-B', orch, '--home', tmp, 'alarm'],
                           cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        _same('P7 orchestrator alarm rc=3：体检零落盘', tmp, before, r, 3)

    # 9) build(dry=True)：rc=0 也必须零落盘（dry 自证：闭包面不把 dry 当写边）
    with common.tmpdir('p7i_') as tmp:
        common.make_ledger(tmp)
        common.run_entry(tmp, ['baseline'])
        common.run_entry(tmp, ['index'])
        before = common.snapshot(tmp)
        code = ('import io,sys; sys.path.insert(0, "."); import daybook;'
                'c=daybook.parse_conf(io.open("daybook.conf",encoding="utf-8").read(),".");'
                'daybook.build(c,".",dry=True,authors=True)')
        r = subprocess.run([PY, '-B', '-c', code], cwd=tmp, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
        _same('P7 build(dry=True) rc=0：只算不写·账本目录零变化', tmp, before, r, 0)
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
