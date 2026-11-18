#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P1 · 根身份与换根语义（属性层）
P1 · root identity and root-swap semantics
================================================
同一 inode 的任意写法（尾斜杠 / `.` / `..` / 软链）必须得到同一把锁；换根之后，
已持有的锁只能写打开时的 inode。变异 M1（锁键退回 label 字符串）必须让本件变红。
"""
import os
import time

import common
from common import check
import safeio
from safeio import Root, WriteMode


def run(seed=7, mode='const'):
    print('  -- P1 根身份 / 换根语义（seed=%d mode=%s） --' % (seed, mode))
    with common.tmpdir('p1_') as base:
        root = os.path.join(base, 'root')
        os.makedirs(os.path.join(root, 'sub'))
        with open(os.path.join(root, 'vol.txt'), 'wb') as f:
            f.write(b'a\n')
        alias = os.path.join(base, 'alias')
        os.symlink(root, alias)

        spellings = [root, root + os.sep, os.path.join(root, '.'),
                     os.path.join(base, 'sub', '..', 'root'), alias]
        roots = [Root._from_dir_path(p) for p in spellings]
        try:
            ids = [r.dev_ino for r in roots]
            check('P1 同一根的 %d 种写法 ⇒ 同一 dev_ino' % len(spellings),
                  len(set(ids)) == 1, 'ids=%r' % (ids,))
            check('P1 label 归一为 realpath',
                  all(r.label == os.path.realpath(root) for r in roots),
                  '%r' % ([r.label for r in roots],))

            # label 只是文案：同一 dev_ino、不同 label 的句柄仍是同一把锁
            r0 = roots[0]
            alt = Root(os.dup(r0._fd), r0.dev_ino, 'another-label', root)
            try:
                with r0.lock(timeout=1.0):
                    try:
                        lr2 = alt.lock(timeout=0.3)
                        got2 = 'acquired'
                        lr2.release()
                    except RuntimeError:
                        got2 = 'runtime'
                    except TimeoutError:
                        got2 = 'timeout'
                check('P1 同一 dev_ino / 不同 label ⇒ 同一把锁（同线程立即 RuntimeError）',
                      got2 == 'runtime', 'got=%s' % got2)
            finally:
                alt.close()

            # 同线程重入：另一种写法也必须被认成同一把锁（立即 RuntimeError，不挂起）
            r1 = roots[-1]
            t0 = time.time()
            try:
                with r0.lock(timeout=1.0):
                    try:
                        r1.lock(timeout=0.5)
                        got = 'acquired'
                    except RuntimeError:
                        got = 'runtime'
                    except TimeoutError:
                        got = 'timeout'
                check('P1 同一 inode 另一写法 ⇒ 同线程立即 RuntimeError',
                      got == 'runtime', 'got=%s %.3fs' % (got, time.time() - t0))
            except Exception as exc:                       # M1：释放键与获取键不一致
                check('P1 同一 inode 另一写法 ⇒ 锁释放/获取未抛 RuntimeError', False,
                      '锁释放/获取异常：%s' % (exc,))

            # 释放后可再次取得（锁状态没有泄漏）
            try:
                ok = False
                with r0.lock(timeout=1.0):
                    ok = True
                with r0.lock(timeout=1.0):
                    ok = ok and True
                check('P1 释放后可再次取锁（无泄漏）', ok)
            except Exception as exc:
                check('P1 释放后再次取锁异常（无泄漏）', False, repr(exc))

            # 换根：先开根、后换名，写必须落旧 inode
            old = os.path.join(base, 'old')
            os.makedirs(old)
            with open(os.path.join(old, 'seed.txt'), 'wb') as f:
                f.write(b'old\n')
            rt = Root._from_dir_path(old)
            try:
                with rt.lock(timeout=2.0) as lr:
                    moved = os.path.join(base, 'old_moved')
                    os.rename(old, moved)
                    os.makedirs(old)                   # 原路径换成新 inode
                    lr.write(rt.rel('after.txt'), b'old-inode\n',
                             mode=WriteMode.APPEND_CREATE)
                check('P1 换根后写落打开时的 inode',
                      os.path.exists(os.path.join(moved, 'after.txt'))
                      and not os.path.exists(os.path.join(old, 'after.txt')),
                      'moved=%s new=%s'
                      % (os.path.exists(os.path.join(moved, 'after.txt')),
                         os.path.exists(os.path.join(old, 'after.txt'))))
            finally:
                rt.close()
        finally:
            for r in roots:
                r.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
