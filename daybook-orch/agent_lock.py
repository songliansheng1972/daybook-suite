#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""账本根锁与租约（W-DB-023-G3·第 5 项）
Ledger-root lock and leases (W-DB-023-G3 · item 5)
================================================
★ 互斥范围是**整个账本根**，不是 `label` 字符串。
★ The exclusion scope is the **whole ledger root**, not the `label` string.

`acquire(label, agent_id)` 拿到的是**账本根锁**：同一账本根下任何写入（不同 label、不同任务、
不同卷）都串行。`label` 只用于记账/命名租约 id，不参与互斥范围的判定。
`acquire(label, agent_id)` returns the **ledger-root lock**: every write under that root
serializes (different labels, tasks and volumes alike). `label` only names the lease id and
labels the audit record; it never narrows the exclusion scope.

- flock 账本根目录（多 Agent 同时改一任务·OS 级互斥·不落锁件）
  flock the ledger-root directory (multiple agents editing one task · OS-level exclusion · no lock file)
- 同线程重复获取 ⇒ 立即 RuntimeError（不等待、不静默放行：同线程等自己必自死锁）
  A second acquisition from the same thread ⇒ immediate RuntimeError (no waiting, no silent
  pass-through: waiting on yourself is a guaranteed self-deadlock)
- 租约 id 仅作审计线索，随 acquire/release 落租约卷
  The lease id is an audit trail only, written to the lease volume on acquire/release
- 零依赖：仅用 Python 3 标准库（time/os/threading/safeio）
  Zero dependencies: only the Python 3 standard library (time/os/threading/safeio)

租约卷.txt 格式（append-only）：
Lease volume (租约卷.txt) format (append-only):
  [时间] [租约] [lease_id] [label] [agent_id] acquire
  [时间] [租约] [lease_id] release

锁实现：
Lock implementation:
  - 不建任何锁件：互斥＝账本根目录 flock（进程退出自动释放）
    No lock artifact at all: exclusion is a flock on the ledger-root directory
    (auto-released when the process exits)
  - 线程间同样按账本根排队（safeio 内每根一把 threading.Lock）
    Threads queue on the same ledger root (one threading.Lock per root inside safeio)
  - lease_id = agent_id + ':' + label + ':' + ts

用法：
Usage:
  lk = AgentLock()
  lease = lk.acquire('task:T001', 'agent_xxx')   # 锁的是账本根，不是这个标签
  lk.release(lease)
"""
import os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LEASE_VOL = os.path.join(HERE, '租约卷.txt')


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _now_ts():
    return time.time()


class AgentLock:
    """账本根锁：一切互斥都走 `safeio.locked(账本根)`（flock 目录本身）。
    Ledger-root lock: every exclusion goes through `safeio.locked(ledger root)` (flock the directory).
    ★ 不落任何锁件（无 lock 文件、无 lock 目录）：只读安装下也不会因 makedirs 失败。
    ★ No lock artifact at all (no lock file, no lock directory): a read-only install never
      fails on makedirs."""

    def __init__(self, lock_dir=None, lease_vol=None, root=None):
        # lock_dir 仅为旧签名兼容保留，不再使用（锁＝账本根目录本身）
        # lock_dir is kept only for signature compatibility and is no longer used
        self.lock_dir = lock_dir
        self.lease_vol = lease_vol or LEASE_VOL
        self.root = root or os.path.dirname(os.path.abspath(self.lease_vol))
        # 租约：lease_id -> {'cm': 已进入的锁上下文, 'tid': 获取线程 ident}
        # Leases: lease_id -> {'cm': entered lock context, 'tid': acquiring thread id}
        self._ctx = {}
        self._fds = self._ctx            # 旧名兼容 · legacy attribute name

    def _lease_id(self, label, agent_id, ts):
        return '%s:%s:%d' % (agent_id, label, int(ts))

    def _log(self, lease_id, action, extra=''):
        from safeio import atomic_append
        rec = ('[%s] [租约] [%s] %s %s\n' % (_now(), lease_id, action, extra)).rstrip() + '\n'
        atomic_append(self.lease_vol, rec, root=self.root)

    def acquire(self, label, agent_id, blocking=False):
        """获取**账本根锁**。返回 lease_id 或 None。
        Acquire the **ledger-root lock**. Returns a lease_id or None.
        `label` 只用于记账/命名租约 id；互斥范围是整个账本根，与 label 无关。
        `label` only names/records the lease; the exclusion scope is the whole ledger root.
        - 本线程已持该根锁（任何实例、任何 label）⇒ 立即 RuntimeError，不等待
          This thread already holds that root lock (any instance, any label) ⇒ immediate
          RuntimeError, never waits
        - blocking=True：阻塞直到拿到锁
          blocking=True: block until the lock is acquired
        - blocking=False：拿不到立刻返回 None
          blocking=False: return None immediately if unavailable
        锁＝账本根目录 flock（进程退出自动释放），不落任何锁文件。
        The lock is a flock on the ledger-root directory (auto-released on process exit);
        no lock file is ever created."""
        from safeio import locked, exclusive_held
        if exclusive_held(self.root):
            raise RuntimeError('agent_lock: 同线程重复获取账本根锁（%s）·拒绝等待'
                               '（同线程等自己必自死锁；互斥范围是整个账本根）' % self.root)
        cm = locked(self.root, timeout=None if blocking else 0)
        try:
            cm.__enter__()
        except TimeoutError:
            return None
        ts = _now_ts()
        lease_id = self._lease_id(label, agent_id, ts)
        self._ctx[lease_id] = {'cm': cm, 'tid': threading.get_ident()}
        self._log(lease_id, 'acquire', 'label=%s agent=%s' % (label, agent_id))
        return lease_id

    def release(self, lease_id):
        """主动释放。Explicit release.
        释放记录先写（仍在临界区内，直接追加、不排队），再退锁；否则退锁后记日志会与下一个
        持锁者互等（等锁者拿到锁、释放者卡在日志上 ⇒ 死锁）。
        The release record is written first (still inside the critical section: append directly,
        no queueing) and the lock is dropped afterwards; logging after the drop would wait on the
        next holder while that holder waits for us ⇒ deadlock."""
        ent = self._ctx.get(lease_id)
        if ent is None:
            return False
        if ent['tid'] != threading.get_ident():
            raise RuntimeError('agent_lock: 租约 %s 由线程 %s 获取，不能由本线程释放'
                               '（锁按账本根、按线程持有）' % (lease_id, ent['tid']))
        self._ctx.pop(lease_id, None)
        try:
            self._log(lease_id, 'release')
        finally:
            ent['cm'].__exit__(None, None, None)
        return True

    def held_by(self, label):
        """查 label 对应的租约（互斥范围仍是整个账本根）。返回 lease_id 或 None。
        Look up the lease for `label` (the exclusion scope is still the whole ledger root).
        Returns a lease_id or None.
        本进程持有：按 lease_id 里的 label 匹配；否则只要还持着任意租约即 'unknown'。
        Held in this process: match the label in the lease_id; otherwise any outstanding lease
        yields 'unknown'."""
        for lid in list(self._ctx):
            if label in lid:
                return lid
        if self._ctx:
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
