#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P10 · build 换根不建新目录（属性层）
P10 · build keeps the original root inode after a rename
================================================
`daybook.build` 的索引 outdir、`_backup_locked` 的 backup/、`daybook_record.record` 的
「对话原件」都必须走 `LockedRoot`。根 rename 走后就地建同名空目录，再跑：新根不得长出
任何目录。变异 M13（退回 os.makedirs(outdir)）必须让 build 那条变红。
"""
import glob
import importlib.util
import os
import shutil
import types

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

            # backup：卷用绝对路径（旧 inode），backup/ 目录必须建在旧根
            conf['_files'] = {'账': vol}
            from safeio import locked as _locked
            with _locked(rt) as lr:
                daybook._backup_locked(conf, rt, lr)
            backs = sorted(glob.glob(os.path.join(moved, 'backup', '*')))
            check('P10 换根后 backup 写旧 inode',
                  len(backs) == 1
                  and os.path.exists(os.path.join(backs[0], '账卷.txt'))
                  and sorted(os.listdir(root)) == [],
                  'backs=%d new_entries=%r' % (len(backs), sorted(os.listdir(root))))
        finally:
            rt.close()

    # record：模块副本的 HERE 就是临时根；换根后归档目录仍须落旧 inode
    with common.tmpdir('p10rec_') as base:
        rec_dir = os.path.join(base, 'root')
        os.makedirs(rec_dir)
        shutil.copy2(os.path.join(common.SRC, 'daybook_record.py'), rec_dir)
        spec = importlib.util.spec_from_file_location(
            'p10_record', os.path.join(rec_dir, 'daybook_record.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        class _Done(object):
            returncode = 0
            stdout = ''
            stderr = ''

        real_sub = mod.subprocess
        mod.subprocess = types.SimpleNamespace(
            run=lambda *a, **k: _Done(), PIPE=-1, DEVNULL=-3, STDOUT=-2)
        rt2 = Root._from_dir_path(rec_dir)
        try:
            moved2 = os.path.join(base, 'root_moved')
            os.rename(rec_dir, moved2)
            os.makedirs(rec_dir)
            mod.record('用户', 'P10', '换根归档正文'.encode('utf-8'),
                       stamp='20260101_000000', update_index=False, root=rt2)
            arc = os.path.join(moved2, '对话原件')
            files = sorted(os.listdir(arc)) if os.path.isdir(arc) else []
            check('P10 换根后 record 归档写旧 inode',
                  bool(files) and files[0].endswith('.txt')
                  and sorted(os.listdir(rec_dir)) == [],
                  'files=%r new_entries=%r' % (files[:1], sorted(os.listdir(rec_dir))))
        finally:
            mod.subprocess = real_sub
            rt2.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
