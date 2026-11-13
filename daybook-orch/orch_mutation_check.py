#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""四条缺陷的变异回归：把每条改回旧行为，测试必须红；恢复后必须绿。
Mutation regression for the four defects: revert each fix to the old behavior —
the test must go red; restore it — the test must go green.

做法：把本包复制到临时目录 → 用文本替换注入旧行为 → 在临时目录里跑对应单测。
Approach: copy this package to a temp dir → text-replace the old behavior in → run that single test there.
原始输出与 rc 全部打印。
Raw output and rc are printed for both runs.

用法：python3 orch_mutation_check.py
退出码：0=四条都满足「变异红·原版绿」；1=有不服。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TEST = 'orch_fixes_test.py'

IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.locks', '.daybook_keys',
                                '.safeio_lock.*', '*.tmp')

# (编号, 名称, [(文件, 旧片段, 新片段), ...])
MUTATIONS = [
    (1, 'pull 改回按位置判已回', [(
        'orchestrator.py',
        """            if not e.get('id'):
                e['reply_state'] = 'unknown'
            elif e['id'] in replied:
                e['reply_state'] = 'replied'
                continue
            else:
                e['reply_state'] = 'pending'""",
        """            _pos_replied = any(entries[j]['author'] in (who, who_id)
                               for j in range(i + 1, len(entries)))
            if _pos_replied:
                e['reply_state'] = 'replied'
                continue
            if not e.get('id'):
                e['reply_state'] = 'unknown'
            else:
                e['reply_state'] = 'pending'""",
    )]),
    (2, '身份改回不验签', [(
        'orchestrator.py',
        """        if not e.get('sig'):
            return 'unsigned'""",
        """        if not e.get('sig'):
            return 'ok'""",
    )]),
    (3, '根解析改回写死代码目录', [
        ('orchestrator.py',
         "        self.ledger = self.vols['ledger']",
         "        self.ledger = os.path.join(HERE, '编排卷.txt')"),
        ('agent_message.py',
         """    return INBOX_VOL if root is None else _vp.resolve_volumes(root)['inbox']""",
         """    return INBOX_VOL"""),
    ]),
    (4, 'read_vol 改回无锁读', [(
        'safeio.py',
        """    with locked(path, shared=True):
        with open(path, 'rb') as f:
            raw = f.read()""",
        """    with open(path, 'rb') as f:
        raw = f.read()""",
    )]),
]


def run_test(pkg, only):
    """在 pkg 目录里跑单测，返回 (rc, output)。 · Run the single test in pkg; return (rc, output)."""
    r = subprocess.run([sys.executable, TEST, '--only', str(only)],
                       cwd=pkg, capture_output=True, text=True)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def tail(output, n=12):
    lines = [x for x in output.strip().splitlines() if x.strip()]
    return '\n'.join('    ' + x for x in lines[-n:])


def make_mutant(n, subs):
    pkg = tempfile.mkdtemp(prefix='orch_mut%d_' % n)
    dest = os.path.join(pkg, 'pkg')
    shutil.copytree(HERE, dest, ignore=IGNORE)
    for fn, old, new in subs:
        path = os.path.join(dest, fn)
        with open(path, encoding='utf-8') as f:
            src = f.read()
        if old not in src:
            raise RuntimeError('变异锚点未命中：%s / %s' % (fn, old.splitlines()[0]))
        src = src.replace(old, new, 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(src)
    return pkg, dest


def main():
    ok = True
    print('=== 四条缺陷：变异回归 ===')
    for n, name, subs in MUTATIONS:
        pkg, mutant = make_mutant(n, subs)
        try:
            mrc, mout = run_test(mutant, n)
            print('\n-- 第 %d 条：%s --' % (n, name))
            print('  变异体 rc=%d（要求 ≠0）' % mrc)
            print(tail(mout))
            orc, oout = run_test(HERE, n)
            print('  原版   rc=%d（要求 =0）' % orc)
            print(tail(oout))
            good = (mrc != 0 and orc == 0)
            print('  判：%s' % ('红→绿 成立' if good else '不成立'))
            ok = ok and good
        finally:
            shutil.rmtree(pkg, ignore_errors=True)
    print('\n=== %s ===' % ('四条全部成立' if ok else '有不服'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
