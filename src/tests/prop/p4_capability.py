#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""P4 · 能力形态（属性层 · 反射/静态）
P4 · capability shape (property layer · reflection/static)
================================================
写能力只能长在 `LockedRoot` 上：`Root` 没有写方法，`write/update` 不收 root/path 参数，
模块级没有以路径字符串为入参的写函数，`LockedRoot` 也不能绕过 `Root.lock()` 自行构造。
"""
import ast
import inspect
import os

import common
from common import check
import safeio
from safeio import LockedRoot, Root, WriteMode


def _module_write_functions(tree):
    """模块级函数里出现写打开/替换/删除 ⇒ 返回函数名（写能力不该在模块级）。"""
    bad = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        hit = False
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, 'id', '')
            if name in ('replace', 'unlink', 'remove', 'rename'):
                hit = True
            elif name == 'open':
                flags = sub.args[1] if len(sub.args) > 1 else None
                text = ast.dump(flags) if flags is not None else ''
                if any(k in text for k in ('O_WRONLY', 'O_CREAT', 'O_APPEND', 'O_TRUNC')):
                    hit = True
            elif isinstance(fn, ast.Name) and fn.id == 'open':
                mode = sub.args[1] if len(sub.args) > 1 else None
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                        and any(c in mode.value for c in 'wax+'):
                    hit = True
        if hit:
            bad.append(node.name)
    return bad


def run(seed=7, mode='const'):
    print('  -- P4 能力形态（seed=%d mode=%s） --' % (seed, mode))
    for attr in ('write', 'update', '_append', '_replace', 'append', 'atomic_write'):
        check('P4 Root 无写方法 %s' % attr, not hasattr(Root, attr))
    wparams = list(inspect.signature(LockedRoot.write).parameters)
    uparams = list(inspect.signature(LockedRoot.update).parameters)
    check('P4 LockedRoot.write 不收 root/path',
          'root' not in wparams and 'path' not in wparams, '%r' % (wparams,))
    check('P4 LockedRoot.update 不收 root/path',
          'root' not in uparams and 'path' not in uparams, '%r' % (uparams,))
    check('P4 LockedRoot 不能绕过 Root.lock() 构造',
          _raises(lambda: LockedRoot(None)),
          '直接构造必须 RuntimeError')

    src = open(os.path.join(common.SRC, 'safeio.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    bad = _module_write_functions(tree)
    check('P4 模块级无写函数（写能力只在 LockedRoot 上）', not bad, 'bad=%r' % (bad,))
    legacy = [n for n in ('atomic_write', 'atomic_append', 'append_inplace',
                          'read_modify_write') if ('def %s(' % n) in src]
    check('P4 旧四原语不再存在（无 shim）', not legacy, 'legacy=%r' % (legacy,))

    with common.tmpdir('p4_') as base:
        root = os.path.join(base, 'root')
        os.makedirs(root)
        rt = Root._from_dir_path(root)
        try:
            with rt.lock(timeout=2.0) as lr:
                check('P4 Root.lock() 产出的凭证可直接写',
                      lr.write(rt.rel('ok.txt'), b'x\n',
                               mode=WriteMode.APPEND_CREATE) is False)
        finally:
            rt.close()
    return common.summary()


def _raises(fn):
    try:
        fn()
        return False
    except RuntimeError:
        return True


if __name__ == '__main__':
    raise SystemExit(run())
