#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并发写卷器：调用被测件 daybook-orch 的写原语 daybook_append.append_one。
Concurrent writer using the exact primitive orchestrator._log calls.

--inject：0 号写者把一条分成两段写（不加锁），与 1 号写者握手，
          保证另一条记录插进两段之间 => 判据必须报错。
"""
import argparse
import json
import os
import platform
import sys
import time

import common as C

sys.path.insert(0, C.payload('orch'))
import daybook_append as dba   # noqa: E402


def write_one(seq, wid, aid, secret, start=1):
    dba.append_one(C.VOLUME, C.KIND, C.title(seq), C.body(seq, wid),
                   author=aid, msg_id=C.eid(seq),
                   sig=C.sign(seq, wid, aid, secret), now=C.NOW)


def _rss(ru):
    v = ru.ru_maxrss
    return v if platform.system() == 'Darwin' else v * 1024


def run(n, writers, inject=False, start=1):
    agents = C.load_agents()
    if writers > len(agents):
        raise SystemExit('注册 agent 不够：需要 %d，实有 %d' % (writers, len(agents)))
    parent_start = time.time()
    pipes = {}
    if inject:
        pipes = {'p1r': None, 'p1w': None, 'p2r': None, 'p2w': None}
        pipes['p1r'], pipes['p1w'] = os.pipe()
        pipes['p2r'], pipes['p2w'] = os.pipe()
    kids = []
    for wid in range(writers):
        pid = os.fork()
        if pid == 0:
            try:
                aid, secret = C.agent_of(wid, agents)
                t0 = time.time()
                k = 0
                seqs_all = [s for s in range(start, start + n)
                            if (s - start) % writers == wid]
                if inject and wid == 0:
                    seq = start
                    rec = C.record(seq, 0, aid, secret).encode('utf-8')
                    fd = os.open(C.VOLUME, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                    try:
                        os.write(fd, rec[:len(rec) // 2])
                    finally:
                        os.close(fd)
                    os.write(pipes['p1w'], b'1')
                    os.read(pipes['p2r'], 1)
                    fd = os.open(C.VOLUME, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                    try:
                        os.write(fd, rec[len(rec) // 2:])
                    finally:
                        os.close(fd)
                    k += 1
                    rest = [s for s in seqs_all if s != seq]
                elif inject and wid == 1:
                    os.read(pipes['p1r'], 1)
                    seq = start + 1
                    write_one(seq, 1, aid, secret, start)
                    os.write(pipes['p2w'], b'1')
                    k += 1
                    rest = [s for s in seqs_all if s != seq]
                else:
                    rest = seqs_all
                for seq in rest:
                    write_one(seq, wid, aid, secret, start)
                    k += 1
                with open(os.path.join(C.DATA_ROOT, '.writer_%d.json' % wid), 'w') as f:
                    json.dump({'wid': wid, 'n': k, 'start': t0, 'end': time.time()}, f)
            except BaseException as exc:   # noqa: BLE001
                os.write(2, ('writer %d failed: %r\n' % (wid, exc)).encode('utf-8', 'replace'))
                os._exit(3)
            os._exit(0)
        kids.append(pid)
    for fd in pipes.values():
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    codes, max_child_rss = [], 0
    for pid in kids:
        _, st, ru = os.wait4(pid, 0)
        codes.append(os.waitstatus_to_exitcode(st))
        max_child_rss = max(max_child_rss, _rss(ru))
    wall = time.time() - parent_start
    stats = []
    for wid in range(writers):
        p = os.path.join(C.DATA_ROOT, '.writer_%d.json' % wid)
        if os.path.exists(p):
            with open(p) as f:
                stats.append(json.load(f))
            os.remove(p)
    self_ru = __import__('resource').getrusage(__import__('resource').RUSAGE_SELF)
    return {'n': n, 'writers': writers, 'start': start, 'inject': inject,
            'wall_s': round(wall, 3), 'entries_per_s': round(n / wall, 1),
            'nonzero_exit': [c for c in codes if c != 0],
            'children_seen': len(stats), 'volume_bytes': os.path.getsize(C.VOLUME),
            'peak_rss_mb': round(max(max_child_rss, _rss(self_ru)) / 1048576.0, 1),
            'loadavg': list(os.getloadavg())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--writers', type=int, default=8)
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--inject', action='store_true')
    a = ap.parse_args()
    r = run(a.n, a.writers, a.inject, a.start)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if not r['nonzero_exit'] else 1


if __name__ == '__main__':
    sys.exit(main())
