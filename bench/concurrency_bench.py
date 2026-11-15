#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""并发写者上限实测（可复跑）：8 / 64 / 256 / 1000 四点。
Concurrent-writer readings (re-runnable) at 8 / 64 / 256 / 1000.

口径 / Scope:
  · 写者 = 同进程线程，每个写者自己持一个 Root 句柄，逐条走公开追加入口（含账本根排他锁）。
  · Writers are threads in one process; each opens its own Root handle and appends one entry at
    a time through the public entry (root lock included).
  · 跨进程互斥由既有 P0/Q 判据覆盖；这里量的是「同一根锁下 N 个写者」的成功率与延迟分布。
    Cross-process exclusion is covered by the existing P0/Q criteria; this measures success rate
    and latency distribution for N writers under one root lock.
  · 延迟 = 单条追加从调用进入到返回的墙钟时间（含排队等锁）。
    Latency = wall time of one append call, including lock queueing.

判据 / Criteria:
  · 成功率 100%（任何异常都算失败，逐条记录）
  · p95 与 max 只报读数，不设「必须小于」的阈值——上限档 1000 的闸门是成功率与「超阈值等待计数」
  · 阈值默认 250 ms；超过即计入 slow，逐档打印
用法 / Usage:
  python3 concurrency_bench.py --check
  python3 concurrency_bench.py --points 8,64 --appends 50
退出码：0 = 全部档位成功率 100%（--check 时）；1 = 有失败。
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

DEFAULT_POINTS = (8, 64, 256, 1000)


def _pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def run_point(root, n_writers, per_writer, threshold):
    import safeio
    lat = []
    errs = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_writers + 1)

    def writer(w):
        rt = safeio.Root._from_dir_path(root, 'concurrency_bench')
        try:
            barrier.wait()
            for i in range(per_writer):
                t0 = time.perf_counter()
                try:
                    safeio.atomic_append(os.path.join(root, '账卷.txt'),
                                         '[2026-11-15 12:00:00] [并发] [写者%03d-%03d] [皮特] 正文\n'
                                         % (w, i), root=rt, ensure_newline=True)
                    dt = time.perf_counter() - t0
                    with lock:
                        lat.append(dt)
                except BaseException as exc:
                    with lock:
                        errs.append('%s: %s' % (type(exc).__name__, exc))
        finally:
            rt.close()

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(n_writers)]
    for t in threads:
        t.start()
    barrier.wait()
    t0 = time.perf_counter()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0

    attempted = n_writers * per_writer
    ok = len(lat)
    slow = sum(1 for v in lat if v >= threshold)
    ms = [v * 1000.0 for v in lat]
    return {
        'writers': n_writers,
        'per_writer': per_writer,
        'attempted': attempted,
        'ok': ok,
        'success_rate': round(ok / attempted, 4) if attempted else 0.0,
        'p50_ms': round(_pct(ms, 0.50), 3),
        'p95_ms': round(_pct(ms, 0.95), 3),
        'max_ms': round(max(ms), 3) if ms else 0.0,
        'slow': slow,
        'threshold_ms': threshold * 1000.0,
        'wall_s': round(wall, 3),
        'errors': errs[:3],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='并发写者上限实测 / concurrency benchmark')
    ap.add_argument('--points', default=','.join(str(p) for p in DEFAULT_POINTS))
    ap.add_argument('--appends', type=int, default=20)
    ap.add_argument('--threshold', type=float, default=0.25)
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)

    points = [int(p) for p in a.points.split(',') if p.strip()]
    root = tempfile.mkdtemp(prefix='daybook_concurrency_')
    try:
        with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n账=账卷.txt\n\n[index]\nout_dir=索引\n')
        open(os.path.join(root, '账卷.txt'), 'wb').close()
        rows = []
        for n in points:
            row = run_point(root, n, a.appends, a.threshold)
            rows.append(row)
            print('[点数 %4d] 成功率 %.2f%%（%d/%d）· p50 %.2fms / p95 %.2fms / max %.2fms'
                  ' · 等待≥%.0fms 的写 %d 条 · 墙钟 %.2fs'
                  % (n, row['success_rate'] * 100.0, row['ok'], row['attempted'],
                     row['p50_ms'], row['p95_ms'], row['max_ms'],
                     row['threshold_ms'], row['slow'], row['wall_s']))
            if row['errors']:
                print('  首例错误：%s' % row['errors'][0])
        print('JSON ' + json.dumps(rows, ensure_ascii=False, sort_keys=True))
        if a.check:
            bad = [r for r in rows if r['success_rate'] < 1.0]
            print('CHECK %s' % ('PASS' if not bad else
                                'FAIL ' + '；'.join('%d 写者成功率 %.2f%%'
                                                   % (r['writers'], r['success_rate'] * 100)
                                                   for r in bad)))
            return 0 if not bad else 1
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
