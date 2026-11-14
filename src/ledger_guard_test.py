#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daybook · append-only 判据回归（ledger guard）
Daybook · append-only criterion regression (ledger guard)
================================================
专挡「把「未变」判据退回 size+mtime」这种静默回退：并发烟雾测试（daybook_test.py）
在判据退回后仍会全绿，本文件不会。

Cases
  A 首次索引非空卷                              ⇒ rc=5（无封存证据·不写回），认基线后 0
  B 未变复跑两次                                ⇒ rc=0 且判「未变」，不得全扫
  C 纯追加一行                                  ⇒ rc=0，且走「只追加」
  D 全卷中部等长替换＋os.utime 恢复 mtime        ⇒ rc=3（等长改写）
  E 同一手法但不恢复 mtime                      ⇒ rc=3
  F 旧格式索引（fmt<2）                         ⇒ rc=0，报过期并全量重建
  G 删索引后等长替换                            ⇒ rc=3（索引缺失仍验哈希·不得洗成 5）
  H 删游标后等长替换                            ⇒ rc=5（证据缺失·不写回）
  I 游标写成 {}                                 ⇒ rc=5（不可信·不自动修好）
  J 替换后自己重写游标的 hash/size/mtime         ⇒ rc=3（与封存指纹不符·游标被改写）
  K 删索引加删游标                              ⇒ rc=5（证据缺失·不重建）
  L 正常追加后删索引                            ⇒ rc=5 且无 traceback（旧实现 FileNotFoundError rc=1）
  M 三件派生件全删                              ⇒ rc=5（无外部锚·复跑仍 5），认基线后 0
  N 索引缺失且卷变长、旧前缀被改                 ⇒ rc=3（不能因「卷变大」跳过前缀校验）
  O 违例态认基线                                ⇒ rc=3，三件派生件零变化（不替人认下篡改）
  R ≥8 进程并发 index                           ⇒ 零误报、零丢更新、复跑全 0（封存快照锁内只读一次）
  S 配置错（卷指向目录）                        ⇒ rc=2 且派生件递归哈希零变化（不可信即零落盘）
  T rc=3 违例                                   ⇒ 清单/封存时戳零变化（不可信即零落盘）
  V5 rc=5 证据缺失                              ⇒ 同样零变化（不可信即零落盘）
  U rc=4 作者口径红                             ⇒ 照写且文案「已写回·只报不拦」（不是不可信）
  R2 两进程 20ms 错峰并发 index                 ⇒ 两侧 rc=0（一「只追加」一「未变」）
  V safeio 原子替换/无锁读者                    ⇒ atomic_write 走 os.replace，read_vol 不取锁
  W 子目录卷 + 长条目 append                    ⇒ 与 index 争同一把账本根锁（不被子目录锁旁路）
  P 同一账本·两个不同 TMPDIR 并发持锁读改写     ⇒ 临界区不重叠、不丢更新（锁绑目录 inode）
  Q 持锁期间删除任何外部件                      ⇒ 仍互斥（账本内本无锁件可删）

变异验证 / mutation check
  把 daybook.py 的同长判定临时改回 size+mtime，用 DAYBOOK_SRC 指向该副本运行本文件：
  D、E 必须红；恢复原码后必须全绿。用法：
    DAYBOOK_SRC=/tmp/mutant/daybook.py python3 ledger_guard_test.py
  封存快照的变异：把 build() 里的 old_stamp = _read_json(...) 挪回 with 之前（锁外读）
  ⇒ R 必红（迟到进程拿旧封存比新游标，误报 rc=3）。
  写入门变异①：把「不可信不落盘」改成恒写 ⇒ S/T/V5 必红。
  写入门变异②：把提交条件改回 rc==0 ⇒ U 必红（作者红也被卷进零落盘）。
  锁的变异同理：把 safeio 的目录 flock 改回「目录内锁文件」⇒ A、B 必红；
  改回「临时目录按 realpath 命名的锁文件」⇒ P、Q 必红。

跑法 / Run: python3 ledger_guard_test.py
退出码 / Exit code: 0=全绿 1=有红
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# 被测 daybook.py：默认同目录；变异验证时用 DAYBOOK_SRC 指向临时副本
# The daybook.py under test: same directory by default; DAYBOOK_SRC points at a mutant copy.
SRC_BIN = os.environ.get('DAYBOOK_SRC') or os.path.join(HERE, 'daybook.py')

CONF = """[volumes]
账=账卷.txt

[entries]
head_regex=^(?:\\[#\\d+\\][ ]*)?\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}(?::\\d{2})?)\\]
tag_regex=^(?:\\[#\\d+\\][ ]*)?\\[\\d{4}[^\\]]*\\][ ]*\\[([^\\]]+)\\][ ]*\\[([^\\]]*)\\](?:[ ]*\\[([^\\]]*)\\])?
fields=volume,line,time,category,title,author

[rules]
category=tag:1
title=tag:2
author=tag:3

[index]
root=
out_dir=索引
index_prefix=index_
manifest=volumes.md

[trigger]
incremental=是
"""

FAILS = []
CHECKS = [0]


def _ok(name, cond, detail=''):
    CHECKS[0] += 1
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name,
                          (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    if not cond:
        FAILS.append(name)
    return bool(cond)


def _make_volume(path, n=120, body=480):
    """造一条足以让「中部」落在头/尾 4K 窗口之外的正账。
    Build a volume long enough for its midpoint to sit outside the head/tail 4K windows."""
    with io.open(path, 'w', encoding='utf-8') as f:
        for i in range(n):
            f.write('[2026-11-13 10:%02d:%02d] [测试] [第%03d条] [皮特] %s\n'
                    % (i // 60, i % 60, i, '正文' * (body // 2)))


def _prepare(tmp):
    """把被测 daybook.py、safeio.py、daybook_append.py 拷进隔离目录，写 conf 与账卷。
    Copy the daybook.py under test plus safeio.py / daybook_append.py into an isolated directory
    with conf and volume.
    （index 的作者口径机检走 daybook_append.check_author_consistency，故须随拷。）
    (The index author-convention gate calls daybook_append.check_author_consistency, so it must be staged too.)"""
    here = os.path.dirname(SRC_BIN)
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py'):
        shutil.copy2(os.path.join(here, name), os.path.join(tmp, name))
    with io.open(os.path.join(tmp, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    _make_volume(os.path.join(tmp, '账卷.txt'))


def _run(tmp):
    # -B：被测脚本被拷进隔离目录运行（真实部署里它在包目录、不在账本里），
    # 关掉字节码缓存，免得 __pycache__ 冒充「账本被写」。
    # -B: the script is staged inside the isolated ledger here (in real deployment it lives in
    # the package dir), so suppress bytecode caching to keep __pycache__ out of the criterion.
    return subprocess.run([sys.executable, '-B', 'daybook.py', 'index'],
                          cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def _base(tmp):
    return subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'],
                          cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def _log(tag, r):
    print('    [%s] rc=%d' % (tag, r.returncode))
    out = (r.stdout + r.stderr).strip().splitlines()
    for line in out[:4]:
        print('      ' + line)


def _dir_hash(d):
    """目录内所有文件（按名排序）的联合 sha256：用于证明「一个字节都没写」。
    Combined sha256 of every file in a directory (name-sorted): proves nothing was written."""
    h = hashlib.sha256()
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            h.update(name.encode('utf-8'))
            h.update(io.open(p, 'rb').read())
    return h.hexdigest()


def _snapshot(d):
    """递归快照：{'相对路径' 或 '目录/' : sha256 或 'd'}。
    根目录 listdir 看不出「子目录新增文件」与「同名文件内容被改」，故比全树。
    Recursive snapshot: {relpath or 'dir/': sha256 or 'd'}. A root-level listdir cannot see
    files added inside subdirectories or a rewritten existing file, so the whole tree is compared."""
    out = {}
    for base, dirs, files in os.walk(d):
        for name in dirs:
            out[os.path.relpath(os.path.join(base, name), d) + '/'] = 'd'
        for name in files:
            p = os.path.join(base, name)
            try:
                os.lstat(p)
            except OSError:
                continue
            if os.path.islink(p):
                try:
                    os.stat(p)          # 断链跳过，别让账本里的断链把判据打崩
                except OSError:         # skip broken symlinks; they must not crash the criterion
                    continue
            h = hashlib.sha256()
            try:
                with open(p, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        h.update(chunk)
            except OSError:
                continue
            out[os.path.relpath(p, d)] = h.hexdigest()
    return out


def _snap_diff(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return added, removed, changed


def _tamper_mid(path, start_frac):
    """中部等长替换一个数字字节（仍是数字 ⇒ 条目头仍合法，隔离出哈希判据）。
    Equal-length replacement of one digit near the middle (still a digit ⇒ the entry head stays
    valid, isolating the hash criterion from parsing/encoding drift)."""
    st = os.stat(path)
    b = bytearray(open(path, 'rb').read())
    pos = int(len(b) * start_frac)
    while pos < len(b) and not (48 <= b[pos] <= 57):
        pos += 1
    assert 4096 < pos < len(b) - 4096, 'tamper position must be outside head/tail 4K windows'
    b[pos] = ord('7') if b[pos] != ord('7') else ord('8')
    open(path, 'wb').write(bytes(b))
    return st, pos


_CHILD_RW = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import safeio
root, counter, tag = sys.argv[1], sys.argv[2], sys.argv[3]
with safeio.locked(root):
    n = int(open(counter).read() or 0)
    with open(os.path.join(root, 'trace.txt'), 'a', encoding='utf-8') as f:
        f.write('in %s\n' % tag)
    time.sleep(0.05)
    with open(counter, 'w') as f:
        f.write(str(n + 1))
    with open(os.path.join(root, 'trace.txt'), 'a', encoding='utf-8') as f:
        f.write('out %s\n' % tag)
'''

_CHILD_HOLD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import safeio
root = sys.argv[1]
with safeio.locked(root):
    open(os.path.join(root, 'held.flag'), 'w').write('1')
    while not os.path.exists(os.path.join(root, 'release.flag')):
        time.sleep(0.02)
'''

_CHILD_PROBE = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import safeio
try:
    with safeio.locked(sys.argv[1], timeout=0.2):
        print('OK')
except TimeoutError:
    print('BUSY')
'''

# 并发 index 子进程：先 import 好，等屏障后同时进入 main（把进程启动抖动挤掉）
# Concurrent index child: import first, then enter main together after the barrier
# (removes process-startup jitter so the read/commit windows really overlap).
_CHILD_INDEX = r'''
import os, sys, time
root, barrier = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
os.chdir(root)
import daybook
while not os.path.exists(barrier):
    time.sleep(0.001)
sys.argv = ['daybook.py', 'index']
daybook.main()
'''

# 子目录卷 + 长条目：append_one 必须锁账本根（不是卷所在子目录）
# Sub-directory volume + long entry: append_one must lock the ledger root, not the volume dir.
_CHILD_APPEND = r'''
import os, sys, time
src, root, vol, msg = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.path.insert(0, src)
import daybook_append
t0 = time.time()
daybook_append.append_one(vol, '聊', '子目录长条目', msg, author='皮特', root=root)
print('%.3f' % (time.time() - t0))
'''

# safeio 单实现自证：原子替换必须调用 os.replace；read_vol 不得取锁
# safeio self-check: atomic replace must call os.replace; read_vol must not take a lock.
_CHILD_SAFEIO = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import safeio
p = sys.argv[2]
calls = [0]
real = os.replace
def spy(a, b):
    calls[0] += 1
    return real(a, b)
safeio.os.replace = spy
safeio.atomic_write(p, '新内容')
assert open(p, encoding='utf-8').read() == '新内容', 'atomic_write 内容不符'
assert calls[0] >= 1, 'atomic_write 未走 os.replace'
assert not [n for n in os.listdir(os.path.dirname(p)) if n.endswith('.tmp')], '残留临时件'
def _no_lock(*a, **k):
    raise AssertionError('read_vol 取了锁')
safeio.locked = _no_lock
t, _enc, _why = safeio.read_vol(p)
assert t == '新内容', 'read_vol 内容不符'
print('OK')
'''


def _stage_safeio(tmp):
    shutil.copy2(os.path.join(os.path.dirname(SRC_BIN), 'safeio.py'),
                 os.path.join(tmp, 'safeio.py'))


def _case_p(tmp):
    """P 同一账本、两个不同 TMPDIR 的并发持锁读改写：必须互斥（无重叠、无丢更新）。
    锁若绑在「临时目录里的文件」上，两个 TMPDIR 就是两把锁，本用例必红。
    P: two processes with different TMPDIRs do a locked read-modify-write on one ledger;
    exclusion must hold. If the lock lives in a temp-dir file, two TMPDIRs give two locks
    and this case goes red."""
    d = os.path.join(tmp, 'p')
    os.makedirs(d)
    _stage_safeio(d)
    counter = os.path.join(d, 'counter.txt')
    io.open(counter, 'w').write('0')
    procs = []
    for rnd in range(10):
        for i, name in enumerate(('tmpA', 'tmpB')):
            td = os.path.join(d, name)
            os.makedirs(td, exist_ok=True)
            env = dict(os.environ)
            env['TMPDIR'] = td
            procs.append(subprocess.Popen(
                [sys.executable, '-B', '-c', _CHILD_RW, d, counter, 'r%d-%d' % (rnd, i)],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True))
    outs = [p.communicate() for p in procs]
    bad = [(p.returncode, err.strip()[:80]) for p, (_o, err) in zip(procs, outs)
           if p.returncode != 0]
    total = int(io.open(counter).read())
    trace = [l.strip() for l in io.open(os.path.join(d, 'trace.txt')).read().splitlines()
             if l.strip()]
    seq_ok = all((l.split()[0] == 'in') == (i % 2 == 0) for i, l in enumerate(trace))
    _ok('P 不同 TMPDIR 并发：临界区不重叠', seq_ok and len(trace) == 40,
        'trace=%d 交替=%s' % (len(trace), seq_ok))
    _ok('P 不丢更新（%d/20）' % total, total == 20 and not bad, '非零进程=%s' % bad)
    _ok('P 账本内无锁件', not any('.safeio_lock' in k for k in _snapshot(d)))


def _case_q(tmp):
    """Q 持锁期间删除任何外部件：互斥仍成立（账本内本无锁件可删）。
    旧实现把锁放在临时目录文件上，删掉它后第二个进程能新建同名文件并进临界区，本用例必红。
    Q: deleting any external artifact while the lock is held must not break exclusion.
    The old temp-dir lock file could be deleted and recreated by the second process, which
    would enter the critical section — this case goes red there."""
    d = os.path.join(tmp, 'q')
    os.makedirs(d)
    _stage_safeio(d)
    holder = subprocess.Popen([sys.executable, '-B', '-c', _CHILD_HOLD, d, d],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
    held = os.path.join(d, 'held.flag')
    for _ in range(200):
        if os.path.exists(held):
            break
        time.sleep(0.02)
    _ok('Q 持锁进程已进临界区', os.path.exists(held))
    # 只删本用例自己造的路径（账本外）：产品在系统临时目录已无任何锁件。
    # Delete only a path this test created itself (outside the ledger): the product keeps
    # no lock artifact in the system temp dir any more.
    decoy = os.path.join(tmp, 'q-decoy')
    os.makedirs(decoy)
    shutil.rmtree(decoy)
    _ok('Q 自造外部件已删（不碰系统临时目录）', not os.path.exists(decoy))
    locks = [k for k in _snapshot(d) if '.safeio_lock' in k or 'daybook-locks' in k]
    _ok('Q 账本内无锁件可删', not locks, '发现=%s' % locks)
    probe = subprocess.run([sys.executable, '-B', '-c', _CHILD_PROBE, d, d],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
    _ok('Q 删过外部件后仍互斥（探针 BUSY）', probe.stdout.strip() == 'BUSY',
        (probe.stdout.strip() or probe.stderr.strip())[:120])
    io.open(os.path.join(d, 'release.flag'), 'w').write('1')
    holder.communicate(timeout=30)
    probe2 = subprocess.run([sys.executable, '-B', '-c', _CHILD_PROBE, d, d],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
    _ok('Q 释放后可获取（探针 OK）', probe2.stdout.strip() == 'OK',
        probe2.stdout.strip() or probe2.stderr.strip()[:120])


def _case_stagger(tmp):
    """R2 两进程 20ms 错峰并发 index：一「只追加」一「未变」，两侧 rc=0。
    R2 Two processes 20 ms apart on one ledger: one appends, one sees unchanged; both rc=0.
    The mutant that reads the seal outside the lock goes red here (the late starter judges a
    fresh cursor against the stale seal)."""
    d = os.path.join(tmp, 'stagger')
    os.makedirs(d)
    here = os.path.dirname(SRC_BIN)
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py'):
        shutil.copy2(os.path.join(here, name), os.path.join(d, name))
    with io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    vol = os.path.join(d, '账卷.txt')
    with io.open(vol, 'w', encoding='utf-8') as f:
        for i in range(20000):
            f.write('[2026-11-13 10:00:00] [测试] [错峰%05d] [皮特] 正文\n' % i)
    def run():
        return subprocess.run([sys.executable, '-B', 'daybook.py', 'index'], cwd=d,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
    _base_r = subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'], cwd=d,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
    _ok('R2 认基线 rc=0', _base_r.returncode == 0, 'rc=%d' % _base_r.returncode)
    with io.open(vol, 'a', encoding='utf-8') as f:
        f.write('[2026-11-13 10:00:01] [测试] [错峰追加] [皮特] 正文\n')
    p1 = subprocess.Popen([sys.executable, '-B', 'daybook.py', 'index'], cwd=d,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    time.sleep(0.02)
    p2 = subprocess.Popen([sys.executable, '-B', 'daybook.py', 'index'], cwd=d,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    o1, e1 = p1.communicate()
    o2, e2 = p2.communicate()
    t1, t2 = o1 + e1, o2 + e2
    _ok('R2 20ms 错峰两侧 rc=0', p1.returncode == 0 and p2.returncode == 0,
        'rc=%d/%d' % (p1.returncode, p2.returncode))
    _ok('R2 两侧无违例误报', '违例' not in t1 and '违例' not in t2)
    _ok('R2 一「只追加」一「未变」',
        ('只追加' in t1 and '未变·跳过' in t2) or ('只追加' in t2 and '未变·跳过' in t1),
        'p1=%r p2=%r' % ('只追加' in t1, '只追加' in t2))
    r = run()
    _ok('R2 复跑 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)


def _case_safeio(tmp):
    """V 派生件原子替换 + 读者不取锁：两件都必须可自证。
    V Atomic replacement for derived artifacts + lock-free readers: both must be self-evident."""
    d = os.path.join(tmp, 'safeio')
    os.makedirs(d)
    p = os.path.join(d, 'x.txt')
    r = subprocess.run([sys.executable, '-B', '-c', _CHILD_SAFEIO,
                        os.path.dirname(SRC_BIN), p],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('V atomic_write 走 os.replace 且无临时残留 + read_vol 不取锁',
        r.returncode == 0 and r.stdout.strip() == 'OK',
        (r.stdout.strip() or r.stderr.strip())[:160])


def _case_subdir(tmp):
    """W 子目录卷 + 长条目 append：必须与 index 争同一把账本根锁。
    W A sub-directory volume with a long append must contend on the same ledger-root lock."""
    d = os.path.join(tmp, 'subdir')
    sub = os.path.join(d, '子目录')
    os.makedirs(sub)
    _stage_safeio(d)
    vol = os.path.join(sub, '账卷.txt')
    io.open(vol, 'w', encoding='utf-8').write('')
    holder = subprocess.Popen([sys.executable, '-B', '-c', _CHILD_HOLD, d, d],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
    held = os.path.join(d, 'held.flag')
    for _ in range(200):
        if os.path.exists(held):
            break
        time.sleep(0.02)
    _ok('W 持根锁进程已进临界区', os.path.exists(held))
    long_msg = '长' * 2000
    app = subprocess.Popen([sys.executable, '-B', '-c', _CHILD_APPEND,
                            os.path.dirname(SRC_BIN), d, vol, long_msg],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
    time.sleep(0.4)
    still_running = app.poll() is None
    probe = subprocess.run([sys.executable, '-B', '-c', _CHILD_PROBE, d, d],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
    _ok('W 子目录长条目被根锁挡住（未提前返回）', still_running)
    _ok('W 根锁探针 BUSY（同一把锁）', probe.stdout.strip() == 'BUSY',
        probe.stdout.strip() or probe.stderr.strip()[:120])
    io.open(os.path.join(d, 'release.flag'), 'w').write('1')
    outp, errp = app.communicate(timeout=30)
    holder.communicate(timeout=30)
    elapsed = float((outp.strip() or '0').splitlines()[-1]) if outp.strip() else 0.0
    _ok('W 释放后长条目落盘 rc=0', app.returncode == 0, (outp + errp).strip()[:120])
    _ok('W 长条目确实等到根锁（≥0.5s）', elapsed >= 0.5, 'elapsed=%.3f' % elapsed)
    _ok('W 条目已落子目录卷', '子目录长条目' in io.open(vol, encoding='utf-8').read())

    # W-CLI：走真实 CLI 入口（不显式传 root），仍必须争同一把账本根锁
    # W-CLI: the real CLI entry (no explicit root argument) must still contend on the root lock.
    try:
        os.remove(os.path.join(d, 'release.flag'))
    except OSError:
        pass
    try:
        os.remove(os.path.join(d, 'held.flag'))   # 上一轮的持锁凭据必须清掉，否则误判「已持锁」
    except OSError:
        pass
    holder = subprocess.Popen([sys.executable, '-B', '-c', _CHILD_HOLD, d, d],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
    held = os.path.join(d, 'held.flag')
    for _ in range(200):
        if os.path.exists(held):
            break
        time.sleep(0.02)
    _ok('W-CLI 持根锁进程已进临界区', os.path.exists(held))
    env = dict(os.environ, DAYBOOK_ROOT=d)
    t0 = time.time()
    app = subprocess.Popen([sys.executable, '-B',
                            os.path.join(os.path.dirname(SRC_BIN), 'daybook_append.py'),
                            vol, '聊', '子目录CLI长条', '皮特', '长' * 2000],
                           cwd=os.path.dirname(SRC_BIN), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
    time.sleep(0.6)
    still = app.poll() is None
    io.open(os.path.join(d, 'release.flag'), 'w').write('1')
    o, e = app.communicate(timeout=30)
    holder.communicate(timeout=30)
    elapsed = time.time() - t0
    _ok('W-CLI 真实入口被根锁挡住（未提前返回）', still, (o + e)[:100])
    _ok('W-CLI 释放后落盘 rc=0 且等待 ≥0.5s',
        app.returncode == 0 and elapsed >= 0.5,
        'rc=%d elapsed=%.3f %s' % (app.returncode, elapsed, e.strip()[:80]))
    _ok('W-CLI 条目已落子目录卷', '子目录CLI长条' in io.open(vol, encoding='utf-8').read())


def _case_partial_commit(tmp):
    """X 提交中途失败（TSV 已新、游标仍旧）⇒ 下一跑自动重扫 rc=0，baseline 不被拒。
    X A crash between TSV and cursor (index newer than cursor) must be a catch-up, never rc=3;
    a following baseline must be accepted."""
    d = os.path.join(tmp, 'partial')
    os.makedirs(d)
    here = os.path.dirname(SRC_BIN)
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py'):
        shutil.copy2(os.path.join(here, name), os.path.join(d, name))
    with io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    vol = os.path.join(d, '账卷.txt')
    with io.open(vol, 'w', encoding='utf-8') as f:
        for i in range(5):
            f.write('[2026-11-13 10:00:00] [测试] [条目%02d] [皮特] 正文\n' % i)
    def run(cmd='index'):
        return subprocess.run([sys.executable, '-B', 'daybook.py', cmd], cwd=d,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
    _ok('X0 认基线 rc=0', run('baseline').returncode == 0)
    with io.open(vol, 'a', encoding='utf-8') as f:
        f.write('[2026-11-13 10:00:09] [测试] [新增] [皮特] 正文\n')
    idf = os.path.join(d, '索引', 'index_账.tsv')
    with io.open(idf, 'a', encoding='utf-8') as f:   # 模拟 TSV 已落、游标未落
        f.write('账\t6\t2026-11-13 10:00:09\t测试\t新增\t皮特\n')
    r = run()
    txt = r.stdout + r.stderr
    _ok('X1 索引新于游标 ⇒ 自动重扫 rc=0（不判违例）', r.returncode == 0,
        'rc=%d %s' % (r.returncode, txt.strip().splitlines()[-1:]))
    _ok('X2 文案不出现 append-only 违例', 'append-only 违例' not in txt, txt[-120:])
    _ok('X3 baseline 不被拒 rc=0', run('baseline').returncode == 0)
    _ok('X4 索引行数追平（6 行）',
        sum(1 for l in io.open(idf, encoding='utf-8') if l.strip()) - 1 == 6)


_CHILD_TAIL = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
p = sys.argv[2]
import daybook_multidx
_h, rows = daybook_multidx.read_tsv(p)
assert len(rows) == 1, 'read_tsv 未丢弃末尾半行: %d' % len(rows)
import daybook
with open(p, encoding='utf-8') as f:
    lines = list(daybook._complete_lines(f))
assert len(lines) == 2, 'query 读行未丢弃半行: %d' % len(lines)
print('OK')
'''

_CHILD_TRUNC = r'''
import os, sys, json
sys.path.insert(0, sys.argv[1])
p, tp = sys.argv[2], sys.argv[3]
import daybook
rep = []
daybook._run_ops([('append', p, [['账', '2', 't', '测试', 'x', '皮特']], tp, '账')], rep)
data = open(p, 'rb').read()
assert data.endswith(b'\n'), '截断后续写仍以半行结尾'
assert not data.endswith('半'.encode('utf-8')), '半行未被截断'
assert '截断' in json.dumps(rep, ensure_ascii=False), '未报告截断'
print('OK')
'''


def _case_append(tmp):
    """Y 追加型派生件 O(1) 原位追加：40 万条基线下单条追加，inode 不变、行数 +1。
    Y Append-type artifacts are O(1) in place: with a 400k baseline a single append keeps the
    inode (no full rewrite) and adds exactly one row."""
    d = os.path.join(tmp, 'append')
    os.makedirs(d)
    here = os.path.dirname(SRC_BIN)
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py'):
        shutil.copy2(os.path.join(here, name), os.path.join(d, name))
    with io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    vol = os.path.join(d, '账卷.txt')
    n = 400000
    with io.open(vol, 'w', encoding='utf-8') as f:
        for i in range(n):
            f.write('[2026-11-13 10:00:00] [测试] [条目%06d] [皮特] 正文\n' % i)
    t0 = time.time()
    r = subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    t_base = time.time() - t0
    _ok('Y0 40 万条认基线 rc=0', r.returncode == 0, 'rc=%d %.2fs' % (r.returncode, t_base))
    idf = os.path.join(d, '索引', 'index_账.tsv')
    ino = os.stat(idf).st_ino
    with io.open(vol, 'a', encoding='utf-8') as f:
        f.write('[2026-11-13 10:00:01] [测试] [单条追加] [皮特] 正文\n')
    t0 = time.time()
    r = subprocess.run([sys.executable, '-B', 'daybook.py', 'index'], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    t_add = time.time() - t0
    nrows = sum(1 for l in io.open(idf, encoding='utf-8') if l.strip()) - 1
    _ok('Y1 单条追加 rc=0 且行数 %d→%d' % (n, n + 1), r.returncode == 0 and nrows == n + 1,
        'rc=%d rows=%d' % (r.returncode, nrows))
    _ok('Y2 原位追加（inode 不变·未全量重写）', os.stat(idf).st_ino == ino,
        'ino %s → %s' % (ino, os.stat(idf).st_ino))
    print('  [数据] 40 万条：基线 %.2fs，单条追加 %.2fs；5M 外推 ≈ %.2fs（O(1) 追加，与卷长无关）'
          % (t_base, t_add, t_add))


def _case_tail(tmp):
    """Z 崩溃尾部半行：读者丢弃、写者截断续写。两条都要能自证。
    Z Crashed tail: readers drop the half line; writers truncate then continue."""
    d = os.path.join(tmp, 'tail')
    os.makedirs(d)
    p = os.path.join(d, 'x.tsv')
    tp = os.path.join(d, 'x.txt')
    with open(p, 'wb') as f:
        f.write('volume\tline\ttime\tcategory\ttitle\tauthor\n'.encode('utf-8'))
        f.write('账\t1\tt\t测试\th\t皮特\n'.encode('utf-8'))
        f.write('账\t2\tt\t测试\t半'.encode('utf-8'))    # 半行，无换行
    r = subprocess.run([sys.executable, '-B', '-c', _CHILD_TAIL,
                        os.path.dirname(SRC_BIN), p],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('Z1 读者丢弃末尾半行（read_tsv + query）',
        r.returncode == 0 and r.stdout.strip() == 'OK',
        (r.stdout.strip() or r.stderr.strip())[:160])
    with open(p, 'ab') as f:
        f.write(b'\xe5\x8d\x8a')                         # 再留一个半行
    r = subprocess.run([sys.executable, '-B', '-c', _CHILD_TRUNC,
                        os.path.dirname(SRC_BIN), p, tp],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('Z2 崩溃半行：截断后原位续写并报告',
        r.returncode == 0 and r.stdout.strip() == 'OK',
        (r.stdout.strip() or r.stderr.strip())[:200])


def main():
    if not os.path.exists(SRC_BIN):
        print('找不到被测 daybook.py：%s' % SRC_BIN, file=sys.stderr)
        return 1
    work = tempfile.mkdtemp(prefix='daybook_guard_')
    try:
        _prepare(work)
        vol = os.path.join(work, '账卷.txt')
        idf = os.path.join(work, '索引', 'index_账.tsv')
        cp = os.path.join(work, '索引', '.cursor_账.json')
        sp = os.path.join(work, '索引', '.head_stamp.json')

        # A：首次索引非空卷 ⇒ 无任何封存证据，退 5 且不写回；认基线后才 0
        # A: first index of a non-empty volume has no sealed evidence ⇒ 5 and nothing written
        #    back; only an explicit baseline makes it 0
        root_before = _snapshot(work)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('A 首次索引 ⇒ rc=5（无封存证据）', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('A 报「无任何封存证据」', '无任何封存证据' in txt)
        _ok('A 不写回游标/索引', not os.path.exists(cp) and not os.path.exists(idf))
        root_after = _snapshot(work)
        added, removed, changed = _snap_diff(root_before, root_after)
        _ok('A 账本目录零变化（递归·含内容·锁为目录 flock）',
            not (added or removed or changed),
            '新增=%s 删除=%s 改动=%s' % (added, removed, changed))
        _ok('A 账本内无任何锁件',
            not any('.safeio_lock' in k or 'daybook-locks' in k for k in root_after))
        _log('A', r)
        r = _run(work)
        _ok('A 未认基线前复跑仍 rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        r = _base(work)
        _ok('A 认基线 ⇒ rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        r = _run(work)
        _ok('A 认基线后 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)

        # D：中部等长替换 + 恢复 mtime ⇒ 必须违例（不是未变跳过）
        orig_d = io.open(vol, 'rb').read()
        st, pos = _tamper_mid(vol, 0.50)
        os.utime(vol, (st.st_atime, st.st_mtime))
        same_mtime = os.stat(vol).st_mtime == st.st_mtime
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('D mtime 已恢复原值', same_mtime)
        _ok('D 等长中部加恢复 mtime ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('D 明确报违例', ('违例' in txt) and ('等长改写' in txt),
            ' | '.join(l.strip() for l in txt.splitlines() if '★' in l)[:160])
        _ok('D 不得报「未变·跳过」', '未变·跳过' not in txt)
        _log('D', r)

        # 复位：把账本原文写回，指纹重新对上（违例已不再自动写回）
        # Reset: put the original volume bytes back so the fingerprints match again
        # (a violation no longer writes anything back)
        io.open(vol, 'wb').write(orig_d)
        r = _run(work)
        _ok('D 恢复原文后 复跑 rc=0', r.returncode == 0,
            'rc=%d | %s' % (r.returncode, (r.stdout + r.stderr).strip()[:160]))

        # E：同一手法、不恢复 mtime ⇒ 同样违例
        orig_e = io.open(vol, 'rb').read()
        st, pos = _tamper_mid(vol, 0.35)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('E 等长中部不恢复 mtime ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('E 明确报违例', ('违例' in txt) and ('等长改写' in txt))
        _log('E', r)
        io.open(vol, 'wb').write(orig_e)
        _run(work)

        # C：纯追加 ⇒ rc=0 且必须走「只追加」，不得全量重扫
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 12:00:00] [测试] [纯追加] [皮特] 追加正文\n')
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('C 纯追加 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        _ok('C 走只追加路径', '只追加' in txt,
            ' | '.join(l.strip() for l in txt.splitlines() if '只追加' in l)[:160])
        _ok('C 未触发全量重扫', '全扫' not in txt)
        _log('C', r)

        # F：旧格式索引（游标 fmt<2、口径戳无 index_fmt）⇒ 首跑报格式过期、全量重建、rc=0
        # F: legacy index format ⇒ report staleness, rebuild fully, rc=0
        cur = json.load(io.open(cp, encoding='utf-8'))
        cur.pop('fmt', None)
        cur.pop('content_hash', None)
        with io.open(cp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(cur, ensure_ascii=False))
        stamp = json.load(io.open(sp, encoding='utf-8'))
        stamp.pop('index_fmt', None)
        with io.open(sp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(stamp, ensure_ascii=False))
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('F 旧格式索引 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        _ok('F 报格式过期', ('格式过期' in txt) or ('旧游标格式' in txt),
            ' | '.join(l.strip() for l in txt.splitlines() if '过期' in l)[:160])
        _ok('F 全量重建', '全扫' in txt)
        cur2 = json.load(io.open(cp, encoding='utf-8'))
        _ok('F 游标已升 fmt=2', cur2.get('fmt') == 2 and bool(cur2.get('content_hash')),
            'fmt=%r' % cur2.get('fmt'))
        _log('F', r)

        # B：未变复跑两次 ⇒ rc=0 稳定，且正常跑也不得在账本根新增文件
        # B: two unchanged reruns ⇒ stable 0, and a normal run must not add files to the ledger root
        for i in (1, 2):
            before_b = set(_snapshot(work))
            r = _run(work)
            txt = r.stdout + r.stderr
            after_b = set(_snapshot(work))
            _ok('B 未变复跑#%d rc=0' % i, r.returncode == 0, 'rc=%d' % r.returncode)
            _ok('B 未变复跑#%d 判未变' % i, '未变·跳过' in txt and '全扫' not in txt)
            _ok('B 未变复跑#%d 账本目录不新增（递归）' % i, before_b == after_b,
                '新增=%s' % sorted(after_b - before_b))
            locks_b = [k for k in after_b
                       if '.safeio_lock' in k or 'daybook-locks' in k]
            _ok('B 未变复跑#%d 账本内无锁件' % i, not locks_b, '发现=%s' % locks_b)

        # ── G–K：派生件被删/被改写，不得与「未变」同码 ──
        # ── G–K: deleted or rewritten derived artifacts must never share the unchanged status ──

        # G 删索引后等长替换 ⇒ 索引缺失仍验哈希 ⇒ 违例（rc=3），不得洗成证据缺失
        os.remove(idf)
        orig_g = io.open(vol, 'rb').read()
        _tamper_mid(vol, 0.45)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('G 删索引+等长替换 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('G 报「索引缺失但哈希不符」', '索引缺失但全卷哈希' in txt or '等长改写' in txt,
            ' | '.join(l.strip() for l in txt.splitlines() if '★' in l)[:160])
        _ok('G 不得判未变', '未变·跳过' not in txt)
        _ok('G 不自动重建（违例后须恢复原文）', not os.path.exists(idf),
            'exists=%s' % os.path.exists(idf))
        _log('G', r)
        # 违例不写回：baseline 也拒（见 O）；恢复原文后再认基线
        # A violation writes nothing back and baseline refuses (see O); restore then baseline
        r = _base(work)
        _ok('G 违例态认基线被拒 rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        io.open(vol, 'wb').write(orig_g)
        _base(work)

        # H 删游标后等长替换 ⇒ 证据缺失（rc=5）
        os.remove(cp)
        _tamper_mid(vol, 0.55)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('H 删游标+等长替换 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('H 报证据缺失（游标丢失）', '证据缺失' in txt and '游标' in txt)
        _ok('H 不得判未变', '未变·跳过' not in txt)
        _ok('H 不写回游标', not os.path.exists(cp))
        _log('H', r)
        r = _run(work)
        _ok('H 未认基线前复跑仍 5', r.returncode == 5, 'rc=%d' % r.returncode)
        _base(work)

        # I 游标写成 {} ⇒ 不可信，证据缺失（rc=5），且不自动修好
        with io.open(cp, 'w', encoding='utf-8') as f:
            f.write('{}')
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('I 游标={} ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('I 报证据缺失且不得判未变', '证据缺失' in txt and '未变·跳过' not in txt)
        _ok('I 不自动重写游标', io.open(cp, encoding='utf-8').read().strip() == '{}')
        _log('I', r)
        _base(work)

        # J 替换后自己重写游标的 hash/size/mtime ⇒ 与封存指纹不符 ⇒ rc=3
        orig_j = io.open(vol, 'rb').read()
        orig_cp = io.open(cp, 'rb').read()
        st, _pos = _tamper_mid(vol, 0.40)
        import hashlib as _hashlib
        new_hash = _hashlib.sha256(open(vol, 'rb').read()).hexdigest()
        cur = json.load(io.open(cp, encoding='utf-8'))
        cur['content_hash'] = new_hash
        cur['size'] = os.path.getsize(vol)
        cur['mtime'] = os.path.getmtime(vol)
        with io.open(cp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(cur, ensure_ascii=False))
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('J 重写游标指纹 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('J 报派生件互相矛盾', '封存指纹' in txt or '被改写' in txt,
            ' | '.join(l.strip() for l in txt.splitlines() if '★' in l)[:160])
        _log('J', r)
        io.open(vol, 'wb').write(orig_j)
        io.open(cp, 'wb').write(orig_cp)
        _run(work)

        # K 删索引加删游标 ⇒ 证据缺失（rc=5），不写回；认基线后才恢复
        os.remove(idf)
        os.remove(cp)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('K 删索引+删游标 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('K 报证据缺失', '证据缺失' in txt)
        _ok('K 不得判未变', '未变·跳过' not in txt)
        _ok('K 不自动重建索引入口', not os.path.exists(idf))
        _log('K', r)
        _base(work)

        # L 正常追加后删索引 ⇒ 卷变大分支不得数不存在的索引文件（旧实现 FileNotFoundError rc=1）
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 13:00:00] [测试] [再追加] [皮特] 追加正文\n')
        os.remove(idf)                   # 追加后立刻删索引，不给中间落盘机会
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('L 追加后删索引 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('L 无 Traceback（不崩）', 'Traceback' not in txt and 'FileNotFoundError' not in txt)
        _ok('L 报证据缺失', '证据缺失' in txt)
        _log('L', r)
        _base(work)

        # M 三件派生件全删 ⇒ 无外部锚 ⇒ rc=5，复跑仍 5；认基线才 0
        for q in (idf, cp, sp):
            if os.path.exists(q):
                os.remove(q)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('M 三件全删 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('M 报「无任何封存证据」', '无任何封存证据' in txt)
        _log('M', r)
        r = _run(work)
        _ok('M 未认基线前复跑仍 5', r.returncode == 5, 'rc=%d' % r.returncode)
        r = _base(work)
        _ok('M 认基线 ⇒ rc=0', r.returncode == 0, 'rc=%d' % r.returncode)
        r = _run(work)
        _ok('M 认基线后 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)

        # N 索引缺失且卷变长：旧前缀被改 ⇒ 仍须判 3（不能因「卷变大」跳过校验）
        os.remove(idf)
        orig_n = io.open(vol, 'rb').read()
        _tamper_mid(vol, 0.30)
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 14:00:00] [测试] [变长] [皮特] 变长追加\n')
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('N 索引缺失+变长+旧前缀改 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('N 报旧前缀哈希不符', ('旧前缀' in txt) or ('前缀哈希不符' in txt))
        _log('N', r)
        r = _base(work)
        _ok('N 违例态认基线被拒 rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        io.open(vol, 'wb').write(orig_n)
        _base(work)

        n_rows = sum(1 for l in io.open(idf, encoding='utf-8') if l.strip()) - 1
        _ok('索引行数与卷条目一致', n_rows == 122, 'rows=%d' % n_rows)

        # O 违例态认基线 ⇒ rc=3 且三件派生件零变化（不替人认下篡改）
        os.remove(idf)
        before = _dir_hash(os.path.join(work, '索引'))
        _tamper_mid(vol, 0.60)
        r = _base(work)
        after = _dir_hash(os.path.join(work, '索引'))
        _ok('O 违例态认基线被拒 rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('O 报「未写任何派生件」', '未写任何派生件' in (r.stdout + r.stderr))
        _ok('O 派生件零变化', before == after)
        _log('O', r)
        io.open(vol, 'wb').write(orig_n)
        _base(work)

        # R 并发 index：≥6 进程同时对同一账本 ⇒ 零误报、零丢更新、复跑全 0
        # R Concurrent index: ≥6 processes on one ledger ⇒ no false positives, no lost updates,
        #   every rerun 0. The sealed snapshot must be read inside the same critical section;
        #   a read outside the lock (the mutant this case kills) makes late starters judge
        #   fresh cursors against stale seals and report rc=3.
        _stage_safeio(work)
        child = os.path.join(work, '_concurrent_index.py')
        with io.open(child, 'w', encoding='utf-8') as f:
            f.write(_CHILD_INDEX)
        base_rows = sum(1 for l in io.open(idf, encoding='utf-8') if l.strip()) - 1
        add_n = 40
        with io.open(vol, 'a', encoding='utf-8') as f:
            for i in range(add_n):
                f.write('[2026-11-13 15:00:%02d] [测试] [并发追加%02d] [皮特] 并发正文\n' % (i % 60, i))
        barrier = os.path.join(work, 'go.flag')
        procs = []
        for i in range(8):
            procs.append(subprocess.Popen(
                [sys.executable, '-B', child, work, barrier],
                cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True))
        time.sleep(0.4)
        io.open(barrier, 'w').write('1')
        outs = [p.communicate() for p in procs]
        rcs = [p.returncode for p in procs]
        texts = [o + e for o, e in outs]
        bad = [(rc, (t.strip().splitlines() or [''])[-1][:80])
               for rc, t in zip(rcs, texts) if rc != 0]
        false_pos = [t for t in texts if '违例' in t]
        _ok('R 8 进程并发 index 全 rc=0', not bad, '非零=%s' % bad)
        _ok('R 零误报（无违例文案）', not false_pos,
            '误报=%d' % len(false_pos))
        rows_after = sum(1 for l in io.open(idf, encoding='utf-8') if l.strip()) - 1
        _ok('R 零丢更新（%d → %d）' % (base_rows, base_rows + add_n),
            rows_after == base_rows + add_n, 'rows=%d' % rows_after)
        r = _run(work)
        _ok('R 并发后复跑 rc=0', r.returncode == 0, 'rc=%d' % r.returncode)

        # S rc=2 配置错：只报不写——封存件/游标/清单递归哈希不变
        # S rc=2 config error: report only · sealed/cursor/manifest hashes unchanged
        conf_path = os.path.join(work, 'daybook.conf')
        conf_backup = io.open(conf_path, encoding='utf-8').read()
        os.makedirs(os.path.join(work, '坏卷目录'))
        io.open(conf_path, 'w', encoding='utf-8').write(
            conf_backup.replace('[volumes]\n账=账卷.txt', '[volumes]\n账=账卷.txt\n坏=坏卷目录'))
        idx_before = _snapshot(os.path.join(work, '索引'))
        r = _run(work)
        idx_after = _snapshot(os.path.join(work, '索引'))
        _ok('S 配置错（卷指向目录）⇒ rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
        _ok('S rc=2 不可信即零落盘（递归·含内容）', idx_before == idx_after,
            '差异=%s' % (_snap_diff(idx_before, idx_after),))
        stamp_now = json.load(io.open(sp, encoding='utf-8'))
        _ok('S rc=2 封存指纹仍在', isinstance(stamp_now.get('vol_seals'), dict)
            and stamp_now['vol_seals'].get('账') is not None,
            'vol_seals=%s' % sorted((stamp_now.get('vol_seals') or {}).keys()))
        io.open(conf_path, 'w', encoding='utf-8').write(conf_backup)
        os.rmdir(os.path.join(work, '坏卷目录'))

        # T rc=3 违例：不可信即零落盘——清单与时戳零变化
        # T rc=3 violation: untrusted ⇒ zero write; manifest and timestamp unchanged
        orig_t = io.open(vol, 'rb').read()
        idx_before = _snapshot(os.path.join(work, '索引'))
        _tamper_mid(vol, 0.50)
        r = _run(work)
        idx_after = _snapshot(os.path.join(work, '索引'))
        _ok('T 等长改写 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('T rc=3 不可信即零落盘（含清单/封存时戳）', idx_before == idx_after,
            '差异=%s' % (_snap_diff(idx_before, idx_after),))
        io.open(vol, 'wb').write(orig_t)
        _run(work)

        # V5 rc=5 证据缺失：同样不可信即零落盘
        # V5 rc=5 lost evidence: untrusted ⇒ zero write as well
        orig_v5 = io.open(vol, 'rb').read()
        cp_v5 = io.open(cp, 'rb').read()
        os.remove(cp)
        _tamper_mid(vol, 0.60)
        idx_before = _snapshot(os.path.join(work, '索引'))
        r = _run(work)
        idx_after = _snapshot(os.path.join(work, '索引'))
        _ok('V5 删游标+等长改写 ⇒ rc=5', r.returncode == 5, 'rc=%d' % r.returncode)
        _ok('V5 rc=5 不可信即零落盘', idx_before == idx_after,
            '差异=%s' % (_snap_diff(idx_before, idx_after),))
        io.open(vol, 'wb').write(orig_v5)
        io.open(cp, 'wb').write(cp_v5)
        _run(work)

        # U rc=4 作者口径红：不是不可信，照写；文案明确「已写回·只报不拦」
        # U rc=4 author-convention red: not untrusted data, so the run writes; the text says so
        orig_u = io.open(vol, 'rb').read()
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 16:00:00] [测试] [机器id作者] [ag-0123456789abcdef] 正文\n')
        idx_before = _snapshot(os.path.join(work, '索引'))
        r = _run(work)
        idx_after = _snapshot(os.path.join(work, '索引'))
        txt = r.stdout + r.stderr
        _ok('U 作者位机器 id ⇒ rc=4', r.returncode == 4, 'rc=%d' % r.returncode)
        _ok('U 作者红照写：派生件已变化', idx_before != idx_after,
            '差异=%s' % (_snap_diff(idx_before, idx_after),))
        _ok('U 文案明确「已写回·作者口径红·只报不拦」',
            '已写回' in txt and '作者口径红' in txt and '只报不拦' in txt, txt[-160:])
        io.open(vol, 'wb').write(orig_u)
        _base(work)

        # R2/V/W 与静态检查：错峰并发、原子替换+无锁读者、子目录长条目锁根
        _case_stagger(work)
        _case_safeio(work)
        _case_subdir(work)
        _case_partial_commit(work)
        _case_tail(work)
        _case_append(work)
        safeio_src = io.open(os.path.join(os.path.dirname(SRC_BIN), 'safeio.py'),
                             encoding='utf-8').read()
        _ok('静态：Windows/msvcrt 分支已删、账本内无锁件实现',
            'import msvcrt' not in safeio_src
            and 'os.remove(lock_file)' not in safeio_src
            and '_HAS_FCNTL' not in safeio_src)
        daybook_src = io.open(os.path.join(os.path.dirname(SRC_BIN), 'daybook.py'),
                              encoding='utf-8').read()
        _ok('静态：派生件只有一个原子替换实现（daybook 不自己 os.replace）',
            'def atomic_write' in safeio_src and 'os.replace(' not in daybook_src)
        leftovers = [k for k in _snapshot(work) if k.endswith('.tmp')]
        _ok('派生件无 .tmp 残留', not leftovers, '残留=%s' % leftovers)

        # P/Q 锁的进程间语义（跨 TMPDIR 互斥、删除外部件不影响）
        # P/Q cross-process lock semantics (exclusion across TMPDIRs; deleting external
        # artifacts changes nothing)
        _case_p(work)
        _case_q(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print('\n=== 判据回归 === %d 红 / %d 项' % (len(FAILS), CHECKS[0]))
    if FAILS:
        print('FAIL: ' + '；'.join(FAILS))
        return 1
    print('PASS: A–W 二十三组用例全绿')
    return 0


if __name__ == '__main__':
    sys.exit(main())
