#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能探针：建索引 / 未变复跑 / 查询 / 多级目录（digest 生成）/ orch digest 读取。
Perf probe. Each op runs in its own process and prints one JSON line with
wall seconds, logical read/write bytes by class, OS ru_inblock and peak RSS.
"""
import argparse
import json
import os
import sys
import time

import common as C
import iocount

sys.path.insert(0, C.payload('suite'))

import daybook as DB            # noqa: E402
import daybook_multidx as MI    # noqa: E402


def _conf():
    return DB.load_conf(path=os.path.join(C.ROOT_DB, 'daybook.conf'))


def op_index():
    conf = _conf()
    iocount.install()
    ib0 = iocount.inblock()
    t0 = time.perf_counter()
    per, total, report = DB.build(conf, root=C.ROOT_DB)
    dt = time.perf_counter() - t0
    return {'op': 'index', 'seconds': round(dt, 3), 'total_entries': total,
            'per_volume': per,
            'actions': [[v, w] for v, w in report],
            'read_bytes': iocount.snapshot()['read'],
            'write_bytes': iocount.snapshot()['write'],
            'ru_inblock_512B': iocount.inblock() - ib0,
            'maxrss_mb': iocount.maxrss_mb()}


def op_query(args):
    conf = _conf()
    iocount.install()
    ib0 = iocount.inblock()
    t0 = time.perf_counter()
    out = DB.query(conf, C.ROOT_DB, args)
    dt = time.perf_counter() - t0
    first = out.splitlines()[0] if out.splitlines() else ''
    return {'op': 'query ' + ' '.join(args), 'seconds': round(dt, 3),
            'first_line': first, 'output_bytes': len(out.encode('utf-8')),
            'read_bytes': iocount.snapshot()['read'],
            'write_bytes': iocount.snapshot()['write'],
            'ru_inblock_512B': iocount.inblock() - ib0,
            'maxrss_mb': iocount.maxrss_mb()}


def op_multidx():
    conf = MI.load_conf(os.path.join(C.ROOT_DB, 'daybook.conf'))
    root = MI.resolve_root(conf, C.ROOT_DB)
    iocount.install()
    ib0 = iocount.inblock()
    t0 = time.perf_counter()
    per, total = MI.build(conf, root, now='2026-11-14 00:00')
    dt = time.perf_counter() - t0
    return {'op': 'multiindex(digest 生成)', 'seconds': round(dt, 3),
            'total_entries': total, 'per_volume': dict(per),
            'read_bytes': iocount.snapshot()['read'],
            'write_bytes': iocount.snapshot()['write'],
            'ru_inblock_512B': iocount.inblock() - ib0,
            'maxrss_mb': iocount.maxrss_mb()}


def op_digest():
    sys.path.insert(0, C.payload('orch'))
    import orchestrator as O
    iocount.install()
    ib0 = iocount.inblock()
    t0 = time.perf_counter()
    hub = O.Hub(root=C.ROOT_DB)
    lines, rows, src = hub.digest(None, None, 20)
    dt = time.perf_counter() - t0
    return {'op': 'orch digest', 'seconds': round(dt, 3), 'source': src,
            'rows': len(rows), 'lines': len(lines),
            'read_bytes': iocount.snapshot()['read'],
            'write_bytes': iocount.snapshot()['write'],
            'ru_inblock_512B': iocount.inblock() - ib0,
            'maxrss_mb': iocount.maxrss_mb()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('op', choices=['index', 'query_count', 'query_one', 'multidx', 'digest'])
    ap.add_argument('--needle', default='')
    a = ap.parse_args()
    if a.op == 'index':
        r = op_index()
    elif a.op == 'query_count':
        r = op_query(['category=' + C.KIND, '--count'])
    elif a.op == 'query_one':
        r = op_query(['title=' + C.title(int(a.needle or 500000)), '--limit=1'])
    elif a.op == 'multidx':
        r = op_multidx()
    else:
        r = op_digest()
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
