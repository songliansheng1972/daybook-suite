#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P3 · 单写路径（属性层 · 审计钩子）
P3 · single write path (property layer · audit hook)
================================================
`sys.addaudithook` 记录落在账本根内的写打开/重命名/删除，并检查调用栈里是否有
`safeio.LockedRoot.write/_append/_replace/update`。任何一条根内写事件不经过 safeio
即判红。变异 M4（在 append_one 里插 `open(path, 'ab')` 旁路）必须让本件变红。
"""
import os
import sys

import common
from common import check
import safeio
from safeio import Root, WriteMode

_ROOT_REAL = {'v': ''}
_EVENTS = []
_HOOKED = {'v': False}
_WRITE_FLAGS = 0
for _n in ('O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC', 'O_APPEND'):
    _WRITE_FLAGS |= getattr(os, _n, 0)


def _is_write(mode, flags):
    if isinstance(mode, str) and any(c in mode for c in 'wax+'):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _via_safeio():
    f = sys._getframe(1)
    while f is not None:
        if (f.f_globals.get('__name__') == 'safeio'
                and f.f_code.co_name in ('write', '_append', '_replace', 'update')):
            return True
        f = f.f_back
    return False


def _rel(path):
    if not isinstance(path, str):
        return None
    if os.path.isabs(path):
        rp = os.path.realpath(path)
        base = _ROOT_REAL['v']
        if rp == base:
            return '<root>'
        if rp.startswith(base + os.sep):
            return os.path.relpath(rp, base)
        return None
    return path


def _hook(event, args):
    if event == 'open' and len(args) >= 2:
        path, mode = args[0], args[1]
        flags = args[2] if len(args) > 2 else 0
        if _is_write(mode, flags):
            rel = _rel(path)
            if rel is not None:
                _EVENTS.append(('open', rel, _via_safeio()))
    elif event in ('os.rename', 'os.remove', 'os.unlink', 'os.mkdir'):
        path = args[0] if args else None
        rel = _rel(path)
        if rel is not None:
            _EVENTS.append((event, rel, _via_safeio()))


def _install(root):
    _ROOT_REAL['v'] = os.path.realpath(root)
    if not _HOOKED['v']:
        sys.addaudithook(_hook)
        _HOOKED['v'] = True


def run(seed=7, mode='const'):
    print('  -- P3 单写路径（seed=%d mode=%s） --' % (seed, mode))
    import daybook_append
    with common.tmpdir('p3_') as base:
        root = os.path.join(base, 'root')
        os.makedirs(root)
        vol = os.path.join(root, 'vol.txt')
        with open(vol, 'wb') as f:
            f.write(b'a\n')
        _install(root)

        rt = Root._from_dir_path(root)
        try:
            with rt.lock(timeout=2.0) as lr:
                del _EVENTS[:]
                lr.write(rt.rel('direct.txt'), b'd\n', mode=WriteMode.APPEND_CREATE)
                direct = list(_EVENTS)
                check('P3 直接写：根内写事件全部经 safeio',
                      bool(direct) and all(v for _e, _r, v in direct),
                      '%r' % (direct,))

                del _EVENTS[:]
                daybook_append.append_one(vol, '测试', 'P3', '正文', author='皮特',
                                          root=root)
                events = list(_EVENTS)
                bad = [e for e in events if not e[2]]
                check('P3 append_one：根内写事件全部经 safeio',
                      bool(events) and not bad,
                      '事件=%d 旁路=%r' % (len(events), bad[:4]))
                check('P3 append_one：无旁路写点（open 事件全在 LockedRoot 链上）',
                      not any(e[0] == 'open' and not e[2] for e in events),
                      '%r' % ([e for e in events if not e[2]][:4],))
        finally:
            rt.close()
    return common.summary()


if __name__ == '__main__':
    raise SystemExit(run())
