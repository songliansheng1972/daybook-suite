#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""4.0.6 长跑（soak）：watch 长跑 + 多写者并发混合，看崩不崩、漏不漏。
4.0.6 soak: long-running `watch` mixed with concurrent writers; checks crashes and leaks.

测什么 / What it measures:
  · 多个独立进程持续追加同一卷（每个进程一条 Root 句柄、每次追加都取根锁）；
  · 同时跑 `daybook.py watch 30`（每 30 秒判一次变动并重建索引/多级目录/备份）；
  · 每 30 秒采样每个进程的 RSS 与 fd 数，形成曲线；
  · 结束后核对：账卷条数 == 初始 + 成功追加数、全部行可解析、失败/重试为 0、
    RSS 与 fd 无持续增长（首末对比）。
It runs N independent writer processes against one volume (each holds one Root handle and takes
the root lock per append) while `watch` re-indexes: samples RSS/fd every 30 s, then verifies the
line count, parseability, zero failures, and no monotonic RSS/fd growth.

用法 / Usage:
  python3 soak.py --minutes 60 --writers 8 --interval 2.0          # 1 小时（非 24 小时）
  python3 soak.py --minutes 2 --writers 8 --interval 0.2 --check   # 冒烟
退出码：0 = 完成（--check 时且判据全绿）；1 = 判据红；2 = 环境不支持。
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'src')
LINE = re.compile(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] '
                  r'\[[^\]]+\] \[[^\]]+\] \[[^\]]+\] .*$')


def _env():
    e = dict(os.environ)
    e['PYTHONPATH'] = SRC + (os.pathsep + e['PYTHONPATH'] if e.get('PYTHONPATH') else '')
    e['PYTHONUNBUFFERED'] = '1'
    return e


def _rss_kb(pid):
    try:
        out = subprocess.run(['ps', '-o', 'rss=', '-p', str(pid)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             universal_newlines=True, timeout=10).stdout.strip()
        return int(out) if out else 0
    except Exception:
        return 0


def _fds(pid):
    d = '/proc/%d/fd' % pid
    if os.path.isdir(d):
        try:
            return len(os.listdir(d))
        except OSError:
            return 0
    try:
        out = subprocess.run(['lsof', '-p', str(pid)], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, universal_newlines=True,
                             timeout=20).stdout
        return max(0, len(out.splitlines()) - 1)
    except Exception:
        return 0


def _child(root, tag, interval, seconds):
    """子进程写者：一条 Root 句柄，按间隔追加，退出时打印 JSON 读数。
    Child writer: one Root handle, appends at an interval, prints JSON on exit."""
    sys.path.insert(0, SRC)
    import safeio
    rt = safeio.Root._from_dir_path(root, 'soak')
    vol = os.path.join(root, '账卷.txt')
    ok = fail = 0
    t_end = time.time() + seconds
    i = 0
    while time.time() < t_end:
        try:
            with rt.lock(timeout=120) as lr:
                lr.write(rt.rel_of(vol, 'soak.child'),
                         '[%s] [长跑] [写者%s-%05d] [皮特] 正文 %d\n'
                         % (time.strftime('%Y-%m-%d %H:%M:%S'), tag, i, i),
                         mode=safeio.WriteMode.APPEND_CREATE, pad_newline=True)
            ok += 1
        except Exception:
            fail += 1
        i += 1
        time.sleep(interval)
    rt.close()
    print('__CHILD__' + json.dumps({'tag': tag, 'ok': ok, 'fail': fail}))
    return 0 if fail == 0 else 1


def _init_root(root):
    os.makedirs(root)
    with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[volumes]\n账=账卷.txt\n')
    open(os.path.join(root, '账卷.txt'), 'wb').close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=float, default=60)
    ap.add_argument('--writers', type=int, default=8)
    ap.add_argument('--interval', type=float, default=2.0)
    ap.add_argument('--sample', type=float, default=30.0)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--child', nargs=4)
    args = ap.parse_args()
    if args.child:
        root, tag, interval, seconds = args.child
        return _child(root, tag, float(interval), float(seconds))
    if os.name == 'nt':
        print('SOAK SKIP：本长跑脚本依赖 POSIX ps/lsof（Windows 未验证）')
        return 2

    work = tempfile.mkdtemp(prefix='daybook_soak_')
    root = os.path.join(work, 'ledger')
    _init_root(root)
    dur = args.minutes * 60.0
    env = _env()
    daybook = os.path.join(SRC, 'daybook.py')
    n0 = 0
    print('SOAK 开始：时长=%.1f 分钟（%s）写者=%d 间隔=%.1fs 根=%s'
          % (args.minutes, '1 小时，非 24 小时' if args.minutes == 60 else '冒烟/自定义',
             args.writers, args.interval, root))
    watch = subprocess.Popen([sys.executable, '-B', daybook, 'watch', '30'], cwd=root,
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    writers = [subprocess.Popen([sys.executable, '-B', os.path.abspath(__file__),
                                 '--child', root, 'W%02d' % i, str(args.interval),
                                 str(dur)], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True)
               for i in range(args.writers)]
    curve = []
    t0 = time.time()
    try:
        while time.time() - t0 < dur + 15:
            if watch.poll() is not None:
                break
            if time.time() - t0 >= 5:
                row = {'t': round(time.time() - t0, 1),
                       'watch': (_rss_kb(watch.pid), _fds(watch.pid)),
                       'writers': [(p.pid, _rss_kb(p.pid), _fds(p.pid))
                                   for p in writers if p.poll() is None]}
                curve.append(row)
            if all(p.poll() is not None for p in writers) and \
                    time.time() - t0 >= dur:
                break
            time.sleep(min(args.sample, 5.0 if args.minutes < 1 else args.sample))
    finally:
        for p in writers:
            if p.poll() is None:
                p.wait(timeout=180)
        if watch.poll() is None:
            watch.send_signal(signal.SIGTERM)
        try:
            watch_out = watch.communicate(timeout=60)[0] or ''
        except subprocess.TimeoutExpired:
            watch.kill()
            watch_out = watch.communicate()[0] or ''
        child_out = []
        for p in writers:
            try:
                child_out.append(p.communicate(timeout=60)[0] or '')
            except subprocess.TimeoutExpired:
                p.kill()
                child_out.append('')

    res = []
    for out in child_out:
        for line in out.splitlines():
            if line.startswith('__CHILD__'):
                res.append(json.loads(line[len('__CHILD__'):]))
    ok = sum(r['ok'] for r in res)
    fail = sum(r['fail'] for r in res)
    with open(os.path.join(root, '账卷.txt'), 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8', 'replace')
    lines = [x for x in text.split('\n') if x]
    bad = [i + 1 for i, x in enumerate(text.split('\n')) if x and not LINE.match(x)]
    total_ok = (len(lines) == n0 + ok and not bad)
    w0, w1 = curve[0]['watch'] if curve else (0, 0), curve[-1]['watch'] if curve else (0, 0)
    # 按 pid 取「首末两次都活着」的样本，避免写者退出把合计拉低造成假象
    # Compare first/last samples per pid that is alive at both ends (writers exiting must not
    # look like a drop).
    wr = {}
    for c in curve:
        for pid, rss, fd in c['writers']:
            wr.setdefault(pid, []).append((rss, fd))
    wr = {k: v for k, v in wr.items() if len(v) >= 2}
    wr_rss0 = sum(v[0][0] for v in wr.values())
    wr_rss1 = sum(v[-1][0] for v in wr.values())
    wr_fd0 = sum(v[0][1] for v in wr.values())
    wr_fd1 = sum(v[-1][1] for v in wr.values())
    fd0, fd1 = wr_fd0, wr_fd1
    rss_growth = (w1[0] - w0[0]) / w0[0] * 100 if w0[0] else 0
    wr_growth = (wr_rss1 - wr_rss0) / wr_rss0 * 100 if wr_rss0 else 0
    leak = (rss_growth > 50) or (wr_growth > 50) or (fd1 - fd0 > 2) or (w1[1] - w0[1] > 2)
    crashed = watch.returncode not in (0, -signal.SIGTERM) or 'Traceback' in watch_out
    failures = fail + (0 if total_ok else 1) + (1 if crashed else 0) + (1 if leak else 0)
    print('SOAK 读数：写入成功=%d 失败=%d 最终行数=%d（应为 %d）坏行=%d'
          % (ok, fail, len(lines), n0 + ok, len(bad)))
    print('SOAK RSS：watch %.1f→%.1f MB（%+.1f%%）；写者合计 %.1f→%.1f MB'
          % (w0[0] / 1024.0, w1[0] / 1024.0, rss_growth, wr_rss0 / 1024.0,
             wr_rss1 / 1024.0))
    print('SOAK 写者 RSS 变化（同一批 pid 首末）：%+.1f%%' % wr_growth)
    print('SOAK fd：watch %d→%d；写者峰值 %d→%d'
          % (w0[1], w1[1], fd0, fd1))
    print('SOAK 曲线（每 %.0fs）：%s'
          % (args.sample, ' | '.join('t=%.0fs watch_rss=%.1fMB fd=%d'
                                     % (c['t'], c['watch'][0] / 1024.0, c['watch'][1])
                                     for c in curve[:8])) + (' ...' if len(curve) > 8 else ''))
    print('SOAK watch 轮次输出行=%d 崩溃=%s' % (len(watch_out.splitlines()), crashed))
    if watch_out.strip():
        print('SOAK watch 尾部：%s' % watch_out.strip().splitlines()[-1][:160])
    print('SOAK 判据：%s' % ('PASS' if failures == 0 else
                             'FAIL（失败=%d 崩溃=%s 泄漏=%s 条数一致=%s）'
                             % (fail, crashed, leak, total_ok)))
    shutil.rmtree(work, ignore_errors=True)
    if args.check:
        return 0 if failures == 0 else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
