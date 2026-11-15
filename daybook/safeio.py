#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""SafeIO · 根句柄 + 唯一写链（W-75·造①）
SafeIO · root handle + the single write chain (W-75 · build ①)
================================================
四个单一所有权（架构收口版 · 步骤 1）：
  Root        账本根的唯一样本：目录 fd + dev_ino（fstat 一次）+ 只用于文案的 label。
  Rel         已校验的相对段序列；构造即合法，别处不再校验。
  LockedRoot  持锁凭证；写方法只存在于此类型上。
  WriteMode   追加创建 / 追加已存在 / 原子替换，三选一，不再有布尔参数分叉。

旧四原语（locked / atomic_append / append_inplace / read_modify_write / atomic_write）
保留为**薄适配器**：只做「路径 → Rel」和「取锁/复用本线程已持锁」，写链一律进
LockedRoot.write。适配器在步骤 3 删除，不是第二套实现。

锁粒度：目录级——flock 账本根目录本身的 fd（O_RDONLY|O_DIRECTORY），全程不新建任何文件。
锁身份只来自 fstat(root_fd) 的 (st_dev, st_ino)：同 inode 的任何写法都是同一把锁。
Lock granularity: directory-level — flock the ledger-root directory fd itself; identity comes
only from fstat(root_fd), so every spelling of one inode is the same lock.

换根语义（由 fd 定义，不靠复核）：写永远落在 Root 打开时的那个 inode 上。根路径在运行中
被换走，已持有的 LockedRoot 仍写旧 inode；要「路径现在还是我」的场合，入口显式调用
root.revalidate()。没有「加锁后现算 inode 再比对」这类自证判据。
Root-swap semantics are defined by the fd, not by re-checking: a write always lands on the inode
captured when Root was opened. If the path is swapped mid-run, a held LockedRoot keeps writing
the old inode; entries that need "the path is still me" call root.revalidate() explicitly.

读者：`read_vol` 不取任何锁。卷是 append-only，派生件一律「同目录临时文件 + os.replace」
原子换入，读者拿到的永远是一致快照，且不会被写者的临界区整段阻塞。
Readers: `read_vol` takes no lock. Volumes are append-only and every derived artifact is swapped
in atomically (temp file in the same directory + os.replace), so a reader always sees a
consistent snapshot and is never blocked for the whole writer critical section.
"""
import contextlib
import enum
import os
import threading
import time

try:
    import fcntl
except ImportError:                                     # pragma: no cover - POSIX only
    fcntl = None

# 进程内持有表：{锁身份: {'fd','owner'}}，锁身份**只能**是 Root.dev_ino 的 (st_dev, st_ino)。
# 只有**本线程**持有才算持有：同进程另一线程不继承、也不复用 fd——它必须在 threading.Lock
# 上排队，与跨进程 flock 语义一致。
# Process-wide held map: {lock identity: {'fd','owner'}}; the identity can only be Root.dev_ino.
# Only **this thread** counts as holding: another thread inherits nothing and reuses no fd — it
# queues on a threading.Lock, matching the cross-process flock semantics.
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


_TLS = threading.local()


def _held_list():
    """本线程已持的 LockedRoot 栈（只给**适配器**查「本线程是否已持锁/该复用哪个根」用；
    它不是锁身份：锁身份只在 Root.dev_ino）。"""
    lst = getattr(_TLS, 'held', None)
    if lst is None:
        lst = []
        _TLS.held = lst
    return lst


def _held_for(path):
    """本线程在 `path` 所指账本根上已持的 LockedRoot；没有则 None。
    The LockedRoot this thread already holds for the ledger root `path` names, else None.
    先按 label（realpath 字符串）匹配：换根后路径仍叫同一个名字，复用的必须是打开时那个
    inode（探针 1/3b 的语义）。再按 dev_ino 兜住大小写/别名等不同拼写。
    Label first (the path still has the same name after a swap, and the held handle must keep the
    inode it opened); then dev_ino for case/alias spellings of a still-existing path."""
    try:
        lp = os.path.realpath(path)
    except OSError:
        return None
    held = _held_list()
    for lr in reversed(held):
        if lr.root.label == lp:
            return lr
    try:
        st = os.stat(lp)
    except OSError:
        return None
    ident = (st.st_dev, st.st_ino)
    for lr in reversed(held):
        if lr.root.dev_ino == ident:
            return lr
    return None


class WriteMode(enum.Enum):
    """写入语义的三选一：追加（可创建）/ 追加（必须已存在）/ 原子替换。
    The three write semantics: append (may create) / append (must exist) / atomic replace."""
    APPEND_CREATE = 'append_create'
    APPEND_EXISTING = 'append_existing'
    REPLACE = 'replace'


class Rel:
    """已校验的相对段序列。构造即合法；`..`、`.`、空段、分隔符一律拒绝。
    A validated relative-segment sequence: `..`, `.`, empty segments and separators are refused
    at construction, so no other place needs to re-validate."""
    __slots__ = ('parts',)

    def __init__(self, parts):
        parts = tuple(parts)
        if not parts:
            raise RuntimeError('safeio.Rel: 空相对路径·拒绝（账本根本身不是可写目标）')
        for seg in parts:
            if not isinstance(seg, str) or not seg:
                raise RuntimeError('safeio.Rel: 空段·拒绝（%r）' % (seg,))
            if seg in (os.curdir, os.pardir):
                raise RuntimeError('safeio.Rel: 段 %r 不允许（不做词法折叠）' % seg)
            if os.sep in seg or os.altsep and os.altsep in seg or (os.sep != '/' and '/' in seg):
                raise RuntimeError('safeio.Rel: 段 %r 含路径分隔符·拒绝' % seg)
            if seg.startswith('/') or ('\x00' in seg):
                raise RuntimeError('safeio.Rel: 段 %r 非法·拒绝' % seg)
        self.parts = parts

    def __repr__(self):
        return 'Rel(%r)' % (self.parts,)


def _walk_parent(root_fd, parts, who):
    """★唯一走查实现：从账本根目录 fd 起逐级 openat O_NOFOLLOW|O_DIRECTORY 到目标父目录，
    返回 (父目录 fd, 末段名)；调用方负责关闭 fd。
    ★The single walk implementation: openat each component from the ledger-root directory fd with
    O_NOFOLLOW|O_DIRECTORY down to the target's parent; returns (parent fd, final name) and the
    caller closes the fd."""
    fd = os.dup(root_fd)
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


def _lex_rel(root, path):
    """按 Root 的**原始拼写**（orig）做纯文本取相对段：只截前缀，不做 abspath 折叠、
    不跟随软链。结果仍要交给 openat O_NOFOLLOW 逐段物理校验，故它只解决「路径文本与
    realpath 拼写不同（/var ↔ /private/var）或根已被换走」时的取名问题，不承担归属判定。
    Take relative segments by plain prefix cutting against Root.orig: no abspath folding and no
    symlink following. Every segment is still physically checked by the openat walk, so this
    only names the target when the textual spelling differs from realpath (or the root path was
    swapped); it never decides containment."""
    base = root.orig
    if not base or path == base:
        return None
    prefix = base.rstrip(os.sep) + os.sep
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):].rstrip(os.sep)
    if not rest:
        return None
    return rest.split(os.sep)


def _rel_from_path(root, path, who):
    """把 `path` 变成 root 内的 Rel：目标的父目录交给 `os.path.realpath` 解释（`..` 按真实
    文件系统语义、先解软链再上跳），再从那一点起逐级向上，按 root.dev_ino 找到根即止。
    归属判据是 **inode**，不做 `abspath` 词法折叠——`root/link/../x`（link 指向根外）解析到
    根外即拒绝，不会被折成 root/x 静默改道。末段保留原名，由 O_NOFOLLOW 拒绝软链。
    真实祖先链已不再指向本根时（根路径被换走，或 /var ↔ /private/var 这类拼写差），退回
    `_lex_rel` 按 orig 取段；`..` 段由 Rel 直接拒绝，软链段由 openat O_NOFOLLOW 拒绝。
    Turn `path` into a Rel under root: the parent is resolved through `os.path.realpath` (`..`
    follows the real filesystem: symlinks first, then up), then walked up by root.dev_ino.
    Containment is judged by **inode**, with no `abspath` lexical folding, so `root/link/../x`
    resolves outside and is refused instead of silently rerouted. When the real ancestry no
    longer points at this root (the root path was swapped, or /var ↔ /private/var spelling),
    fall back to `_lex_rel` against orig; `..` segments are refused by Rel and symlink segments
    by openat O_NOFOLLOW."""
    raw = path.rstrip(os.sep) or os.sep
    name = os.path.basename(raw)
    if not name or name in (os.curdir, os.pardir):
        raise RuntimeError('%s: 目标（%s）不是可写文件·拒绝写入（零写）' % (who, path))
    try:
        cur = os.path.realpath(os.path.dirname(raw))
        parts = []
        while True:
            st = os.stat(cur)
            if (st.st_dev, st.st_ino) == root.dev_ino:
                return root.rel(*(parts[::-1] + [name]))
            up = os.path.dirname(cur)
            if up == cur:
                break
            parts.append(os.path.basename(cur))
            cur = up
    except OSError:
        pass
    lex = _lex_rel(root, path)
    if lex is not None:
        return root.rel(*lex)
    raise RuntimeError('%s: 目标（%s）不在账本根（%s）内·拒绝写入（零写）'
                       % (who, path, root.label))


class Root:
    """账本根的唯一样本：目录 fd + dev_ino（fstat 一次，永不重算）+ 展示名。
    The single sample of a ledger root: directory fd + dev_ino (fstat once, never recomputed)
    + a display name.
    label 是 realpath（只用于报错文案与适配器查找）；orig 是调用方给的原始拼写（只用于把
    同一拼写下的目标取成相对段）。两者都**不参与任何锁判定**。
    label is the realpath (error text and adapter lookup); orig is the caller's spelling (used
    only to cut relative segments). Neither decides a lock."""
    __slots__ = ('_fd', 'dev_ino', 'label', 'orig')

    def __init__(self, fd, dev_ino, label, orig):
        self._fd = fd
        self.dev_ino = dev_ino
        self.label = label
        self.orig = orig

    @classmethod
    def open(cls, conf_dir=None):
        """唯一解析入口：ledger_root.locate → conf [index] root → os.open → fstat。
        找不到 conf / 根不存在 / 根不是目录 ⇒ RuntimeError（入口按配置错处理）。
        The one resolution entry: locate → conf [index] root → open → fstat. A missing conf or
        root raises RuntimeError (entries classify it as a config error)."""
        import ledger_root
        try:
            root = ledger_root.ledger_root(conf_dir)
        except (ValueError, OSError) as exc:
            raise RuntimeError('safeio.Root.open: %s' % exc) from None
        return cls._from_dir_path(root, 'safeio.Root.open')

    @classmethod
    def _from_dir_path(cls, path, who='safeio.Root'):
        """从「账本根目录路径」构造（适配器用：旧 API 的 root 已经是根，不是 conf 目录）。
        Build from a ledger-root **directory path** (used by adapters: the old API's root is
        already the root, not a conf directory).
        旧语义保留：路径存在但是文件时，锁它所在目录；路径不存在 ⇒ 明确报「账本根不存在」。
        Old semantics kept: an existing file locks its directory; a missing path raises an
        explicit "ledger root missing" error."""
        raw = os.path.realpath(path)
        if not os.path.exists(raw):
            raise RuntimeError('%s: 账本根不存在（%s）·拒绝加锁（不退回父目录）' % (who, path))
        given = os.path.abspath(path)
        p = raw if os.path.isdir(raw) else os.path.dirname(raw)
        orig = given if os.path.isdir(given) else os.path.dirname(given)
        try:
            fd = os.open(p, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        except OSError as exc:
            raise RuntimeError('%s: 账本根不可访问（%s）：%s' % (who, p, exc.strerror)) from None
        try:
            st = os.fstat(fd)
        except BaseException:
            os.close(fd)
            raise
        return cls(fd, (st.st_dev, st.st_ino), p, orig)

    def rel(self, *segs):
        """构造一条已校验的相对路径。构造即合法，别处不再校验。
        Build a validated relative path; construction is the only validation point."""
        return Rel(segs)

    def read(self, rel):
        """无锁读：openat(self._fd) 逐级 O_NOFOLLOW|O_DIRECTORY，末段 O_RDONLY|O_NOFOLLOW。
        Lock-free read through openat from self._fd."""
        if not isinstance(rel, Rel):
            raise TypeError('safeio.Root.read: 需要 Rel（由 Root.rel 构造）')
        dfd, name = _walk_parent(self._fd, rel.parts, 'safeio.Root.read')
        try:
            ffd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        finally:
            os.close(dfd)
        try:
            chunks = []
            while True:
                blk = os.read(ffd, 65536)
                if not blk:
                    break
                chunks.append(blk)
            return b''.join(chunks)
        finally:
            os.close(ffd)

    def lock(self, timeout=None):
        """唯一取锁入口：同一 Root 只有一把锁（身份＝dev_ino）。
        同线程重入立即 RuntimeError；timeout 秒内拿不到抛 TimeoutError；None=阻塞等待。
        The only way to lock: one lock per Root (identity = dev_ino). Same-thread re-entry raises
        immediately; TimeoutError when not acquired within timeout; None blocks."""
        if fcntl is None:
            raise RuntimeError('safeio: 本版仅支持 POSIX（fcntl/flock）；'
                               'Windows 需另开单用命名互斥量')
        key = self.dev_ino
        me = threading.get_ident()
        ent = _PROC.get(key)
        if ent is not None and ent['owner'] == me:
            raise RuntimeError('safeio.locked: 同线程重复获取账本根锁（%s）·拒绝等待'
                               '（同线程重入必自死锁）' % self.label)
        mx = _proc_mutex(key)
        t0 = time.time()
        if timeout is None:
            mx.acquire()
        elif timeout <= 0:
            if not mx.acquire(blocking=False):
                raise TimeoutError('safeio: lock timeout for %s' % self.label)
        elif not mx.acquire(timeout=timeout):
            raise TimeoutError('safeio: lock timeout for %s' % self.label)
        try:
            # 打开目录本身取 fd：不新建文件，不需要写权限；flock 绑在目录 inode 上。
            # Open the directory itself: no file is created, no write permission is required,
            # and the flock is bound to the directory inode.
            if timeout is None:
                fcntl.flock(self._fd, fcntl.LOCK_EX)
            else:
                deadline = t0 + timeout
                while True:
                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except (BlockingIOError, OSError):
                        if time.time() >= deadline:
                            raise TimeoutError('safeio: lock timeout for %s' % self.label)
                        time.sleep(0.05)
        except BaseException:
            mx.release()
            raise
        _PROC[key] = {'fd': self._fd, 'owner': me}
        lr = LockedRoot(self, _LOCK_TOKEN)
        _held_list().append(lr)
        return lr

    def revalidate(self):
        """入口显式调用一次：路径现在是否仍指向打开时的 inode。写路径**不调用**它——
        写路径的承诺是「写到我打开的那个 inode」，不是「路径现在还是我」。
        Called explicitly once by an entry: does the path still name the inode we opened?
        The write path never calls it: its promise is "write to the inode I opened"."""
        try:
            st = os.stat(self.label)
        except OSError as exc:
            raise RuntimeError('safeio.Root: 账本根（%s）已不可访问（%s）·拒绝继续'
                               % (self.label, exc)) from None
        if (st.st_dev, st.st_ino) != self.dev_ino:
            raise RuntimeError('safeio.Root: 账本根（%s）已不是打开时的 inode·拒绝继续'
                               % self.label)

    def close(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


_LOCK_TOKEN = object()


class LockedRoot:
    """持有根锁的能力凭证。**写方法只在这个类型上存在**；模块外只能经 Root.lock() 得到。
    The capability token that holds the root lock. **Write methods exist only here**; outside
    this module it can only be obtained from Root.lock()."""
    __slots__ = ('root', '_released')

    def __init__(self, root, _token=None):
        if _token is not _LOCK_TOKEN:
            raise RuntimeError('safeio.LockedRoot: 只能由 Root.lock() 产生')
        self.root = root
        self._released = False

    def write(self, rel, data, *, mode, perm=0o644, pad_newline=False):
        """★唯一写链。rel 已合法；走查、错误包装、fsync、追加后 inode 复核全在这里。
        ★The single write chain: walk, error wrapping, fsync and the post-append inode check
        all live here.
        APPEND_*：末字节检查（读不到就跳过补换行）→ 写 → stat(dir_fd) 复核写 fd 的 inode。
        REPLACE：临时件（dir_fd, O_EXCL|O_NOFOLLOW）→ fsync → os.replace(dir_fd 两端) → fsync(dfd)。
        Returns the padded flag for append modes (False for REPLACE)."""
        if not isinstance(rel, Rel):
            raise TypeError('safeio.LockedRoot.write: 需要 Rel（由 Root.rel 构造）')
        if isinstance(data, str):
            data = data.encode('utf-8')
        if mode is WriteMode.REPLACE:
            return self._replace(rel, data, perm)
        return self._append(rel, data, mode, perm, pad_newline)

    def _append(self, rel, data, mode, perm, pad_newline):
        dfd, name = _walk_parent(self.root._fd, rel.parts, 'safeio.write')
        try:
            padded = False
            flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
            if mode is WriteMode.APPEND_CREATE:
                flags |= os.O_CREAT
            try:
                tfd = os.open(name, flags, perm, dir_fd=dfd)
            except FileNotFoundError:
                raise RuntimeError('safeio.write: 目标（%s）不存在·append 不创建'
                                   '（要建请用 atomic_write）'
                                   % os.path.join(*rel.parts)) from None
            try:
                wst = os.fstat(tfd)
                if pad_newline and data:
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
                    raise RuntimeError('safeio.write: 目标（%s）在追加期间被替换·数据可能未落盘'
                                       % os.path.join(*rel.parts))
            finally:
                os.close(tfd)
            return padded
        except OSError as exc:
            raise RuntimeError('safeio.write: 目标（%s）不可用（%s）·拒绝写入（零写）'
                               % (os.path.join(*rel.parts), exc)) from None
        finally:
            os.close(dfd)

    def _replace(self, rel, data, perm):
        dfd, name = _walk_parent(self.root._fd, rel.parts, 'safeio.write')
        tmp = '.%s.%s.tmp' % (name, os.urandom(6).hex())
        try:
            try:
                tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600 if perm is None else perm, dir_fd=dfd)
            except OSError as exc:
                raise RuntimeError('safeio.write: 创建临时件（%s）失败（%s）·拒绝写入（零写）'
                                   % (name, exc)) from None
            try:
                try:
                    os.write(tfd, data)
                    os.fsync(tfd)
                finally:
                    os.close(tfd)
                os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
                # 持久化语义集中在这里：替换后 fsync 目录，崩溃后名字不再指向旧 inode。
                # Persistence semantics live here: fsync the directory after the replace so a
                # crash cannot leave the name pointing at the old inode.
                os.fsync(dfd)
            except OSError as exc:
                try:
                    os.unlink(tmp, dir_fd=dfd)
                except OSError:
                    pass
                raise RuntimeError('safeio.write: 原子替换（%s）失败（%s）·拒绝写入'
                                   % (name, exc)) from None
            return False
        finally:
            os.close(dfd)

    def update(self, rel, fn):
        """持锁读-改-写：读旧值（缺件按空）→ fn → 同一个 write(REPLACE)。不是第二个原语。
        Locked read-modify-write: read (missing ⇒ empty) → fn → the same write(REPLACE)."""
        if not isinstance(rel, Rel):
            raise TypeError('safeio.LockedRoot.update: 需要 Rel（由 Root.rel 构造）')
        try:
            old = self.root.read(rel)
        except FileNotFoundError:
            old = b''
        except OSError as exc:
            raise RuntimeError('safeio.write: 目标（%s）不可用（%s）·拒绝写入（零写）'
                               % (os.path.join(*rel.parts), exc)) from None
        self.write(rel, fn(old), mode=WriteMode.REPLACE)

    def release(self):
        """释放根锁（幂等）。fd 属于 Root，不在这里关闭。
        Release the root lock (idempotent). The fd belongs to Root and is not closed here."""
        if self._released:
            return
        self._released = True
        key = self.root.dev_ino
        held = _held_list()
        try:
            held.remove(self)
        except ValueError:
            pass
        ent = _PROC.get(key)
        if ent is not None and ent.get('owner') == threading.get_ident():
            _PROC.pop(key, None)
        try:
            if fcntl is not None:
                fcntl.flock(self.root._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        _proc_mutex(key).release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def exclusive_held(path):
    """**本线程**是否对该账本根持独占锁（同进程别的线程持有不算）。
    Whether **this thread** holds an exclusive lock on that ledger root (another thread's hold
    in the same process does not count)."""
    return _held_for(path) is not None


@contextlib.contextmanager
def locked(path, timeout=None):
    """账本根**独占**锁上下文（没有共享锁这回事）。
    Ledger-root **exclusive** lock context (there is no shared-lock mode).
    同一账本根下所有写操作串行：线程间排队（threading.Lock），跨进程 flock 独占。
    All writes under one ledger root are serialized: threads queue on a threading.Lock and
    processes contend on the exclusive flock.
    退出自动释放（Root.close ⇒ flock 自动解）。
    Released automatically on exit (Root.close ⇒ flock auto-unlock).
    同线程再取（任意写法，只要指向同一 inode）⇒ 立即 RuntimeError，不等待、不静默放行。
    Re-acquiring in the same thread (any spelling that hits the same inode) ⇒ immediate
    RuntimeError — no waiting, no silent pass-through.
    timeout 秒内拿不到则超时；None=阻塞等待。"""
    ro = Root._from_dir_path(path, 'safeio.locked')
    try:
        lr = ro.lock(timeout)
        try:
            yield ro._fd
        finally:
            lr.release()
    finally:
        ro.close()


def _require_root(root, who):
    """root 必填（账本根）；不再回退到目标所在目录（那会绕过根锁）。
    `root` is mandatory; no fallback to the target's directory (that would bypass the root lock)."""
    if not root:
        raise RuntimeError('%s: 必须显式传 root（账本根）·'
                           '不再回退到目标所在目录（那会绕过根锁）' % who)


def atomic_write(path, data, mode=None, root=None):
    """原子替换写：临时件 + os.replace（dir_fd 两端）+ fsync(dfd)。
    Atomic replace: temp file + os.replace (both dir_fd) + fsync(dfd).
    ★ root 必填（账本根）。本线程已持该根锁时复用已持有的 LockedRoot（换根后仍写打开时的
      inode）；否则新开 Root 取锁，写完释放。
    ★ `root` is mandatory. When this thread already holds that root, the held LockedRoot is
      reused (after a root swap it still writes the inode it opened); otherwise a fresh Root is
      opened, locked and released.
    过渡适配器（步骤 3 删除）：写链在 LockedRoot.write。
    Transitional adapter (removed in step 3): the write chain lives in LockedRoot.write."""
    who = 'safeio.atomic_write'
    _require_root(root, who)
    if isinstance(data, str):
        data = data.encode('utf-8')
    lr = _held_for(root)
    if lr is not None:
        lr.write(_rel_from_path(lr.root, path, who), data, mode=WriteMode.REPLACE, perm=mode)
        return
    with Root._from_dir_path(root, who) as ro:
        with ro.lock() as lr:
            lr.write(_rel_from_path(ro, path, who), data, mode=WriteMode.REPLACE, perm=mode)


def atomic_append(path, data, root=None, ensure_newline=False):
    """持账本根锁追加（O_APPEND + 单次 write）。
    Append while holding the ledger-root lock (O_APPEND + a single write).
    ★ root 必须显式给出（账本根；子目录卷也争同一把锁）。省略不再回退到「目标所在目录」。
    ★ `root` is mandatory (the ledger root; sub-directory volumes contend on it too).
    ensure_newline=True：锁内看末字节，不是 \\n 就先补一个（既有字节不动），返回 True 表示
    补过；读不到末字节（只写/拒读）时跳过补换行并返回 False。
    ensure_newline=True: under the lock, check the last byte and prepend one \\n when missing
    (existing bytes untouched); True means it padded. When the tail cannot be read (write-only /
    read denied) padding is skipped and False is returned.
    过渡适配器（步骤 3 删除）。"""
    who = 'safeio.atomic_append'
    _require_root(root, who)
    if isinstance(data, str):
        data = data.encode('utf-8')
    lr = _held_for(root)
    if lr is not None:
        return lr.write(_rel_from_path(lr.root, path, who), data,
                        mode=WriteMode.APPEND_CREATE, pad_newline=ensure_newline)
    with Root._from_dir_path(root, who) as ro:
        with ro.lock() as lr:
            return lr.write(_rel_from_path(ro, path, who), data,
                            mode=WriteMode.APPEND_CREATE, pad_newline=ensure_newline)


def append_inplace(path, data, root=None, conf_path=None):
    """持账本根锁原位追加：追加型派生件的唯一写入口（过渡适配器，步骤 3 删除）。
    Single write entry for append-type artifacts (transitional adapter).

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

    归属靠**物理走查**：从账本根目录 fd 出发，用 openat（dir_fd）逐级 O_NOFOLLOW|O_DIRECTORY
    走到目标所在目录，最后一级 openat 打开目标文件（O_APPEND|O_NOFOLLOW）。每级都必须是真
    目录，路径物理上出不去；父目录先 `realpath` 按真实文件系统解释（`..` 先解软链再上跳，
    不做词法折叠），大小写、NFC/NFD、`/tmp` 与 `/private/tmp` 等别名混写不会误拒。
    Containment is a **physical walk**: from the ledger-root directory fd, openat each component
    with O_NOFOLLOW|O_DIRECTORY down to the target's directory, then openat the target with
    O_APPEND|O_NOFOLLOW. Every level must be a real directory, so the path physically cannot
    leave; the parent is resolved by `realpath` with real filesystem semantics (`..` follows
    symlinks first, no lexical folding), so case/NFC-NFD/alias spellings are not falsely
    rejected.

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
    is appended as-is and False is returned."""
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
    lr = _held_for(resolved)
    if lr is None:
        raise RuntimeError('%s: 未在本线程于账本根（%s）持独占锁'
                           '（别的线程持锁/子目录锁/别的根都不算）·拒绝写入（零写）'
                           % (who, resolved))
    if isinstance(data, str):
        data = data.encode('utf-8')
    return lr.write(_rel_from_path(lr.root, path, who), data,
                    mode=WriteMode.APPEND_EXISTING, pad_newline=True)


def read_modify_write(path, fn, root=None):
    """持账本根锁读-改-写（过渡适配器，步骤 3 删除）。fn(old_bytes) -> new_bytes。
    Locked read-modify-write (transitional adapter). fn(old_bytes) -> new_bytes.
    只走独占锁：本线程已持则直接读写（临界区内），否则排队；无共享锁降级路径。
    ★ root 必须显式给出（账本根），省略即报错；不再回退到目标所在目录。
    ★ `root` is mandatory; omitting it raises instead of falling back."""
    who = 'safeio.read_modify_write'
    _require_root(root, who)
    lr = _held_for(root)
    if lr is not None:
        lr.update(_rel_from_path(lr.root, path, who), fn)
        return
    with Root._from_dir_path(root, who) as ro:
        with ro.lock() as lr:
            lr.update(_rel_from_path(ro, path, who), fn)


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
