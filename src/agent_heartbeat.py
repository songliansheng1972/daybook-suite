#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""Agent 心跳卷（W-DB-023-G3·第 6 项）
================================================
- 心跳卷 append-only：[时间] [心跳] [agent_id] alive
- 缺心跳 > 3 周期 → 标 dead → 触发恢复
- 零依赖：仅用 Python 3 标准库（os/time）

用法：
  hb = Heartbeat(period=10)         # 周期 10 秒
  hb.beat('agent_xxx')              # Agent 自报心跳
  alive = hb.is_alive('agent_xxx')  # 查活/死
  dead = hb.dead_agents()           # 列出所有 dead
"""
import os, time

HERE = os.path.dirname(os.path.abspath(__file__))


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _now_ts():
    return time.time()


class Heartbeat:
    def __init__(self, path=None, period=10, dead_after=3):
        """period：心跳周期（秒）。dead_after：缺多少周期判定 dead。"""
        self.path = path or os.path.join(HERE, '心跳卷.txt')
        self.period = period
        self.dead_after = dead_after
        if not os.path.exists(self.path):
            open(self.path, 'a', encoding='utf-8').close()

    def beat(self, agent_id):
        """Agent 自报心跳·append-only。"""
        from safeio import atomic_append
        rec = '[%s] [心跳] [%s] alive\n' % (_now(), agent_id)
        atomic_append(self.path, rec)
        return True

    def _last_beat(self, agent_id):
        """单遍扫描心跳卷·返回 agent 最后心跳时间戳。"""
        import re as _re
        _aid_pat = _re.compile(r'^\[[^\]]+\] \[心跳\] \[%s\] ' % _re.escape(agent_id))
        last_str = None
        from safeio import read_vol
        text, _enc, _why = read_vol(self.path)
        for line in text.splitlines():
            # [时间] [心跳] [agent_id] alive
            if _aid_pat.match(line) and 'alive' in line:
                try:
                    ts_str = line.split(']')[0].lstrip(' [').strip()
                    last_str = ts_str
                except Exception:
                    continue
        if not last_str:
            return None
        try:
            return time.mktime(time.strptime(last_str, '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            return None

    def is_alive(self, agent_id):
        """缺心跳 > dead_after 周期 → False。"""
        last = self._last_beat(agent_id)
        if last is None:
            return False
        return (_now_ts() - last) < (self.period * self.dead_after)

    def dead_agents(self):
        """扫所有出现过的 agent_id·返回 dead 列表。"""
        agents = set()
        from safeio import read_vol
        text, _enc, _why = read_vol(self.path)
        for line in text.splitlines():
            if '[心跳]' not in line or 'alive' not in line:
                continue
            # [时间] [心跳] [agent_id] alive → parts[2] 是 agent_id
            parts = [p.strip(' []') for p in line.split(']') if p.strip()]
            if len(parts) < 3:
                continue
            agent_id = parts[2]
            if agent_id and agent_id not in ('心跳', 'alive'):
                agents.add(agent_id)
        return [a for a in agents if not self.is_alive(a)]

    def recover(self, agent_id):
        """恢复：写一条 alive 条目·reset 计时。"""
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
