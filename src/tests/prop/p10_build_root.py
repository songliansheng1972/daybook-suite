#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P10 · build 换根不建新目录（属性层）
P10 · build keeps the original root inode after a rename
================================================
`daybook.build` 的索引 outdir、`_backup_locked` 的 backup/、`daybook_record.record` 的
「对话原件」都必须走 `LockedRoot`。根 rename 走后就地建同名空目录，再跑：新根不得长出
任何目录。变异 M13（退回 os.makedirs(outdir)）必须让 build 那条变红。

覆盖面（声明，不夸大）：record 的换根用例只覆盖 `update_index=False`（归档与登记）。
换根后索引腿按路径读证据，属于**失败关闭**（`update_index=True` ⇒ 2/5，零落盘），
不是「索引仍可用」；该腿不在本属性承诺内。
Coverage (declared, not overstated): the record rename case covers `update_index=False`
(archive + register) only. After a rename the index leg reads evidence by path and fails
closed (`update_index=True` ⇒ 2/5, zero writes); it is not "index still works" and is
outside this property's promise.
"""
import glob
import os
import subprocess
import sys
import time

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

    # record：**真实子进程** + 换根。子进程先打开 Root（拿到旧 inode），父进程再把根
    # rename 走并就地建同名空目录；归档与登记必须仍落旧 inode，且原件与登记同一 dev_ino。
    # 禁止 stub subprocess：stub 会让「子进程按路径重解析根」这个缺陷完全隐形。
    # record: a **real child process** plus a root rename. The child opens Root (old inode)
    # first; the parent then renames the root away and recreates an empty same-named dir. The
    # archive and the registration must still land on the old inode, with the same dev_ino.
    # Never stub subprocess: a stub hides the "child re-resolves the root by path" defect.
    with common.tmpdir('p10rec_') as base:
        rec_dir = os.path.join(base, 'root')
        os.makedirs(rec_dir)
        common.stage(rec_dir)
        with open(os.path.join(rec_dir, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write(common.CONF)
        common.make_volume(os.path.join(rec_dir, '账卷.txt'), n=5)
        b0 = subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'],
                            cwd=rec_dir, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
        check('P10 record 前置：基线 rc=0', b0.returncode == 0,
              'rc=%d out=%s' % (b0.returncode, (b0.stdout + b0.stderr)[-160:]))

        child = os.path.join(base, 'child.py')
        ready = os.path.join(base, 'ready')
        go = os.path.join(base, 'go')
        with open(child, 'w', encoding='utf-8') as f:
            f.write("""import os, sys, time
root, ready, go = sys.argv[1:4]
sys.path.insert(0, root)
from safeio import Root
import daybook_record
rt = Root._from_dir_path(root)
open(ready, 'w').close()
while not os.path.exists(go):
    time.sleep(0.01)
try:
    daybook_record.record('用户', 'P10', '换根归档正文'.encode('utf-8'),
                          stamp='20260101_000000', update_index=False, root=rt)
    print('DEVINO %d %d' % rt.dev_ino)
finally:
    rt.close()
""")
        p = subprocess.Popen([sys.executable, '-B', child, rec_dir, ready, go],
                             cwd=base, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        deadline = time.time() + 20
        while not os.path.exists(ready) and time.time() < deadline:
            time.sleep(0.02)
        moved2 = os.path.join(base, 'root_moved')
        os.rename(rec_dir, moved2)
        os.makedirs(rec_dir)
        open(go, 'w').close()
        out2, err2 = p.communicate(timeout=90)
        arc = os.path.join(moved2, '对话原件')
        files = sorted(os.listdir(arc)) if os.path.isdir(arc) else []
        vol = os.path.join(moved2, '对话卷.txt')
        devino = ''
        for line in out2.splitlines():
            if line.startswith('DEVINO '):
                devino = line.split()[1:3]
        moved_st = os.stat(moved2)
        check('P10 换根后 record 归档写旧 inode（真实子进程 rc=0）',
              p.returncode == 0 and bool(files) and files[0].endswith('.txt')
              and sorted(os.listdir(rec_dir)) == [],
              'rc=%d files=%r new_entries=%r err=%s'
              % (p.returncode, files[:1], sorted(os.listdir(rec_dir)), err2[-160:]))
        check('P10 换根后 record 登记写旧 inode 且原件/登记同一 dev_ino',
              os.path.exists(vol) and devino == [str(moved_st.st_dev),
                                                 str(moved_st.st_ino)]
              and os.stat(os.path.dirname(vol)).st_ino == moved_st.st_ino
              and os.stat(os.path.dirname(os.path.dirname(
                  os.path.join(arc, files[0])))).st_ino == moved_st.st_ino
              if files else False,
              'devino=%r moved=%r vol_parent=%r' % (
                  devino, (moved_st.st_dev, moved_st.st_ino),
                  os.stat(os.path.dirname(vol)).st_ino if os.path.exists(vol) else None))
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
