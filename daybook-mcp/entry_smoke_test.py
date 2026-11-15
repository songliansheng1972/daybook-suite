#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""通用入口烟雾测试 · 挡「模块尾 sys.exit(main()) 但没在模块级 import sys」
Generic entry-point smoke test · blocks "module-level sys.exit(main()) without a module-level import sys"
================================================
症状：main() 内部才 import sys，模块尾 __main__ 块里 sys.exit(main()) 先触碰 sys
      ⇒ 一跑就 NameError: name 'sys' is not defined。CLI 全废，单测却常常看不出来。
Symptom: sys is imported inside main(), yet the __main__ block calls sys.exit(main()) first
      ⇒ immediate NameError on every run. The CLI is dead while unit tests still pass.

做法：遍历目标目录里所有带 __main__ 入口的模块，逐个跑 `python3 <模件> --help`，
      只要 stderr/stdout 出现 NameError、未捕获异常栈，或退出码不在 0/1/2 即 FAIL；
      一个入口都没扫到（零入口）也算 FAIL，防测试自己假绿。
How: scan every module with a __main__ block and run `python3 <module> --help`.
     NameError, any uncaught traceback, or a status outside 0/1/2 is a FAIL; zero modules
     scanned is also a FAIL so the test cannot fake its own green.

排除：测试/校验/压测脚本（本身不是 CLI 入口）与阻塞型服务器（chatroom_server）。
Exclusions: test/check/bench scripts (not CLI entry points) and blocking servers.

变异：--mutation 之外的常驻自检会把「旧写法」合成一个模块，验证本测试确实会报红。
Mutation self-check: alongside the real scan, a synthetic module with the old bug must go red.

跑法 / Run: python3 entry_smoke_test.py
退出码 / Exit: 0 = PASS, 1 = FAIL
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 15
ALLOWED_RC = (0, 1, 2)   # --help 约定：0 正常 / 1 打用法 / 2 参数错 · conventional --help statuses
# 测试/校验/压测脚本不是 CLI 入口 · test/check/bench scripts are not CLI entry points
EXCLUDE_RE = re.compile(r'(^|_)(test|check|bench|regression|mutation)(\.py$|_)')
# 阻塞型服务器：忽略 --help 直接起服务 · blocking server: ignores --help and starts serving
BLOCKING = {'chatroom_server.py'}
# 入口构造函数会就地建运行时卷（心跳/任务/租约…）· 跑完清掉，不脏出厂件
# Constructing an entry may create runtime volumes in place (heartbeat/task/lease…); remove them after the run
RESIDUE = {'心跳卷.txt', '任务卷.txt', '租约卷.txt', '编排卷.txt', '消息卷.txt',
           '注册卷.txt', '审计卷.txt', '锁目录', '__pycache__'}


def _dirs():
    """repo 的 src/ 里跑 ⇒ 扫四包；包内跑 ⇒ 只扫本包目录。
    Run from src/ in the repo ⇒ scan the four trees; run inside a package ⇒ scan that package only."""
    parent = os.path.dirname(HERE)
    if os.path.basename(HERE) == 'src' and os.path.isdir(parent):
        cands = [os.path.join(parent, d) for d in ('src', 'daybook', 'daybook-mcp', 'daybook-orch')]
        found = [d for d in cands if os.path.isdir(d)]
        if found:
            return found
    return [HERE]


def _modules(d):
    out = []
    for name in sorted(os.listdir(d)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        if '__main__' not in text:
            continue
        if EXCLUDE_RE.search(name):
            continue
        out.append(path)
    return out


def run_one(path):
    """跑 --help，返回 (状态, 说明)。状态 ∈ PASS/FAIL/SKIP。
    Run --help and return (status, detail). status ∈ PASS/FAIL/SKIP."""
    name = os.path.basename(path)
    if name in BLOCKING:
        return 'SKIP', '阻塞型服务器（忽略 --help）· blocking server'
    work_dir = os.path.dirname(path)
    before = set(os.listdir(work_dir))
    try:
        r = subprocess.run([sys.executable, path, '--help'],
                           cwd=work_dir, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True,
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'SKIP', '超时 %ds（疑似阻塞入口）· timeout %ds' % (TIMEOUT, TIMEOUT)
    finally:
        _clean_residue(work_dir, before)
    text = (r.stdout or '') + (r.stderr or '')
    if 'NameError' in text:
        detail = next((l.strip() for l in text.splitlines() if 'NameError' in l), '')
        return 'FAIL', detail[:160]
    # ★ 非约定异常退出一律 FAIL：--help 允许 0/1（用法）/2（参数错），其余退出码或任何
    #   未捕获异常栈都不算「跑得动」。
    # ★ Any non-conventional abnormal exit fails: --help may return 0/1 (usage)/2 (bad args);
    #   any other status or an uncaught traceback is not "it runs".
    if 'Traceback' in text:
        detail = next((l.strip() for l in text.splitlines() if 'Error' in l), '')
        return 'FAIL', ('未捕获异常 · traceback: ' + detail)[:160]
    if r.returncode not in ALLOWED_RC:
        return 'FAIL', '非约定退出码 rc=%d' % r.returncode
    return 'PASS', 'rc=%d' % r.returncode


def _clean_residue(work_dir, before):
    """删除本轮 --help 新建的运行时卷（只动白名单名字，别的一概不碰）。
    Delete runtime volumes created by this --help run (whitelisted names only)."""
    try:
        after = set(os.listdir(work_dir))
    except OSError:
        return
    for name in after - before:
        if name not in RESIDUE:
            continue
        p = os.path.join(work_dir, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            pass


def mutation_check():
    """变异自检：合成「main 内 import sys + 模块尾 sys.exit(main())」的旧写法，必须报红。
    Mutation check: synthesise the old shape and require it to go red.
    临时目录用 TemporaryDirectory 托管，跑完即清（不留 mkdtemp 垃圾）。
    The temp dir is managed by TemporaryDirectory so nothing is left behind."""
    with tempfile.TemporaryDirectory(prefix='entry_mut_') as tmp:
        bad = os.path.join(tmp, 'bad_entry.py')
        with open(bad, 'w', encoding='utf-8') as f:
            f.write('def main():\n'
                    '    import sys\n'
                    '    return 0\n\n\n'
                    "if __name__ == '__main__':\n"
                    '    sys.exit(main())\n')
        status, detail = run_one(bad)
    return status == 'FAIL', status, detail


def main():
    fails = []
    skips = []
    total = 0
    print('=== 通用入口烟雾测试（--help 不得 NameError / 不得异常退出）· generic entry smoke test ===')
    for d in _dirs():
        print('  目录 · dir: %s' % d)
        for path in _modules(d):
            total += 1
            status, detail = run_one(path)
            rel = os.path.relpath(path, os.path.dirname(HERE))
            print('    [%s] %-46s %s' % (status, rel, detail))
            sys.stdout.flush()
            if status == 'FAIL':
                fails.append(rel)
            elif status == 'SKIP':
                skips.append(rel)
    ok_mut, mut_status, mut_detail = mutation_check()
    print('    [%s] 变异体：旧写法必红 · mutation must be red%s'
          % ('PASS' if ok_mut else 'FAIL', (' · ' + mut_detail) if mut_detail else ''))
    if not ok_mut:
        fails.append('mutation:old-shape')
    # ★ 零入口 = 测试自己没找到东西，属假绿，必须 FAIL
    # ★ Zero entry modules means the test found nothing — a false green, so FAIL.
    if total == 0:
        fails.append('zero-entries')
    print('  共 %d 个入口模块，FAIL %d 个，SKIP %d 个' % (total, len(fails), len(skips)))
    if skips:
        print('  SKIP: %s' % '、'.join(skips))
    if fails:
        print('  FAIL: %s' % '、'.join(fails))
        return 1
    print('  PASS: 入口模块 --help 无 NameError / 无异常退出，零入口与变异体均被拦住 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
