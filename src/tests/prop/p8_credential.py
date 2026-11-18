#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P8 · 写凭证生命周期（属性层）
P8 · write-credential lifetime (property layer)
================================================
写能力不是「曾经拿到过的对象」，而是「此刻仍在本线程持有表里的凭证」：
释放后、跨线程、跨进程窗口内用旧 `LockedRoot` 写，都必须 RuntimeError 且零写。
变异 M9（去掉 `_ensure_live()`）必须让本件变红。
"""
import os
import subprocess
import sys
import time

import common
from common import check
import safeio
from safeio import Root, WriteMode


def run(seed=7, mode='const'):
    print('  -- P8 写凭证生命周期（seed=%d mode=%s） --' % (seed, mode))
    with common.tmpdir('p8_') as base:
        root = os.path.join(base, 'root')
        os.makedirs(root)
        rt = Root._from_dir_path(root)
        try:
            # 1) 释放后旧凭证失效，且零写
            with rt.lock(timeout=2.0) as lr:
                lr.write(rt.rel('live.txt'), b'live\n', mode=WriteMode.APPEND_CREATE)
            try:
                lr.write(rt.rel('after_release.txt'), b'x\n', mode=WriteMode.APPEND_CREATE)
                got = 'wrote'
            except RuntimeError:
                got = 'refused'
            check('P8 释放后旧凭证 ⇒ RuntimeError 且零写',
                  got == 'refused' and not os.path.exists(
                      os.path.join(root, 'after_release.txt')), 'got=%s' % got)
            try:
                lr.update(rt.rel('after_release_u.txt'), lambda b: b + b'x')
                gotu = 'wrote'
            except RuntimeError:
                gotu = 'refused'
            check('P8 释放后旧凭证 update ⇒ RuntimeError 且零写',
                  gotu == 'refused' and not os.path.exists(
                      os.path.join(root, 'after_release_u.txt')), 'got=%s' % gotu)

            # 2) 凭证跨线程使用：本线程持有表里没有它 ⇒ 拒绝
            got = {}
            with rt.lock(timeout=2.0) as lr:
                def other_thread():
                    try:
                        lr.write(rt.rel('cross_thread.txt'), b'x\n',
                                 mode=WriteMode.APPEND_CREATE)
                        got['v'] = 'wrote'
                    except RuntimeError:
                        got['v'] = 'refused'
                import threading
                th = threading.Thread(target=other_thread)
                th.start()
                th.join(5)
            check('P8 凭证跨线程使用 ⇒ RuntimeError 且零写',
                  got.get('v') == 'refused' and not os.path.exists(
                      os.path.join(root, 'cross_thread.txt')),
                  'got=%r' % (got.get('v'),))

            # 3) 跨进程窗口：本进程释放后，子进程持 flock 期间，旧凭证仍必须拒绝
            with rt.lock(timeout=2.0) as stale:
                pass
            child = (
                'import sys, time\n'
                'sys.path.insert(0, %r)\n'
                'from safeio import Root\n'
                'rt = Root._from_dir_path(%r)\n'
                'lr = rt.lock(timeout=5)\n'
                'print("ready", flush=True)\n'
                'time.sleep(2.0)\n'
                'lr.release()\n' % (common.SRC, root))
            p = subprocess.Popen([sys.executable, '-B', '-c', child],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 universal_newlines=True)
            try:
                line = p.stdout.readline().strip()
                t0 = time.time()
                try:
                    stale.write(rt.rel('during_child.txt'), b'x\n',
                                mode=WriteMode.APPEND_CREATE)
                    got = 'wrote'
                except RuntimeError:
                    got = 'refused'
                check('P8 子进程持锁窗口内旧凭证 ⇒ RuntimeError 且零写',
                      line == 'ready' and got == 'refused'
                      and not os.path.exists(os.path.join(root, 'during_child.txt')),
                      'child=%r got=%s %.2fs' % (line, got, time.time() - t0))
            finally:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        finally:
            rt.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
