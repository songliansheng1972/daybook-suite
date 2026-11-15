#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""锁与租约（W-DB-023-G3·第 5 项）
Locks and leases (W-DB-023-G3 · item 5)
================================================
- flock 账本根目录（多 Agent 同时改一任务·OS 级互斥·不落锁件）
  flock the ledger-root directory (multiple agents editing one task · OS-level exclusion · no lock file)
- 租约 id 仅作审计线索，随 acquire/release 落租约卷
  The lease id is an audit trail only, written to the lease volume on acquire/release
- 续租/强制释放/后台扫描不在编排闭环内，已删除（见 CHANGELOG）
  Renew / force-release / background sweep are not in the orchestration loop and have been removed (see CHANGELOG)
- 零依赖：仅用 Python 3 标准库（time/os/safeio）
  Zero dependencies: only the Python 3 standard library (fcntl/time/os)

租约卷.txt 格式（append-only）：
Lease volume (租约卷.txt) format (append-only):
  [时间] [租约] [lease_id] [resource] [agent_id] acquire
  [时间] [租约] [lease_id] release

锁实现：
Lock implementation:
  - 不建任何锁件：互斥＝账本根目录 flock（进程退出自动释放）
    No lock artifact at all: exclusion is a flock on the ledger-root directory
    (auto-released when the process exits)
  - lease_id = agent_id + ':' + resource + ':' + ts

用法：
Usage:
  lk = AgentLock()
  lease = lk.acquire('task:T001', 'agent_xxx')
  lk.release(lease)
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LEASE_VOL = os.path.join(HERE, '租约卷.txt')


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _now_ts():
    return time.time()


_MUTEX = {}
_MUTEX_GUARD = None


def _proc_mutex(root):
    """同一账本根的进程内租约互斥（另一线程 blocking=False 立刻 None、blocking=True 真等）。
    In-process lease mutex per ledger root (another thread gets None immediately with
    blocking=False, and really waits with blocking=True)."""
    global _MUTEX_GUARD
    import threading
    if _MUTEX_GUARD is None:
        _MUTEX_GUARD = threading.Lock()
    key = os.path.realpath(root)
    with _MUTEX_GUARD:
        m = _MUTEX.get(key)
        if m is None:
            m = threading.Lock()
            _MUTEX[key] = m
        return m


class AgentLock:
    """租约锁：一切互斥都走 `safeio.locked(账本根)`（flock 目录本身）。
    Lease lock: every exclusion goes through `safeio.locked(ledger_root)` (flock the directory).
    ★ 不落任何锁件（无 lock 文件、无 lock 目录）：只读安装下也不会因 makedirs 失败。
    ★ No lock artifact at all (no lock file, no lock directory): a read-only install never
      fails on makedirs."""

    def __init__(self, lock_dir=None, lease_vol=None, root=None):
        # lock_dir 仅为旧签名兼容保留，不再使用（锁＝账本根目录本身）
        # lock_dir is kept only for signature compatibility and is no longer used
        self.lock_dir = lock_dir
        self.lease_vol = lease_vol or LEASE_VOL
        self.root = root or os.path.dirname(os.path.abspath(self.lease_vol))
        # 内存租约：lease_id -> 已进入的锁上下文（进程内持有，释放时退出）
        # In-memory leases: lease_id -> entered lock context (held in-process, exited on release)
        self._ctx = {}
        self._fds = self._ctx            # 旧名兼容 · legacy attribute name
        self._mutex = _proc_mutex(self.root)

    def _lease_id(self, resource, agent_id, ts):
        return '%s:%s:%d' % (agent_id, resource, int(ts))

    def _log(self, lease_id, action, extra=''):
        from safeio import atomic_append
        rec = ('[%s] [租约] [%s] %s %s\n' % (_now(), lease_id, action, extra)).rstrip() + '\n'
        atomic_append(self.lease_vol, rec, root=self.root)

    def acquire(self, resource, agent_id, blocking=False):
        """获取资源锁。返回 lease_id 或 None。
        Acquire the resource lock. Returns a lease_id or None.
        - blocking=True：阻塞直到拿到锁
          blocking=True: block until the lock is acquired
        - blocking=False：拿不到立刻返回 None
          blocking=False: return None immediately if unavailable
        锁＝账本根目录 flock（进程退出自动释放），不落任何锁文件。
        The lock is a flock on the ledger-root directory (auto-released on process exit);
        no lock file is ever created."""
        from safeio import locked
        if not self._mutex.acquire(blocking=bool(blocking)):
            return None
        cm = locked(self.root, timeout=None if blocking else 0)
        try:
            cm.__enter__()
        except TimeoutError:
            self._mutex.release()
            return None
        except BaseException:
            self._mutex.release()
            raise
        ts = _now_ts()
        lease_id = self._lease_id(resource, agent_id, ts)
        self._ctx[lease_id] = cm
        self._log(lease_id, 'acquire', 'resource=%s agent=%s' % (resource, agent_id))
        return lease_id

    def release(self, lease_id):
        """主动释放。Explicit release."""
        cm = self._ctx.pop(lease_id, None)
        if cm is None:
            return False
        try:
            cm.__exit__(None, None, None)
        finally:
            try:
                self._mutex.release()
            except RuntimeError:
                pass
            self._log(lease_id, 'release')
        return True

    def held_by(self, resource):
        """查 resource 当前被谁持有。返回 lease_id 或 None。
        Check who currently holds the resource. Returns a lease_id or None.
        本进程持有：按 lease_id 里的 resource 匹配；否则看进程内租约互斥是否被占。
        Held in this process: match the resource in the lease_id; otherwise look at the
        in-process lease mutex."""
        for lid in list(self._ctx):
            if resource in lid:
                return lid
        if self._ctx or self._mutex.locked() is True:
            return 'unknown'
        return None


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 1
    lk = AgentLock()
    cmd = sys.argv[1]
    if cmd == 'acquire' and len(sys.argv) >= 4:
        agent = sys.argv[3] if len(sys.argv) >= 5 else 'cli'
        lid = lk.acquire(sys.argv[2], agent)
        print(lid or '（已锁·获取失败）')
    elif cmd == 'release' and len(sys.argv) >= 3:
        ok = lk.release(sys.argv[2])
        print('OK' if ok else 'FAIL')
    elif cmd == 'held' and len(sys.argv) >= 3:
        print(lk.held_by(sys.argv[2]) or '（空闲）')
    else:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
