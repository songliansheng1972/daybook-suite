#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""产物本机路径机检 · 出厂件里不得出现作者本机的绝对路径
Artifact local-path check · shipped files must not contain the author's absolute home paths
================================================
判据 / Criterion:
  产物（src + 三个包）任何文本文件里出现本机绝对路径前缀即 FAIL。
  Any text file in the artifacts (src + the three packages) containing the local absolute
  path prefix is a FAIL.
  扫到 0 个文本文件也算 FAIL（防测试自己假绿）。
  Scanning zero text files is also a FAIL (so the test cannot fake its own green).
  变异：合成一个含该前缀的文件，必须被抓到。
  Mutation: a synthetic file containing the prefix must be caught.

跑法 / Run: python3 path_leak_check.py
退出码 / Exit: 0 = PASS, 1 = FAIL
"""
import os
import sys
import tempfile

# 机检入口零字节码：本进程与子进程都不写 __pycache__。
os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
# 拼出来而不是写死，免得本文件自己被自己的判据抓 —— 这不是绕过，是机检脚本的自指豁免。
# Assembled rather than hard-coded so this file does not trip its own criterion — a self-reference
# exemption, not a bypass.
NEEDLE = '/Use' + 'rs/'
SKIP_DIRS = {'.git', '__pycache__'}


def _dirs():
    """repo 的 src/ 里跑 ⇒ 扫四树；包内跑 ⇒ 只扫本包目录。
    Run from src/ in the repo ⇒ scan the four trees; run inside a package ⇒ scan that package only."""
    parent = os.path.dirname(HERE)
    if os.path.basename(HERE) == 'src' and os.path.isdir(parent):
        cands = [os.path.join(parent, d) for d in ('src', 'daybook', 'daybook-mcp', 'daybook-orch')]
        found = [d for d in cands if os.path.isdir(d)]
        if found:
            return found
    return [HERE]


def scan(d):
    """返回 (文本文件数, 命中列表)。不可解码的二进制跳过。
    Return (text files scanned, hits). Undecodable binaries are skipped."""
    n, hits = 0, []
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for name in sorted(files):
            p = os.path.join(root, name)
            try:
                with open(p, encoding='utf-8') as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            n += 1
            for ln, line in enumerate(text.splitlines(), 1):
                if NEEDLE in line:
                    hits.append((p, ln, line.strip()[:120]))
    return n, hits


def verdict(n, hits):
    """判绿红：零文件=FAIL，有命中=FAIL。Returns (ok, reason)."""
    if n == 0:
        return False, '零文本文件（假绿）· zero text files (false green)'
    if hits:
        return False, '命中 %d 处 · %d hit(s)' % (len(hits), len(hits))
    return True, '%d 个文本文件零命中' % n


def mutation_check():
    """变异：含本机前缀的合成文件必须被抓到；空目录必须判 FAIL。
    Mutation: the synthetic leak must be caught, and an empty dir must FAIL."""
    with tempfile.TemporaryDirectory(prefix='path_leak_') as tmp:
        with open(os.path.join(tmp, 'leak.txt'), 'w', encoding='utf-8') as f:
            f.write('home: ' + NEEDLE + 'demo\n')
        n1, h1 = scan(tmp)
        leak_caught = (not verdict(n1, h1)[0]) and len(h1) == 1
        with tempfile.TemporaryDirectory(prefix='path_empty_') as empty:
            n2, h2 = scan(empty)
            empty_caught = not verdict(n2, h2)[0]
    return leak_caught and empty_caught, n1, len(h1)


def main():
    fails = []
    total_files = 0
    total_hits = 0
    print('=== 产物本机路径机检（不得出现本机绝对路径前缀）· artifact local-path check ===')
    for d in _dirs():
        n, hits = scan(d)
        ok, reason = verdict(n, hits)
        total_files += n
        total_hits += len(hits)
        print('  [%s] %-28s %s' % ('PASS' if ok else 'FAIL', os.path.relpath(d, os.path.dirname(HERE)), reason))
        for p, ln, line in hits[:20]:
            print('        %s:%d  %s' % (os.path.relpath(p, os.path.dirname(HERE)), ln, line))
        sys.stdout.flush()
        if not ok:
            fails.append(os.path.relpath(d, os.path.dirname(HERE)))
    ok_mut, mut_n, mut_h = mutation_check()
    print('  [%s] 变异：含前缀的文件必被抓、空目录必红（扫描 %d / 命中 %d）'
          % ('PASS' if ok_mut else 'FAIL', mut_n, mut_h))
    if not ok_mut:
        fails.append('mutation')
    print('  共扫 %d 个文本文件，命中 %d 处，FAIL 目录 %d 个' % (total_files, total_hits, len(fails)))
    if fails:
        print('  FAIL: %s' % '、'.join(fails))
        return 1
    print('  PASS: 产物无本机绝对路径 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
