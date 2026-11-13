#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逻辑读/写字节计量：包住 builtins.open 与 io.open。
Logical byte counter wrapping builtins.open / io.open, attributed to
volume / index / multilevel / other.

口径：文件 API 层读到的字节，不含缺页与元数据 I/O；OS 层另报 ru_inblock（受页缓存影响）。
"""
import builtins
import io
import os
import resource

import common as C

_orig_bopen = builtins.open
_orig_iopen = io.open
_installed = False
stats = {'read': {}, 'write': {}}


def _classify(path):
    try:
        p = os.path.abspath(os.fspath(path))
    except TypeError:
        return 'other'
    if p.startswith(C.VOL_DIR):
        return 'volume'
    if p.startswith(os.path.join(C.ROOT_DB, 'multilevel')):
        return 'multilevel'
    if p.startswith(C.ROOT_DB):
        return 'index'
    if p.startswith(C.ROOT_ORCH):
        return 'orch-state'
    return 'other'


def _size(data):
    if isinstance(data, bytes):
        return len(data)
    if isinstance(data, str):
        return len(data.encode('utf-8'))
    return 0


class _Counted:
    def __init__(self, f, cls):
        self._f = f
        self._cls = cls

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        self._f.__enter__()
        return self

    def __exit__(self, *a):
        return self._f.__exit__(*a)

    def __iter__(self):
        return self

    def __next__(self):
        v = next(self._f)
        stats['read'][self._cls] = stats['read'].get(self._cls, 0) + _size(v)
        return v

    def read(self, *a):
        v = self._f.read(*a)
        stats['read'][self._cls] = stats['read'].get(self._cls, 0) + _size(v)
        return v

    def readline(self, *a):
        v = self._f.readline(*a)
        stats['read'][self._cls] = stats['read'].get(self._cls, 0) + _size(v)
        return v

    def readlines(self, *a):
        vs = self._f.readlines(*a)
        stats['read'][self._cls] = stats['read'].get(self._cls, 0) + sum(_size(v) for v in vs)
        return vs

    def write(self, data):
        n = self._f.write(data)
        stats['write'][self._cls] = stats['write'].get(self._cls, 0) + _size(data)
        return n

    def writelines(self, lines):
        lines = list(lines)
        self._f.writelines(lines)
        stats['write'][self._cls] = stats['write'].get(self._cls, 0) + sum(_size(x) for x in lines)


def install():
    global _installed
    if _installed:
        return

    def _bopen(file, *a, **k):
        f = _orig_bopen(file, *a, **k)
        return _Counted(f, _classify(file)) if isinstance(file, (str, bytes, os.PathLike)) else f

    def _iopen(file, *a, **k):
        f = _orig_iopen(file, *a, **k)
        return _Counted(f, _classify(file)) if isinstance(file, (str, bytes, os.PathLike)) else f

    builtins.open = _bopen
    io.open = _iopen
    _installed = True


def snapshot():
    return {'read': dict(stats['read']), 'write': dict(stats['write'])}


def inblock():
    return resource.getrusage(resource.RUSAGE_SELF).ru_inblock


def maxrss_mb():
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    import platform
    v = ru if platform.system() == 'Darwin' else ru * 1024
    return round(v / 1048576.0, 1)
