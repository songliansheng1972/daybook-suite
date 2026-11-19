#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""4.0.7 三个观察点 · 判红读数（机判）
=====================================
先定码表，再写判据。三个观察点各给一条能判红的读数：
  A 账本坏：坏 conf 下 daybook.py index / mcp_server.py / orchestrator.py alarm 三口同 rc=2，
           首行同码表文案；跑完零落盘（文件树快照不变）。
  B 司南挂：司南入口不可用（独立坏 conf）时 who/alarm/board 全 rc=2；与此同时账本 append
           仍 rc=0 且新增 1 行 —— 调度层挂了，存储不受牵连，且不出现「假 alive」。
  C 璇玑连不上：mcp_server 坏 conf 下 rc=2、stdout 0 字节、无 daybook://；健康对照 tools=4
           且有 daybook:// —— 不是「进程在、工具全报错」。
  D 密钥本机生成：两个隔离 BASE 各跑一次 install，各得 3 把密钥；两两指纹零交集，
           每把 600 + 64 字符 —— 固定 key 复制进来会立刻同指纹判红。

码表（rc + 首行文案）：
  0  成功
  2  ★ 运行失败（rc=2）：配置/参数/根目录错
  5  ★ 运行失败（rc=5）：派生件证据缺失（指数基线）
  6  ★ 运行失败（rc=6）：体检执行失败（内部错误）

用法：python3 observe_407.py [--suite DIR]
退出码：0=观察点全绿；1=有红项
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

# 本入口及其子进程零字节码：观察点要从产品目录跑入口，绝不把 __pycache__ 留进盒内。
# Zero bytecode in this entry and its children: the probes run product entries in-place and
# must never leave __pycache__ inside the boxes.
os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
RC2 = '★ 运行失败（rc=2）：'


def find_suite(explicit=None):
    cands = []
    if explicit:
        cands.append(os.path.abspath(explicit))
    cands += [os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]
    for c in cands:
        if entry_paths(c):
            return c
    return ''


def _first(*paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return ''


def _first_file(*paths):
    for p in paths:
        if os.path.isfile(p):
            return p
    return ''


def entry_paths(suite):
    """兼容开发树（扁平的 src）与发行树（三包同级）。"""
    daybook = _first(os.path.join(suite, 'daybook.py'),
                     os.path.join(suite, 'daybook', 'daybook.py'))
    mcp = _first(os.path.join(suite, 'mcp_server.py'),
                 os.path.join(suite, 'daybook-mcp', 'mcp_server.py'))
    orch = _first(os.path.join(suite, 'orchestrator.py'),
                  os.path.join(suite, 'daybook-orch', 'orchestrator.py'))
    launcher = _first_file(os.path.join(suite, 'daybook-orch'),
                           os.path.join(suite, 'daybook-orch', 'daybook-orch'))
    dist_conf = _first(os.path.join(suite, 'daybook.dist.conf'),
                       os.path.join(suite, 'daybook', 'daybook.conf'))
    sample = _first(os.path.join(suite, 'sample'),
                    os.path.join(suite, 'daybook', 'sample'))
    setup = _first_file(os.path.join(suite, 'setup', 'daybook-setup'),
                        os.path.join(suite, 'daybook-mcp', 'setup', 'daybook-setup'))
    if not (daybook and mcp and orch and launcher and
            os.path.isfile(launcher)):
        return {}
    return {'daybook': daybook, 'mcp': mcp, 'orch': orch,
            'launcher': launcher, 'conf': dist_conf, 'sample': sample,
            'setup': setup}


def snapshot(root):
    snap = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            try:
                with open(p, 'rb') as fh:
                    snap[rel] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                snap[rel] = 'unreadable'
    return snap


def run(cmd, cwd, env=None, stdin='', timeout=30):
    e = dict(os.environ)
    e.update(env or {})
    try:
        p = subprocess.run(cmd, cwd=cwd, env=e, input=stdin, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, '', 'TIMEOUT'


def first_line(s):
    for line in (s or '').splitlines():
        if line.strip():
            return line.strip()
    return ''


def make_bad(d):
    with open(os.path.join(d, 'daybook.conf'), 'wb') as f:
        f.write(b'\xff\xfe[volumes]\n')


def make_control(P, d):
    conf = P.get('conf')
    if conf:
        shutil.copy2(conf, os.path.join(d, 'daybook.conf'))
    sample = P.get('sample')
    if sample and os.path.isdir(sample):
        shutil.copytree(sample, os.path.join(d, 'sample'), dirs_exist_ok=True)


def mcp_probe(P, root, timeout=20):
    req = '\n'.join([
        json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}),
        json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'resources/list'}),
        json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}),
    ]) + '\n'
    rc, out, err = run([sys.executable, P['mcp']],
                       cwd=os.path.dirname(P['mcp']),
                       env={'DAYBOOK_ROOT': root, 'PYTHONDONTWRITEBYTECODE': '1'},
                       stdin=req, timeout=timeout)
    tools, uris = [], []
    for line in out.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        res = obj.get('result') or {}
        if 'tools' in res:
            tools = [t.get('name') for t in res['tools']]
        if 'resources' in res:
            uris = [r.get('uri') for r in res['resources']]
    return rc, out, err, tools, uris


def check(name, ok, detail):
    print('  %-4s %-28s %s' % ('GREEN' if ok else 'RED', name, detail))
    return ok


def key_snapshot(base):
    """读一个 BASE 的密钥指纹：{agent_id: (sha256, mode, 长度)}。只留指纹，不打印明文。
    Read key fingerprints for one BASE: {agent_id: (sha256, mode, length)}. Never print the secret."""
    d = os.path.join(base, 'ledger', '.daybook_keys')
    out = {}
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith('.key'):
            continue
        p = os.path.join(d, name)
        try:
            raw = open(p, encoding='utf-8').read().strip()
            mode = os.stat(p).st_mode & 0o777
        except OSError:
            continue
        out[name[:-4]] = (hashlib.sha256(raw.encode()).hexdigest(), mode, len(raw))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', default=None)
    a = ap.parse_args()
    suite = find_suite(a.suite)
    P = entry_paths(suite) if suite else {}
    if not P:
        print('RED   找不到源码/运行副本（需 daybook.py + mcp_server.py + orchestrator.py + daybook-orch）')
        return 2
    print('== 4.0.7 三观察点判红读数 ==')
    print('suite=%s' % suite)
    print('码表：0=成功｜2=%s｜5=证据缺失｜6=体检执行失败' % RC2)
    tmp = tempfile.mkdtemp(prefix='daybook_obs407_')
    ok_all = True
    try:
        # ── A 账本坏 ──
        bad = os.path.join(tmp, 'bad'); os.makedirs(bad); make_bad(bad)
        before = snapshot(bad)
        a1 = run([sys.executable, P['daybook'], '--home', bad, 'index'],
                 cwd=os.path.dirname(P['daybook']))
        a2 = run([sys.executable, P['mcp']],
                 cwd=os.path.dirname(P['mcp']),
                 env={'DAYBOOK_ROOT': bad, 'PYTHONDONTWRITEBYTECODE': '1'}, stdin='')
        a3 = run([sys.executable, P['orch'], '--home', bad, 'alarm'],
                 cwd=os.path.dirname(P['orch']))
        after = snapshot(bad)
        rcs = [a1[0], a2[0], a3[0]]
        firsts = [first_line(x[2]) for x in (a1, a2, a3)]
        delta = sum(1 for k, v in after.items() if before.get(k) != v) + \
                sum(1 for k in before if k not in after)
        print('\n[A] 账本坏（坏 conf：非 UTF-8）')
        print('  rc：index=%d · mcp=%d · alarm=%d' % tuple(rcs))
        print('  首行：%s' % (firsts[0][:60] or '∅'))
        print('  落盘增量：%d 个文件' % delta)
        ok_all &= check('A.1 三口同 rc=2', rcs == [2, 2, 2], 'rc=%s' % rcs)
        ok_all &= check('A.2 首行同码表文案', all(f.startswith(RC2) for f in firsts),
                        'all_prefix=%s' % all(f.startswith(RC2) for f in firsts))
        ok_all &= check('A.3 零落盘', delta == 0, 'delta=%d' % delta)
        print('  判据：A.1/A.2/A.3 任一不满足即红。')

        # ── B 司南挂（入口缺失），账本仍可写 ──
        ctrl = os.path.join(tmp, 'ctrl'); os.makedirs(ctrl); make_control(P, ctrl)
        bad_orch = os.path.join(tmp, 'bad_orch'); os.makedirs(bad_orch)
        bad_launcher = os.path.join(bad_orch, 'daybook-orch')
        shutil.copy2(P['launcher'], bad_launcher)
        os.chmod(bad_launcher, 0o755)
        b = []
        for cmd in ('who', 'submit', 'pull', 'alarm'):
            b.append(run([bad_launcher, '--home', ctrl, cmd], cwd=bad_orch))
        b_first = [first_line(x[2]) for x in b]
        b_ctrl = run([P['launcher'], '--home', ctrl, 'who'],
                     cwd=os.path.dirname(P['launcher']))
        # 账本写：走唯一落盘入口 append_one（不依赖司南）
        ledger_before = snapshot(ctrl)
        code = ('import sys,daybook_append as a;'
                'sys.exit(a.append_one(%r,"测","观察点B","ledger-alive",'
                'author="观察点",author_id="ag-probe",root=%r))'
                % (os.path.join(ctrl, 'sample', '协作卷.txt'), ctrl))
        w = run([sys.executable, '-c', code], cwd=os.path.dirname(P['daybook']))
        ledger_after = snapshot(ctrl)
        w_delta = sum(1 for k, v in ledger_after.items() if ledger_before.get(k) != v) + \
                  sum(1 for k in ledger_before if k not in ledger_after)
        print('\n[B] 司南挂（入口文件缺失；账本健康）')
        print('  rc：who=%d · submit=%d · pull=%d · alarm=%d · 账本 append=%d · 健康 who=%d'
              % (b[0][0], b[1][0], b[2][0], b[3][0], w[0], b_ctrl[0]))
        print('  首行：%s' % (b_first[0][:60] or '∅'))
        print('  首行同文案：%s' % all(f.startswith(RC2) for f in b_first))
        print('  账本落盘增量：%d 个文件' % w_delta)
        ok_all &= check('B.1 司南四口同 rc=2', [x[0] for x in b] == [2, 2, 2, 2],
                        'rc=%s' % [x[0] for x in b])
        ok_all &= check('B.2 首行同码表文案', all(f.startswith(RC2) for f in b_first),
                        'all=%s' % all(f.startswith(RC2) for f in b_first))
        ok_all &= check('B.3 账本写不受牵连', w[0] == 0 and w_delta == 1,
                        'append_rc=%d delta=%d' % (w[0], w_delta))
        ok_all &= check('B.4 健康对照 who rc=0（不假死）', b_ctrl[0] == 0,
                        'ctrl_rc=%d' % b_ctrl[0])
        ok_all &= check('B.5 alarm 不假活', b[3][0] == 2, 'alarm_rc=%d' % b[3][0])
        print('  判据：司南非 2 / 首行不齐 / 账本写失败或 delta≠1 / 健康对照非 0 / alarm 回 0 ⇒ 红。')

        # ── C 璇玑连不上 ──
        c_rc, c_out, c_err, _t, _u = mcp_probe(P, bad)
        ctrl_rc, ctrl_out, ctrl_err, ctrl_tools, ctrl_uris = mcp_probe(P, ctrl)
        print('\n[C] 璇玑连不上（坏 conf）与健康对照')
        print('  坏：rc=%d · stdout=%d 字节 · 含 daybook://=%s'
              % (c_rc, len(c_out.encode()), 'daybook://' in c_out))
        print('  好：rc=%d · tools=%d · 含 daybook://=%s'
              % (ctrl_rc, len(ctrl_tools), 'daybook://' in ctrl_out))
        ok_all &= check('C.1 坏 conf 立即退 2', c_rc == 2, 'rc=%d' % c_rc)
        ok_all &= check('C.2 坏 conf stdout 为空', len(c_out.encode()) == 0,
                        'bytes=%d' % len(c_out.encode()))
        ok_all &= check('C.3 坏 conf 无 daybook://', 'daybook://' not in c_out,
                        'present=%s' % ('daybook://' in c_out))
        ok_all &= check('C.4 健康对照 tools=4 且有资源', ctrl_rc == 0 and len(ctrl_tools) == 4
                        and 'daybook://' in ctrl_out,
                        'rc=%d tools=%d uri=%s' % (ctrl_rc, len(ctrl_tools),
                                                   'daybook://' in ctrl_out))
        print('  判据：坏 conf 非 2 / stdout 非空 / 出现 daybook:// / 健康对照非 4 工具 ⇒ 红。')

        # ── D 密钥本机生成：同一台机器两次独立安装（隔离 BASE）密钥必须不同 ──
        print('\n[D] 密钥本机生成（两次独立安装必须不同）')
        setup = P.get('setup')
        if not setup:
            ok_all &= check('D.0 安装器在场', False, 'setup/daybook-setup 缺失')
        else:
            src_root = suite if os.path.isdir(os.path.join(suite, 'daybook-mcp')) \
                else os.path.dirname(suite)
            bases = [os.path.join(tmp, 'kbase1'), os.path.join(tmp, 'kbase2')]
            cfgs = []
            for i in (1, 2):
                cfgs.append({
                    'DAYBOOK_TRAE_CFG': os.path.join(tmp, 'ktrae%d.json' % i),
                    'DAYBOOK_WB_CFG': os.path.join(tmp, 'kwb%d.json' % i),
                    'DAYBOOK_DSH_CFG': os.path.join(tmp, 'kdsh%d.yml' % i),
                    'DAYBOOK_PLIST': os.path.join(tmp, 'kp%d.plist' % i),
                })
            inst_rcs, snaps = [], []
            try:
                for i in (0, 1):
                    r = run([setup, '--base', bases[i], '--source', src_root, 'install'],
                            cwd=os.path.dirname(setup), env=cfgs[i], timeout=180)
                    inst_rcs.append(r[0])
                    snaps.append(key_snapshot(bases[i]))
                fps = [set(v[0] for v in s.values()) for s in snaps]
                all_keys = [v for s in snaps for v in s.values()]
                # 形状按「600 + 长度 64」判；生成器保证 hex，不在此重复解码
                shapes_ok = len(all_keys) == 6 and all(m == 0o600 and n == 64
                                                       for _f, m, n in all_keys)
                print('  两次 install rc：%s；密钥数：%d / %d'
                      % (inst_rcs, len(snaps[0]), len(snaps[1])))
                print('  指纹前缀：A=%s B=%s'
                      % ([v[0][:8] for v in snaps[0].values()],
                         [v[0][:8] for v in snaps[1].values()]))
                ok_all &= check('D.1 两次独立安装均成功', inst_rcs == [0, 0],
                                'rc=%s' % inst_rcs)
                ok_all &= check('D.2 每侧 3 把密钥（身份 3）',
                                len(snaps[0]) == 3 and len(snaps[1]) == 3,
                                '%d / %d' % (len(snaps[0]), len(snaps[1])))
                ok_all &= check('D.3 两 BASE 密钥指纹零交集', not (fps[0] & fps[1]),
                                'shared=%d' % len(fps[0] & fps[1]))
                ok_all &= check('D.4 密钥形状 600 + 64 字符', shapes_ok,
                                '%d/6' % sum(1 for _f, m, n in all_keys
                                             if m == 0o600 and n == 64))
            finally:
                for i in (0, 1):
                    run([setup, '--base', bases[i], 'uninstall'],
                        cwd=os.path.dirname(setup), env=cfgs[i], timeout=120)
            print('  判据：任一 install 非 0 / 每侧非 3 把 / 指纹有交集 / 形状不合 ⇒ 红。')

        print('\n== 总结：%s ==' % ('三观察点 + 密钥自证全绿' if ok_all else '存在红项'))
        return 0 if ok_all else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
