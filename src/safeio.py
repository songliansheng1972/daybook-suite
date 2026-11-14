#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""SafeIO · 原子写小件（W-75·造①）
SafeIO · small atomic-write utility (W-75 · build ①)
================================================
三个原语，零依赖（仅标准库），API 极简：
Three primitives, zero dependencies (standard library only), minimal API:
  with locked(path): ...           # 独占锁（临界区内任意读改写）· exclusive lock (arbitrary read-modify-write in the critical section)
  atomic_append(path, bytes)      # O_APPEND 追加（持锁）· O_APPEND append (holding the lock)
  read_modify_write(path, fn)     # 持锁读-改-写 · locked read-modify-write

锁粒度：目录级——flock 账本根目录本身的 fd（O_RDONLY|O_DIRECTORY），全程不新建任何文件。
同一账本内的所有路径都落到同一个目录 inode，故跨 TMPDIR、跨用户、跨 cron/launchd 都是同一把锁；
锁不需要写权限（只读卷上的读路径也能取到锁）；没有「锁文件被删」这回事。
Lock granularity: directory-level — flock the ledger-root directory fd itself (O_RDONLY|O_DIRECTORY);
no file is ever created. Every path of one ledger resolves to the same directory inode, so different
TMPDIRs / users / cron jobs all contend on one lock. No write permission is needed (read paths on a
read-only volume can still lock), and there is no lock file anyone could delete.

平台：本版只支持 POSIX（fcntl/flock）。Windows 分支已删除——旧实现会在账本内建
`.safeio_lock` 并释放时删除，既违反「账本内零锁件」，也与发行包声明的 POSIX 平台不符。
Platform: POSIX (fcntl/flock) only. The Windows branch is gone: it created `.safeio_lock` inside
the ledger and removed it on release, breaking the "no lock artifact in the ledger" promise and
contradicting the POSIX-only platform claim of the distribution.

读者：`read_vol` 不取任何锁。卷是 append-only，派生件一律「同目录临时文件 + os.replace」
原子换入，读者拿到的永远是一致快照，且不会被写者的临界区整段阻塞。
Readers: `read_vol` takes no lock. Volumes are append-only and every derived artifact is swapped
in atomically (temp file in the same directory + os.replace), so a reader always sees a
consistent snapshot and is never blocked for the whole writer critical section.
"""
import os, contextlib, threading, tempfile

try:
    import fcntl
except ImportError:                                     # pragma: no cover - POSIX only
    fcntl = None

# 同线程已持锁表：{锁文件绝对路径: [fd, 深度]}。
# 读卷会在持锁的临界区内被调用（如 task_volume.transition 里 read_vol），
# 若不记重入，同进程第二个 fd 再要共享锁会与自己的独占锁冲突而死锁。
# Per-thread held-lock map: {abs lock-file path: [fd, depth]}.
# read_vol is called inside locked critical sections (e.g. task_volume.transition);
# without reentrancy tracking, a second fd in the same process asking for a shared lock
# would conflict with our own exclusive lock and deadlock.
_HELD = threading.local()


def _held_map():
    m = getattr(_HELD, 'locks', None)
    if m is None:
        m = {}
        _HELD.locks = m
    return m


def _lock_dir(path):
    """锁目标＝目录本身：目标所在目录的 realpath（目标本身是目录则取它）。
    锁的身份是目录 inode，与 TMPDIR、用户名、启动方式无关；不落任何文件。
    Lock target = the directory itself: realpath of the containing directory (or the path
    itself when it is a directory). The lock identity is the directory inode, independent of
    TMPDIR / user / how the process was started, and no file is created."""
    p = os.path.realpath(path)
    return p if os.path.isdir(p) else os.path.dirname(p)


@contextlib.contextmanager
def locked(path, timeout=None, shared=False):
    """锁上下文。shared=True 取共享锁（读侧），False 取独占锁（写侧）。
    Lock context. shared=True takes a shared lock (reader side); False takes an exclusive lock (writer side).
    退出自动释放（fd close ⇒ flock 自动解）。
    Released automatically on exit (fd close ⇒ flock auto-unlock).
    同线程可重入：已在临界区内再取同一把锁直接放行（不再开第二个 fd）。
    重入时不做 shared→exclusive 升级（防止自锁）。
    Reentrant within one thread: re-locking the same file inside a held critical section passes through
    without opening a second fd. No shared→exclusive upgrade on reentry (prevents self-deadlock).
    timeout 秒内拿不到则超时；None=阻塞等待。
    Times out if not acquired within timeout seconds; None=block indefinitely."""
    lp = _lock_dir(path)
    held = _held_map()
    if lp in held:
        held[lp][1] += 1
        try:
            yield held[lp][0]
        finally:
            held[lp][1] -= 1
        return
    if fcntl is None:
        raise RuntimeError('safeio: 本版仅支持 POSIX（fcntl/flock）；Windows 需另开单用命名互斥量')
    # 打开目录本身取 fd：不新建文件，不需要写权限；flock 绑在目录 inode 上。
    # Open the directory itself: no file is created, no write permission is required,
    # and the flock is bound to the directory inode.
    fd = os.open(lp, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    flag = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
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
        fcntl.flock(fd, flag)
    held[lp] = [fd, 1]
    try:
        yield fd
    finally:
        held.pop(lp, None)
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def atomic_write(path, data):
    """原子替换写：同目录临时文件 + os.replace（★唯一实现，派生件一律走这里）。
    Atomic replace: a temp file in the same directory + os.replace (★ the single implementation;
    every derived artifact goes through it). Readers never see a half-written file."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def repair_partial_tail(path):
    """锁内调用：末尾无换行即视为崩溃留下的半行，截到最后一个换行处。
    返回被丢弃的字节数（0 表示完整）。非追加型派生件不走这里。
    Called under the lock: a file whose last byte is not a newline ends in a half-written
    line from a crash; truncate back to the last newline. Returns bytes dropped (0 = intact).
    Only append-type artifacts use this; non-append artifacts keep atomic replacement."""
    if not os.path.exists(path):
        return 0
    with open(path, 'r+b') as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        if end == 0:
            return 0
        f.seek(end - 1)
        if f.read(1) == b'\n':
            return 0
        pos = end
        keep = 0
        while pos > 0:
            step = min(1 << 16, pos)
            f.seek(pos - step)
            chunk = f.read(step)
            idx = chunk.rfind(b'\n')
            if idx >= 0:
                keep = pos - step + idx + 1
                break
            pos -= step
        f.truncate(keep)
        return end - keep



def atomic_append(path, data, root=None, ensure_newline=False):
    """持账本根锁追加。O_APPEND + 单次 write。
    Append while holding the ledger-root lock. O_APPEND + a single write.
    root 给出账本根（子目录卷也争同一把锁）；缺省退到目标所在目录。
    `root` names the ledger root (sub-directory volumes contend on the same lock);
    without it the target's own directory is used.
    ensure_newline=True：锁内看末字节，不是 \\n 就先补一个（既有字节不动），
    返回 True 表示补过；避免新条目粘在合法但无换行的末行行尾。
    ensure_newline=True: under the lock, check the last byte and prepend one \\n when it is
    missing (existing bytes untouched); True means it padded. This stops a new entry from
    being glued onto a legal last line that simply lacked a newline."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    padded = False
    with locked(root if root else path):
        if ensure_newline and os.path.exists(path):
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b'\n' and data:
                        data = b'\n' + data
                        padded = True
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    return padded


def sniff_bytes(raw):
    """字节 → 文本的解码检测（★唯一真理源·全仓读卷一律经此）。
    Bytes → text decoding detection (★ single source of truth · every volume read in the repo goes through this).
    返回 (text, enc, why)。
    Returns (text, enc, why).
    检测序：BOM(utf-8-sig/utf-16) → 严格 utf-8
            → (gb18030/big5/cp936/shift_jis 严格·首个成功者) → gb18030（replace 兜底）。
    Detection order: BOM (utf-8-sig/utf-16) → strict utf-8
            → (gb18030/big5/cp936/shift_jis strict · first success) → gb18030 (replace fallback).
    ★ replace 兜底仍永不抛错，但不再静默：编码名标 gb18030!replace，依据里写明替换处数。
    ★ The replace fallback still never throws, but is no longer silent: the encoding label
      becomes gb18030!replace and the reason carries the number of replaced bytes.
    ⚠ 无中文占比阈值：阈值会把 gb18030 短卷（心跳等）误推 latin-1 乱码，
       且对 big5 并无保护（实测有损无益·#463）。切勿再加阈值。
    ⚠ No Chinese-ratio threshold: a threshold misroutes short gb18030 volumes (heartbeat, etc.) to latin-1 mojibake
       and gives no protection for big5 (measured as harmful, not helpful · #463). Never add a threshold back."""
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
    txt = raw.decode('gb18030', 'replace')
    bad = txt.count('\ufffd')
    return txt, ('gb18030!replace' if bad else 'gb18030'), \
        '兜底（replace·%d 处不可解码→U+FFFD·损坏不静默）' % bad


def read_vol(path):
    """读卷·自动检测编码（零依赖·不静默）。MCP/orch/基座读卷一律经此。
    Read a volume · auto-detect encoding (zero dependencies · no silent fallback). All MCP/orch/base volume reads go through this.
    读侧**不取锁**：写者持账本根排他锁串行，派生件靠原子替换换入，读者拿到的
    永远是一致快照，也不会被 40 万条索引的写临界区整段阻塞。
    The reader takes **no lock**: writers are serialized by the ledger-root exclusive lock and
    derived artifacts are swapped in atomically, so a reader always sees a consistent snapshot
    and is never blocked for the whole critical section of a 400k-entry index build.
    返回 (text, enc, why)。检测逻辑唯一在 sniff_bytes（#463 合一）。
    Returns (text, enc, why). The detection logic lives only in sniff_bytes (merged in #463)."""
    with open(path, 'rb') as f:
        raw = f.read()
    return sniff_bytes(raw)


def append_inplace(path, data):
    """锁内原位追加（先截断崩溃半行）：索引等追加型派生件的唯一写入口。
    In-place append under the caller's lock (truncating a crashed half-line first): the single
    write entry for append-type artifacts such as indexes.
    返回被截断的字节数。调用方必须已持账本根锁。
    Returns bytes dropped. The caller must already hold the ledger-root lock."""
    dropped = repair_partial_tail(path)
    if isinstance(data, str):
        data = data.encode('utf-8')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return dropped


def read_modify_write(path, fn, root=None):
    """持账本根锁读-改-写。fn(old_bytes) -> new_bytes。写入走 atomic_write。
    Locked (ledger root) read-modify-write. fn(old_bytes) -> new_bytes; the write is atomic.
    用于游标 json（修②）：读旧值→改→写回，全程持锁。
    Used for cursor json (fix ②): read the old value → modify → write back, holding the lock throughout."""
    with locked(root if root else path):
        if os.path.exists(path):
            with open(path, 'rb') as f:
                old = f.read()
        else:
            old = b''
        new = fn(old)
        atomic_write(path, new)
