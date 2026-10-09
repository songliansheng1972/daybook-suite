#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""SafeIO · 原子写小件（W-75·造①）
================================================
三个原语，零依赖（仅标准库），API 极简：
  with locked(path): ...           # 独占锁（临界区内任意读改写）
  atomic_append(path, bytes)      # O_APPEND 追加（持锁）
  read_modify_write(path, fn)     # 持锁读-改-写

降级：无 fcntl 平台（Windows）退 mkdir 原子锁（os.mkdir 天生原子）。
锁粒度：每个目标文件一把锁（.safeio_lock.<basename>），不锁卷原文。
"""
import os, io, json, contextlib

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


def _lock_path(path):
    """锁文件路径：与目标同目录，隐藏前缀。"""
    d = os.path.dirname(path) or os.curdir
    return os.path.join(d, '.safeio_lock.' + os.path.basename(path))


@contextlib.contextmanager
def locked(path, timeout=None):
    """独占锁上下文。退出自动释放（fd close ⇒ flock 自动解）。
    timeout 秒内拿不到则超时；None=阻塞等待。"""
    lp = _lock_path(path)
    if _HAS_FCNTL:
        fd = os.open(lp, os.O_RDWR | os.O_CREAT, 0o644)
        flag = fcntl.LOCK_EX
        if timeout is not None:
            import time
            deadline = time.time() + timeout
            flag |= fcntl.LOCK_NB
            while True:
                try:
                    fcntl.flock(fd, flag)
                    break
                except (BlockingIOError, OSError):
                    if time.time() >= deadline:
                        os.close(fd)
                        raise TimeoutError('safeio: lock timeout for %s' % path)
                    time.sleep(0.05)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield fd
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
    else:
        # 降级：mkdir 原子锁（os.mkdir 天生原子·同路径只能成功一次）
        import time
        if timeout is None:
            timeout = 10
        deadline = time.time() + timeout
        while True:
            try:
                os.mkdir(lp)
                break
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError('safeio: mkdir lock timeout for %s' % path)
                time.sleep(0.05)
        try:
            yield None
        finally:
            os.rmdir(lp)


def atomic_append(path, data):
    """持锁追加。O_APPEND + 单次 write。
    用于索引 TSV 追加（修②）与长条目写入（修③）。"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    with locked(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


def sniff_bytes(raw):
    """字节 → 文本的解码检测（★唯一真理源·全仓读卷一律经此）。
    返回 (text, enc, why)。
    检测序：BOM(utf-8-sig/utf-16) → 严格 utf-8
            → (gb18030/big5/cp936/shift_jis 严格·首个成功者) → gb18030（replace 兜底）。
    ⚠ 无中文占比阈值：阈值会把 gb18030 短卷（心跳等）误推 latin-1 乱码，
       且对 big5 并无保护（实测有损无益·#463）。切勿再加阈值。"""
    if raw[:3] == b'\xef\xbb\xbf':
        return raw[3:].decode('utf-8', 'replace'), 'utf-8-sig', 'BOM efbbbf'
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16', 'replace'), 'utf-16', 'BOM fffe/feff'
    try:
        return raw.decode('utf-8'), 'utf-8', '严格 utf-8 解码通过'
    except UnicodeDecodeError:
        pass
    for enc in ('gb18030', 'big5', 'cp936', 'shift_jis'):
        try:
            return raw.decode(enc), enc, '严格 %s 解码通过' % enc
        except UnicodeDecodeError:
            continue
    return raw.decode('gb18030', 'replace'), 'gb18030', '兜底（replace·永不失败）'


def read_vol(path):
    """读卷·自动检测编码（零依赖·不静默）。MCP/orch/基座读卷一律经此。
    返回 (text, enc, why)。检测逻辑唯一在 sniff_bytes（#463 合一）。"""
    with open(path, 'rb') as f:
        raw = f.read()
    return sniff_bytes(raw)


def read_modify_write(path, fn):
    """持锁读-改-写。fn(old_bytes) -> new_bytes。
    用于游标 json（修②）：读旧值→改→写回，全程持锁。"""
    with locked(path):
        if os.path.exists(path):
            with open(path, 'rb') as f:
                old = f.read()
        else:
            old = b''
        new = fn(old)
        if isinstance(new, str):
            new = new.encode('utf-8')
        # 原子写：先写临时文件再 rename（同分区原子）
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(new)
        os.replace(tmp, path)


def read_json(path, default=None):
    """持锁读 json。不存在返 default。"""
    with locked(path):
        if not os.path.exists(path):
            return default
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)


def write_json(path, obj):
    """持锁写 json（读-改-写语义）。"""
    def _replace(_):
        return json.dumps(obj, ensure_ascii=False)
    read_modify_write(path, _replace)
