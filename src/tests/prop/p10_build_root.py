#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P10 · build 换根不建新目录（属性层）
P10 · build keeps the original root inode after a rename
================================================
`daybook.build` 的索引 outdir 必须走 `LockedRoot.mkdirs_path`。根 rename 走后就地建同名
空目录，再 build：新根不得长出「索引」。变异 M13（退回 os.makedirs(outdir)）必须让本件变红。
"""
import os

import common
from common import check
from safeio import Root


def run(seed=7, mode='const'):
    print('  -- P10 build 换根不建新目录（seed=%d mode=%s） --' % (seed, mode))
    with common.tmpdir('p10_') as base:
        root = os.path.join(base, 'root')
        os.makedirs(root)
        common.stage(root)
        with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write(common.CONF)
        common.make_volume(os.path.join(root, '账卷.txt'), n=20)

        import daybook
        conf = daybook.load_conf(os.path.join(root, 'daybook.conf'))
        rt = Root._from_dir_path(root)
        try:
            daybook.build(conf, rt, baseline=True)
            check('P10 基线 build 建立索引目录',
                  os.path.isdir(os.path.join(root, '索引')),
                  '索引=%s' % os.path.isdir(os.path.join(root, '索引')))

            moved = os.path.join(base, 'root_moved')
            os.rename(root, moved)
            os.makedirs(root)
            vol = os.path.join(moved, '账卷.txt')
            conf['volumes']['账'] = vol
            # 追加一条：换根后的 build 必须重扫并写回旧 inode，否则「零目录」是空跑
            with open(vol, 'a', encoding='utf-8') as f:
                f.write('[2026-11-13 11:59:59] [测试] [第020条] [皮特] 换根追加\n')
            daybook.build(conf, rt, baseline=True)
            new_entries = sorted(os.listdir(root))
            tsv = os.path.join(moved, '索引', 'index_账.tsv')
            check('P10 换根后 build 不往新根建「索引」',
                  os.path.isdir(os.path.join(moved, '索引'))
                  and not os.path.exists(os.path.join(root, '索引')),
                  'old=%s new=%s' % (os.path.isdir(os.path.join(moved, '索引')),
                                     os.path.exists(os.path.join(root, '索引'))))
            check('P10 换根后 build 写回旧 inode 且新根零目录',
                  new_entries == []
                  and os.path.exists(tsv)
                  and '第020条' in open(tsv, encoding='utf-8').read(),
                  'new_entries=%r tsv=%s' % (new_entries, os.path.exists(tsv)))
        finally:
            rt.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
