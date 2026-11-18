#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""变异记分板：属性 × 变异（步骤 5）
Mutation scoreboard: properties × mutations (step 5)
================================================
每条变异在临时树里按 AST 改一处，只跑它声明的期望属性：
  红            ⇒ 杀死
  绿、但别的属性红 ⇒ 死变异（未被对应属性杀死）
  绿、全量也全绿   ⇒ 存活
锚点消失 / 无法编译 ⇒ 死变异。健康指标：存活 0 且 死变异 0。
跑法 / Run:
  python3 tools/score.py                 # 全矩阵
  python3 tools/score.py --only M2       # 只跑一条
  python3 tools/score.py --self-check    # 故意错映射（M2→P1），必须报「未被对应属性杀死」
退出码：0=全杀死且无死变异 1=有存活/死变异 2=参数错。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mutate

_PROP_RE = re.compile(r'^PROP (P\d) (PASS|FAIL)$', re.M)


def _run_props(tree, only=''):
    """在临时 src 树里跑属性；返回 (rc, {P#: 'PASS'|'FAIL'}, stdout)。"""
    cmd = [sys.executable, '-B',
           os.path.join(tree, 'tests', 'prop', 'run_all.py'),
           '--seed', '7', '--mode', 'const']
    if only:
        cmd += ['--only', only]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    r = subprocess.run(cmd, cwd=tree, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
    props = dict(_PROP_RE.findall(r.stdout))
    return r.returncode, props, (r.stdout + r.stderr)


def _score_one(mut_id, expect_override=None):
    """返回 (verdict, detail)：verdict ∈ killed / survivor / dead。"""
    mut = mutate.BY_ID[mut_id]
    expect = expect_override or mut['expect']
    tmp = tempfile.mkdtemp(prefix='daybook_mut_')
    try:
        tree = os.path.join(tmp, 'src')
        mutate.copy_src(SRC, tree)
        try:
            mutate.apply_one(tree, mut_id)
        except mutate.MutationError as exc:
            return 'dead', '锚点消失/无法应用：%s' % exc
        t0 = time.time()
        rc, props, out = _run_props(tree, only=expect)
        if props.get(expect) == 'FAIL':
            return 'killed', '期望属性 %s 红（rc=%d）' % (expect, rc)
        if rc != 0 and not props:
            return 'dead', '属性入口崩溃（rc=%d）' % rc
        # 期望属性绿：再跑全量，看是否被别的属性杀死（错映射/声明不符）
        rc2, props2, out2 = _run_props(tree)
        others = sorted(k for k, v in props2.items() if v == 'FAIL')
        if others:
            return 'dead', '未被对应属性杀死（%s 绿；实际被 %s 杀死）' % (
                expect, ','.join(others))
        if rc2 == 0:
            return 'survivor', '全量属性仍绿（变异存活）'
        return 'dead', '全量属性入口异常（rc=%d）' % rc2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def self_check():
    """错映射红证：M2 声明期望 P1（实际只该由 P2 杀）⇒ 必须被报为死变异。"""
    print('== 自检：故意把 M2 的期望属性写成 P1 ==')
    verdict, detail = _score_one('M2', expect_override='P1')
    ok = verdict == 'dead' and '未被对应属性杀死' in detail
    print('  M2 → P1：%s · %s' % (verdict, detail))
    print('  自检%s：错映射没有被静默通过' % ('通过' if ok else '失败'))
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--self-check', action='store_true')
    args = ap.parse_args(argv)
    if args.self_check:
        return self_check()

    ids = [args.only] if args.only else [m['id'] for m in mutate.MUTATIONS]
    bad_ids = [i for i in ids if i not in mutate.BY_ID]
    if bad_ids:
        print('未知变异：%s' % ','.join(bad_ids), file=sys.stderr)
        return 2

    print('== 变异记分板（属性层 seed=7 mode=const）==')
    killed = survivors = dead = 0
    rows = []
    for mid in ids:
        mut = mutate.BY_ID[mid]
        t0 = time.time()
        verdict, detail = _score_one(mid)
        dt = time.time() - t0
        if verdict == 'killed':
            killed += 1
        elif verdict == 'survivor':
            survivors += 1
            rows.append('%s（期望 %s）存活：%s' % (mid, mut['expect'], detail))
        else:
            dead += 1
            rows.append('%s（期望 %s）死变异：%s' % (mid, mut['expect'], detail))
        print('  %-3s → %-2s  %-6s  %.2fs  %s'
              % (mid, mut['expect'], verdict, dt, detail))
    total = len(ids)
    print('\n变异 %d / 杀死 %d / 存活 %d / 死变异 %d'
          % (total, killed, survivors, dead))
    for row in rows:
        print('  ' + row)
    ok = (survivors == 0 and dead == 0 and killed == total)
    print('判据健康度：属性全绿 + 存活变异 %d + 死变异 %d ⇒ %s'
          % (survivors, dead, '收口' if ok else '未收口'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
