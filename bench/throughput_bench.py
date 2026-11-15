#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""4.0.6 吞吐实测（可复跑）：写入（含根锁）与查询两条读数。
4.0.6 throughput measurement (re-runnable): one reading for writes (root lock included)
and one for queries.

为什么需要这个读数：4.0.6 之前的「6.2–9.3 万条/秒」来自**无锁**追加路径（O_APPEND 单写），
不代表 4.0.6 的「全根串行写」。本脚本只测收口版真实形态：
  · 单条追加：`daybook_append.append_one` 公开入口，含账本根排他锁 + O_APPEND 单写；
  · 增量索引：追加一条后跑一次 `daybook.py index`（全根临界区）；
  · 查询：在 N 条索引上跑一次 `daybook.py query`；
  · 锁等待：另一进程持根锁 H 秒，本进程实测等待秒数。
Why: the old "62k–93k entries/s" came from the **lock-free** append path; it does not represent
4.0.6's serialized whole-root write. This script measures only the shipped shape: one append
through the public entry (root lock + single O_APPEND write), one incremental `index` run, one
`query` over the index, and the measured wait of a second writer while the root lock is held.

用法 / Usage:
  python3 throughput_bench.py                 # 默认 40 万条 / 200 次追加 / 持锁 1.0s
  python3 throughput_bench.py --entries 100000 --appends 100 --hold 0.5
  python3 throughput_bench.py --check         # 读数必须落在收口判据的宽松上限内
退出码：0 = 完成（--check 时且全部落在上限内）；1 = --check 越界。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'src')

# 收口判据的宽松上限（只挡「退化一个数量级」，不追求机器间的微秒差）。
# Loose ceilings for the acceptance criteria (catch an order-of-magnitude regression only).
CHECK_APPEND_MS = 200.0     # 单条追加（含根锁）上限
CHECK_QUERY_S = 60.0        # 40 万条索引上的一次查询上限
CHECK_WAIT_RATIO = 0.8      # 实测等待 ≥ 持锁时长 × 该比例


def _conf(root):
    path = os.path.join(root, 'daybook.conf')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('[volumes]\n账=账卷.txt\n\n[index]\nout_dir=索引\n')
    return path


def _make_volume(path, n):
    with open(path, 'w', encoding='utf-8') as f:
        for i in range(n):
            f.write('[2026-11-13 10:00:00] [测试] [条目%06d] [皮特] 正文\n' % i)


def _run(root, *args):
    script = 'daybook.py'
    cmd = [sys.executable, '-B', os.path.join(SRC, script)] + list(args) + ['--home', root]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=1800)


def main(argv=None):
    ap = argparse.ArgumentParser(description='4.0.6 吞吐实测 / throughput benchmark')
    ap.add_argument('--entries', type=int, default=400000)
    ap.add_argument('--appends', type=int, default=200)
    ap.add_argument('--hold', type=float, default=1.0)
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)

    root = tempfile.mkdtemp(prefix='daybook_bench_')
    try:
        _conf(root)
        vol = os.path.join(root, '账卷.txt')
        _make_volume(vol, a.entries)
        vol_bytes = os.path.getsize(vol)

        t0 = time.time()
        r = _run(root, 'baseline')
        build_s = time.time() - t0
        if r.returncode:
            sys.stderr.write('baseline 失败 rc=%d\n%s\n' % (r.returncode, r.stderr))
            return 1

        # ── 1. 单条追加（公开入口：根锁 + O_APPEND 单写）──
        sys.path.insert(0, SRC)
        import daybook_append
        from safeio import Root
        rt = Root.open(root)
        try:
            t0 = time.time()
            for i in range(a.appends):
                daybook_append.append_one(
                    vol, '基准', '追加%04d' % i, '正文', author='皮特', root=rt)
            append_s = time.time() - t0
        finally:
            rt.close()
        append_ms = append_s * 1000.0 / a.appends

        # ── 2. 追加一条后的增量索引（全根临界区）──
        rt = Root.open(root)
        try:
            daybook_append.append_one(vol, '基准', '增量', '正文', author='皮特', root=rt)
        finally:
            rt.close()
        t0 = time.time()
        r2 = _run(root, 'index')
        index_s = time.time() - t0
        if r2.returncode:
            sys.stderr.write('index 失败 rc=%d\n%s\n' % (r2.returncode, r2.stderr))
            return 1

        # ── 3. 查询（读侧不取锁）──
        t0 = time.time()
        r3 = _run(root, 'query', 'title=条目000001')
        query_s = time.time() - t0
        if r3.returncode:
            sys.stderr.write('query 失败 rc=%d\n%s\n' % (r3.returncode, r3.stderr))
            return 1

        # ── 4. 持根锁期间另一写者的等待（跨进程 flock）──
        hold_cmd = [sys.executable, '-B', '-c', _HOLD, SRC, root, str(a.hold)]
        holder = subprocess.Popen(hold_cmd, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, universal_newlines=True)
        try:
            line = holder.stdout.readline().strip()
            if line != 'READY':
                sys.stderr.write('持锁进程未就位：%r\n' % line)
                return 1
            rt2 = Root.open(root)
            try:
                t0 = time.time()
                with rt2.lock():
                    wait_s = time.time() - t0
            finally:
                rt2.close()
        finally:
            holder.communicate(timeout=60)

        out = {
            'entries': a.entries,
            'volume_bytes': vol_bytes,
            'appends': a.appends,
            'append_ms_per_entry': round(append_ms, 3),
            'append_entries_per_s': round(1000.0 / append_ms, 1) if append_ms else 0.0,
            'baseline_s': round(build_s, 3),
            'incremental_index_s': round(index_s, 3),
            'query_s': round(query_s, 3),
            'hold_s': a.hold,
            'other_writer_wait_s': round(wait_s, 3),
        }
        print('[读数] 数据规模：%d 条 / 卷 %.1f MB（基线 index %.2fs）'
              % (a.entries, vol_bytes / 1048576.0, build_s))
        print('[读数] 写入（含根锁）：单条追加 %.2f ms（≈ %.0f 条/秒）；追加一条后的增量 index %.2f s'
              % (append_ms, out['append_entries_per_s'], index_s))
        print('[读数] 查询：%d 条索引上一次 query %.2f s' % (a.entries, query_s))
        print('[读数] 持根锁 %.2fs 期间另一写者实测等待 %.2f s'
              % (a.hold, wait_s))
        print('JSON ' + json.dumps(out, ensure_ascii=False, sort_keys=True))

        if a.check:
            bad = []
            if append_ms > CHECK_APPEND_MS:
                bad.append('单条追加 %.2fms > %.0fms' % (append_ms, CHECK_APPEND_MS))
            if query_s > CHECK_QUERY_S:
                bad.append('查询 %.2fs > %.0fs' % (query_s, CHECK_QUERY_S))
            if wait_s < a.hold * CHECK_WAIT_RATIO:
                bad.append('锁等待 %.2fs < %.2fs×%.2f' % (wait_s, a.hold, CHECK_WAIT_RATIO))
            print('CHECK %s' % ('PASS' if not bad else 'FAIL ' + '；'.join(bad)))
            return 0 if not bad else 1
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


_HOLD = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from safeio import Root
rt = Root.open(sys.argv[2])
with rt.lock():
    print('READY', flush=True)
    time.sleep(float(sys.argv[3]))
rt.close()
'''


if __name__ == '__main__':
    sys.exit(main())
