#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 0 · 写路径运行时观测（只观测，不阻断）
Step 0 · runtime observation of write paths (observe only, never block)
================================================
`sys.addaudithook` 记录 open / os.rename / os.remove / os.mkdir 事件，只保留落在账本根内
（绝对路径按根前缀；dir_fd 相对名直接算根内）的**写**事件，打印「调用栈顶层函数 + 目标
相对段」，并与登记表逐条对账：

    登记=N 实扫=M 未登记=K

自检三态（缺一不可，否则本工具自己是死代码）：
  绿  基线夹具跑完 ⇒ 未登记=0
  红  在夹具副本里插一行 stray 写 ⇒ 未登记≥1
  红  把过滤条件改成「全部忽略」⇒ 实扫=0 而登记>0（登记未实扫）⇒ 判据红

跑法 / Run: python3 tools/write_audit.py
退出码 / Exit code: 0=三态符合预期 1=有红
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.abspath(__file__)
FIXTURE = os.path.join(HERE, 'audit_fixture.py')

# 登记表：基线下应出现的「写事件 → 产生它的函数 + 目标相对段」。
# Temp names are randomised, so any `.xxx.tmp` normalises to `.tmp`.
# Registry: the write events the baseline fixture is expected to produce.
EXPECTED = {
    ('run', 'vol.txt'),              # 夹具自建卷（临时直写，唯一的非 safeio 写点，已登记）
    ('_append', 'vol.txt'),          # atomic_append / append_inplace（两次，集合去重）
    ('_replace', '.tmp'),            # 原子替换的临时件
    ('_replace', 'vol.txt'),         # os.replace 换入
}

_WRITE_FLAGS = 0
for _n in ('O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC', 'O_APPEND'):
    _WRITE_FLAGS |= getattr(os, _n, 0)


def _is_write_open(mode, flags):
    if isinstance(mode, str) and any(c in mode for c in 'wax+'):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _top_frame():
    """调用栈里第一个不属于本工具的 Python 帧的 co_name。
    The co_name of the first Python frame that is not this tool."""
    f = sys._getframe(1)
    while f is not None:
        if os.path.abspath(f.f_code.co_filename) != SELF:
            return f.f_code.co_name
        f = f.f_back
    return '?'


def _norm(path, root_real, dir_fd=None):
    """绝对路径 → 根内相对段（根外返回 None）；dir_fd 相对名直接当作根内段。
    Absolute path → in-root relative segment (None outside); a dir_fd-relative name is in-root."""
    if not isinstance(path, str):
        return None
    if os.path.isabs(path):
        rp = os.path.realpath(path)
        if rp == root_real:
            return '<root>'
        if not rp.startswith(root_real + os.sep):
            return None
        rel = os.path.relpath(rp, root_real)
    else:
        rel = path
    return '.tmp' if re.match(r'^\..*\.tmp$', os.path.basename(rel)) else rel


def _audit_child(fixture, root, ignore=False):
    """子进程：装钩子 → 跑夹具 → 打印 JSON 事件表。
    Child: install the hook → run the fixture → print the event table as JSON."""
    root_real = os.path.realpath(root)
    events = []

    def hook(name, args):
        if ignore:
            return
        if name == 'open' and len(args) >= 2:
            path, mode = args[0], args[1]
            flags = args[2] if len(args) > 2 else 0
            if not _is_write_open(mode, flags):
                return
            rel = _norm(path, root_real)
            if rel is not None:
                events.append([_top_frame(), rel])
        elif name == 'os.rename' and len(args) >= 2:
            for p, dfd in ((args[0], args[2] if len(args) > 2 else None),
                           (args[1], args[3] if len(args) > 3 else None)):
                rel = _norm(p, root_real, dfd)
                if rel is not None:
                    rel = '.tmp' if re.match(r'^\..*\.tmp$', os.path.basename(rel)) else rel
                    events.append([_top_frame(), rel])
        elif name in ('os.remove', 'os.mkdir') and args:
            rel = _norm(args[0], root_real, args[1] if len(args) > 1 else None)
            if rel is not None:
                events.append([_top_frame(), rel])

    sys.addaudithook(hook)
    sys.path.insert(0, os.path.dirname(HERE))
    sys.path.insert(0, os.path.dirname(fixture))
    mod = {}
    with io.open(fixture, encoding='utf-8') as f:
        exec(compile(f.read(), fixture, 'exec'), mod)
    mod['run'](root, os.path.join(root, 'daybook.conf'))
    print(json.dumps([tuple(e) for e in events], ensure_ascii=False))


def _child_main(argv):
    fixture, root = argv[0], argv[1]
    _audit_child(fixture, root, ignore='--ignore' in argv)
    return 0


def _make_root(base):
    root = os.path.join(base, '账本根')
    os.makedirs(root)
    with io.open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[index]\nroot=\nout_dir=索引\n')
    with io.open(os.path.join(root, 'vol.txt'), 'wb') as f:
        f.write(b'a\n')
    return root


def _run_child(base, fixture, root, ignore=False):
    args = [sys.executable, '-B', SELF, '--child', fixture, root]
    if ignore:
        args.append('--ignore')
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    try:
        return set(tuple(e) for e in json.loads(r.stdout.strip().splitlines()[-1])), r
    except (ValueError, IndexError):
        return None, r


def _reconcile(got):
    """返回 (登记数, 实扫数, 未登记, 登记未实扫)。Returns the four readings."""
    reg = EXPECTED
    scanned = got or set()
    unreg = sorted(scanned - reg)
    missing = sorted(reg - scanned)
    return len(reg), len(scanned), unreg, missing


def main(argv):
    if argv and argv[0] == '--child':
        return _child_main(argv[1:])
    base = tempfile.mkdtemp(prefix='write_audit_')
    try:
        root = _make_root(base)

        got, r = _run_child(base, FIXTURE, root)
        n_reg, n_scan, unreg, missing = _reconcile(got)
        green_ok = got is not None and not unreg
        print('[绿] 基线：登记=%d 实扫=%d 未登记=%d 登记未实扫=%d'
              % (n_reg, n_scan, len(unreg), len(missing)))
        if got is None:
            print('  stderr: %s' % (r.stderr or '').strip()[:300])

        # 红证：夹具副本里插一行 stray 写 ⇒ 必须报「未登记写点」
        bad_fixture = os.path.join(base, 'audit_fixture_stray.py')
        src = io.open(FIXTURE, encoding='utf-8').read()
        needle = "    safeio.atomic_append(p, b'b\\n', root=root)"
        if needle not in src:
            print('[红] 注入锚点消失 ⇒ 死变异（判据失效）')
            return 1
        injected = src.replace(
            needle,
            "    open(os.path.join(root, 'stray.txt'), 'w').close()\n" + needle, 1)
        io.open(bad_fixture, 'w', encoding='utf-8').write(injected)
        got2, r2 = _run_child(base, bad_fixture, root)
        _n2, _s2, unreg2, _m2 = _reconcile(got2)
        red_ok = got2 is not None and any(rel == 'stray.txt' for _fn, rel in unreg2)
        print('[红] 插入 stray 写：未登记=%d 命中stray=%s'
              % (len(unreg2), any(rel == 'stray.txt' for _fn, rel in unreg2)))

        # 变异红：过滤条件「全部忽略」⇒ 实扫=0 而登记>0 ⇒ 登记未实扫，判据必须红
        got3, r3 = _run_child(base, FIXTURE, root, ignore=True)
        n3, s3, _u3, m3 = _reconcile(got3)
        mut_ok = got3 is not None and s3 == 0 and n3 > 0 and len(m3) == n3
        print('[变异红] 过滤全部忽略：登记=%d 实扫=%d 登记未实扫=%d'
              % (n3, s3, len(m3)))

        ok = green_ok and red_ok and mut_ok
        print('\n=== 写路径观测 === %s（绿=%s 红=%s 变异红=%s）'
              % ('通过' if ok else '失败', green_ok, red_ok, mut_ok))
        return 0 if ok else 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
