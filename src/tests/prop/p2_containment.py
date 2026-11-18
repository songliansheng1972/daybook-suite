#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P2 · 归属封闭（属性层）
P2 · containment closure
================================================
根内写成功；软链祖先、`link/..` 折叠陷阱、以及直接构造带 `..` 的 Rel 都必须拒绝，
且根外文件一字节不增。变异 M2（去 O_NOFOLLOW）、M3（abspath 词法折叠）、
M8（Rel 只校验首段）各自必须让本件变红。
"""
import os

import common
from common import check
import safeio
from safeio import Root, WriteMode


def _try_write(rt, lr, make_rel, data=b'x\n'):
    try:
        lr.write(make_rel(), data, mode=WriteMode.APPEND_CREATE)
        return True, ''
    except Exception as exc:
        return False, str(exc)


def run(seed=7, mode='const'):
    print('  -- P2 归属封闭（seed=%d mode=%s） --' % (seed, mode))
    with common.tmpdir('p2_') as base:
        root = os.path.join(base, 'root')
        outside = os.path.join(base, 'outside')
        os.makedirs(os.path.join(root, 'sub'))
        os.makedirs(os.path.join(root, 'x'))
        os.makedirs(outside)
        with open(os.path.join(outside, 'keep.txt'), 'wb') as f:
            f.write(b'outside\n')
        os.symlink(outside, os.path.join(root, 'link'))

        rt = Root._from_dir_path(root)
        try:
            with rt.lock(timeout=2.0) as lr:
                ok, why = _try_write(rt, lr, lambda: rt.rel('sub', 'ok.txt'))
                check('P2 根内普通写成功', ok and os.path.exists(
                    os.path.join(root, 'sub', 'ok.txt')), why)

                got, why = _try_write(rt, lr, lambda: rt.rel_of(
                    os.path.join(root, 'link', 'escaped.txt'), 'P2'))
                check('P2 软链祖先 ⇒ 拒绝且根外零字节',
                      not got and not os.path.exists(os.path.join(outside, 'escaped.txt')),
                      '%s %s' % (got, why[:100]))

                got, why = _try_write(rt, lr, lambda: rt.rel_of(
                    os.path.join(root, 'link', '..', 'folded.txt'), 'P2'))
                check('P2 link/../x 折叠陷阱 ⇒ 拒绝（不静默改道）',
                      not got and not os.path.exists(os.path.join(root, 'folded.txt'))
                      and not os.path.exists(os.path.join(outside, 'folded.txt')),
                      '%s %s' % (got, why[:100]))

                got, why = _try_write(rt, lr, lambda: rt.rel('x', '..', '..', 'escape.txt'))
                check('P2 直接构造 .. 段 ⇒ Rel 构造即拒绝',
                      not got and not os.path.exists(os.path.join(base, 'escape.txt')),
                      '%s %s' % (got, why[:100]))

                got, why = _try_write(rt, lr, lambda: rt.rel('..', 'up.txt'))
                check('P2 首段 .. ⇒ 拒绝',
                      not got and not os.path.exists(os.path.join(base, 'up.txt')),
                      '%s %s' % (got, why[:100]))

                # 根外目录仍然只有 keep.txt
                names = sorted(os.listdir(outside))
                check('P2 根外目录零新增', names == ['keep.txt'], 'names=%r' % (names,))
        finally:
            rt.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
