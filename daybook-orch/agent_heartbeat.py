#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""Agent 心跳卷（W-DB-023-G3·第 6 项）
Agent heartbeat volume (W-DB-023-G3 · item 6)
================================================
- 心跳卷 append-only：[时间] [心跳] [agent_id] alive
  The heartbeat volume is append-only: [时间] [心跳] [agent_id] alive
- 缺心跳 > 3 周期 → 标 dead → 触发恢复
  Missing heartbeat > 3 periods → mark dead → trigger recovery
- 零依赖：仅用 Python 3 标准库（os/time）
  Zero dependencies: only the Python 3 standard library (os/time)

用法：
Usage:
  hb = Heartbeat(period=10)         # 周期 10 秒 · period 10 seconds
  hb.beat('agent_xxx')              # Agent 自报心跳 · agent reports its own heartbeat
  alive = hb.is_alive('agent_xxx')  # 查活/死 · check alive/dead
  dead = hb.dead_agents()           # 列出所有 dead · list all dead agents
"""
import os, time

HERE = os.path.dirname(os.path.abspath(__file__))


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _now_ts():
    return time.time()


class Heartbeat:
    def __init__(self, path=None, period=10, dead_after=3):
        """period：心跳周期（秒）。dead_after：缺多少周期判定 dead。
        period: heartbeat period (in seconds). dead_after: how many missed periods count as dead."""
        self.path = path or os.path.join(HERE, '心跳卷.txt')
        self.period = period
        self.dead_after = dead_after
        if not os.path.exists(self.path):
            open(self.path, 'a', encoding='utf-8').close()

    def beat(self, agent_id):
        """Agent 自报心跳·append-only。
        Agent reports its own heartbeat · append-only."""
        from safeio import atomic_append
        rec = '[%s] [心跳] [%s] alive\n' % (_now(), agent_id)
        atomic_append(self.path, rec)
        return True

    def _last_beats(self):
        """单遍扫心跳卷 → {agent_id: 最后心跳 epoch}。整卷只读一次。
        Single pass over the heartbeat volume → {agent_id: last heartbeat epoch}. One volume read only.
        修前 dead_agents 对每个 agent 各调一次 is_alive，每个 agent 都把整卷重读一遍；
        现在一次扫描拿到全部最后时间戳，再按阈值比较。
        Before, dead_agents called is_alive per agent, re-reading the whole volume for each;
        now one scan collects every last timestamp, then compares against the threshold."""
        last = {}
        from safeio import read_vol
        text, _enc, _why = read_vol(self.path)
        for line in text.splitlines():
            # [时间] [心跳] [agent_id] alive
            # Entry format: [time] [heartbeat] [agent_id] alive
            if '[心跳]' not in line or 'alive' not in line:
                continue
            parts = [p.strip(' []') for p in line.split(']') if p.strip()]
            if len(parts) < 3:
                continue
            agent_id = parts[2]
            if not agent_id or agent_id in ('心跳', 'alive'):
                continue
            try:
                ts = time.mktime(time.strptime(parts[0], '%Y-%m-%d %H:%M:%S'))
            except ValueError:
                continue
            if agent_id not in last or ts > last[agent_id]:
                last[agent_id] = ts
        return last

    def _last_beat(self, agent_id):
        """单 agent 最后心跳时间戳（单遍扫描）。
        Last heartbeat timestamp for one agent (single pass)."""
        return self._last_beats().get(agent_id)

    def is_alive(self, agent_id):
        """缺心跳 > dead_after 周期 → False。
        Missing heartbeat > dead_after periods → False."""
        last = self._last_beat(agent_id)
        if last is None:
            return False
        return (_now_ts() - last) < (self.period * self.dead_after)

    def dead_agents(self):
        """扫所有出现过的 agent_id·返回 dead 列表（单遍扫描 + 时间戳阈值，不按字串判断）。
        Scan all agent_ids ever seen · return the dead list (one scan + timestamp threshold, never substring matching)."""
        now = _now_ts()
        limit = self.period * self.dead_after
        return [a for a, ts in self._last_beats().items() if (now - ts) >= limit]

    def recover(self, agent_id):
        """恢复：写一条 alive 条目·reset 计时。
        Recovery: write an alive entry · reset the timer."""
        return self.beat(agent_id)


def main():
    import sys
    if len(sys.argv) < 2:
        print(__doc__); return 1
    hb = Heartbeat()
    cmd = sys.argv[1]
    if cmd == 'beat' and len(sys.argv) >= 3:
        hb.beat(sys.argv[2])
        print('beat OK')
    elif cmd == 'alive' and len(sys.argv) >= 3:
        print('alive' if hb.is_alive(sys.argv[2]) else 'dead')
    elif cmd == 'dead':
        for a in hb.dead_agents():
            print(a)
    elif cmd == 'recover' and len(sys.argv) >= 3:
        hb.recover(sys.argv[2])
        print('recovered')
    else:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
