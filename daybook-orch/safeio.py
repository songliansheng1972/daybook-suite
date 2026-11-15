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

# 进程内持有表：{锁身份: {'fd','owner'}}，锁身份＝目录 inode (st_dev, st_ino)。
# 只有**本线程**持有才算持有（exclusive_held 据此判定）：同进程另一线程不继承、
# 也不复用 fd——它必须在 threading.Lock 上排队，与跨进程 flock 语义一致。
# Process-wide held map: {lock identity: {'fd','owner'}}, identity = dir inode (st_dev, st_ino).
# Only **this thread** counts as holding (exclusive_held judges by owner): another thread of the
# same process inherits nothing and reuses no fd — it queues on a threading.Lock, matching the
# cross-process flock semantics.
_PROC = {}

# 每个锁身份一把进程内互斥（threading.Lock）：跨线程必须排队（这是「同一账本根下所有写
# 操作串行」的线程侧实现；跨进程由 flock 独占）。
# One in-process mutex (threading.Lock) per lock identity: threads must queue — the thread-side
# half of "all writes under one ledger root are serialized"; cross-process exclusion is the flock.
_MUTEX = {}
_MUTEX_GUARD = threading.Lock()


def _proc_mutex(key):
    with _MUTEX_GUARD:
        m = _MUTEX.get(key)
        if m is None:
            m = threading.Lock()
            _MUTEX[key] = m
        return m


def _lock_dir(path):
    """锁目标＝目录本身：目标所在目录的 realpath（目标本身是目录则取它）。
    Lock target = the directory itself: realpath of the containing directory (or the path
    itself when it is a directory)."""
    p = os.path.realpath(path)
    return p if os.path.isdir(p) else os.path.dirname(p)


def _ident(path):
    """锁身份＝(st_dev, st_ino)：realpath 字符串不归一大小写、NFD/NFC、软链、尾斜杠，
    不能当键；字符串只用于报错文案。两条写法指向同一 inode 即同一把锁。
    路径不存在 ⇒ 明确报「账本根不存在」（不退回父目录去锁）。
    Lock identity = (st_dev, st_ino): a realpath string does not normalize case, NFD/NFC,
    symlinks or trailing slashes, so it cannot be the key; the string is error text only.
    Two spellings of one inode are one lock. A missing path ⇒ explicit "ledger root missing"
    error (never fall back to locking the parent)."""
    if not os.path.exists(path):
        raise RuntimeError('safeio.locked: 账本根不存在（%s）·拒绝加锁（不退回父目录）' % path)
    lp = _lock_dir(path)
    try:
        st = os.stat(lp)
    except OSError as e:
        raise RuntimeError('safeio.locked: 账本根不可访问（%s）：%s' % (lp, e.strerror))
    return (st.st_dev, st.st_ino), lp


def exclusive_held(path):
    """**本线程**是否对该目录持独占锁（同进程别的线程持有不算）。
    Whether **this thread** holds an exclusive lock on that directory (another thread's hold
    in the same process does not count)."""
    e = _PROC.get(_ident(path)[0])
    return bool(e and e['owner'] == threading.get_ident())


@contextlib.contextmanager
def locked(path, timeout=None):
    """账本根**独占**锁上下文（没有共享锁这回事）。
    Ledger-root **exclusive** lock context (there is no shared-lock mode).
    同一账本根下所有写操作串行：线程间排队（threading.Lock），跨进程 flock 独占。
    All writes under one ledger root are serialized: threads queue on a threading.Lock and
    processes contend on the exclusive flock.
    退出自动释放（fd close ⇒ flock 自动解）。
    Released automatically on exit (fd close ⇒ flock auto-unlock).
    同线程再取（任意写法，只要指向同一 inode）⇒ 立即 RuntimeError，不等待、不静默放行；
    临界区内要写请用 atomic_append / append_inplace（它们检测到本线程已持锁就直接写）。
    Re-acquiring in the same thread (any spelling that hits the same inode) ⇒ immediate
    RuntimeError — no waiting, no silent pass-through. Inside a critical section write through
    atomic_append / append_inplace, which append directly when this thread already holds it.
    timeout 秒内拿不到则超时；None=阻塞等待。
    Times out if not acquired within timeout seconds; None=block indefinitely."""
    key, lp = _ident(path)
    me = threading.get_ident()
    ent = _PROC.get(key)
    if ent is not None and ent['owner'] == me:
        raise RuntimeError('safeio.locked: 同线程重复获取账本根锁（%s）·拒绝等待'
                           '（同线程重入必自死锁）' % lp)
    if fcntl is None:
        raise RuntimeError('safeio: 本版仅支持 POSIX（fcntl/flock）；Windows 需另开单用命名互斥量')
    mx = _proc_mutex(key)
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
        _PROC[key] = {'fd': fd, 'owner': me}
        try:
            yield fd
        finally:
            _PROC.pop(key, None)
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
    finally:
        mx.release()


def _real_root(root, who):
    """root 必填（账本根）；返回 realpath 归一值。`root` is mandatory; returns its realpath."""
    if not root:
        raise RuntimeError('%s: 必须显式传 root（账本根）·'
                           '不再回退到目标所在目录（那会绕过根锁）' % who)
    return os.path.realpath(root)


def _rel_parts(path, root_real, who):
    """算目标相对根的分量：目标的父目录交给 `os.path.realpath` 解释（`..` 按真实文件系统
    语义、先解软链再上跳），再从那一点起逐级向上，按 (st_dev, st_ino) 找到与根同一 inode
    的目录即止。归属判据是 **inode**，不是字符串前缀，也不做 `abspath` 的词法折叠——
    `root/link/../x`（link 指向根外）解析到根外即拒绝，不会被折成 root/x 静默改道。
    大小写、NFC/NFD、`/tmp` ↔ `/private/tmp`、尾斜杠等写法只要指向同一 inode 都算根内。
    末段保留原名，由 `O_NOFOLLOW` 拒绝软链。
    Components are computed by resolving the target's parent through `os.path.realpath`
    (`..` follows real filesystem semantics: symlinks first, then up), then walking **up by
    inode** until a directory with the same (st_dev, st_ino) as the root. Containment is judged
    by inode, not a string prefix, and `abspath` lexical folding is deliberately absent:
    `root/link/../x` (link → outside) resolves outside and is refused instead of being silently
    rerouted to root/x. Case variants, NFC/NFD spellings, `/tmp` ↔ `/private/tmp` and trailing
    slashes all count as inside when they hit the same inode. The final component keeps its
    original spelling and a symlink there is refused by O_NOFOLLOW."""
    raw = path.rstrip(os.sep) or os.sep
    cur = os.path.realpath(os.path.dirname(raw))
    try:
        rst = os.stat(root_real)
    except OSError as exc:
        raise RuntimeError('%s: 账本根（%s）不可访问（%s）·拒绝写入（零写）'
                           % (who, root_real, exc)) from None
    root_id = (rst.st_dev, rst.st_ino)
    parts = []
    while True:
        try:
            st = os.stat(cur)
        except OSError as exc:
            raise RuntimeError('%s: 目标（%s）的祖先目录不可用（%s）·拒绝写入（零写）'
                               % (who, path, exc)) from None
        if (st.st_dev, st.st_ino) == root_id:
            break
        up = os.path.dirname(cur)
        if up == cur:
            raise RuntimeError('%s: 目标（%s）不在账本根（%s）内·拒绝写入（零写）'
                               % (who, path, root_real))
        parts.append(os.path.basename(cur))
        cur = up
    parts.reverse()
    name = os.path.basename(raw)
    if name in ('', os.curdir, os.pardir):
        raise RuntimeError('%s: 目标（%s）不是可写文件·拒绝写入（零写）' % (who, path))
    parts.append(name)
    return parts


def _open_root_dir(root_real, who):
    """打开账本根目录 fd，并复核其 inode 与取锁身份一致（防根被换）。"""
    try:
        fd = os.open(root_real, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise RuntimeError('%s: 账本根（%s）不可打开（%s）·拒绝写入（零写）'
                           % (who, root_real, exc)) from None
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != _ident(root_real)[0]:
            raise RuntimeError('%s: 账本根（%s）在加锁后被替换·拒绝写入（零写）'
                               % (who, root_real))
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_parent_at(root_real, parts, who):
    """★唯一走查实现：从账本根目录 fd 起逐级 openat O_NOFOLLOW|O_DIRECTORY 到目标父目录，
    返回 (父目录 fd, 末段名)；调用方负责关闭 fd。
    ★The single walk implementation: openat each component from the ledger-root directory fd with
    O_NOFOLLOW|O_DIRECTORY down to the target's parent; returns (parent fd, final name) and the
    caller closes the fd."""
    root_fd = _open_root_dir(root_real, who)
    fd = os.dup(root_fd)
    os.close(root_fd)
    try:
        for comp in parts[:-1]:
            try:
                nfd = os.open(comp, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=fd)
            except OSError as exc:
                raise RuntimeError('%s: 目标（%s）的祖先目录不可用（%s）·拒绝写入（零写）'
                                   % (who, os.path.join(*parts), exc)) from None
            os.close(fd)
            fd = nfd
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def _atomic_replace_at(dfd, name, data, mode, who):
    """在目标目录 fd 上落临时件并 os.replace（src_dir_fd/dst_dir_fd 同 fd），不碰任何路径字面。"""
    tmp = '.%s.%s.tmp' % (name, os.urandom(6).hex())
    try:
        tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      mode if mode is not None else 0o600, dir_fd=dfd)
    except OSError as exc:
        raise RuntimeError('%s: 创建临时件（%s）失败（%s）·拒绝写入（零写）'
                           % (who, name, exc)) from None
    try:
        try:
            os.write(tfd, data)
            os.fsync(tfd)
        finally:
            os.close(tfd)
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    except OSError as exc:
        try:
            os.unlink(tmp, dir_fd=dfd)
        except OSError:
            pass
        raise RuntimeError('%s: 原子替换（%s）失败（%s）·拒绝写入'
                           % (who, name, exc)) from None


def atomic_write(path, data, mode=None, root=None):
    """原子替换写：目标目录 fd 上落临时件 + os.replace(src_dir_fd/dst_dir_fd)。
    Atomic replace: a temp file in the target directory fd + os.replace with src/dst dir_fd.
    ★ root 必填（账本根）；临时件与 replace 全走 openat 走查，不再有第二条路径字面打开。
    ★ `root` is mandatory; the temp file and the replace both go through the openat walk, so
    there is no second literal-path write path.
    本函数**不取锁**：纯原子替换，调用方自行决定临界区。
    This function takes **no lock**: a pure atomic replace; the caller decides the critical
    section."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    who = 'safeio.atomic_write'
    root_real = _real_root(root, who)
    dfd, name = _open_parent_at(root_real, _rel_parts(path, root_real, who), who)
    try:
        _atomic_replace_at(dfd, name, data, mode, who)
    finally:
        os.close(dfd)


def _append_now(root, path, data, ensure_newline, who='safeio.atomic_append', create=True):
    """已在临界区内：走 openat 唯一走查直接追加（不取锁）。Returns padded.
    Inside the critical section: append through the single openat walk (no lock).
    create=False（append_inplace）：目标必须已存在，绝不隐式创建。写后复核
    `stat(path)` 与写 fd 的 inode 一致；不一致即视为「追加期间被替换」，抛错不静默。
    create=False (append_inplace): the target must already exist — never create implicitly.
    After writing, `stat(path)` is compared with the write fd's inode; a mismatch means the
    target was replaced mid-append and raises instead of failing silently."""
    root_real = _real_root(root, who)
    dfd, name = _open_parent_at(root_real, _rel_parts(path, root_real, who), who)
    try:
        padded = False
        flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
        if create:
            flags |= os.O_CREAT
        try:
            tfd = os.open(name, flags, 0o644, dir_fd=dfd)
        except FileNotFoundError:
            raise RuntimeError('%s: 目标（%s）不存在·append 不创建（要建请用 atomic_write）'
                               % (who, path)) from None
        try:
            wst = os.fstat(tfd)
            if ensure_newline and data:
                # 末字节检查另开只读 fd；读不到（只写/拒读）就跳过补换行，不影响追加。
                # The last-byte check uses a separate read-only fd; if it cannot be opened
                # (write-only / read denied) padding is skipped and the append proceeds.
                try:
                    rfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
                except PermissionError:
                    rfd = None
                if rfd is not None:
                    try:
                        size = os.fstat(rfd).st_size
                        if size > 0 and os.pread(rfd, 1, size - 1) != b'\n':
                            data = b'\n' + data
                            padded = True
                    finally:
                        os.close(rfd)
            os.write(tfd, data)
            try:
                now = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            except OSError:
                now = None
            if now is None or (now.st_dev, now.st_ino) != (wst.st_dev, wst.st_ino):
                raise RuntimeError('%s: 目标（%s）在追加期间被替换·数据可能未落盘'
                                   % (who, path))
        finally:
            os.close(tfd)
        return padded
    except OSError as exc:
        raise RuntimeError('%s: 目标（%s）不可用（%s）·拒绝写入（零写）'
                           % (who, path, exc)) from None
    finally:
        os.close(dfd)


def atomic_append(path, data, root=None, ensure_newline=False):
    """持账本根锁追加。O_APPEND + 单次 write。只走独占锁：本线程已持则直接写（临界区内），
    否则在独占锁上排队；没有共享锁、也没有跨线程复用。
    Append while holding the ledger-root lock. O_APPEND + a single write. Exclusive only: if this
    thread already holds it, write inside the critical section; otherwise queue on the exclusive
    lock. There is no shared lock and no cross-thread fd reuse.
    ★ root 必须显式给出（账本根；子目录卷也争同一把锁）。省略不再回退到「目标所在目录」——
      那条兜底会让异线程持根锁时照样零等待写入，故删除。
    ★ `root` is mandatory (the ledger root; sub-directory volumes contend on it too). The old
      fallback to "the target's own directory" is gone: it let another thread write with zero
      wait while the root was held.
    ensure_newline=True：锁内看末字节，不是 \\n 就先补一个（既有字节不动），
    返回 True 表示补过；避免新条目粘在合法但无换行的末行行尾。
    ensure_newline=True: under the lock, check the last byte and prepend one \\n when it is
    missing (existing bytes untouched); True means it padded. This stops a new entry from
    being glued onto a legal last line that simply lacked a newline."""
    if not root:
        raise RuntimeError('safeio.atomic_append: 必须显式传 root（账本根）·'
                           '不再回退到目标所在目录（那会绕过根锁）')
    if isinstance(data, str):
        data = data.encode('utf-8')
    if exclusive_held(root):
        return _append_now(root, path, data, ensure_newline)
    with locked(root):
        return _append_now(root, path, data, ensure_newline)


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

    ★ **目标必须已存在**：本函数不创建目标（无 `O_CREAT`）；不存在即 RuntimeError。
      要建新件请用 `atomic_write`（它负责临时件 + 原子换入）。
    ★ **The target must already exist**: this function never creates it (no `O_CREAT`); a
      missing target raises RuntimeError. Create new artifacts with `atomic_write` instead.

    账本根**不许由调用方自报**：内部用 ledger_root 同一套解析（conf_path 指定，缺省按
    locate() 找当前 conf）得出根；传入 root 与解析结果逐字不同即 RuntimeError。
    The ledger root is **never taken on the caller's word**: it is resolved internally through
    the same ledger_root path (conf_path when given, else locate()); a `root` that differs
    verbatim from the resolution raises RuntimeError.

    归属靠**物理走查**（与 atomic_append / read_modify_write / atomic_write 共用同一实现）：
    从账本根目录 fd 出发，用 openat（dir_fd）逐级 O_NOFOLLOW|O_DIRECTORY 走到目标所在目录，
    最后一级 openat 打开目标文件（O_APPEND|O_NOFOLLOW）。每级都必须是真目录，路径物理上出
    不去；父目录先 `realpath` 按真实文件系统解释（`..` 先解软链再上跳，不做词法折叠），
    大小写、NFC/NFD、`/tmp` 与 `/private/tmp` 等别名混写不会误拒。
    Containment is a **physical walk** (the same implementation shared by atomic_append,
    read_modify_write and atomic_write): from the ledger-root directory fd, openat each component
    with O_NOFOLLOW|O_DIRECTORY down to the target's directory, then openat the target with
    O_APPEND|O_NOFOLLOW. Every level must be a real directory, so the path physically cannot
    leave; the parent is resolved by `realpath` with real filesystem semantics (`..` follows
    symlinks first, no lexical folding), so case, NFC/NFD and alias spellings
    (/tmp vs /private/tmp) are not falsely rejected.

    ⚠ 威胁模型：防「路径重定向」（软链/别名把写入指向根外），**不防已进入目录被整体 rename
      搬走**——fd 语义固有，目录 fd 一旦取得，后续写入落在该 inode 上。这里不宣称「已封死」。
    ⚠ Threat model: it stops **path redirection** (symlink/alias pointing outside), but not a
      directory that is renamed away after it was entered — that is inherent to fd semantics:
      once the directory fd is held, writes land on that inode. No "fully sealed" claim.

    锁前置：**本线程**必须在**该账本根**上持**独占**锁（别的线程持锁、子目录锁、别的根都不算）。
    先判后开文件 ⇒ 不满足时零写。返回 True 表示补过换行，False 表示末字节本来是换行。
    读不到末字节时（只写目标，或 ACL／权限拒读）**跳过补换行**：只追加、不加前缀换行，
    此时返回 False——不看末字节就无法判定是否需要补。
    Lock precondition: **this thread** must hold an **exclusive** lock on **that ledger root**
    (a lock held by another thread, a sub-directory lock and another root do not count). All
    checks run before the file is opened ⇒ nothing is written when they fail. Returns True when
    a newline was padded, False when the last byte already was one. When the last byte cannot be
    read (write-only target, or read denied by ACL/permissions) padding is **skipped**: the data
    is appended as-is and False is returned — without inspecting the tail there is no way to
    tell whether padding is needed."""
    from ledger_root import locate, read_conf_value, resolve_root
    who = 'safeio.append_inplace'
    if conf_path:
        conf_dir = os.path.realpath(os.path.dirname(os.path.abspath(conf_path)))
    else:
        conf_dir, conf_path = locate()
        if not conf_path:
            raise RuntimeError('%s: 找不到 daybook.conf（%s）·拒绝写入（零写）'
                               % (who, conf_dir))
    resolved = resolve_root(conf_dir, {'index': {'root': read_conf_value(conf_path, 'index', 'root')}})
    if root is not None and os.path.realpath(root) != resolved:
        raise RuntimeError('%s: 传入的账本根（%s）与 conf 解析结果（%s）不一致'
                           '·拒绝写入（零写）' % (who, os.path.realpath(root), resolved))
    if not exclusive_held(resolved):
        raise RuntimeError('%s: 未在本线程于账本根（%s）持独占锁'
                           '（别的线程持锁/子目录锁/别的根都不算）·拒绝写入（零写）'
                           % (who, resolved))
    if isinstance(data, str):
        data = data.encode('utf-8')
    return _append_now(resolved, path, data, True, who=who, create=False)


def read_modify_write(path, fn, root=None):
    """持账本根锁读-改-写。fn(old_bytes) -> new_bytes。写入走原子替换（openat 走查）。
    Locked (ledger root) read-modify-write. fn(old_bytes) -> new_bytes; the write is an atomic
    replace through the same openat walk (no literal-path second implementation).
    只走独占锁：本线程已持则直接读写（临界区内），否则排队；无共享锁降级路径。
    Exclusive only: if this thread already holds the root lock it works inside that critical
    section; otherwise it queues on the exclusive lock. No shared-lock downgrade path.
    ★ root 必须显式给出（账本根），省略即报错；不再回退到目标所在目录。
    ★ `root` is mandatory; omitting it raises instead of falling back to the target's directory.
    用于游标 json（修②）：读旧值→改→写回，全程持锁。
    Used for cursor json (fix ②): read the old value → modify → write back, holding the lock throughout."""
    who = 'safeio.read_modify_write'
    root_real = _real_root(root, who)

    def _rmw():
        dfd, name = _open_parent_at(root_real, _rel_parts(path, root_real, who), who)
        try:
            try:
                rfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
            except FileNotFoundError:
                old = b''
            else:
                try:
                    chunks = []
                    while True:
                        blk = os.read(rfd, 65536)
                        if not blk:
                            break
                        chunks.append(blk)
                    old = b''.join(chunks)
                finally:
                    os.close(rfd)
            _atomic_replace_at(dfd, name, fn(old), None, who)
        except OSError as exc:
            raise RuntimeError('%s: 目标（%s）不可用（%s）·拒绝写入（零写）'
                               % (who, path, exc)) from None
        finally:
            os.close(dfd)

    if exclusive_held(root_real):
        _rmw()
    else:
        with locked(root_real):
            _rmw()
