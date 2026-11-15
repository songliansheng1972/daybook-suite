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
import os, contextlib, threading, tempfile, time

try:
    import fcntl
except ImportError:                                     # pragma: no cover - POSIX only
    fcntl = None

# 进程内持有表：{锁目录 realpath: {'fd','owner'}}。owner = 持锁线程 ident。
# 只有**本线程**持有才算持有（exclusive_held 据此判定）：同进程另一线程不继承、
# 也不复用 fd——它必须在 threading.Lock 上排队，与跨进程 flock 语义一致。
# Process-wide held map: {lock dir realpath: {'fd','owner'}}, owner = holding thread id.
# Only **this thread** counts as holding (exclusive_held judges by owner): another thread of the
# same process inherits nothing and reuses no fd — it queues on a threading.Lock, matching the
# cross-process flock semantics.
_PROC = {}

# 每个锁目录一把进程内互斥（threading.Lock）：跨线程必须排队（这是「同一账本根下所有写
# 操作串行」的线程侧实现；跨进程由 flock 独占）。
# One in-process mutex (threading.Lock) per lock dir: threads must queue — the thread-side half
# of "all writes under one ledger root are serialized"; cross-process exclusion is the flock.
_MUTEX = {}
_MUTEX_GUARD = threading.Lock()


def _proc_mutex(lp):
    with _MUTEX_GUARD:
        m = _MUTEX.get(lp)
        if m is None:
            m = threading.Lock()
            _MUTEX[lp] = m
        return m


def exclusive_held(path):
    """**本线程**是否对该目录持独占锁（同进程别的线程持有不算）。
    Whether **this thread** holds an exclusive lock on that directory (another thread's hold
    in the same process does not count)."""
    e = _PROC.get(_lock_dir(path))
    return bool(e and e['owner'] == threading.get_ident())


def _lock_dir(path):
    """锁目标＝目录本身：目标所在目录的 realpath（目标本身是目录则取它）。
    锁的身份是目录 inode，与 TMPDIR、用户名、启动方式无关；不落任何文件。
    Lock target = the directory itself: realpath of the containing directory (or the path
    itself when it is a directory). The lock identity is the directory inode, independent of
    TMPDIR / user / how the process was started, and no file is created."""
    p = os.path.realpath(path)
    return p if os.path.isdir(p) else os.path.dirname(p)


@contextlib.contextmanager
def locked(path, timeout=None):
    """账本根**独占**锁上下文（没有共享锁这回事）。
    Ledger-root **exclusive** lock context (there is no shared-lock mode).
    同一账本根下所有写操作串行：线程间排队（threading.Lock），跨进程 flock 独占。
    All writes under one ledger root are serialized: threads queue on a threading.Lock and
    processes contend on the exclusive flock.
    退出自动释放（fd close ⇒ flock 自动解）。
    Released automatically on exit (fd close ⇒ flock auto-unlock).
    同线程可重入：本线程已在临界区内再取同一把锁只加深度（不再开第二个 fd）；
    产品代码靠这一点在「持根锁」内调用 atomic_append（租约卷/任务卷）。
    Reentrant within one thread: re-locking the same directory inside this thread's held critical
    section only bumps a depth counter (no second fd). Product code relies on it to call
    atomic_append (lease/task volumes) while the root lock is held.
    timeout 秒内拿不到则超时；None=阻塞等待。
    Times out if not acquired within timeout seconds; None=block indefinitely."""
    lp = _lock_dir(path)
    me = threading.get_ident()
    ent = _PROC.get(lp)
    if ent is not None and ent['owner'] == me:
        yield ent['fd']
        return
    if fcntl is None:
        raise RuntimeError('safeio: 本版仅支持 POSIX（fcntl/flock）；Windows 需另开单用命名互斥量')
    mx = _proc_mutex(lp)
    t0 = time.time()
    if timeout is None:
        mx.acquire()
    elif timeout <= 0:
        if not mx.acquire(blocking=False):
            raise TimeoutError('safeio: lock timeout for %s' % path)
    elif not mx.acquire(timeout=timeout):
        raise TimeoutError('safeio: lock timeout for %s' % path)
    try:
        # 打开目录本身取 fd：不新建文件，不需要写权限；flock 绑在目录 inode 上。
        # Open the directory itself: no file is created, no write permission is required,
        # and the flock is bound to the directory inode.
        fd = os.open(lp, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            if timeout is None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                deadline = t0 + timeout
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except (BlockingIOError, OSError):
                        if time.time() >= deadline:
                            raise TimeoutError('safeio: lock timeout for %s' % path)
                        time.sleep(0.05)
        except BaseException:
            os.close(fd)
            raise
        _PROC[lp] = {'fd': fd, 'owner': me}
        try:
            yield fd
        finally:
            _PROC.pop(lp, None)
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
    finally:
        mx.release()


def atomic_write(path, data, mode=None):
    """原子替换写：同目录临时文件 + os.replace（★唯一实现，派生件一律走这里）。
    Atomic replace: a temp file in the same directory + os.replace (★ the single implementation;
    every derived artifact goes through it). Readers never see a half-written file.
    mode 给出时在 mkstemp 后 fchmod（如密钥 0600）；缺省沿用现有（默认 0600 受 umask 影响前的
    mkstemp 语义，即替换后权限沿用临时件）。
    With `mode`, fchmod the temp fd right after mkstemp (e.g. 0600 for keys); without it the
    existing behaviour (the mkstemp temp file's mode) is kept.
    本函数**不取锁**：它是纯原子替换，与任何锁形态无关，因此不存在「共享/跨线程降级」路径；
    需要读-判-写的调用方自行在 `locked(账本根)` 临界区内调用（产品件一律如此）。
    This function takes **no lock**: it is a pure atomic replace, independent of any lock state,
    so there is no shared/cross-thread downgrade path. Callers that need read-check-write call it
    inside their own `locked(ledger_root)` critical section (all product code does)."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        if mode is not None:
            os.fchmod(fd, mode)
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


def atomic_append(path, data, root=None, ensure_newline=False):
    """持账本根锁追加。O_APPEND + 单次 write。只走独占锁：本线程已持则直接写（临界区内），
    否则在独占锁上排队；没有共享锁、也没有跨线程复用。
    Append while holding the ledger-root lock. O_APPEND + a single write. Exclusive only: if this
    thread already holds it, write inside the critical section; otherwise queue on the exclusive
    lock. There is no shared lock and no cross-thread fd reuse.
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


def append_inplace(path, data, root=None, conf_path=None):
    """持账本根锁原位追加：追加型派生件的唯一写入口。
    Single write entry for append-type artifacts, appending in place under the ledger-root lock.

    语义只有一句：**追加到文件末尾；若末字节不是换行，先补一个换行，其余字节一概不动。**
    Semantics, in one sentence: **append at end of file; if the last byte is not a newline,
    first add one newline — every other byte is left untouched.**

    ★ 不截断、不修复半行。末尾无换行既可能是崩溃残行，也可能是合法的完整行，静态无法区分；
      增量路径由调用方先判、转全量重建（见 daybook.build）。
    ★ No truncation and no half-line repair. A newline-less tail may be a crash residue or a
      legal complete line; that cannot be told apart statically, so the incremental caller
      detects it first and falls back to a full rebuild (see daybook.build).

    账本根**不许由调用方自报**：内部用 ledger_root 同一套解析（conf_path 指定，缺省按
    locate() 找当前 conf）得出根；传入 root 与解析结果逐字不同即 RuntimeError。
    The ledger root is **never taken on the caller's word**: it is resolved internally through
    the same ledger_root path (conf_path when given, else locate()); a `root` that differs
    verbatim from the resolution raises RuntimeError.

    锁前置：**本线程**必须在**该账本根**上持**独占**锁（别的线程持锁、子目录锁、别的根都不算）。
    先判后开文件 ⇒ 不满足时零写。返回 True 表示补过换行，False 表示末字节本来是换行。
    Lock precondition: **this thread** must hold an **exclusive** lock on **that ledger root**
    (a lock held by another thread, a sub-directory lock and another root do not count). All
    checks run before the file is opened ⇒ nothing is written when they fail. Returns True when
    a newline was padded, False when the last byte already was one."""
    from ledger_root import locate, read_conf_value, resolve_root
    if conf_path:
        conf_dir = os.path.realpath(os.path.dirname(os.path.abspath(conf_path)))
    else:
        conf_dir, conf_path = locate()
        if not conf_path:
            raise RuntimeError('safeio.append_inplace: 找不到 daybook.conf（%s）·拒绝写入（零写）'
                               % conf_dir)
    resolved = resolve_root(conf_dir, {'index': {'root': read_conf_value(conf_path, 'index', 'root')}})
    if root is not None and os.path.realpath(root) != resolved:
        raise RuntimeError('safeio.append_inplace: 传入的账本根（%s）与 conf 解析结果（%s）不一致'
                           '·拒绝写入（零写）' % (os.path.realpath(root), resolved))
    if not exclusive_held(resolved):
        raise RuntimeError('safeio.append_inplace: 未在本线程于账本根（%s）持独占锁'
                           '（别的线程持锁/子目录锁/别的根都不算）·拒绝写入（零写）' % resolved)
    if isinstance(data, str):
        data = data.encode('utf-8')
    padded = False
    if data and os.path.exists(path):
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b'\n':
                    data = b'\n' + data
                    padded = True
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return padded


def read_modify_write(path, fn, root=None):
    """持账本根锁读-改-写。fn(old_bytes) -> new_bytes。写入走 atomic_write。
    Locked (ledger root) read-modify-write. fn(old_bytes) -> new_bytes; the write is atomic.
    只走独占锁：本线程已持则直接读写（临界区内），否则排队；无共享锁降级路径。
    Exclusive only: if this thread already holds the root lock it works inside that critical
    section; otherwise it queues on the exclusive lock. No shared-lock downgrade path.
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
