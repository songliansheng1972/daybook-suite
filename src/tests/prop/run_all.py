#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""属性层入口：P1–P10（步骤 5）
Property-layer entry: P1–P10 (step 5)
================================================
跑法 / Run:
  python3 tests/prop/run_all.py                    # 全部属性（默认 seed=7 mode=const）
  python3 tests/prop/run_all.py --only P1 --seed 7 # 只跑一件（score.py 用）
  python3 tests/prop/run_all.py --mode random --seed 42
退出码：0=全绿 1=有红。机器可读行：`PROP P# PASS|FAIL`。
"""
import argparse
import ast
import io
import os
import sys
import traceback

import common

MODULES = [
    ('P1', 'p1_root_identity'),
    ('P2', 'p2_containment'),
    ('P3', 'p3_single_write'),
    ('P4', 'p4_capability'),
    ('P5', 'p5_atomic'),
    ('P6', 'p6_exit_codes'),
    ('P7', 'p7_zero_write'),
    ('P8', 'p8_credential'),
    ('P9', 'p9_entry_root'),
    ('P10', 'p10_build_root'),
]


def check_names_unique():
    """每个属性件里的断言名必须唯一（score 按名字精确匹配失败原因）。
    Assertion names must be unique per property file (score matches failure names exactly)."""
    here = os.path.dirname(os.path.abspath(__file__))
    bad = []
    for tag, modname in MODULES:
        tree = ast.parse(io.open(os.path.join(here, modname + '.py'),
                                 encoding='utf-8').read())
        names = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                    and n.func.id == 'check' and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    names.append(a.value)
        dup = sorted({x for x in names if names.count(x) > 1})
        if dup:
            bad.append((tag, dup))
    return bad


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--mode', default='const', choices=('const', 'random', 'shuffle'))
    ap.add_argument('--only', default='', help='只跑指定属性，如 P1 或 P1,P2')
    ap.add_argument('--audit-names', action='store_true',
                    help='只校验断言名唯一性')
    args = ap.parse_args(argv)
    dup = check_names_unique()
    if dup:
        print('断言名重复（要求唯一）：%s' % dup)
        return 1
    if args.audit_names:
        print('断言名唯一 ✓')
        return 0
    want = {s.strip().upper() for s in args.only.split(',') if s.strip()}
    print('=== 属性层 · seed=%d mode=%s 只跑=%s ==='
          % (args.seed, args.mode, ','.join(sorted(want)) or '全部'))
    bad = []
    for tag, modname in MODULES:
        if want and tag not in want:
            continue
        p0, f0 = common.STATE['pass'], common.STATE['fail']
        try:
            mod = __import__(modname)
            mod.run(seed=args.seed, mode=args.mode)
        except Exception:
            common.check('%s 运行异常' % tag, False,
                         traceback.format_exc().strip().splitlines()[-1])
        failed = common.STATE['fail'] > f0
        print('PROP %s %s' % (tag, 'FAIL' if failed else 'PASS'))
        if failed:
            bad.append(tag)
    print('=== 属性层结果：%s ==='
          % ('全绿' if not bad else '红 %s' % ','.join(bad)))
    print('健康度：属性%s；存活变异/死变异见 tools/score.py'
          % ('全绿' if not bad else '红'))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
