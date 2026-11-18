#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P6 · 退出码矩阵（属性层）
P6 · exit-code matrix (property layer)
================================================
同一故障类在所有入口同一个码；多故障按严重度合成；入口不打 traceback。
变异 M6（入口插 `return 2`）必须让本件变红：违例场景应得 3，而不是 2。
"""
import contextlib
import io
import os

import common
from common import check
import errors


def _entry_code(fn):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        rc = errors.run_entry(fn)
    return rc, buf.getvalue()


def run(seed=7, mode='const'):
    print('  -- P6 退出码矩阵（seed=%d mode=%s） --' % (seed, mode))
    check('P6 TABLE 是唯一映射（2/3/4/5/6）',
          errors.TABLE == {2: 2, 3: 3, 4: 4, 5: 5, 6: 6},
          '%r' % (errors.TABLE,))
    pairs = [(errors.ConfigError, 2), (errors.LedgerViolation, 3),
             (errors.AuthorConvention, 4), (errors.EvidenceMissing, 5),
             (errors.RuntimeFailure, 6), (errors.WriteRefused, 6)]
    bad = [(c.__name__, errors.exit_code(c('x'))) for c, want in pairs
           if errors.exit_code(c('x')) != want]
    check('P6 每个错误类 → 表里的码', not bad, 'bad=%r' % (bad,))
    check('P6 多故障按严重度：违例 > 作者 > 运行 > 配置 > 证据',
          errors.worst([errors.EvidenceMissing('e'), errors.ConfigError('c')]).kind == 2
          and errors.worst([errors.RuntimeFailure('r'), errors.ConfigError('c')]).kind == 6
          and errors.worst([errors.AuthorConvention('a'), errors.RuntimeFailure('r')]).kind == 4)
    rc, text = _entry_code(lambda: (_ for _ in ()).throw(errors.LedgerViolation('v')))
    check('P6 run_entry 只打印文案、不打 traceback',
          rc == 3 and 'Traceback' not in text and 'rc=3' in text,
          'rc=%d text=%r' % (rc, text[:120]))

    with common.tmpdir('p6_') as tmp:
        common.make_ledger(tmp)
        r0 = common.run_entry(tmp, ['baseline'])
        r1 = common.run_entry(tmp, ['index'])
        check('P6 基线后 index rc=0', r0.returncode in (0, 5) and r1.returncode == 0,
              'baseline=%d index=%d' % (r0.returncode, r1.returncode))
        common.tamper_mid(os.path.join(tmp, '账卷.txt'))
        r2 = common.run_entry(tmp, ['index'])
        check('P6 等长改写 ⇒ rc=3（不是 2/6）', r2.returncode == 3,
              'rc=%d' % r2.returncode)
        check('P6 违例入口无 traceback',
              'Traceback' not in (r2.stdout + r2.stderr),
              (r2.stderr or '')[-160:])

    with common.tmpdir('p6b_') as tmp:
        common.make_ledger(tmp)
        os.makedirs(os.path.join(tmp, '坏卷目录'))
        conf = os.path.join(tmp, 'daybook.conf')
        text = io.open(conf, encoding='utf-8').read()
        io.open(conf, 'w', encoding='utf-8').write(
            text.replace('账=账卷.txt', '账=坏卷目录'))
        r3 = common.run_entry(tmp, ['index'])
        check('P6 配置错 ⇒ rc=2', r3.returncode == 2, 'rc=%d' % r3.returncode)
        check('P6 配置错入口无 traceback',
              'Traceback' not in (r3.stdout + r3.stderr),
              (r3.stderr or '')[-160:])

    with common.tmpdir('p6c_') as tmp:
        common.make_ledger(tmp)
        r4 = common.run_entry(tmp, ['watch', 'abc'], timeout=20)
        check('P6 畸形参数（watch abc）⇒ rc=2 且无 traceback',
              r4.returncode == 2 and 'Traceback' not in (r4.stdout + r4.stderr),
              'rc=%d out=%s' % (r4.returncode,
                                (r4.stdout + r4.stderr)[-160:].replace('\n', ' ')))
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
