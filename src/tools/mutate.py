#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""AST 变异器注册表 M1–M8（步骤 5）
AST mutation registry M1–M8 (step 5)
================================================
每条变异声明「目标文件 + 期望杀死它的属性」。`tools/score.py` 把 `src/` 拷成临时树，
在本模块里按 AST 改一处，然后只跑期望属性：红=杀死；绿=存活（并再跑全量看是否
「未被对应属性杀死」→ 死变异）。锚点消失、变换后无差异、编译失败也都是死变异。
"""
import argparse
import ast
import os
import shutil
import sys


class MutationError(Exception):
    """变异无法应用（锚点消失等）——记分时算死变异。"""


def _parse(text):
    return ast.parse(text)


def _func(tree, name, cls=None):
    node = tree
    if cls:
        node = _find_class(tree, cls)
    found = _find_func(node, name)
    if found is None:
        raise MutationError('找不到函数 %s%s' % ((cls + '.') if cls else '', name))
    return found


def _find_class(tree, name):
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == name:
            return n
    raise MutationError('找不到类 %s' % name)


def _find_func(node, name):
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _expr(src):
    return ast.parse(src, mode='eval').body


def _insert_after_doc(func, stmt_src):
    body = func.body
    i = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], 'value', None), ast.Constant) and isinstance(
            body[0].value.value, str):
        i = 1
    body.insert(i, _parse(stmt_src).body[0])
    ast.fix_missing_locations(func)


def _strip_nofollow(expr):
    """从 BinOp 或链里删掉 os.O_NOFOLLOW（返回 None 表示整条删掉）。"""
    if isinstance(expr, ast.Attribute) and expr.attr == 'O_NOFOLLOW':
        return None
    if isinstance(expr, ast.BinOp):
        left = _strip_nofollow(expr.left)
        right = _strip_nofollow(expr.right)
        if left is None:
            return right
        if right is None:
            return left
        expr.left, expr.right = left, right
        return expr
    return expr


def m1_lock_key_to_label(text):
    """锁键与释放键一起退回 label（保持变异体内部自洽，只破坏「身份=inode」）。"""
    tree = _parse(text)
    hit = 0
    for cls, fn in (('Root', 'lock'), ('LockedRoot', 'release')):
        f = _func(tree, fn, cls)
        for node in ast.walk(f):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'key' for t in node.targets):
                node.value = _expr('self.label' if cls == 'Root' else 'self.root.label')
                hit += 1
    if hit < 2:
        raise MutationError('M1 锚点消失：lock/release 的 key 赋值不全（hit=%d）' % hit)
    return ast.unparse(tree)


def m2_drop_nofollow(text):
    tree = _parse(text)
    walk = _func(tree, '_walk_parent')
    hit = False
    for node in ast.walk(walk):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'open' and len(node.args) >= 2:
            new = _strip_nofollow(node.args[1])
            if new is not None:
                node.args[1] = new
                hit = True
    if not hit:
        raise MutationError('M2 锚点消失：_walk_parent 无 O_NOFOLLOW')
    return ast.unparse(tree)


def m3_abspath_fold(text):
    tree = _parse(text)
    f = _func(tree, '_rel_from_path')
    for node in ast.walk(f):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'cur' for t in node.targets):
            node.value = _expr('os.path.realpath(os.path.dirname(os.path.abspath(path)))')
            return ast.unparse(tree)
    raise MutationError('M3 锚点消失：_rel_from_path 无 cur 赋值')


def m4_append_bypass(text):
    tree = _parse(text)
    f = _func(tree, 'append_one')
    emit = _find_func(f, '_emit')
    if emit is None:
        raise MutationError('M4 锚点消失：append_one 无 _emit')
    _insert_after_doc(emit, "open(path, 'ab').close()")
    return ast.unparse(tree)


def m5_lock_bypass(text):
    tree = _parse(text)
    f = _func(tree, 'lock', 'Root')
    _insert_after_doc(f, 'return LockedRoot(self, _LOCK_TOKEN)')
    return ast.unparse(tree)


def m6_entry_return_2(text):
    tree = _parse(text)
    f = _func(tree, 'main')
    _insert_after_doc(f, 'return 2')
    return ast.unparse(tree)


def _drop_stmt(node, pred):
    """在任意嵌套语句块里删掉第一个满足 pred 的表达式语句。"""
    for _field, value in ast.iter_fields(node):
        if isinstance(value, list):
            for i, child in enumerate(value):
                if isinstance(child, ast.Expr) and pred(child):
                    del value[i]
                    return True
                if isinstance(child, ast.AST) and _drop_stmt(child, pred):
                    return True
    return False


def m7_drop_dir_fsync(text):
    tree = _parse(text)
    f = _func(tree, '_replace', 'LockedRoot')

    def pred(node):
        call = node.value
        return (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == 'fsync'
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == 'dfd')

    if not _drop_stmt(f, pred):
        raise MutationError('M7 锚点消失：_replace 无 fsync(dfd)')
    return ast.unparse(tree)


def m8_rel_first_segment(text):
    tree = _parse(text)
    f = _func(tree, '__init__', 'Rel')
    for node in ast.walk(f):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) \
                and node.target.id == 'seg' and isinstance(node.iter, ast.Name) \
                and node.iter.id == 'parts':
            node.iter = ast.Subscript(value=ast.Name(id='parts', ctx=ast.Load()),
                                      slice=ast.Slice(upper=ast.Constant(value=1)),
                                      ctx=ast.Load())
            return ast.unparse(tree)
    raise MutationError('M8 锚点消失：Rel.__init__ 无 for seg in parts')


def m9_drop_liveness(text):
    """去掉写前凭证校验（write/update 各一处）。"""
    tree = _parse(text)

    def pred(node):
        c = node.value
        return (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == '_ensure_live')

    hit = 0
    for fn in ('write', 'update'):
        if _drop_stmt(_func(tree, fn, 'LockedRoot'), pred):
            hit += 1
    if hit < 2:
        raise MutationError('M9 锚点消失：write/update 的 _ensure_live 不全（hit=%d）' % hit)
    return ast.unparse(tree)


def m10_task_reopen_by_path(text):
    """TaskVolume.create 写前把 Root 退回 str(path) 重开（换根后改道新 inode）。"""
    tree = _parse(text)
    f = _func(tree, 'create', 'TaskVolume')
    hit = False
    for node in ast.walk(f):
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                        and call.func.id == 'locked' and call.args \
                        and isinstance(call.args[0], ast.Attribute) \
                        and call.args[0].attr == 'root':
                    call.args[0] = ast.Call(func=ast.Name(id='str', ctx=ast.Load()),
                                            args=[call.args[0]], keywords=[])
                    hit = True
    if not hit:
        raise MutationError('M10 锚点消失：TaskVolume.create 无 locked(self.root)')
    return ast.unparse(tree)


def m11_hub_pass_path(text):
    """Hub 把路径字符串而不是 Root 句柄传给各件（换根后按路径重开）。"""
    tree = _parse(text)
    hit = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            for kw in node.keywords:
                if kw.arg == 'root' and isinstance(kw.value, ast.Attribute) \
                        and kw.value.attr == 'root_handle':
                    kw.value = ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()),
                                             attr='root', ctx=ast.Load())
                    hit += 1
    if not hit:
        raise MutationError('M11 锚点消失：orchestrator 无 root=self.root_handle')
    return ast.unparse(tree)


def m12_registry_mkdir_by_path(text):
    """Registry 密钥目录退回 os.makedirs(str(root))，换根后建到新 inode。"""
    tree = _parse(text)
    f = _func(tree, '_write_secret', 'Registry')
    hit = False
    for node in ast.walk(f):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) \
                and node.value.func.attr == 'mkdirs':
            node.value = _expr("os.makedirs(os.path.join(str(self.root), KEY_DIR_NAME), "
                               "mode=0o700, exist_ok=True)")
            hit = True
    if not hit:
        raise MutationError('M12 锚点消失：_write_secret 无 mkdirs')
    return ast.unparse(tree)


MUTATIONS = [
    {'id': 'M1', 'file': 'safeio.py', 'expect': 'P1',
     'desc': '锁键改 label（同 inode 不再同一把锁）', 'apply': m1_lock_key_to_label},
    {'id': 'M2', 'file': 'safeio.py', 'expect': 'P2',
     'desc': '去掉走查 O_NOFOLLOW（祖先软链逃逸）', 'apply': m2_drop_nofollow},
    {'id': 'M3', 'file': 'safeio.py', 'expect': 'P2',
     'desc': '归属判退回 abspath 词法折叠（link/.. 改道）', 'apply': m3_abspath_fold},
    {'id': 'M4', 'file': 'daybook_append.py', 'expect': 'P3',
     'desc': 'append_one 插 open(path, "ab") 旁路', 'apply': m4_append_bypass},
    {'id': 'M5', 'file': 'safeio.py', 'expect': 'P5',
     'desc': 'Root.lock 直接发凭证、不取锁', 'apply': m5_lock_bypass},
    {'id': 'M6', 'file': 'daybook.py', 'expect': 'P6',
     'desc': '入口插 return 2（改退出码）', 'apply': m6_entry_return_2},
    {'id': 'M7', 'file': 'safeio.py', 'expect': 'P5',
     'desc': '删 _replace 的 fsync(dfd)', 'apply': m7_drop_dir_fsync},
    {'id': 'M8', 'file': 'safeio.py', 'expect': 'P2',
     'desc': 'Rel 只校验首段（.. 逃逸）', 'apply': m8_rel_first_segment},
    {'id': 'M9', 'file': 'safeio.py', 'expect': 'P8',
     'desc': '去掉写凭证的释放/线程校验', 'apply': m9_drop_liveness},
    {'id': 'M10', 'file': 'task_volume.py', 'expect': 'P9',
     'desc': 'TaskVolume 写时按路径重开 Root（换根改道）', 'apply': m10_task_reopen_by_path},
    {'id': 'M11', 'file': 'orchestrator.py', 'expect': 'P9',
     'desc': 'Hub 传路径而不是 Root 句柄', 'apply': m11_hub_pass_path},
    {'id': 'M12', 'file': 'agent_registry.py', 'expect': 'P9',
     'desc': 'Registry 密钥目录按路径 os.makedirs', 'apply': m12_registry_mkdir_by_path},
]

BY_ID = {m['id']: m for m in MUTATIONS}


def apply_one(tree_root, mut_id):
    """在 tree_root（= 临时 src 目录）上就地应用一条变异；失败抛 MutationError。"""
    mut = BY_ID[mut_id]
    path = os.path.join(tree_root, mut['file'])
    with open(path, encoding='utf-8') as f:
        text = f.read()
    try:
        new = mut['apply'](text)
    except MutationError:
        raise
    except Exception as exc:
        raise MutationError('%s 应用失败：%s' % (mut_id, exc))
    if new == text:
        raise MutationError('%s 变换后无差异' % mut_id)
    try:
        compile(new, path, 'exec')
    except SyntaxError as exc:
        raise MutationError('%s 编译失败：%s' % (mut_id, exc))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new)
    return mut


def copy_src(src_root, dst_root):
    """只拷被测件与属性层（score 用），忽略缓存。"""
    shutil.copytree(src_root, dst_root,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))


def main(argv):
    ap = argparse.ArgumentParser(description='AST 变异器 M1–M8')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--apply', default='')
    ap.add_argument('--src', default=os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    ap.add_argument('--out', default='')
    args = ap.parse_args(argv)
    if args.list or not args.apply:
        for m in MUTATIONS:
            print('%s → %s  %s  %s' % (m['id'], m['expect'], m['file'], m['desc']))
        return 0
    if not args.out:
        print('--apply 需要 --out', file=sys.stderr)
        return 2
    copy_src(args.src, args.out)
    try:
        apply_one(args.out, args.apply)
    except MutationError as exc:
        print('✗ %s' % exc, file=sys.stderr)
        return 1
    print('已应用 %s → %s' % (args.apply, args.out))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
