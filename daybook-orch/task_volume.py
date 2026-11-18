#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""任务状态卷（W-DB-023-G3·第 2 项）
Task status volume (W-DB-023-G3 · item 2)
================================================
- 任务流转状态机：待办 → 进行中 → 完成 → 待审 → 已审
  Task-flow state machine: 待办 → 进行中 → 完成 → 待审 → 已审
- 任务卷 append-only·不改历史（状态变更只追加·不删不修改）
  The task volume is append-only · history is never rewritten (state changes only append · nothing deleted or modified)
- 零依赖：仅用 Python 3 标准库
  Zero dependencies: only the Python 3 standard library

任务卷.txt 格式（每行一条·append-only）：
Task volume (任务卷.txt) format (one entry per line · append-only):
  [时间] [任务] [T001] [待办] [agent_id] 内容
  [时间] [任务] [T001] [进行中] [agent_id] 开始实现
  [时间] [任务] [T001] [完成] [agent_id] 提交·待审
  [时间] [任务] [T001] [已审] [agent_id] 通过

合法状态：待办 / 进行中 / 完成 / 待审 / 已审
Legal states: 待办 / 进行中 / 完成 / 待审 / 已审
合法迁移：
Legal transitions:
  待办 → 进行中 → 完成 → 待审 → 已审
  待审 → 进行中  # 审方驳回·返工 · reviewer rejects · rework
  任何 → 取消    # 强制取消（append-only 留痕）· forced cancel (leaves a trace, append-only)

用法：
Usage:
  tv = TaskVolume('任务卷.txt')
  tid = tv.create('agent_id_xxx', '实现 MCP resources/list')
  tv.transition(tid, '进行中', 'agent_id_xxx', '开始实现')
  tasks = tv.list(state='进行中')
"""
import os, sys, time, weakref

import errors

HERE = os.path.dirname(os.path.abspath(__file__))

# 状态机：键=当前状态·值=合法后继 · state machine: key=current state · value=legal successors
STATE_MACHINE = {
    '待办':   {'进行中'},
    '进行中': {'完成', '取消'},
    '完成':   {'待审', '取消'},
    '待审':   {'已审', '进行中'},  # 通过/驳回 · pass/reject
    '已审':   set(),               # 终态 · terminal state
    '取消':   set(),               # 终态 · terminal state
}
ALL_STATES = set(STATE_MACHINE.keys())


def _now():
    return time.strftime('%Y-%m-%d %H:%M')


class TaskVolume:
    """任务状态卷·append-only。
    Task status volume · append-only."""
    def __init__(self, path=None, root=None):
        self.path = path or os.path.join(HERE, '任务卷.txt')
        # 账本根一律显式给出；收 Root 就复用同一 dev_ino，绝不按路径重开（入口换根后仍写旧 inode）
        # The ledger root is always explicit; a Root is reused (same dev_ino) instead of being
        # reopened by path, so an entry-level rename keeps writing the original inode.
        from safeio import as_root, locked, WriteMode
        self.root, _opened = as_root(root or HERE, 'task_volume')
        # 从路径构造时本件拥有该 Root：GC 时关闭，避免按次构造漏 fd。
        # A Root opened from a path is owned here and closed at GC, so per-call construction
        # cannot leak file descriptors.
        self._root_finalizer = (weakref.finalize(self, self.root.close)
                                if _opened else None)
        if not os.path.exists(self.path):
            with locked(self.root) as lr:
                lr.write(lr.root.rel_of(self.path, 'task_volume.init'), b'',
                         mode=WriteMode.REPLACE)

    def _read_all(self):
        """单遍扫描任务卷·构建 (tid -> list of (时间, 状态, agent, 内容))。
        Single-pass scan of the task volume · builds (tid -> list of (time, state, agent, content))."""
        tasks = {}
        if not os.path.exists(self.path):
            return tasks
        from safeio import read_vol
        text, _enc, _why = read_vol(self.path)
        for line in text.splitlines():
            line = line.rstrip('\n')
            if not line.startswith('['):
                continue
            # [时间] [任务] [T001] [状态] [agent] 内容 · [time] [task] [T001] [state] [agent] content
            # split(']') 后 strip·留非空 · split on ']' then strip · keep non-empty
            parts = [p.strip(' []') for p in line.split(']') if p.strip()]
            if len(parts) < 5:
                continue
            t, _, tid, state, agent = parts[0], parts[1], parts[2], parts[3], parts[4]
            content = ' '.join(parts[5:]) if len(parts) > 5 else ''
            tasks.setdefault(tid, []).append((t, state, agent, content))
        return tasks

    def _next_tid(self):
        """下一个任务 ID：T001, T002, ...
        The next task ID: T001, T002, ..."""
        tasks = self._read_all()
        if not tasks:
            return 'T001'
        max_n = 0
        for tid in tasks:
            if tid.startswith('T') and tid[1:].isdigit():
                max_n = max(max_n, int(tid[1:]))
        return 'T%d' % (max_n + 1)

    def create(self, agent_id, content):
        """创建任务·状态=待办。返回 task_id。
        Create a task · state=待办. Returns task_id."""
        from safeio import locked, WriteMode
        tid = self._next_tid()
        rec = '[%s] [任务] [%s] [待办] [%s] %s\n' % (_now(), tid, agent_id, content.rstrip('\n'))
        with locked(self.root) as lr:
            lr.write(lr.root.rel_of(self.path, 'task_volume.create'), rec,
                     mode=WriteMode.APPEND_CREATE)
        return tid

    def transition(self, tid, new_state, agent_id, note=''):
        """状态迁移。违例 raise。
        State transition. Raises on violation."""
        if new_state not in ALL_STATES:
            raise ValueError('非法状态：%s' % new_state)
        from safeio import exclusive_held, root_scope
        with root_scope(self.root, 'task_volume.transition') as rt:
            if exclusive_held(rt):
                return self._transition_locked(tid, new_state, agent_id, note)
            with rt.lock():
                return self._transition_locked(tid, new_state, agent_id, note)

    def _transition_locked(self, tid, new_state, agent_id, note=''):
        """已持账本根独占锁时执行迁移（不再取锁）。
        Perform the transition while already holding the exclusive ledger-root lock."""
        from safeio import held, WriteMode
        tasks = self._read_all()
        hist = tasks.get(tid)
        if not hist:
            raise KeyError('任务 %s 不存在' % tid)
        cur_state = hist[-1][1]
        if cur_state in ('已审', '取消'):
            raise PermissionError('终态不可迁移：%s' % cur_state)
        legal_next = STATE_MACHINE.get(cur_state, set())
        if new_state not in legal_next:
            raise PermissionError('非法迁移：%s → %s（合法：%s）' % (
                cur_state, new_state, ' '.join(legal_next) or '无'))
        rec = '[%s] [任务] [%s] [%s] [%s] %s\n' % (
            _now(), tid, new_state, agent_id, note.rstrip('\n'))
        lr = held(self.root, 'task_volume.transition')
        lr.write(lr.root.rel_of(self.path, 'task_volume.transition'), rec,
                 mode=WriteMode.APPEND_CREATE)
        return True

    def list(self, state=None):
        """列出任务·可按状态过滤。返回 [(tid, 当前状态, 当前负责人, 当前内容, 历史)]。
        List tasks · optionally filtered by state. Returns [(tid, current_state, current_owner, current_content, history)]."""
        tasks = self._read_all()
        out = []
        for tid, hist in tasks.items():
            cur = hist[-1]
            if state and cur[1] != state:
                continue
            out.append((tid, cur[1], cur[2], cur[3], hist))
        return out

    def get(self, tid):
        return self._read_all().get(tid)


def main():
    """统一出口：任务卷 CLI 是运维工具（不进 8 入口契约），但同样不裸 traceback。"""
    return errors.run_entry(_main)


def _main():
    if len(sys.argv) < 2:
        raise errors.ConfigError(__doc__ or '缺子命令')
    tv = TaskVolume()
    cmd = sys.argv[1]
    if cmd == 'create' and len(sys.argv) >= 4:
        tid = tv.create(sys.argv[2], sys.argv[3])
        print('task_id: %s (待办)' % tid)
    elif cmd == 'list':
        state = sys.argv[2] if len(sys.argv) >= 3 else None
        for tid, st, ag, ct, _ in tv.list(state):
            print('%s [%s] %s | %s' % (tid, st, ag, ct))
    elif cmd == 'transition' and len(sys.argv) >= 5:
        note = sys.argv[5] if len(sys.argv) >= 6 else ''
        try:
            tv.transition(sys.argv[2], sys.argv[3], sys.argv[4], note)
        except KeyError as exc:
            raise errors.ConfigError('任务不存在：%s' % (exc,))
        print('OK')
    else:
        raise errors.ConfigError(__doc__ or '未知子命令')
    return 0


if __name__ == '__main__':
    sys.exit(main())
