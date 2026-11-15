#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""SafeIO · 根句柄 + 唯一写链（W-75·造①）
SafeIO · root handle + the single write chain (W-75 · build ①)
================================================
四个单一所有权（架构收口版 · 步骤 1）：
  Root        账本根的唯一样本：POSIX 为目录 fd + dev_ino（fstat 一次），Windows 为目录
              (st_dev, st_ino) + 路径；label 只用于文案。
  Rel         已校验的相对段序列；构造即合法，别处不再校验。
  LockedRoot  持锁凭证；写方法只存在于此类型上。
  WriteMode   追加创建 / 追加已存在 / 原子替换，三选一，不再有布尔参数分叉。

旧四原语（locked / atomic_append / append_inplace / read_modify_write / atomic_write）
保留为**薄适配器**：只做「路径 → Rel」和「取锁/复用本线程已持锁」，写链一律进
LockedRoot.write。适配器在步骤 3 删除，不是第二套实现。

锁粒度：账本根级。POSIX：flock 根目录本身的 fd（O_RDONLY|O_DIRECTORY），全程不新建文件；
Windows：按根的 (dev, ino) 命名互斥量（CreateMutexW），进程崩溃由系统自动放弃，也不落锁件。
锁身份只来自打开根时固定下来的 (st_dev, st_ino)——同 inode 的任何写法都是同一把锁。
Lock granularity: the ledger root. POSIX flocks the root directory fd itself (no file is ever
created); Windows uses a named mutex keyed by the root's (dev, ino), abandoned automatically on
crash — also no lock artifact. Identity is the (st_dev, st_ino) fixed when the root was opened,
so every spelling of one inode is the same lock.

换根语义（由 fd 定义，不靠复核）：写永远落在 Root 打开时的那个 inode 上。根路径在运行中
被换走，已持有的 LockedRoot 仍写旧 inode；要「路径现在还是我」的场合，入口显式调用
root.revalidate()。没有「加锁后现算 inode 再比对」这类自证判据。
Root-swap semantics are defined by the fd, not by re-checking: a write always lands on the inode
captured when Root was opened. If the path is swapped mid-run, a held LockedRoot keeps writing
the old inode; entries that need "the path is still me" call root.revalidate() explicitly.

入口与句柄（架构收口版 · 步骤 2）：每个进程入口在启动时 `Root.open()` 一次，向下传 Root，
不再传根路径字符串；没有以路径为键的全局状态。`locked(x)` / 四个旧原语既能接 Root（入口
持有，**不关闭**），也能接路径（临时打开、退出关闭，供步骤 3 前的回归判据使用）。
Entries and handles (step 2): every process entry calls `Root.open()` once and passes the Root
down instead of a root path string; no path-keyed global state remains. `locked(x)` and the four
legacy primitives accept either a Root (owned by the caller — never closed here) or a path
(opened and closed here, for the pre-step-3 regression criteria).

读者：`read_vol` 不取任何锁。卷是 append-only，派生件一律「同目录临时文件 + os.replace」
原子换入，读者拿到的永远是一致快照，且不会被写者的临界区整段阻塞。
Readers: `read_vol` takes no lock. Volumes are append-only and every derived artifact is swapped
in atomically (temp file in the same directory + os.replace), so a reader always sees a
consistent snapshot and is never blocked for the whole writer critical section.
"""
import contextlib
import enum
import hashlib
import os
import threading
import time

# ── 平台层（语义一条，系统调用两套）────────────────────────────────────
# 语义契约（两个平台完全相同）：同一账本根 ⇒ 同一把独占锁；写只落根内；追加后复核 inode；
# 替换＝同目录临时件 + 原子换入。差异只在系统调用：
#   POSIX   ：flock(根目录 fd) + openat/O_NOFOLLOW 走查 + fsync(dir)
#   Windows ：命名互斥量（CreateMutexW，进程崩溃自动放弃）+ realpath/commonpath 归属判
#             + reparse point 拒绝 + os.replace（目录 fsync 在 Windows 不可用，见 docstring）
# Semantic contract is identical on both platforms; only the syscall layer differs.
_PLATFORM = os.name
_WINDOWS = (_PLATFORM == 'nt')

try:
    import fcntl
except ImportError:                                     # Windows
    fcntl = None

try:
    import msvcrt
except ImportError:                                     # POSIX
    msvcrt = None

if _WINDOWS:                                            # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _k32.CreateMutexW.restype = wintypes.HANDLE
    _k32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _k32.ReleaseMutex.restype = wintypes.BOOL
    _k32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_ABANDONED = 0x00000080
    _WAIT_TIMEOUT = 0x00000102

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


# ── Windows：命名互斥量 + 路径归属（无 openat/flock）────────────────────
# Named mutex + path containment for Windows (there is no openat/flock there).
def _win_mutex_name(rt):
    key = repr(rt.dev_ino) if rt.dev_ino else os.path.normcase(rt.label)
    return 'Local\\daybook-' + hashlib.sha1(key.encode('utf-8')).hexdigest()


def _win_lock(rt, timeout):                             # pragma: no cover - Windows only
    h = _k32.CreateMutexW(None, False, _win_mutex_name(rt))
    if not h:
        raise RuntimeError('safeio: 无法创建账本根互斥量（%s）' % rt.label)
    ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
    rc = _k32.WaitForSingleObject(h, ms)
    if rc in (_WAIT_OBJECT_0, _WAIT_ABANDONED):         # 崩溃遗留的互斥量视为已获得
        return h
    _k32.CloseHandle(h)
    raise TimeoutError('safeio: lock timeout for %s' % rt.label)


def _win_unlock(h):                                     # pragma: no cover - Windows only
    try:
        _k32.ReleaseMutex(h)
    finally:
        _k32.CloseHandle(h)


def _win_key(p):
    return os.path.normcase(os.path.abspath(p)).rstrip('\\')


def _win_inside(root_real, p):
    a, b = _win_key(root_real), _win_key(p)
    return b == a or b.startswith(a + '\\')


def _tail_byte(fd, size):
    """读最后一个字节：POSIX 用 pread，Windows 没有 pread ⇒ lseek+read。
    Read the last byte: pread on POSIX; Windows has no pread ⇒ lseek+read."""
    try:
        return os.pread(fd, 1, size - 1)
    except AttributeError:                              # pragma: no cover - Windows only
        os.lseek(fd, size - 1, os.SEEK_SET)
        return os.read(fd, 1)


def _win_rel(root, path, who):
    """Windows 归属判：父目录 realpath 后必须仍在根内（大小写不敏感），末段保留原名。
    Windows containment: the parent's realpath must stay inside the root (case-insensitive);
    the final component keeps its spelling."""
    raw = path.rstrip('\\/') or path
    name = os.path.basename(raw)
    if not name or name in (os.curdir, os.pardir):
        raise RuntimeError('%s: 目标（%s）不是可写文件·拒绝写入（零写）' % (who, path))
    parent = os.path.realpath(os.path.dirname(raw))
    if not os.path.exists(parent) or not _win_inside(root.label, parent):
        raise RuntimeError('%s: 目标（%s）不在账本根（%s）内·拒绝写入（零写）'
                           % (who, path, root.label))
    relp = os.path.relpath(parent, root.label)
    segs = [] if relp in (os.curdir, '') else relp.split(os.sep)
    return root.rel(*(segs + [name]))


_TLS = threading.local()


def _held_list():
    """本线程已持的 LockedRoot 栈。它不是锁身份：锁身份只在 Root.dev_ino。
    The stack of LockedRoots this thread holds. Not an identity: identity is Root.dev_ino only."""
    lst = getattr(_TLS, 'held', None)
    if lst is None:
        lst = []
        _TLS.held = lst
    return lst


def _held_for_root(rt):
    """本线程在**同一个根句柄**（或同一 dev_ino）上已持的 LockedRoot；没有则 None。
    The LockedRoot this thread already holds for that root handle (or the same dev_ino), else None.
    只认 inode：不存在「按路径字符串重新认一遍」的第二身份。
    Identity is the inode only: there is no second, path-string identity."""
    for lr in reversed(_held_list()):
        if lr.root is rt or lr.root.dev_ino == rt.dev_ino:
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
    by openat O_NOFOLLOW.
    Windows 没有 openat：归属判改用「父目录 realpath + 根前缀（大小写不敏感）」，末段仍保留
    原名；重解析点由每层 `os.path.islink` / realpath 拒绝。
    Windows has no openat: containment uses the parent's realpath against the root prefix
    (case-insensitive); reparse points are refused by `os.path.islink` / realpath."""
    if _WINDOWS:                                        # pragma: no cover - Windows only
        return _win_rel(root, path, who)
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
            # 文案原样上抛：五个入口共用同一句「未找到 daybook.conf…」，不另加前缀。
            # Pass the wording through: all five entries share one "conf not found" sentence.
            raise RuntimeError(str(exc)) from None
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
        if _WINDOWS:                                    # pragma: no cover - Windows only
            # Windows 不能打开目录取 fd：身份来自目录的 (st_dev, st_ino)（卷序列号 + 文件索引）。
            try:
                st = os.stat(p)
            except OSError as exc:
                raise RuntimeError('%s: 账本根不可访问（%s）：%s'
                                   % (who, p, exc.strerror)) from None
            ident = (st.st_dev, st.st_ino)
            if ident == (0, 0):
                ident = ('path', os.path.normcase(p))
            return cls(None, ident, p, orig)
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

    def __fspath__(self):
        """路径式接口：`os.path.join(root, ...)` / `open` 直接用句柄，拼出来的是 orig 拼写。
        Path-like protocol: os.path.join/open accept the handle directly; the joined path keeps
        the original spelling."""
        return self.orig

    def __str__(self):
        return self.orig

    def __repr__(self):
        return 'Root(%r, dev_ino=%r)' % (self.label, self.dev_ino)

    def rel(self, *segs):
        """构造一条已校验的相对路径。构造即合法，别处不再校验。
        Build a validated relative path; construction is the only validation point."""
        return Rel(segs)

    def read(self, rel):
        """无锁读：POSIX 用 openat 逐级 O_NOFOLLOW；Windows 用 realpath 归属判 + 直接打开。
        Lock-free read: openat with O_NOFOLLOW on POSIX; realpath containment + plain open on
        Windows."""
        if not isinstance(rel, Rel):
            raise TypeError('safeio.Root.read: 需要 Rel（由 Root.rel 构造）')
        if _WINDOWS:                                    # pragma: no cover - Windows only
            p = os.path.join(self.orig, *rel.parts)
            _win_rel(self, p, 'safeio.Root.read')
            with open(p, 'rb') as f:
                return f.read()
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
        if fcntl is None and not _WINDOWS:
            raise RuntimeError('safeio: 当前平台既没有 fcntl 也不是 Windows·无可用互斥实现')
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
        mutex = None
        try:
            if _WINDOWS:                            # pragma: no cover - Windows only
                mutex = _win_lock(self, timeout)
            elif timeout is None:
                # 打开目录本身取 fd：不新建文件，不需要写权限；flock 绑在目录 inode 上。
                # Open the directory itself: no file is created, no write permission is required,
                # and the flock is bound to the directory inode.
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
        _PROC[key] = {'fd': self._fd, 'owner': me, 'mutex': mutex}
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
        if _WINDOWS:                                    # pragma: no cover - Windows only
            return self._append_win(rel, data, mode, pad_newline)
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
        if _WINDOWS:                                    # pragma: no cover - Windows only
            return self._replace_win(rel, data, perm)
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

    def _append_win(self, rel, data, mode, pad_newline):
        """Windows 追加：归属判（realpath/commonpath）→ 拒绝重解析点 → O_APPEND 单写 →
        stat 复核写 fd 的 (dev, ino)。语义与 POSIX 完全一致，只换了系统调用。
        Windows append: containment (realpath/commonpath) → refuse reparse points → a single
        O_APPEND write → stat re-check against the write fd's (dev, ino). Identical semantics to
        POSIX; only the syscalls differ."""
        who = 'safeio.write'
        name = os.path.join(*rel.parts)
        full = os.path.join(self.root.orig, *rel.parts)
        parent = os.path.realpath(os.path.dirname(full))
        if not _win_inside(self.root.label, parent):
            raise RuntimeError('%s: 目标（%s）不在账本根（%s）内·拒绝写入（零写）'
                               % (who, name, self.root.label))
        if os.path.islink(full):
            raise RuntimeError('%s: 目标（%s）是重解析点/软链·拒绝写入（零写）' % (who, name))
        flags = os.O_WRONLY | os.O_APPEND | getattr(os, 'O_BINARY', 0)
        if mode is WriteMode.APPEND_CREATE:
            flags |= os.O_CREAT
        try:
            tfd = os.open(full, flags, 0o644)
        except FileNotFoundError:
            raise RuntimeError('%s: 目标（%s）不存在·append 不创建（要建请用 atomic_write）'
                               % (who, name)) from None
        except OSError as exc:
            raise RuntimeError('%s: 目标（%s）不可用（%s）·拒绝写入（零写）'
                               % (who, name, exc)) from None
        padded = False
        try:
            wst = os.fstat(tfd)
            if pad_newline and data:
                try:
                    rfd = os.open(full, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
                except PermissionError:
                    rfd = None
                if rfd is not None:
                    try:
                        size = os.fstat(rfd).st_size
                        if size > 0 and _tail_byte(rfd, size) != b'\n':
                            data = b'\n' + data
                            padded = True
                    finally:
                        os.close(rfd)
            os.write(tfd, data)
            try:
                now = os.stat(full)
            except OSError:
                now = None
            if now is None or (now.st_dev, now.st_ino) != (wst.st_dev, wst.st_ino):
                raise RuntimeError('%s: 目标（%s）在追加期间被替换·数据可能未落盘' % (who, name))
        finally:
            os.close(tfd)
        return padded

    def _replace_win(self, rel, data, perm):
        """Windows 原子替换：同目录临时件 → fsync(文件) → os.replace。
        Windows atomic replace: temp file in the same directory → fsync(file) → os.replace.
        Windows 不能对目录 fsync：换名的持久化交给 NTFS 日志（已在 README 写明，不宣称超越平台）。
        A directory cannot be fsynced on Windows: durability of the rename relies on the NTFS
        journal (documented in the README; no claim beyond the platform)."""
        who = 'safeio.write'
        name = os.path.join(*rel.parts)
        full = os.path.join(self.root.orig, *rel.parts)
        parent = os.path.realpath(os.path.dirname(full))
        if not _win_inside(self.root.label, parent):
            raise RuntimeError('%s: 目标（%s）不在账本根（%s）内·拒绝写入（零写）'
                               % (who, name, self.root.label))
        tmp = os.path.join(os.path.dirname(full),
                           '.%s.%s.tmp' % (os.path.basename(full), os.urandom(6).hex()))
        try:
            tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                          getattr(os, 'O_BINARY', 0), 0o600 if perm is None else perm)
        except OSError as exc:
            raise RuntimeError('%s: 创建临时件（%s）失败（%s）·拒绝写入（零写）'
                               % (who, name, exc)) from None
        try:
            try:
                os.write(tfd, data)
                os.fsync(tfd)
            finally:
                os.close(tfd)
            os.replace(tmp, full)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise RuntimeError('%s: 原子替换（%s）失败（%s）·拒绝写入'
                               % (who, name, exc)) from None
        return False

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
            if ent is not None and ent.get('mutex') is not None:
                _win_unlock(ent['mutex'])
            elif fcntl is not None:
                fcntl.flock(self.root._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        _proc_mutex(key).release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def exclusive_held(root):
    """**本线程**是否对该账本根持独占锁（同进程别的线程持有不算）。
    Whether **this thread** holds an exclusive lock on that ledger root (another thread's hold
    in the same process does not count).
    ★ 只接受 Root / LockedRoot：锁身份是 inode，路径字符串不再是一种身份。
    ★ Accepts Root / LockedRoot only: identity is the inode, a path string is not an identity."""
    if isinstance(root, LockedRoot):
        return not root._released
    if isinstance(root, Root):
        return _held_for_root(root) is not None
    raise TypeError('safeio.exclusive_held: 只接受 Root / LockedRoot（锁身份是 dev_ino，'
                    '不接受路径字符串）')


def as_root(x, who='safeio'):
    """把 Root 句柄或账本根路径归一成 (Root, 是否本次新开)。
    Normalise a Root handle or a ledger-root path into (Root, opened_here)."""
    if isinstance(x, Root):
        return x, False
    if isinstance(x, LockedRoot):
        return x.root, False
    return Root._from_dir_path(x, who), True


@contextlib.contextmanager
def root_scope(x, who='safeio'):
    """句柄作用域：给 Root 就直接用（入口持有，**不关闭**）；给路径就临时打开、退出关闭。
    Handle scope: a Root is used as-is (owned by the entry — never closed here); a path is
    opened here and closed on exit."""
    rt, opened = as_root(x, who)
    try:
        yield rt
    finally:
        if opened:
            rt.close()


@contextlib.contextmanager
def locked(x, timeout=None):
    """账本根**独占**锁上下文（没有共享锁这回事）。
    Ledger-root **exclusive** lock context (there is no shared-lock mode).
    同一账本根下所有写操作串行：线程间排队（threading.Lock），跨进程 flock 独占。
    All writes under one ledger root are serialized: threads queue on a threading.Lock and
    processes contend on the exclusive flock.
    退出自动释放（锁挂在 Root 的目录 fd 上）。
    Released automatically on exit (the lock lives on Root's directory fd).
    同线程再取（任意写法，只要指向同一 inode）⇒ 立即 RuntimeError，不等待、不静默放行。
    Re-acquiring in the same thread (any spelling that hits the same inode) ⇒ immediate
    RuntimeError — no waiting, no silent pass-through.
    timeout 秒内拿不到则超时；None=阻塞等待。
    `x` 可以是 Root（入口持有）或账本根路径（临时打开）。"""
    with root_scope(x, 'safeio.locked') as ro:
        lr = ro.lock(timeout)
        try:
            yield ro._fd
        finally:
            lr.release()


def _require_root(root, who):
    """root 必填（账本根句柄或路径）；不再回退到目标所在目录（那会绕过根锁）。
    `root` is mandatory (a root handle or path); no fallback to the target's directory (that
    would bypass the root lock)."""
    if not root:
        raise RuntimeError('%s: 必须显式传 root（账本根）·'
                           '不再回退到目标所在目录（那会绕过根锁）' % who)


def atomic_write(path, data, mode=None, root=None):
    """原子替换写：临时件 + os.replace（dir_fd 两端）+ fsync(dfd)。
    Atomic replace: temp file + os.replace (both dir_fd) + fsync(dfd).
    ★ root 必填（账本根句柄或路径）。本线程已持该根锁时复用已持有的 LockedRoot（换根后仍写
      打开时的 inode）；否则在同一句柄上取锁，写完释放。
    ★ `root` is mandatory (a root handle or path). When this thread already holds that root, the
      held LockedRoot is reused (after a root swap it still writes the inode it opened);
      otherwise the same handle is locked and released.
    过渡适配器（步骤 3 删除）：写链在 LockedRoot.write。
    Transitional adapter (removed in step 3): the write chain lives in LockedRoot.write."""
    who = 'safeio.atomic_write'
    _require_root(root, who)
    if isinstance(data, str):
        data = data.encode('utf-8')
    with root_scope(root, who) as ro:
        lr = _held_for_root(ro)
        if lr is not None:
            lr.write(_rel_from_path(lr.root, path, who), data, mode=WriteMode.REPLACE, perm=mode)
            return
        with ro.lock() as lr:
            lr.write(_rel_from_path(ro, path, who), data, mode=WriteMode.REPLACE, perm=mode)


def atomic_append(path, data, root=None, ensure_newline=False):
    """持账本根锁追加（O_APPEND + 单次 write）。
    Append while holding the ledger-root lock (O_APPEND + a single write).
    ★ root 必须显式给出（账本根句柄或路径；子目录卷也争同一把锁）。省略不再回退到「目标所在目录」。
    ★ `root` is mandatory (a root handle or path; sub-directory volumes contend on it too).
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
    with root_scope(root, who) as ro:
        lr = _held_for_root(ro)
        if lr is None:
            with ro.lock() as lr:
                return lr.write(_rel_from_path(ro, path, who), data,
                                mode=WriteMode.APPEND_CREATE, pad_newline=ensure_newline)
        return lr.write(_rel_from_path(lr.root, path, who), data,
                        mode=WriteMode.APPEND_CREATE, pad_newline=ensure_newline)


def append_inplace(path, data, root):
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

    账本根**来自入口句柄，本函数不做任何 conf 解析**：`root` 必填，可为 Root（入口启动时
    `Root.open()` 的那一个）或账本根路径（判据里的临时句柄）。不再 locate／读 conf／比对
    字符串——根不自报，也不需要比对；归属与锁都只看这个句柄的 inode。
    The ledger root **comes from the entry handle; nothing is resolved here**: `root` is
    mandatory and may be a Root (the one the entry opened at startup) or a ledger-root path (a
    temporary handle in criteria). No locate / conf read / string comparison — the root is not
    self-reported and needs no cross-check; containment and the lock use this handle's inode.

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

    锁前置：**本线程**必须在**该句柄**上持**独占**锁（别的线程持锁、子目录锁、别的根都不算）。
    先判后开文件 ⇒ 不满足时零写。返回 True 表示补过换行，False 表示末字节本来是换行。
    读不到末字节时（只写目标，或 ACL／权限拒读）**跳过补换行**：只追加、不加前缀换行，
    此时返回 False——不看末字节就无法判定是否需要补。
    Lock precondition: **this thread** must hold an **exclusive** lock on **that handle**
    (a lock held by another thread, a sub-directory lock and another root do not count). All
    checks run before the file is opened ⇒ nothing is written when they fail. Returns True when
    a newline was padded, False when the last byte already was one. When the last byte cannot be
    read (write-only target, or read denied by ACL/permissions) padding is **skipped**: the data
    is appended as-is and False is returned."""
    who = 'safeio.append_inplace'
    _require_root(root, who)
    with root_scope(root, who) as rt:
        lr = _held_for_root(rt)
        if lr is None:
            raise RuntimeError('%s: 未在本线程于账本根（%s）持独占锁'
                               '（别的线程持锁/子目录锁/别的根都不算）·拒绝写入（零写）'
                               % (who, rt.label))
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
    with root_scope(root, who) as ro:
        lr = _held_for_root(ro)
        if lr is None:
            with ro.lock() as lr:
                lr.update(_rel_from_path(ro, path, who), fn)
            return
        lr.update(_rel_from_path(lr.root, path, who), fn)


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
