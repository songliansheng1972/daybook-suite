#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P5 · 原子可见与互斥（属性层）
P5 · atomic visibility and exclusion (property layer)
================================================
替换路径必须 fsync 目录；锁必须真的互斥（别的线程取不到）；换根仍写旧 inode；
无锁读者永远看到完整行。变异 M5（Root.lock 不取锁）、M7（删 fsync(dfd)）必须让本件变红。
"""
import os
import threading
import time

import common
from common import check
import safeio
from safeio import Root, WriteMode


def _dir_fsync_count():
    """返回一个计数器：包装 os.fsync，统计「参数 fd 是目录」的次数。"""
    real = os.fsync
    seen = {'dir': 0, 'all': 0}

    def wrapper(fd):
        seen['all'] += 1
        if common.is_dir_fd(fd):
            seen['dir'] += 1
        return real(fd)

    os.fsync = wrapper
    return seen, lambda: setattr(os, 'fsync', real)


def run(seed=7, mode='const'):
    print('  -- P5 原子可见与互斥（seed=%d mode=%s） --' % (seed, mode))
    with common.tmpdir('p5_') as base:
        root = os.path.join(base, 'root')
        os.makedirs(root)
        rt = Root._from_dir_path(root)
        try:
            # 1) 替换：目录 fsync 至少一次（崩溃后名字不再指旧 inode）
            seen, restore = _dir_fsync_count()
            try:
                with rt.lock(timeout=2.0) as lr:
                    lr.write(rt.rel('rep.txt'), b'v1\n', mode=WriteMode.REPLACE)
            finally:
                restore()
            check('P5 REPLACE 后目录 fsync ≥ 1', seen['dir'] >= 1,
                  'dir=%d all=%d' % (seen['dir'], seen['all']))

            # 2) 互斥：主线程持锁时，另一线程必须超时而不是拿到凭证
            got = {}

            def worker():
                try:
                    with rt.lock(timeout=0.3):
                        got['v'] = 'acquired'
                except TimeoutError:
                    got['v'] = 'timeout'
                except Exception as exc:
                    got['v'] = type(exc).__name__

            with rt.lock(timeout=2.0):
                th = threading.Thread(target=worker)
                th.start()
                th.join(5)
            check('P5 持锁期间另一线程取锁超时（真互斥）', got.get('v') == 'timeout',
                  'got=%r' % (got.get('v'),))

            # 3) 换根：写只落打开时的 inode
            old = os.path.join(base, 'swap')
            os.makedirs(old)
            rs = Root._from_dir_path(old)
            try:
                with rs.lock(timeout=2.0) as lr:
                    os.rename(old, old + '_moved')
                    os.makedirs(old)
                    lr.write(rs.rel('landed.txt'), b'old\n',
                             mode=WriteMode.APPEND_CREATE)
                check('P5 换根后写落旧 inode（新路径零触碰）',
                      os.path.exists(os.path.join(old + '_moved', 'landed.txt'))
                      and not os.path.exists(os.path.join(old, 'landed.txt')))
            finally:
                rs.close()

            # 4) 无锁读者：任何采样都是完整行
            vol = os.path.join(root, 'vol.txt')
            with open(vol, 'wb') as f:
                f.write(b'')
            stop = {'v': False}
            errors = []

            def writer():
                try:
                    with rt.lock(timeout=5.0) as lr:
                        for i in range(40):
                            lr.write(rt.rel('vol.txt'),
                                     ('[2026-11-13 12:00:%02d] [测试] [%03d] [皮特] %s\n'
                                      % (i % 60, i, 'x' * 120)).encode('utf-8'),
                                     mode=WriteMode.APPEND_CREATE)
                except Exception as exc:
                    errors.append(repr(exc))

            th = threading.Thread(target=writer)
            th.start()
            samples = 0
            while th.is_alive():
                with open(vol, 'rb') as f:
                    raw = f.read()
                if raw:
                    samples += 1
                    if not raw.endswith(b'\n'):
                        errors.append('torn: 末尾无换行')
                        break
                    for line in raw.splitlines():
                        if not line.startswith(b'[2026-11-13'):
                            errors.append('torn: 行首残缺 %r' % line[:20])
                            break
                time.sleep(0.002)
            th.join(5)
            check('P5 无锁读者未观察到撕裂行', not errors,
                  '采样=%d %r' % (samples, errors[:3]))

            # 5) update 是同一个 write：读-改-写不丢内容
            with rt.lock(timeout=2.0) as lr:
                lr.update(rt.rel('cnt.txt'), lambda old: old + b'x')
                lr.update(rt.rel('cnt.txt'), lambda old: old + b'y')
            check('P5 update 连续两次不丢更新',
                  open(os.path.join(root, 'cnt.txt'), 'rb').read() == b'xy')
        finally:
            rt.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
