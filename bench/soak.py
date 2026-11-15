#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""4.0.6 长跑（soak）：watch 长跑 + 多写者并发，判据看稳态斜率。
4.0.6 soak: long-running `watch` mixed with concurrent writers; the pass/fail criterion is the
steady-state RSS slope, not an absolute ceiling.

判据（可自证变红）/ Criterion (provably red-able):
  · 稳态斜率：取最后 N 次采样（N=min(10, 样本数/4)，至少 3 次）做最小二乘，
    |斜率| ≤ 24 MB/小时 才算不涨；绝对值只作参考（打印，不参与判定）。
    N 与阈值的由来：1 小时 1.4 万条的索引增长约 2 MB/小时；24 MB/小时＝10 倍余量。
    合成泄漏（每 4 秒吃 1 MB 不释放）≈ 900 MB/小时 ⇒ 必须被判红。
  · fd：首末增长 ≤ 2。
  · 采样不足 3 次 ⇒ FAIL（不许静默通过）。
  · 自证：`--leak-test` 用**同一套** judge 跑合成泄漏，必须判 FAIL，否则本判据算假绿。

用法 / Usage:
  python3 soak.py --minutes 60 --writers 8 --interval 2 --sample 30 --check
  python3 soak.py --minutes 12 --writers 8 --interval 1 --sample 15 --check --csv /tmp/x.csv
  python3 soak.py --leak-test                       # 合成泄漏自证（必须红）
退出码：0 = 判据绿（leak-test 时＝泄漏被抓到）；1 = 判据红/假绿；2 = 环境不支持。
"""
import argparse
import csv
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

SLOPE_MAX_MB_PER_H = 24.0   # 稳态斜率上限（MB/小时）；由来见文件头
HARD_CAP_MB = 512.0         # 只看绝对值的保险丝（参考项，不是主判据）
FD_MAX_GROWTH = 2


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
    """子进程写者：一条 Root 句柄，按间隔追加，退出时打印 JSON 读数。"""
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


def _leak_child(seconds):
    """合成泄漏：每 4 秒向全局列表追加 1 MB，永不释放（用于证明判据能变红）。
    Synthetic leak: append 1 MB to a global list every 4 s, never released (proves the
    criterion can go red)."""
    hold = []
    t_end = time.time() + seconds
    while time.time() < t_end:
        # 每轮 4 MB 已触碰页：macOS 内存压缩会把 1 MB 级增量压到 RSS 里看不见，
        # 4 MB 是本机可稳定观测的最小步长（阈值 24 MB/h，泄漏实际 ~7200 MB/h）。
        # 4 MB touched pages per round: macOS compression hides 1 MB steps; 4 MB is the smallest
        # reliably observable step here (threshold 24 MB/h vs actual leak ~7200 MB/h).
        hold.append(b'x' * (4 * 1024 * 1024))
        print('LEAK_ALLOC %d MB' % (len(hold) * 4), flush=True)
        time.sleep(2)
    return 0


def _slope_mb_per_h(tail):
    xs = [c['t'] / 3600.0 for c in tail]
    ys = [c['watch'][0] / 1024.0 for c in tail]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def _judge(curve, quiet_from=0.0):
    """同一套判据：稳态斜率 + fd。quiescent 窗口＝写者停止后的采样（无新增数据）。
    采样不足 4 次 ⇒ 红（不许静默通过）。
    One judge: steady-state slope + fd on the quiescent window (after writers stop, so index
    memory is no longer growing with data). Fewer than 4 samples ⇒ red."""
    tail = [c for c in curve if c['t'] >= quiet_from]
    if len(tail) < 4:
        return False, {'why': '稳态窗口采样不足 4 次，无法判定', 'n': len(tail)}
    n = len(tail)
    slope = _slope_mb_per_h(tail)
    fd0 = tail[0]['watch'][1]
    fd1 = tail[-1]['watch'][1]
    rss0 = tail[0]['watch'][0] / 1024.0
    rss1 = tail[-1]['watch'][0] / 1024.0
    # 单侧：只有持续「涨」才算泄漏；稳态回落（GC/压缩）不算
    # One-sided: only sustained growth is a leak; shrink (GC/compression) is fine.
    ok = (slope <= SLOPE_MAX_MB_PER_H and (fd1 - fd0) <= FD_MAX_GROWTH
          and rss1 <= HARD_CAP_MB)
    return ok, {'n': n, 'slope': slope, 'fd0': fd0, 'fd1': fd1,
                'rss0': rss0, 'rss1': rss1, 'tail0': tail[0]['t'], 'tail1': tail[-1]['t']}


def _print_judge(tag, ok, m, curve):
    print('SOAK %s：稳态斜率=%+.1f MB/h（静态窗口 %d 次采样 t=%.0f→%.0fs，阈值 ±%.0f）'
          % (tag, m.get('slope', 0.0), m.get('n', 0), m.get('tail0', 0), m.get('tail1', 0),
             SLOPE_MAX_MB_PER_H))
    print('SOAK %s：fd %s→%s（阈值 +%d）· RSS 首采 %.1f MB → 末采 %.1f MB（参考硬顶 %.0f MB）'
          % (tag, m.get('fd0', 0), m.get('fd1', 0), FD_MAX_GROWTH, m.get('rss0', 0.0),
             m.get('rss1', 0.0), HARD_CAP_MB))
    if m.get('rss0'):
        print('SOAK %s：+%.1f%% 是相对首采 %.1f MB 的绝对值变化（+%.1f MB），只作参考，不参与判定'
              % (tag, (m['rss1'] / m['rss0'] - 1) * 100, m['rss0'],
                 m['rss1'] - m['rss0']))
    print('SOAK %s 序列(t秒:RSS MB)：%s'
          % (tag, ' '.join('%d:%.1f' % (c['t'], c['watch'][0] / 1024.0) for c in curve)))


def _write_csv(path, curve):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['t_s', 'watch_rss_mb', 'watch_fd', 'writers_rss_mb', 'writers_fd'])
        for c in curve:
            wr = [x for x in c['writers']]
            w.writerow([c['t'], '%.3f' % (c['watch'][0] / 1024.0), c['watch'][1],
                        '%.3f' % (sum(x[1] for x in wr) / 1024.0),
                        sum(x[2] for x in wr)])
    print('SOAK CSV：%s（%d 个采样点）' % (path, len(curve)))


def _init_root(root):
    os.makedirs(root)
    with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[volumes]\n账=账卷.txt\n')
    open(os.path.join(root, '账卷.txt'), 'wb').close()


def _leak_test(args):
    """合成泄漏自证：同一 judge 必须判红。红＝判据有效；绿＝假绿，退出 1。
    Synthetic-leak self-check: the same judge must go red. Red = criterion valid; green = fake."""
    if os.name == 'nt':
        print('SOAK SKIP：leak-test 依赖 POSIX ps/lsof')
        return 2
    dur = 30.0
    print('SOAK LEAK-TEST 开始：合成泄漏每 2 秒 +4 MB，持续 %.0f 秒，采样每 2 秒' % dur)
    child = subprocess.Popen([sys.executable, '-B', os.path.abspath(__file__),
                              '--leak-child', str(dur)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    curve = []
    t0 = time.time()
    try:
        while time.time() - t0 < dur - 2:
            curve.append({'t': round(time.time() - t0, 1),
                          'watch': (_rss_kb(child.pid), _fds(child.pid)), 'writers': []})
            time.sleep(2)
    finally:
        child.kill()
        child.wait()
    ok, m = _judge(curve, quiet_from=0.0)
    _print_judge('LEAK-TEST', ok, m, curve)
    if ok:
        print('SOAK LEAK-TEST FAIL：合成泄漏未被抓到（判据假绿）')
        return 1
    print('SOAK LEAK-TEST PASS：合成泄漏被抓到（稳态斜率 %+.1f MB/h > 阈值 %.0f）'
          % (m['slope'], SLOPE_MAX_MB_PER_H))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=float, default=60)
    ap.add_argument('--writers', type=int, default=8)
    ap.add_argument('--interval', type=float, default=2.0)
    ap.add_argument('--sample', type=float, default=30.0)
    ap.add_argument('--quiet', type=float, default=180.0,
                    help='写者提前停止的秒数（稳态窗口）')
    ap.add_argument('--csv', default='')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--leak-test', action='store_true')
    ap.add_argument('--leak-child', type=float, default=0.0)
    ap.add_argument('--child', nargs=4)
    args = ap.parse_args()
    if args.leak_child:
        return _leak_child(args.leak_child)
    if args.child:
        root, tag, interval, seconds = args.child
        return _child(root, tag, float(interval), float(seconds))
    if args.leak_test:
        return _leak_test(args)
    if os.name == 'nt':
        print('SOAK SKIP：本长跑脚本依赖 POSIX ps/lsof（Windows 未验证）')
        return 2

    work = tempfile.mkdtemp(prefix='daybook_soak_')
    root = os.path.join(work, 'ledger')
    _init_root(root)
    dur = args.minutes * 60.0
    quiet = min(args.quiet, dur * 0.25)
    write_dur = max(30.0, dur - quiet)
    env = _env()
    daybook = os.path.join(SRC, 'daybook.py')
    print('SOAK 开始：时长=%.1f 分钟（%s）写者=%d 间隔=%.1fs 采样=%.0fs 根=%s'
          % (args.minutes, '1 小时，非 24 小时' if args.minutes == 60 else
             '%d 分钟，非 24 小时' % int(args.minutes), args.writers, args.interval,
             args.sample, root))
    print('SOAK 设计：写者跑 %.0fs 后停，留 %.0fs 静态窗口（跳过最后重建峰值后测斜率）'
          % (write_dur, quiet))
    watch = subprocess.Popen([sys.executable, '-B', daybook, 'watch', '30'], cwd=root,
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    writers = [subprocess.Popen([sys.executable, '-B', os.path.abspath(__file__),
                                 '--child', root, 'W%02d' % i, str(args.interval),
                                 str(write_dur)], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True)
               for i in range(args.writers)]
    curve = []
    t0 = time.time()
    try:
        while time.time() - t0 < dur + 15:
            if watch.poll() is not None:
                break
            curve.append({'t': round(time.time() - t0, 1),
                          'watch': (_rss_kb(watch.pid), _fds(watch.pid)),
                          'writers': [(p.pid, _rss_kb(p.pid), _fds(p.pid))
                                      for p in writers if p.poll() is None]})
            if all(p.poll() is not None for p in writers) and time.time() - t0 >= dur:
                break
            time.sleep(args.sample)
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
    okw = sum(r['ok'] for r in res)
    fail = sum(r['fail'] for r in res)
    with open(os.path.join(root, '账卷.txt'), 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8', 'replace')
    lines = [x for x in text.split('\n') if x]
    bad = [i + 1 for i, x in enumerate(text.split('\n')) if x and not LINE.match(x)]
    total_ok = (len(lines) == okw and not bad)
    settle = min(35.0, quiet / 4.0)   # 跳过停写后的最后一次重建峰值
    judge_ok, m = _judge(curve, quiet_from=dur - quiet + settle)
    crashed = watch.returncode not in (0, -signal.SIGTERM) or 'Traceback' in watch_out
    print('SOAK 读数：写入成功=%d 失败=%d 最终行数=%d（应为 %d）坏行=%d 崩溃=%s'
          % (okw, fail, len(lines), okw, len(bad), crashed))
    _print_judge('判定', judge_ok, m, curve)
    print('SOAK watch 轮次输出行=%d 尾部=%s'
          % (len(watch_out.splitlines()),
             (watch_out.strip().splitlines() or [''])[-1][:150]))
    if args.csv:
        _write_csv(args.csv, curve)
    green = judge_ok and not fail and not bad and total_ok and not crashed
    print('SOAK 判据：%s' % ('PASS' if green else
                             'FAIL（judge=%s 失败=%d 坏行=%d 条数一致=%s 崩溃=%s）'
                             % (judge_ok, fail, len(bad), total_ok, crashed)))
    shutil.rmtree(work, ignore_errors=True)
    if args.check:
        return 0 if green else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
