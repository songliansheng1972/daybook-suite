#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""锁与租约（W-DB-023-G3·第 5 项）
Locks and leases (W-DB-023-G3 · item 5)
================================================
- fcntl.flock 文件锁（多 Agent 同时改一任务·OS 级互斥）
  fcntl.flock file lock (multiple agents editing one task · OS-level mutual exclusion)
- 租约（TTL·默认 60 秒·自动过期）
  Lease (TTL · 60 seconds by default · auto-expires)
- 续租/释放/强制释放
  Renew / release / force-release
- 零依赖：仅用 Python 3 标准库（fcntl/time/os/json）
  Zero dependencies: only the Python 3 standard library (fcntl/time/os/json)

租约卷.txt 格式（append-only）：
Lease volume (租约卷.txt) format (append-only):
  [时间] [租约] [lease_id] [resource] [agent_id] [TTL] acquire
  [时间] [租约] [lease_id] renew
  [时间] [租约] [lease_id] release
  [时间] [租约] [lease_id] expired  # 后台扫描发现过期 · found expired by the background sweep

锁实现：
Lock implementation:
  - 每个 resource 一个 .lock 文件（fcntl.flock·进程退出自动释放）
    One .lock file per resource (fcntl.flock · auto-released when the process exits)
  - lease_id = agent_id + ':' + resource + ':' + ts
  - 后台扫lease 状态·过期则强制 release（带 fenced token 防误释放）
    Background scan of lease state · force-release when expired (with a fenced token to prevent a wrong release)

用法：
Usage:
  lk = AgentLock()
  lease = lk.acquire('task:T001', 'agent_xxx', ttl=60)
  lk.renew(lease)
  lk.release(lease)
"""
import os, sys, time, json, fcntl

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
        self._fds = {}  # lease_id -> (fd, expires_at) · 内存租约映射 · in-memory lease map

    def _lock_path(self, resource):
        safe = resource.replace('/', '_').replace(':', '_')
        return os.path.join(self.lock_dir, '%s.lock' % safe)

    def _lease_id(self, resource, agent_id, ts):
        return '%s:%s:%d' % (agent_id, resource, int(ts))

    def _log(self, lease_id, action, extra=''):
        from safeio import atomic_append
        rec = ('[%s] [租约] [%s] %s %s\n' % (_now(), lease_id, action, extra)).rstrip() + '\n'
        atomic_append(self.lease_vol, rec)

    def acquire(self, resource, agent_id, ttl=60, blocking=False, timeout=5):
        """获取资源锁。返回 lease_id 或 None。
        Acquire the resource lock. Returns a lease_id or None.
        - blocking=True：阻塞等待 timeout 秒
          blocking=True: block and wait up to timeout seconds
        - blocking=False：拿不到立刻返回 None
          blocking=False: return None immediately if unavailable
        锁持有：fcntl.flock + 内存租约·TTL 到自动释放。
        Lock holding: fcntl.flock + in-memory lease · auto-releases when the TTL expires."""
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
        expires = ts + ttl
        self._fds[lease_id] = (fd, expires)
        self._log(lease_id, 'acquire', 'resource=%s agent=%s ttl=%d' % (resource, agent_id, ttl))
        return lease_id

    def renew(self, lease_id, ttl=60):
        """续租。返成功/失败。
        Renew the lease. Returns success/failure."""
        if lease_id not in self._fds:
            return False
        fd, _ = self._fds[lease_id]
        self._fds[lease_id] = (fd, _now_ts() + ttl)
        self._log(lease_id, 'renew', 'ttl=%d' % ttl)
        return True

    def release(self, lease_id):
        """主动释放。
        Explicit release."""
        if lease_id not in self._fds:
            return False
        fd, _ = self._fds.pop(lease_id)
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)
        self._log(lease_id, 'release')
        return True

    def force_release(self, lease_id):
        """强制释放（租约过期·后台扫描调用）。
        Force-release (called by the background sweep when a lease expires).
        fenced token：lease_id 必须在 _fds 里且 expires_at 已过；否则不动。
        fenced token: the lease_id must be in _fds and its expires_at must have passed; otherwise nothing happens."""
        if lease_id not in self._fds:
            return False
        fd, expires = self._fds[lease_id]
        if _now_ts() < expires:
            return False  # 还没过期 · not expired yet
        self._fds.pop(lease_id)
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)
        self._log(lease_id, 'expired')
        return True

    def sweep(self):
        """扫描所有持有租约·过期则强制释放。返回过期数量。
        Scan all held leases · force-release expired ones. Returns the expired count."""
        now = _now_ts()
        dead = [lid for lid, (_, exp) in self._fds.items() if exp < now]
        for lid in dead:
            self.force_release(lid)
        return len(dead)

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
            for lid, (fd2, _) in self._fds.items():
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
        ttl = int(sys.argv[4]) if len(sys.argv) >= 6 else 60
        lid = lk.acquire(sys.argv[2], agent, ttl=ttl)
        print(lid or '（已锁·获取失败）')
    elif cmd == 'release' and len(sys.argv) >= 3:
        ok = lk.release(sys.argv[2])
        print('OK' if ok else 'FAIL')
    elif cmd == 'renew' and len(sys.argv) >= 3:
        ok = lk.renew(sys.argv[2])
        print('OK' if ok else 'FAIL')
    elif cmd == 'sweep':
        print('expired: %d' % lk.sweep())
    elif cmd == 'held' and len(sys.argv) >= 3:
        print(lk.held_by(sys.argv[2]) or '（空闲）')
    else:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
