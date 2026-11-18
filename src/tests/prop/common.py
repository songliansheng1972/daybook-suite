#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""属性层公共件：路径、临时树、快照、子进程与判据计数（步骤 5）
Shared helpers for the property layer: paths, temp trees, snapshots, subprocess and counters.
"""
import contextlib
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

STATE = {'pass': 0, 'fail': 0, 'fails': []}
_LAST = {'pass': 0, 'fail': 0}

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


def check(name, cond, detail=''):
    """记一条判据并立刻打印（失败不中断，便于一次看全）。"""
    STATE['pass' if cond else 'fail'] += 1
    if not cond:
        STATE['fails'].append(name)
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name,
                          (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    return bool(cond)


def summary():
    dp = STATE['pass'] - _LAST['pass']
    df = STATE['fail'] - _LAST['fail']
    _LAST.update(STATE)
    print('  -- 本件 %d 项：PASS %d / FAIL %d' % (dp + df, dp, df))
    if df:
        print('  FAIL: ' + '；'.join(STATE['fails'][-(df):]))
    return 0 if not df else 1


@contextlib.contextmanager
def tmpdir(prefix='daybook_prop_'):
    d = tempfile.mkdtemp(prefix=prefix)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def stage(dst, names=('daybook.py', 'daybook_append.py', 'daybook_record.py',
                      'safeio.py', 'ledger_root.py', 'errors.py')):
    """把被测件拷进隔离目录（属性层永不写源树）。"""
    for n in names:
        shutil.copy2(os.path.join(SRC, n), os.path.join(dst, n))


def make_volume(path, n=120, body=480, author='皮特'):
    with io.open(path, 'w', encoding='utf-8') as f:
        for i in range(n):
            f.write('[2026-11-13 10:%02d:%02d] [测试] [第%03d条] [%s] %s\n'
                    % (i // 60, i % 60, i, author, '正文' * (body // 2)))


def make_ledger(tmp, n=120):
    """隔离账本：conf + 账卷 + 被测件。返回账本根（conf 目录）。"""
    stage(tmp)
    with io.open(os.path.join(tmp, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    make_volume(os.path.join(tmp, '账卷.txt'), n=n)
    return tmp


def run_entry(cwd, args, timeout=90):
    return subprocess.run([sys.executable, '-B', 'daybook.py'] + list(args),
                          cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=timeout)


def tamper_mid(path, ratio=0.5):
    """等长改写中部一个字节（不恢复 mtime）：append-only 判据必须判 3。"""
    raw = bytearray(io.open(path, 'rb').read())
    pos = int(len(raw) * ratio)
    while pos < len(raw) and raw[pos:pos + 1] in (b'\n', b'\r'):
        pos += 1
    if pos >= len(raw):
        pos = len(raw) - 1
    raw[pos] = ord('X') if raw[pos] != ord('X') else ord('Y')
    with io.open(path, 'wb') as f:
        f.write(bytes(raw))


def md5_of(path):
    h = hashlib.md5()
    with io.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root):
    """递归快照：路径 → (类型, 大小, inode, mtime_ns, md5)。用于「零落盘」判据。"""
    out = {}
    for dirpath, dirs, files in os.walk(root):
        for d in sorted(dirs):
            p = os.path.join(dirpath, d)
            st = os.lstat(p)
            out[os.path.relpath(p, root) + '/'] = ('dir', st.st_size,
                                                   st.st_ino, st.st_mtime_ns, '')
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = ('file', st.st_size, st.st_ino,
                                             st.st_mtime_ns, md5_of(p))
    return out


def diff_snap(a, b):
    return sorted(set(a) ^ set(b)) + sorted(k for k in set(a) & set(b) if a[k] != b[k])


def is_dir_fd(fd):
    try:
        return stat.S_ISDIR(os.fstat(fd).st_mode)
    except OSError:
        return False
