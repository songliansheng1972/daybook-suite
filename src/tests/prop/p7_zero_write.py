#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P7 · 非零退出零落盘（属性层）
P7 · zero writes on a non-zero exit (property layer)
================================================
rc=2（配置错）与 rc=3（违例）都不得改动账本目录：递归内容、inode、mtime 全不变。
"""
import io
import os

import common
from common import check


def run(seed=7, mode='const'):
    print('  -- P7 非零退出零落盘（seed=%d mode=%s） --' % (seed, mode))
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
        r = common.run_entry(tmp, ['index'])
        after = common.snapshot(tmp)
        check('P7 rc=2 配置错：账本目录零变化（内容/inode/mtime）',
              r.returncode == 2 and before == after,
              'rc=%d diff=%r' % (r.returncode, common.diff_snap(before, after)[:5]))

    with common.tmpdir('p7b_') as tmp:
        common.make_ledger(tmp)
        common.run_entry(tmp, ['baseline'])
        common.run_entry(tmp, ['index'])
        common.tamper_mid(os.path.join(tmp, '账卷.txt'))
        before = common.snapshot(tmp)
        r = common.run_entry(tmp, ['index'])
        after = common.snapshot(tmp)
        check('P7 rc=3 违例：账本目录零变化（内容/inode/mtime）',
              r.returncode == 3 and before == after,
              'rc=%d diff=%r' % (r.returncode, common.diff_snap(before, after)[:5]))
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
