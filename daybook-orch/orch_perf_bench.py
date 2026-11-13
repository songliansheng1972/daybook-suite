#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook-orch 性能对照：同一批数据，修前 / 修后各跑一遍。
daybook-orch performance A/B: the same dataset, run once on the fixed code and once on the old code.

测两处（批次二第 6 条）：
Two spots (batch 2, item 6):
  1. digest：20 行摘要读几次卷、盘读多少字节、耗时多少；
     digest: how many volume reads, how many bytes, and how long for a 20-line digest;
  2. dead_agents：N 个 agent 判失联，读几次卷、盘读多少字节、耗时多少。
     dead_agents: how many volume reads and bytes to mark N agents dead.

修前行为由「把当前包复制到临时目录 + 文本替换回旧实现」得到，数据同一份。
The "before" behavior is produced by copying this package to a temp dir and text-reverting
the two implementations; the dataset is identical.

用法：python3 orch_perf_bench.py
退出码：0=对照完成（不判绿红，读数供存档）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.locks', '.daybook_keys',
                                '.safeio_lock.*', '*.tmp', 'multilevel', '索引')

# 修前实现（与 orch_mutation_check.py 第 12 条同源）
# The old implementations (same source as mutation item 12).
OLD_DIGEST = (
    """        return cr.make_ref(vol, int(lineno), index=index), ''""",
    """        return cr.make_ref(vol, int(lineno)), ''""",
)
OLD_DEAD = (
    """    def dead_agents(self):
        \"\"\"扫所有出现过的 agent_id·返回 dead 列表（单遍扫描 + 时间戳阈值，不按字串判断）。
        Scan all agent_ids ever seen · return the dead list (one scan + timestamp threshold, never substring matching).\"\"\"
        now = _now_ts()
        limit = self.period * self.dead_after
        return [a for a, ts in self._last_beats().items() if (now - ts) >= limit]""",
    """    def dead_agents(self):
        agents = set()
        from safeio import read_vol
        text, _enc, _why = read_vol(self.path)
        for line in text.splitlines():
            if '[心跳]' not in line or 'alive' not in line:
                continue
            parts = [p.strip(' []') for p in line.split(']') if p.strip()]
            if len(parts) < 3:
                continue
            agent_id = parts[2]
            if agent_id and agent_id not in ('心跳', 'alive'):
                agents.add(agent_id)
        return [a for a in agents if not self.is_alive(a)]""",
)


def build_dataset(root, n_entries=24, body_bytes=900):
    """造同一批数据：1 卷 / n_entries 条；心跳卷 200 agent × 5 次。
    Build the shared dataset: one volume with n_entries; a heartbeat volume with 200 agents × 5 beats."""
    with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[volumes]\n协作=协作卷.txt\n')
    body = 'x' * body_bytes
    with open(os.path.join(root, '协作卷.txt'), 'w', encoding='utf-8') as f:
        for i in range(n_entries):
            f.write('[2026-11-14 10:%02d:%02d] [报] [条目%02d] [汤姆] %s\n\n'
                    % ((i // 60) % 60, i % 60, i, body))
    hb = os.path.join(root, '心跳卷.txt')
    with open(hb, 'w', encoding='utf-8') as f:
        for a in range(200):
            for b in range(5):
                f.write('[2026-11-14 09:%02d:%02d] [心跳] [ag-%03d] alive\n' % (b, a % 60, a))
    return {
        'volume_bytes': os.path.getsize(os.path.join(root, '协作卷.txt')),
        'volume_entries': n_entries,
        'heartbeat_lines': 200 * 5,
        'heartbeat_bytes': os.path.getsize(hb),
    }


def measure(pkg, root, skip_dead=False):
    """在当前进程里测两个场景，返回 dict。pkg 为包目录。
    Measure both scenarios in-process; returns a dict. `pkg` is the package directory."""
    sys.path.insert(0, pkg)
    import safeio
    from orchestrator import Hub

    orig = safeio.read_vol
    stats = {'calls': 0, 'bytes': 0}

    def counted(path):
        stats['calls'] += 1
        try:
            stats['bytes'] += os.path.getsize(path)
        except OSError:
            pass
        return orig(path)

    hub = Hub(root=root)
    out = {}
    safeio.read_vol = counted
    try:
        stats.update(calls=0, bytes=0)
        t0 = time.perf_counter()
        lines, rows, src = hub.digest(limit=20)
        out['digest'] = {'calls': stats['calls'], 'bytes': stats['bytes'],
                         'seconds': time.perf_counter() - t0,
                         'rows': len(rows), 'src': src,
                         'shown': sum(1 for x in lines if x.startswith('  部.'))}
    finally:
        safeio.read_vol = orig
    if skip_dead:
        out['dead_agents'] = {'calls': 0, 'bytes': 0, 'seconds': 0.0, 'agents': 0}
    else:
        safeio.read_vol = counted
        try:
            stats.update(calls=0, bytes=0)
            t0 = time.perf_counter()
            dead = hub.hb.dead_agents()
            out['dead_agents'] = {'calls': stats['calls'], 'bytes': stats['bytes'],
                                  'seconds': time.perf_counter() - t0, 'agents': len(dead)}
        finally:
            safeio.read_vol = orig
    return out


def make_old_pkg():
    """复制包并注入旧实现，返回临时目录。 · Copy the package and inject the old implementations; return the temp dir."""
    tmp = tempfile.mkdtemp(prefix='orch_perf_old_')
    dest = os.path.join(tmp, 'pkg')
    shutil.copytree(HERE, dest, ignore=IGNORE)
    for fn, (old, new) in (('orchestrator.py', OLD_DIGEST),
                           ('agent_heartbeat.py', OLD_DEAD)):
        p = os.path.join(dest, fn)
        with open(p, encoding='utf-8') as f:
            src = f.read()
        if old not in src:
            raise RuntimeError('修前锚点未命中：%s' % fn)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(src.replace(old, new, 1))
    return tmp, dest


def head_sha():
    try:
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=HERE,
                           capture_output=True, text=True)
        return (r.stdout or '').strip() or 'unknown'
    except OSError:
        return 'unknown'


def main(argv):
    if '--pkg' in argv:
        i = argv.index('--pkg')
        pkg = argv[i + 1]
        root = argv[argv.index('--root') + 1]
        print(json.dumps(measure(pkg, root, skip_dead='--skip-dead' in argv),
                         ensure_ascii=False))
        return 0

    n_entries, body_bytes = 24, 900
    if '--scale' in argv:
        n_entries = int(argv[argv.index('--scale') + 1])
    if '--body' in argv:
        body_bytes = int(argv[argv.index('--body') + 1])
    skip_dead = '--skip-dead' in argv

    root = tempfile.mkdtemp(prefix='orch_perf_data_')
    tmp_old = None
    try:
        data = build_dataset(root, n_entries, body_bytes)
        print('HEAD=%s  起跑=%s' % (head_sha(), time.strftime('%Y-%m-%d %H:%M:%S')))
        print('数据：卷 %d 字节（%d 条）｜心跳 %d 行 / %d 字节（200 agent × 5）'
              % (data['volume_bytes'], data['volume_entries'],
                 data['heartbeat_lines'], data['heartbeat_bytes']))
        new = measure(HERE, root, skip_dead=skip_dead)
        tmp_old, old_pkg = make_old_pkg()
        cmd = [sys.executable, os.path.abspath(__file__),
               '--pkg', old_pkg, '--root', root]
        if skip_dead:
            cmd.append('--skip-dead')
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout + r.stderr)
            return 1
        old = json.loads(r.stdout.strip().splitlines()[-1])
        fmt = '  %-14s %8s %12s %10s'
        print(fmt % ('场景', '卷读次数', '盘读字节', '耗时(ms)'))
        for key, label in (('digest', 'digest'), ('dead_agents', 'dead_agents')):
            for tag, d in (('修前', old[key]), ('修后', new[key])):
                print(fmt % ('%s·%s' % (label, tag), d['calls'], d['bytes'],
                             '%.2f' % (d['seconds'] * 1000)))
        print('  digest 明细：修前 %d 条摘要 / 修后 %d 条；来源 %s'
              % (old['digest']['shown'], new['digest']['shown'], new['digest']['src']))
        return 0
    finally:
        if tmp_old:
            shutil.rmtree(tmp_old, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
