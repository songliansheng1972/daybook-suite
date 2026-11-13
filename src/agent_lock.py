#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""锁与租约（W-DB-023-G3·第 5 项）
Locks and leases (W-DB-023-G3 · item 5)
================================================
- fcntl.flock 文件锁（多 Agent 同时改一任务·OS 级互斥）
  fcntl.flock file lock (multiple agents editing one task · OS-level mutual exclusion)
- 租约 id 仅作审计线索，随 acquire/release 落租约卷
  The lease id is an audit trail only, written to the lease volume on acquire/release
- 续租/强制释放/后台扫描不在编排闭环内，已删除（见 CHANGELOG）
  Renew / force-release / background sweep are not in the orchestration loop and have been removed (see CHANGELOG)
- 零依赖：仅用 Python 3 标准库（fcntl/time/os）
  Zero dependencies: only the Python 3 standard library (fcntl/time/os)

租约卷.txt 格式（append-only）：
Lease volume (租约卷.txt) format (append-only):
  [时间] [租约] [lease_id] [resource] [agent_id] acquire
  [时间] [租约] [lease_id] release

锁实现：
Lock implementation:
  - 每个 resource 一个 .lock 文件（fcntl.flock·进程退出自动释放）
    One .lock file per resource (fcntl.flock · auto-released when the process exits)
  - lease_id = agent_id + ':' + resource + ':' + ts

用法：
Usage:
  lk = AgentLock()
  lease = lk.acquire('task:T001', 'agent_xxx')
  lk.release(lease)
"""
import os, sys, time, fcntl

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_DIR = os.path.join(HERE, '.locks')
LEASE_VOL = os.path.join(HERE, '租约卷.txt')


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _now_ts():
    return time.time()


class AgentLock:
    def __init__(self, lock_dir=None, lease_vol=None):
        self.lock_dir = lock_dir or LOCK_DIR
        self.lease_vol = lease_vol or LEASE_VOL
        if not os.path.isdir(self.lock_dir):
            os.makedirs(self.lock_dir, exist_ok=True)
        if not os.path.exists(self.lease_vol):
            open(self.lease_vol, 'a', encoding='utf-8').close()
        # 进程内持有的 fd（避免同进程重复释放） · fds held in-process (to avoid double-release within the same process)
        self._fds = {}  # lease_id -> fd · 内存租约映射 · in-memory lease map

    def _lock_path(self, resource):
        safe = resource.replace('/', '_').replace(':', '_')
        return os.path.join(self.lock_dir, '%s.lock' % safe)

    def _lease_id(self, resource, agent_id, ts):
        return '%s:%s:%d' % (agent_id, resource, int(ts))

    def _log(self, lease_id, action, extra=''):
        from safeio import atomic_append
        rec = ('[%s] [租约] [%s] %s %s\n' % (_now(), lease_id, action, extra)).rstrip() + '\n'
        atomic_append(self.lease_vol, rec)

    def acquire(self, resource, agent_id, blocking=False):
        """获取资源锁。返回 lease_id 或 None。
        Acquire the resource lock. Returns a lease_id or None.
        - blocking=True：阻塞直到拿到锁
          blocking=True: block until the lock is acquired
        - blocking=False：拿不到立刻返回 None
          blocking=False: return None immediately if unavailable
        锁持有：fcntl.flock（进程退出自动释放）。
        Lock holding: fcntl.flock (auto-released when the process exits)."""
        path = self._lock_path(resource)
        ts = _now_ts()
        lease_id = self._lease_id(resource, agent_id, ts)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        flag = fcntl.LOCK_EX
        if not blocking:
            flag |= fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flag)
        except BlockingIOError:
            os.close(fd)
            return None
        self._fds[lease_id] = fd
        self._log(lease_id, 'acquire', 'resource=%s agent=%s' % (resource, agent_id))
        return lease_id

    def release(self, lease_id):
        """主动释放。
        Explicit release."""
        if lease_id not in self._fds:
            return False
        fd = self._fds.pop(lease_id)
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)
        self._log(lease_id, 'release')
        return True

    def held_by(self, resource):
        """查 resource 当前被谁持有。返回 lease_id 或 None。
        Check who currently holds the resource. Returns a lease_id or None.
        试图再获一次非阻塞锁·拿得到说明没人持有。
        Try a non-blocking lock again · if it succeeds, nobody holds it."""
        path = self._lock_path(resource)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return None
        except BlockingIOError:
            for lid, _fd2 in self._fds.items():
                if resource in lid:
                    return lid
            return 'unknown'
        finally:
            os.close(fd)


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
