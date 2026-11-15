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
  H 删游标后等长替换                            ⇒ rc=3（封存仍在即判违例·不是 5）
  I 游标写成 {}                                 ⇒ rc=5（封存缺失/不可判定·不自动修好）
  J 替换后自己重写游标的 hash/size/mtime         ⇒ rc=3（与封存指纹不符·游标被改写）
  K 删索引加删游标                              ⇒ rc=5（证据缺失·不重建）
  L 正常追加后删索引                            ⇒ rc=5 且无 traceback（旧实现 FileNotFoundError rc=1）
  M 三件派生件全删                              ⇒ rc=5（无外部锚·复跑仍 5），认基线后 0
  N 索引缺失且卷变长、旧前缀被改                 ⇒ rc=3（不能因「卷变大」跳过前缀校验）
  O 违例态认基线                                ⇒ rc=3，三件派生件零变化（不替人认下篡改）
  R ≥8 进程并发 index                           ⇒ 零误报、零丢更新、复跑全 0（封存快照锁内只读一次）
  S 配置错（卷指向目录）                        ⇒ rc=2 且派生件递归哈希零变化（不可信即零落盘）
  T rc=3 违例                                   ⇒ 清单/封存时戳零变化（不可信即零落盘）
  V5 删游标+等长改写                            ⇒ rc=3（缺一名证人、另一名仍在 ⇒ 仍判违例），零落盘
  U rc=4 作者口径红                             ⇒ 照写且文案「已写回·只报不拦」（不是不可信）
  R2 两进程 20ms 错峰并发 index                 ⇒ 两侧 rc=0（一「只追加」一「未变」）
  V safeio 原子替换/无锁读者                    ⇒ atomic_write 走 os.replace，read_vol 不取锁
  W 子目录卷 + 长条目 append                    ⇒ 与 index 争同一把账本根锁（不被子目录锁旁路）
  P 同一账本·两个不同 TMPDIR 并发持锁读改写     ⇒ 临界区不重叠、不丢更新（锁绑目录 inode）
  Q 持锁期间删除任何外部件                      ⇒ 仍互斥（账本内本无锁件可删）
  AA 卷末无换行（有换行/合法无换行/半行残渣）    ⇒ 追加后增量条数 == 全量重建条数，行号无幻影
  AB conf 根 ≠ 脚本目录·账本外调用 CLI           ⇒ 锁落账本根；8 并发长条目全存活
  AC 作者缓存绑定内容哈希                        ⇒ 等长改写后喂旧缓存必须红（不许按 size 复用）

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
  根解析变异：把任一处调用点改回旧算法（如 mcp_resources._root 拿 DAYBOOK_ROOT 直接当根）
  ⇒ AE1 必红；把 hook 的 ledger_home 改成 env 当根 ⇒ AE1/AE2 必红。
  补换行点名变异：删掉 daybook.py 里的「卷末行不完整·已补换行」报告行，或让 pad_notice
  不写 stderr ⇒ AA 必红。

跑法 / Run: python3 ledger_guard_test.py
退出码 / Exit code: 0=全绿 1=有红
"""
import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# 被测 daybook.py：默认同目录；变异验证时用 DAYBOOK_SRC 指向临时副本
# The daybook.py under test: same directory by default; DAYBOOK_SRC points at a mutant copy.
SRC_BIN = os.environ.get('DAYBOOK_SRC') or os.path.join(HERE, 'daybook.py')

# 写路径登记表（单一常量）：(文件, 所在函数, 桶, 理由)
# Write-path registry (single constant): (file, enclosing function, bucket, reason)
# 桶（判据机器校验，理由文字不作数）：
#   ledger   = 写账本/账本根内的件（租约卷、keys/、backup/ 都算）⇒ 只许 safeio，扫到直接写即红；
#   lockfile = 锁件本身（目标固定为 <锁目录>/<资源>.lock，不写数据）⇒ 允许 os.open，形态机器校验；
#   other    = 只允许「目标由 tempfile 生成、位于系统临时目录」一类 ⇒ 目标表达式机器校验；
#   impl     = safeio 自身实现。
# Buckets (machine-checked; the prose reason does not count):
#   ledger   = writes the ledger or anything inside the ledger root (lease volume, keys/,
#              backup/ all count) ⇒ safeio only; any direct write fails;
#   lockfile = the lock artifact itself (target fixed to <lock dir>/<resource>.lock, no data
#              written) ⇒ os.open allowed, shape machine-checked;
#   other    = only "target produced by tempfile, inside the system temp dir" ⇒ target
#              expression machine-checked;
#   impl     = safeio's own implementation.
WRITE_PATHS = (
    ('agent_heartbeat.py', '__init__', 'ledger', '账本内容/派生件'),
    ('agent_heartbeat.py', 'beat', 'ledger', '账本内容/派生件'),
    ('agent_lock.py', '_log', 'ledger', '账本内容/派生件'),
    ('agent_message.py', '_append_inbox', 'ledger', '账本内容/派生件'),
    ('agent_registry.py', '_write_secret', 'ledger', 'keys/ 在账本根内（atomic_write 0600）'),
    ('agent_registry.py', 'register', 'ledger', '账本内容/派生件'),
    ('agent_registry.py', 'revoke', 'ledger', '账本内容/派生件'),
    ('daybook.py', '_write_cursor', 'ledger', '账本内容/派生件'),
    ('daybook.py', '_run_ops', 'ledger', '账本内容/派生件'),
    ('daybook.py', 'build', 'ledger', '账本内容/派生件'),
    ('daybook.py', '_backup_copy', 'ledger', 'backup/ 在账本根内（atomic_write）'),
    ('daybook_append.py', 'append_one', 'ledger', '账本内容/派生件'),
    ('daybook_hook.py', 'mark_processed', 'ledger', '账本内容/派生件'),
    ('daybook_multidx.py', '_build_locked', 'ledger', '账本内容/派生件'),
    ('daybook_record.py', 'record', 'ledger', '账本内容/派生件'),
    ('daybook_session_hook.py', 'atomic_json', 'ledger', '账本内容/派生件'),
    ('entry_smoke_test.py', 'mutation_check', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', '_setup', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_cross_ref_numbered', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_root_from_conf', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', '_copy_server', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_zero_bytecode', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_empty_volumes_warns', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'mk', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_resources.py', '_audit', 'ledger', '账本内容/派生件'),
    ('mcp_test.py', '_setup_tmp_root', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_test.py', 'test_daybook_index', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_test.py', 'test_subscribe_push', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_tools.py', '_audit', 'ledger', '账本内容/派生件'),
    ('mcp_tools.py', '_record_signature', 'ledger', '账本内容/派生件'),
    ('mcp_tools.py', '_write_cursor', 'ledger', '账本内容/派生件'),
    ('orch_fixes_test.py', '_fresh_root', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', '_make_volume', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_author_head_parse', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_cli_limit_semantics', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_digest_visibility_and_limit', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_pull_reply', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_identity_signature', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_root_resolution', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_alarm_structure_and_exit_codes', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_single_pass_reads', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_mutation_check.py', 'make_mutant', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_perf_bench.py', 'build_dataset', 'other', '随包压测：目标由 tempfile 生成'),
    ('orch_perf_bench.py', 'make_old_pkg', 'other', '随包压测：目标由 tempfile 生成'),
    ('orch_perf_bench.py', 'main', 'other', '随包压测：目标由 tempfile 生成'),
    ('orchestrator.py', '_selftest', 'other', '自检：目标由 tempfile 生成'),
    ('path_leak_check.py', 'mutation_check', 'other', '随包测试：目标由 tempfile 生成'),
    ('safeio.py', 'atomic_write', 'impl', 'safeio 实现本身'),
    ('safeio.py', 'atomic_append', 'impl', 'safeio 实现本身'),
    ('safeio.py', 'append_inplace', 'impl', 'safeio 实现本身'),
    ('safeio.py', 'read_modify_write', 'impl', 'safeio 实现本身'),
    ('task_volume.py', '__init__', 'ledger', '账本内容/派生件'),
    ('task_volume.py', 'create', 'ledger', '账本内容/派生件'),
    ('task_volume.py', 'transition', 'ledger', '账本内容/派生件'),
)

_WRITE_SAFE = frozenset(('safeio.atomic_write', 'safeio.atomic_append',
                         'safeio.atomic_replace', 'safeio.read_modify_write',
                         'safeio.append_inplace',
                         # safeio 内部的自调用（同模块裸名）
                         # self-calls inside safeio (bare names in the same module)
                         'atomic_write', 'atomic_append', 'atomic_replace',
                         'read_modify_write', 'append_inplace'))
_WRITE_SKIP = ('pack.py', 'ledger_guard_test.py')
_WRITE_TEMP = ('tempfile.mkstemp', 'tempfile.NamedTemporaryFile',
               'tempfile.mkdtemp', 'tempfile.TemporaryFile')


def _write_aliases(tree):
    """收集 import / import ... as / from ... import ... as 的本地名 → 原名。
    Collect local names → original names for import / import-as / from-import-as."""
    m = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                m[a.asname or a.name.split('.')[0]] = ('mod', a.name)
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                m[a.asname or a.name] = ('from', (n.module or '') + '.' + a.name)
    return m


def _resolve_callee(func, aliases):
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            o = aliases.get(func.value.id)
            if o and o[0] == 'mod':
                return o[1] + '.' + func.attr
        return func.attr
    if isinstance(func, ast.Name):
        o = aliases.get(func.id)
        if o and o[0] == 'from':
            return o[1]
        return func.id
    return ''


def _open_mode_writes(node):
    v = node.args[1] if len(node.args) > 1 else None
    for kw in node.keywords:
        if kw.arg == 'mode':
            v = kw.value
    return (isinstance(v, ast.Constant) and isinstance(v.value, str)
            and any(c in v.value for c in 'wax+'))


def _osopen_writes(node):
    v = node.args[1] if len(node.args) > 1 else None

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return n.value
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                and n.value.id == 'os':
            return getattr(os, n.attr, 0)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
            return ev(n.left) | ev(n.right)
        return 0

    f = ev(v) if v is not None else 0
    return bool(f & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))


_TEMP_CALLS = ('tempfile.mkdtemp', 'tempfile.mkstemp', 'tempfile.NamedTemporaryFile',
               'tempfile.TemporaryDirectory', 'tempfile.TemporaryFile', 'tempfile.gettempdir')
_PATH_FIRST = ('os.path.join', 'os.path.dirname', 'os.path.abspath', 'os.path.realpath',
               'os.fspath', 'str')
# os.path.* 经 _resolve_callee 还原后是裸属性名（os.path 是 Attribute 而非 Name）
# os.path.* comes back as a bare attribute name from _resolve_callee (os.path is an Attribute)
_PATH_ATTRS = ('join', 'dirname', 'abspath', 'realpath', 'fspath')


def _is_path_helper(t):
    return t in _PATH_FIRST or t.split('.')[-1] in _PATH_ATTRS


def _expr_temp(e, names, helpers, aliases):
    """表达式是否「由 tempfile 生成」（名字 / join 链首元 / 拼接左元 / 本模块 tempfile 助手返回）。
    Whether the expression is produced by tempfile (a tracked name, the first element of a join
    chain, the left operand of a concatenation, or the return of a module helper)."""
    if isinstance(e, ast.Name):
        return e.id in names
    if isinstance(e, ast.Call):
        t = _resolve_callee(e.func, aliases)
        if t in _TEMP_CALLS:
            return True
        if _is_path_helper(t):
            return bool(e.args) and _expr_temp(e.args[0], names, helpers, aliases)
        if '.' not in t and t in helpers:
            return True
        return False
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
        return _expr_temp(e.left, names, helpers, aliases)
    if isinstance(e, ast.JoinedStr):
        for v in e.values:
            if isinstance(v, ast.FormattedValue):
                return _expr_temp(v.value, names, helpers, aliases)
    return False


def _module_temp_helpers(tree):
    """本模块里「返回 tempfile 派生值」的函数名（固定点，支持一层转手）。
    Module functions returning a tempfile-derived value (fixed point, one level of relay)."""
    aliases = _write_aliases(tree)
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    helpers = set()
    for _ in range(3):
        for fn in funcs:
            if fn.name in helpers:
                continue
            local = _local_temp_names(fn, helpers, aliases)
            for r in ast.walk(fn):
                if isinstance(r, ast.Return) and r.value is not None \
                        and _expr_temp(r.value, local, helpers, aliases):
                    helpers.add(fn.name)
                    break
    return helpers


def _local_temp_names(fn, helpers, aliases, seed=()):
    """函数内被 tempfile 派生的局部名（赋值、with ... as、链式 join）；seed 为已证参数。
    Local names derived from tempfile inside one function (assignments, with-as, join chains);
    `seed` carries parameters already proven temp-derived at every call site."""
    names = set(seed)
    for n in ast.walk(fn):
        if isinstance(n, ast.With):
            for item in n.items:
                if isinstance(item.optional_vars, ast.Name) and item.context_expr is not None \
                        and _expr_temp(item.context_expr, names, helpers, aliases):
                    names.add(item.optional_vars.id)
    changed = True
    while changed:
        changed = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                targets, value = n.targets, n.value
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                targets, value = [n.target], n.value
            elif isinstance(n, ast.NamedExpr):
                targets, value = [n.target], n.value
            else:
                continue
            if _expr_temp(value, names, helpers, aliases):
                for t in targets:
                    if isinstance(t, ast.Name) and t.id not in names:
                        names.add(t.id)
                        changed = True
    return names


def _root_name(e, aliases):
    """写目标表达式 → 根名（('name', x) / ('attr', …) / ('call', …) / ('lit', …)）。
    Write-target expression → root descriptor."""
    if isinstance(e, ast.Name):
        return ('name', e.id)
    if isinstance(e, ast.Call):
        t = _resolve_callee(e.func, aliases)
        if _is_path_helper(t) and e.args:
            return _root_name(e.args[0], aliases)
        return ('call', t)
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
        return _root_name(e.left, aliases)
    if isinstance(e, ast.JoinedStr):
        for v in e.values:
            if isinstance(v, ast.FormattedValue):
                return _root_name(v.value, aliases)
    if isinstance(e, ast.Attribute):
        return ('attr', ast.unparse(e))
    if isinstance(e, ast.Constant):
        return ('lit', repr(e.value)[:20])
    return ('?', type(e).__name__)


def _write_call_targets(call, aliases):
    """一个调用里「写目标」的表达式清单（按各类写调用的参数位置）。
    The target expressions written by one call (per write-call signature)."""
    t = _resolve_callee(call.func, aliases)
    if t == 'os.open':
        return [call.args[0]] if call.args and _osopen_writes(call) else []
    if t in ('open', 'io.open'):
        return [call.args[0]] if call.args and _open_mode_writes(call) else []
    if t in ('os.replace', 'os.rename', 'shutil.copy', 'shutil.copy2',
             'shutil.copyfile', 'shutil.copytree'):
        return [call.args[1]] if len(call.args) > 1 else []
    if isinstance(call.func, ast.Attribute) and call.func.attr in ('write_text', 'write_bytes'):
        return [call.func.value]
    if t in _WRITE_TEMP:
        return []
    if t in _WRITE_SAFE:
        # safeio 写的是「某个路径」，other 桶也必须证明这个路径来自 tempfile
        # safeio writes *some* path; the `other` bucket must prove that path comes from tempfile
        return [call.args[0]] if call.args else []
    if t.split('.')[-1] in ('run', 'Popen', 'call', 'check_call', 'check_output'):
        out = []
        for kw in call.keywords:
            if kw.arg in ('stdout', 'stderr'):
                v = kw.value
                if isinstance(v, ast.Constant):
                    continue
                if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) \
                        and v.value.id == 'subprocess':
                    continue
                out.append(v)
        return out
    return []


def _enclosing(tree, node):
    """node 所在的最内层函数（无则 None）。"""
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(sub is node for sub in ast.walk(n)):
                if best is None or len(list(ast.walk(n))) < len(list(ast.walk(best))):
                    best = n
    return best


def _param_temp_only(tree, fn, param, aliases, helpers):
    """参数 param 在本模块所有调用点是否都收到 tempfile 派生实参。
    Whether every in-module call site passes a tempfile-derived argument for `param`."""
    args = [a.arg for a in fn.args.args]
    if param not in args:
        return False
    idx = args.index(param)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and _resolve_callee(n.func, aliases) == fn.name]
    if not calls:
        return False
    for c in calls:
        owner = _enclosing(tree, c)
        names = _local_temp_names(owner, helpers, aliases) if owner is not None else set()
        arg = c.args[idx] if len(c.args) > idx else None
        for kw in c.keywords:
            if kw.arg == param:
                arg = kw.value
        if arg is None or not _expr_temp(arg, names, helpers, aliases):
            return False
    return True


def _literal_components(e, aliases, out=None):
    """写目标表达式里的字面路径段（join 链、字符串拼接、f-string 常量）。
    Literal path components of a write target (join chain, concatenation, f-string constants)."""
    if out is None:
        out = []
    if isinstance(e, ast.Call):
        t = _resolve_callee(e.func, aliases)
        if _is_path_helper(t):
            for a in e.args:
                _literal_components(a, aliases, out)
        return out
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
        _literal_components(e.left, aliases, out)
        _literal_components(e.right, aliases, out)
        return out
    if isinstance(e, ast.JoinedStr):
        for v in e.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
        return out
    if isinstance(e, ast.Constant) and isinstance(e.value, str):
        out.append(e.value)
    return out


def _targets_stay_in_temp(tgt, aliases):
    """规范化后是否仍在临时目录前缀内：任何 `..` 或绝对段都视为可能逃出，判红。
    Whether the normalized target stays under the temp prefix: any `..` or absolute
    component may escape, so it fails."""
    comps = _literal_components(tgt, aliases)
    for c in comps:
        if c == '..' or os.path.isabs(c):
            return False
        if os.path.normpath(c).startswith('..'):
            return False
    probe = os.path.normpath(os.path.join(*([os.path.join(os.sep, 'tmp', 'x')] + comps)))
    return probe.startswith(os.path.join(os.sep, 'tmp') + os.sep)


def _other_target_reasons(tree, fn):
    """other 桶机器校验：该函数每个写目标都必须由 tempfile 生成、且规范化后仍在临时目录前缀内。
    Machine check for the `other` bucket: every write target must come from tempfile and must
    still normalize inside the system temp prefix.
    返回空清单=通过；否则每项写明「目标可能落在账本根内」的具体调用。
    Empty list = pass; otherwise each item names the offending call."""
    aliases = _write_aliases(tree)
    helpers = _module_temp_helpers(tree)
    seed = {a.arg for a in fn.args.args
            if _param_temp_only(tree, fn, a.arg, aliases, helpers)}
    names = _local_temp_names(fn, helpers, aliases, seed)
    bad = []
    for call in ast.walk(fn):
        if not isinstance(call, ast.Call):
            continue
        for tgt in _write_call_targets(call, aliases):
            root = _root_name(tgt, aliases)
            snippet = ast.unparse(call)[:70]
            if root[0] == 'name':
                if root[1] in names:
                    pass
                elif _param_temp_only(tree, fn, root[1], aliases, helpers):
                    pass
                else:
                    bad.append('%s（%s 非 tempfile 生成·目标可能落在账本根内）' % (snippet, root[1]))
                    continue
            else:
                bad.append('%s（目标形态 %r 无法证明为 tempfile·可能落在账本根内）'
                           % (snippet, root[1]))
                continue
            if not _targets_stay_in_temp(tgt, aliases):
                bad.append('%s（含 `..`/绝对段·可逃出临时目录）' % snippet)
    return bad


def _find_func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _scan_write_sites(d):
    """按包装清单扫产品件与随包脚本，返回 (扫过的件, {(文件,函数): 写种类集合}, {文件: AST})。
    Scan the shipped product/aux files from the pack manifest; return (files, sites, trees).
    别名会还原成原名；覆盖 open 写模式、os.open 写标志、os.replace/rename、
    shutil.copy*、Path.write_text/bytes、tempfile、subprocess 重定向。
    Aliases are resolved; covers open write modes, os.open write flags, os.replace/rename,
    shutil.copy*, Path.write_text/bytes, tempfile and subprocess redirection."""
    try:
        if d not in sys.path:
            sys.path.insert(0, d)
        from pack import PACKAGES
        names = set()
        for spec in PACKAGES.values():
            names.update(spec.get('prog', []))
            names.update(spec.get('prog_aux', []))
        scan = [n for n in sorted(names)
                if n.endswith('.py') and n not in _WRITE_SKIP
                and os.path.exists(os.path.join(d, n))]
    except Exception:
        scan = [n for n in sorted(os.listdir(d))
                if n.endswith('.py') and n not in _WRITE_SKIP
                and not n.endswith('_test.py')]
    files, sites, trees = [], {}, {}
    for fn in scan:
        try:
            tree = ast.parse(io.open(os.path.join(d, fn), encoding='utf-8').read())
        except SyntaxError:
            continue
        files.append(fn)
        trees[fn] = tree
        al = _write_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            kinds = set()
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                t = _resolve_callee(sub.func, al)
                if t in _WRITE_SAFE:
                    kinds.add('safe')
                elif t in ('os.replace', 'os.rename'):
                    kinds.add('replace')
                elif t in ('shutil.copy', 'shutil.copy2', 'shutil.copyfile',
                           'shutil.copytree'):
                    kinds.add('copy')
                elif t in ('open', 'io.open') and _open_mode_writes(sub):
                    kinds.add('open')
                elif t == 'os.open' and _osopen_writes(sub):
                    kinds.add('osopen')
                elif t in _WRITE_TEMP:
                    kinds.add('temp')
                elif isinstance(sub.func, ast.Attribute) \
                        and sub.func.attr in ('write_text', 'write_bytes'):
                    kinds.add('open')
                elif t.split('.')[-1] in ('run', 'Popen', 'call', 'check_call',
                                          'check_output'):
                    for kw in sub.keywords:
                        if kw.arg in ('stdout', 'stderr'):
                            v = kw.value
                            if isinstance(v, ast.Constant):
                                continue
                            if isinstance(v, ast.Attribute) \
                                    and isinstance(v.value, ast.Name) \
                                    and v.value.id == 'subprocess':
                                continue
                            kinds.add('subproc')
            if kinds:
                sites[(fn, node.name)] = kinds
    return files, sites, trees


def _case_write_paths(tmp):
    """AH 写路径登记表判据：登记未实现、实现未登记、账本桶直写，三者都红。
    AH write-path registry: registered-but-absent, present-but-unregistered, and any direct
    write inside a ledger bucket all fail."""
    print('  -- AH 写路径登记表（三向都红） --')
    d = os.path.dirname(os.path.abspath(SRC_BIN))
    files, sites, trees = _scan_write_sites(d)
    reg = {(f, fn): (b, r) for f, fn, b, r in WRITE_PATHS}
    present = {k: v for k, v in reg.items() if k[0] in files}
    if os.path.exists(os.path.join(d, 'pack.py')):
        want = {f for f, _fn, _b, _r in WRITE_PATHS}
        _ok('AH 源树：登记表涉及的件全部在场', want <= set(files),
            '缺=%s' % sorted(want - set(files)))
    absent = sorted(k for k in present if k not in sites)
    unreg = sorted(k for k in sites if k not in reg)
    direct = sorted((k, sorted(v - {'safe'})) for k, v in sites.items()
                    if reg.get(k, ('', ''))[0] == 'ledger' and (v - {'safe'}))
    _ok('AH 登记了但代码里找不到 ⇒ 红', not absent, '找不到=%s' % absent)
    _ok('AH 代码里有写调用但没登记 ⇒ 红', not unreg, '未登记=%s' % unreg)
    _ok('AH 账本桶只许 safeio（直接写 ⇒ 红）', not direct, '直写=%s' % direct)
    # other 桶＝后门：只允许「目标由 tempfile 生成」。任一条改标 other ⇒ 红。
    # `other` is a backdoor if prose suffices: only tempfile-generated targets are allowed.
    bad_other = []
    for (f, fn), (b, _r) in sorted(present.items()):
        if b != 'other':
            continue
        node = _find_func(trees[f], fn)
        if node is None:
            bad_other.append((f, fn, ['函数未找到']))
            continue
        reasons = _other_target_reasons(trees[f], node)
        if reasons:
            bad_other.append((f, fn, reasons[:2]))
    _ok('AH other 桶只许 tempfile 目标（否则必须归账本）⇒ 红', not bad_other,
        '未通过=%s' % bad_other[:4])
    # other 桶条目不许被其他模块调用：跨文件调用 ⇒ 红（否则归回账本）
    # `other` entries must not be called from other modules: a cross-file call ⇒ red
    defs, callers = {}, {}
    for f, tree in trees.items():
        al = _write_aliases(tree)
        defs[f] = {n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                nm = _resolve_callee(n.func, al)
                callers.setdefault(nm, set()).add(f)
                if '.' in nm:                 # mod.func / self.func 也按末段认
                    callers.setdefault(nm.rsplit('.', 1)[1], set()).add(f)
    cross = []
    for (f, fn), (b, _r) in sorted(present.items()):
        if b != 'other':
            continue
        for c in sorted(callers.get(fn, ())):
            if c != f and fn not in defs.get(c, ()):
                cross.append((f, fn, c))
    _ok('AH other 桶条目不许跨文件调用 ⇒ 红', not cross, '跨文件=%s' % cross[:4])
    # 第二套锁实现必须为零：不建锁目录、不建 lock 文件
    # No second lock implementation: no lock directory and no lock file anywhere
    lockref = [f for f in files if '.locks' in io.open(os.path.join(d, f), encoding='utf-8').read()]
    lockmk = []
    for f, tree in trees.items():
        al = _write_aliases(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                for tgt in _write_call_targets(n, al):
                    if '.lock' in ast.unparse(tgt):
                        lockmk.append((f, ast.unparse(tgt)[:40]))
    _ok('AH 全仓无 .locks 目录/引用 ⇒ 红', not lockref, '仍出现=%s' % lockref)
    _ok('AH 无 lock 文件创建点（只许 flock 目录）⇒ 红', not lockmk, '仍出现=%s' % lockmk)
    print('    [数据] AH 登记 %d 条／实扫 %d 条／未登记 %d 条／找不到 %d 条／账本直写 %d 条'
          % (len(present), len(sites), len(unreg), len(absent), len(direct)))
    buckets = {}
    for _k, (_b, _r) in present.items():
        buckets[_b] = buckets.get(_b, 0) + 1
    _TESTISH = tuple('_%s.py' % x for x in ('test', 'check', 'bench', 'regression'))
    prod_other = sum(1 for (f, _fn), (b, _r) in present.items()
                     if b == 'other' and not f.endswith(_TESTISH))
    test_other = sum(1 for (f, _fn), (b, _r) in present.items()
                     if b == 'other' and f.endswith(_TESTISH))
    print('    [数据] AH 在场分桶：账本 %d 条／锁件 %d 条／非账本 %d 条（产品 %d·随包测试 %d）'
          '／safeio 实现 %d 条（扫过 %d 件）'
          % (buckets.get('ledger', 0), buckets.get('lockfile', 0), buckets.get('other', 0),
             prod_other, test_other, buckets.get('impl', 0), len(files)))


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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py'):
        shutil.copy2(os.path.join(here, name), os.path.join(tmp, name))
    with io.open(os.path.join(tmp, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    _make_volume(os.path.join(tmp, '账卷.txt'))


def _run(tmp, cmd='index'):
    # -B：被测脚本被拷进隔离目录运行（真实部署里它在包目录、不在账本里），
    # 关掉字节码缓存，免得 __pycache__ 冒充「账本被写」。
    # -B: the script is staged inside the isolated ledger here (in real deployment it lives in
    # the package dir), so suppress bytecode caching to keep __pycache__ out of the criterion.
    return subprocess.run([sys.executable, '-B', 'daybook.py', cmd],
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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py'):
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
    # 账本根只由 conf 决定：d 自带 conf（[index] root 空 ⇒ 根 = d），env 仅用来找到它。
    # The root is decided by conf alone: d carries its own conf ([index] root empty ⇒ root = d);
    # the env var only locates it.
    io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8').write(
        '[index]\nroot=\n')
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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py'):
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
import os, sys
sys.path.insert(0, sys.argv[1])
p, d = sys.argv[2], sys.argv[3]
import safeio
cp = os.path.join(d, 'daybook.conf')
open(cp, 'w', encoding='utf-8').write('[index]\nroot=\nout_dir=索引\n')
before = open(p, 'rb').read()
# 不持账本根锁直接调用 ⇒ 必须抛错且零写
try:
    safeio.append_inplace(p, 'x\n', d, conf_path=cp)
    print('NO_LOCK_NO_ERROR')
    sys.exit(3)
except RuntimeError:
    pass
assert open(p, 'rb').read() == before, '未持锁调用改动了文件'
with safeio.locked(d):
    padded = safeio.append_inplace(p, '账\t2\tt\t测试\ty\t皮特\n', d, conf_path=cp)
data = open(p, 'rb').read()
assert data.endswith(b'\n'), '追加后仍不是以换行结尾'
assert '半'.encode('utf-8') in data, '合法的末行被截掉了'
assert 'y'.encode('utf-8') in data, '新行未写入'
print('OK')
'''


def _case_append(tmp):
    """Y 追加型派生件 O(1) 原位追加：40 万条基线下单条追加，inode 不变、行数 +1。
    Y Append-type artifacts are O(1) in place: with a 400k baseline a single append keeps the
    inode (no full rewrite) and adds exactly one row."""
    d = os.path.join(tmp, 'append')
    os.makedirs(d)
    here = os.path.dirname(SRC_BIN)
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py'):
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
    """Z 崩溃尾部半行：读者丢弃；写者**不截断**，只补一个换行再追加。
    Z Crashed tail: readers drop the half line; writers never truncate — they pad one newline
    and append."""
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
                        os.path.dirname(SRC_BIN), p, d],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('Z2 无锁调用抛错·持锁补换行追加且不截断（合法末行仍在）',
        r.returncode == 0 and r.stdout.strip() == 'OK',
        (r.stdout.strip() or r.stderr.strip())[:200])


def _aj_run(d, cmd):
    return subprocess.run([sys.executable, '-B', 'daybook.py', cmd], cwd=d,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def _case_tail_no_truncate(tmp):
    """AJ 索引末行无换行：**不截断**，一律全量重扫重建；三种输入都不许丢行。
    AJ A newline-less index tail: never truncate — always fall back to a full rescan; none of
    the three inputs may lose a row."""
    print('  -- AJ 索引末行无换行（不截断·全量重建） --')
    d = os.path.join(tmp, 'aj')
    os.makedirs(d)
    _stage(d)
    io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8').write(CONF)
    vol = os.path.join(d, '账卷.txt')
    io.open(vol, 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [测试] [甲] [皮特] 一\n'
        '[2026-11-13 10:01:00] [测试] [乙] [皮特] 二\n')
    _aj_run(d, 'baseline')
    _aj_run(d, 'index')
    idf = os.path.join(d, '索引', 'index_账.tsv')
    itxt = os.path.join(d, '索引', 'index_账.txt')

    # 形态①：末行完整但无换行（合法行）⇒ 不许截掉，转全量重建
    for f in (idf, itxt):
        data = io.open(f, 'rb').read()
        _ok('AJ 前置：%s 以换行结尾' % os.path.basename(f), data.endswith(b'\n'))
        io.open(f, 'wb').write(data[:-1])
    io.open(vol, 'a', encoding='utf-8').write(
        '[2026-11-13 10:02:00] [测试] [丙] [皮特] 三\n')
    r = _aj_run(d, 'index')
    txt = r.stdout + r.stderr
    _ok('AJ1 末行完整无换行 ⇒ rc=0 且报「不截断·转全量重扫」',
        r.returncode == 0 and '索引末行无换行' in txt and '全量重扫' in txt, txt[-200:])
    rows = _tsv_rows(idf)
    _ok('AJ2 旧行一条不少（甲/乙/丙 三行俱在）',
        [x[4] for x in rows] == ['甲', '乙', '丙'],
        'titles=%s' % [x[4] if len(x) > 4 else '?' for x in rows])

    # 形态②③：半行残渣 / 崩溃残行 ⇒ 全量重扫后条数与行号都和全新重建一致
    for label, cut in (('半行残渣', 4), ('崩溃残行', 1)):
        data = io.open(idf, 'rb').read()
        io.open(idf, 'wb').write(data[:-cut])
        io.open(vol, 'a', encoding='utf-8').write(
            '[2026-11-13 10:0%d:00] [测试] [%s] [皮特] 续\n' % (3 + cut, label))
        r = _aj_run(d, 'index')
        _ok('AJ[%s] rc=0 且报不截断全量重建' % label,
            r.returncode == 0 and '全量重扫' in (r.stdout + r.stderr),
            (r.stdout + r.stderr)[-160:])
        inc = _tsv_rows(idf)
        full = os.path.join(tmp, 'aj_full_' + label)
        os.makedirs(full)
        _stage(full)
        io.open(os.path.join(full, 'daybook.conf'), 'w', encoding='utf-8').write(CONF)
        shutil.copy2(vol, os.path.join(full, '账卷.txt'))
        _aj_run(full, 'baseline')
        ref = _tsv_rows(os.path.join(full, '索引', 'index_账.tsv'))
        _ok('AJ[%s] 条数==全量重建（%d/%d）' % (label, len(inc), len(ref)),
            len(inc) == len(ref), 'inc=%d ref=%d' % (len(inc), len(ref)))
        _ok('AJ[%s] 行号逐个一致' % label,
            [x[1] for x in inc] == [x[1] for x in ref],
            'inc=%s ref=%s' % ([x[1] for x in inc], [x[1] for x in ref]))

    # 变异：增量路径「截断后再追加」⇒ 合法末行被吃掉，判据必须能抓住
    mut = os.path.join(tmp, 'aj_mut')
    os.makedirs(mut)
    _stage(mut)
    src = io.open(os.path.join(mut, 'daybook.py'), encoding='utf-8').read()
    guard = ("""                    bad_tail = [os.path.basename(x) for x in (idf_use, itxt_chk)
                                if _tail_missing_newline(x)]""")
    _ok('AJ 变异前置：找到「末行无换行→全量重建」守卫', guard in src)
    src = src.replace(guard, '                    bad_tail = []')
    n_guard = "                    elif n_idx != cur.get('n', -1):"
    _ok('AJ 变异前置：找到「索引行数与游标不符」守卫', n_guard in src)
    src = src.replace(n_guard, '                    elif False:')
    ap = ("""            if append_inplace(_idf, data, root, conf_path=conf_path) and report is not None:
                report.append((vol, '★ 索引 TSV 末行无换行·已补换行后追加（不截断）'))""")
    mut_ap = ("""            if os.path.exists(_idf):
                _d0 = open(_idf, 'rb').read()
                if _d0 and not _d0.endswith(b'\\n'):
                    open(_idf, 'wb').write(_d0[:_d0.rfind(b'\\n') + 1])
            append_inplace(_idf, data, root, conf_path=conf_path)""")
    _ok('AJ 变异前置：找到增量追加行', ap in src)
    src = src.replace(ap, mut_ap)
    io.open(os.path.join(mut, 'daybook.py'), 'w', encoding='utf-8').write(src)
    io.open(os.path.join(mut, 'daybook.conf'), 'w', encoding='utf-8').write(CONF)
    io.open(os.path.join(mut, '账卷.txt'), 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [测试] [甲] [皮特] 一\n'
        '[2026-11-13 10:01:00] [测试] [乙] [皮特] 二\n')
    _aj_run(mut, 'baseline')
    _aj_run(mut, 'index')
    midf = os.path.join(mut, '索引', 'index_账.tsv')
    mitxt = os.path.join(mut, '索引', 'index_账.txt')
    for f in (midf, mitxt):
        data = io.open(f, 'rb').read()
        io.open(f, 'wb').write(data[:-1])
    io.open(os.path.join(mut, '账卷.txt'), 'a', encoding='utf-8').write(
        '[2026-11-13 10:02:00] [测试] [丙] [皮特] 三\n')
    _aj_run(mut, 'index')
    mrows = _tsv_rows(midf)
    _ok('AJ 变异「增量路径截断」⇒ 判据红（合法末行乙被吃掉）',
        '乙' not in [x[4] for x in mrows],
        'mutant_titles=%s（判据断言 titles==甲/乙/丙 会失败）'
        % [x[4] if len(x) > 4 else '?' for x in mrows])


_AK_CHILD = r'''
import os, sys, threading
sys.path.insert(0, sys.argv[1])
d, mode = sys.argv[2], sys.argv[3]
import safeio
p = os.path.join(d, 'target.tsv')
cp = os.path.join(d, 'daybook.conf')
open(cp, 'w', encoding='utf-8').write('[index]\nroot=\nout_dir=索引\n')
open(p, 'wb').write(b'a\n')
sub = os.path.join(d, 'sub'); os.makedirs(sub, exist_ok=True)
other = os.path.join(d, 'other'); os.makedirs(other, exist_ok=True)


def attempt(root):
    before = open(p, 'rb').read()
    try:
        safeio.append_inplace(p, 'b\n', root, conf_path=cp)
    except RuntimeError:
        return 'RAISED_ZERO' if open(p, 'rb').read() == before else 'RAISED_DIRTY'
    return 'WROTE'


def in_thread(fn):
    out = []
    t = threading.Thread(target=lambda: out.append(fn()))
    t.start(); t.join()
    return out[0]


if mode == 'nolock':
    print(attempt(d))
elif mode == 'ok':
    with safeio.locked(d):
        print(attempt(d))
elif mode == 'subdir':
    with safeio.locked(sub):
        print(attempt(sub))
elif mode == 'shared':
    with safeio.locked(d, shared=True):
        print(attempt(d))
elif mode == 'mismatch':
    with safeio.locked(d):
        print(attempt(other))
elif mode == 'thread_ok':
    with safeio.locked(d):
        print(in_thread(lambda: attempt(d)))
elif mode == 'thread_sub':
    with safeio.locked(sub):
        print(in_thread(lambda: attempt(d)))
'''


def _ak_scenario(src, mode):
    """跑一个锁语义场景，返回 'WROTE' / 'RAISED_ZERO' / 'RAISED_DIRTY' 等。
    Run one lock-semantics scenario and return its verdict token."""
    d = tempfile.mkdtemp(prefix='ak_')
    r = subprocess.run([sys.executable, '-B', '-c', _AK_CHILD, src, d, mode],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    return (r.stdout.strip().splitlines() or ['ERR'])[-1], (r.stderr or '').strip()


def _case_lock_assert(tmp):
    """AK `append_inplace` 锁语义：只认「账本根 + 独占」；无锁/子目录锁/共享锁/别的根都零写。
    AK `append_inplace` lock semantics: only an exclusive hold on the ledger root counts;
    no lock, a sub-directory lock, a shared lock or another root all write nothing."""
    print('  -- AK append_inplace 锁语义（账本根 + 独占·三种绕过全红） --')
    here = os.path.dirname(SRC_BIN)
    safeio_src = io.open(os.path.join(here, 'safeio.py'), encoding='utf-8').read()
    okl = False
    got = _ak_scenario(here, 'ok')[0]
    _ok('AK0 持账本根独占锁 ⇒ 放行（WROTE）', got == 'WROTE', got)
    for mode, label in (('nolock', '无锁'),
                        ('subdir', '持子目录锁、传子目录当根'),
                        ('shared', '持根共享锁'),
                        ('mismatch', '传与 conf 解析不同的根')):
        got, err = _ak_scenario(here, mode)
        _ok('AK[%s] ⇒ 抛错且零写（RAISED_ZERO）' % label, got == 'RAISED_ZERO',
            '%s %s' % (got, err[:120]))
    got = _ak_scenario(here, 'thread_ok')[0]
    _ok('AK[同进程另一线程·主线程持根独占] ⇒ 放行（WROTE）', got == 'WROTE', got)
    got, err = _ak_scenario(here, 'thread_sub')
    _ok('AK[同进程另一线程·主线程只持子目录锁] ⇒ 抛错且零写（RAISED_ZERO）',
        got == 'RAISED_ZERO', '%s %s' % (got, err[:120]))

    # 三条变异：分别去掉「独占」「根一致」「解析根」的约束 ⇒ 对应场景必须放行（判据红）
    mismatch_block = """    if root is not None and os.path.realpath(root) != resolved:
        raise RuntimeError('safeio.append_inplace: 传入的账本根（%s）与 conf 解析结果（%s）不一致'
                           '·拒绝写入（零写）' % (os.path.realpath(root), resolved))"""
    excl_block = "    if not exclusive_held(resolved):"
    assert mismatch_block in safeio_src and excl_block in safeio_src
    muts = (
        ('subdir', '变异①：去掉根一致检查、锁只认传入根',
         safeio_src.replace(mismatch_block, '    pass').replace(
             excl_block, "    if not (_lock_dir(root if root else resolved) in _held_map()):")),
        ('shared', '变异②：共享锁也算',
         safeio_src.replace(excl_block, "    if not (_lock_dir(resolved) in _PROC):")),
        ('mismatch', '变异③：去掉根一致检查',
         safeio_src.replace(mismatch_block, '    pass')),
    )
    for mode, label, text in muts:
        md = os.path.join(tmp, 'ak_mut_' + mode)
        os.makedirs(md)
        io.open(os.path.join(md, 'safeio.py'), 'w', encoding='utf-8').write(text)
        try:
            io.open(os.path.join(md, 'ledger_root.py'), 'w', encoding='utf-8').write(
                io.open(os.path.join(here, 'ledger_root.py'), encoding='utf-8').read())
        except IOError:
            pass
        got, err = _ak_scenario(md, mode)
        _ok('AK %s ⇒ 判据红（场景被放行/走样）' % label,
            got != 'RAISED_ZERO' or 'RAISED_DIRTY' in got,
            '%s %s' % (got, err[:120]))


_AL_PUSH = r'''
import os, sys, threading, time, random, string
sys.path.insert(0, sys.argv[1])
sock_dir, conf, hold = sys.argv[2], sys.argv[3], float(sys.argv[4])
import agent_message as am
am.SOCK_DIR = sock_dir
# 名字带随机后缀；若同名 socket 已存在则换新名——绝不 unlink 别人正在用的 socket
# Random suffix; if the name's socket already exists, pick a new name — never unlink a live socket
for _ in range(20):
    name = '甲' + ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    if not os.path.exists(am.sock_path(name)):
        break
print('NAME', name, flush=True)
srv = am.AgentServer(name, root=conf)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
print('READY', flush=True)
time.sleep(hold)
srv.shutdown()
srv.server_close()
'''


def _al_start(d, conf, hold=20):
    """起一个在线 AgentServer（socket 落在本轮临时目录、名字随机），返回 (Popen, name)。
    Start an online AgentServer (socket inside this run's temp dir, random name) → (Popen, name)."""
    # 每轮独立的短路径 socket 目录（sockaddr_un 上限 104 字节），绝不与别人的同名 socket 相撞
    # A short per-run socket dir (sockaddr_un caps at 104 bytes); never collides with a live socket
    sock_dir = tempfile.mkdtemp(prefix='dbks')
    env = dict(os.environ, DAYBOOK_SOCK_DIR=sock_dir)
    srv = subprocess.Popen([sys.executable, '-B', '-c', _AL_PUSH, d, sock_dir, conf, str(hold)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, env=env)
    name = None
    for _ in range(2):
        line = srv.stdout.readline().strip()
        if line.startswith('NAME '):
            name = line.split(' ', 1)[1]
    return srv, name, sock_dir


def _al_push(d, conf, name, sock_dir=None, timeout=None, wait=True):
    args = [sys.executable, '-B', os.path.join(d, 'orchestrator.py'),
            '--home=' + conf, 'digest', '--limit', '0', '--push', name]
    env = dict(os.environ, DAYBOOK_SOCK_DIR=sock_dir or tempfile.gettempdir())
    if not wait:
        return subprocess.Popen(args, cwd=tempfile.gettempdir(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True,
                                env=env), None
    try:
        r = subprocess.run(args, cwd=tempfile.gettempdir(), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout,
                           env=env)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, 'TIMEOUT'


def _case_push_load_bearing(tmp):
    """AL digest --push 承重：在线场景下 inbox 卷真的新增一行（内容可辨认），且写入要拿账本根锁。
    AL `digest --push` must be load-bearing: with an online peer the inbox volume really gains
    an identifiable line, and the write takes the ledger-root lock."""
    print('  -- AL digest --push 承重（inbox 真写·内容可辨认·锁落账本根） --')
    here = os.path.dirname(SRC_BIN)
    if not os.path.exists(os.path.join(here, 'orchestrator.py')):
        print('    [跳过] AL：当前盒无 orchestrator.py')
        return
    d = os.path.join(tmp, 'al')
    os.makedirs(d)
    for name in _MATRIX_COPY:
        src = os.path.join(here, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(d, name))
    conf = os.path.join(d, 'conf')
    led = os.path.join(d, 'led')
    os.makedirs(conf)
    os.makedirs(led)
    io.open(os.path.join(conf, 'daybook.conf'), 'w', encoding='utf-8').write(
        '[volumes]\n账=账卷.txt\n消息=消息卷.txt\n\n[index]\nroot=%s\nout_dir=索引\n' % led)
    io.open(os.path.join(led, '账卷.txt'), 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
    inbox = os.path.join(led, '消息卷.txt')

    def lines():
        return io.open(inbox, encoding='utf-8').read().splitlines() if os.path.exists(inbox) else []

    # 1) 正常推送：rc=0，inbox 新增一行，且这行带时间戳与本次随机目标名（可辨认）
    srv, name, sock = _al_start(d, conf)
    if not name:
        _ok('AL0 在线 AgentServer 启动（拿到随机 agent 名）', False, '未读到 NAME')
        srv.communicate(timeout=10)
        return
    try:
        b0 = len(lines())
        rc, out = _al_push(d, conf, name, sock, timeout=60)
        after = lines()
        _ok('AL1 在线推送 rc=0', rc == 0, 'rc=%s %s' % (rc, out[-160:]))
        _ok('AL2 inbox 卷（账本根内）真的新增一行（%d→%d）' % (b0, len(after)),
            len(after) > b0 and os.path.commonpath(
                [os.path.realpath(inbox), os.path.realpath(led)]) == os.path.realpath(led),
            'before=%d after=%d' % (b0, len(after)))
        fresh = after[b0:]
        block = '\n'.join(fresh)
        good = bool(fresh) and bool(re.search(r'\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\]', block)) \
            and name in block
        _ok('AL3 新增行可辨认（含时间戳与本次目标名 %s）' % name, good,
            block[:160] if block else '（无新增行）')
        _ok('AL4 推送不回退「未找到 daybook.conf」', '未找到 daybook.conf' not in out, out[-120:])
    finally:
        srv.communicate(timeout=30)

    # 2) 持账本根锁：推送必须表现为明确的阻塞（进程仍在跑、inbox 不增），释放后才完成
    sys.path.insert(0, here)
    import safeio
    srv2, name2, sock2 = _al_start(d, conf)
    try:
        b1 = len(lines())
        with safeio.locked(led):
            proc, _ = _al_push(d, conf, name2, sock2, wait=False)
            time.sleep(1.5)
            blocked = proc.poll() is None
            mid = len(lines())
            _ok('AL5 持账本根锁时推送被明确阻塞（进程未退出·inbox 不增）',
                blocked and mid == b1, 'running=%s inbox=%d→%d' % (blocked, b1, mid))
        try:
            out2, err2 = proc.communicate(timeout=60)
            rc2 = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            rc2, out2 = None, ''
        _ok('AL6 释放后推送完成 rc=0 且 inbox 新增一行',
            rc2 == 0 and len(lines()) > b1, 'rc=%s inbox=%d→%d' % (rc2, b1, len(lines())))
    finally:
        srv2.communicate(timeout=30)

    # 3) 变异：推送被短路（不调用 send）⇒ AL2/AL3 必须红
    mut = os.path.join(tmp, 'al_mut')
    shutil.copytree(d, mut)
    ap = os.path.join(mut, 'orchestrator.py')
    src = io.open(ap, encoding='utf-8').read()
    old = "                ok, info = _am.send('司南', t, 'notify', summary, root=self.conf_dir)"
    _ok('AL 变异前置：找到推送调用', old in src)
    io.open(ap, 'w', encoding='utf-8').write(src.replace(old, "                ok, info = False, 'mutant'"))
    mconf = os.path.join(mut, 'conf')
    mled = os.path.join(mut, 'led')
    minbox = os.path.join(mled, '消息卷.txt')
    srv3, name3, sock3 = _al_start(mut, mconf)
    try:
        mb = len(io.open(minbox, encoding='utf-8').read().splitlines()) \
            if os.path.exists(minbox) else 0
        _al_push(mut, mconf, name3, sock3, timeout=60)
        ma = len(io.open(minbox, encoding='utf-8').read().splitlines()) \
            if os.path.exists(minbox) else 0
        _ok('AL 变异「推送被短路」⇒ 判据红（inbox 未新增）', ma == mb,
            'mutant before=%d after=%d（AL2/AL3 会失败）' % (mb, ma))
    finally:
        srv3.communicate(timeout=30)


def _stage(d):
    """把被测件拷进隔离目录（含 ledger_root：根解析已三处同源）。
    Stage the artifacts under test (including ledger_root: one shared root resolver)."""
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py'):
        shutil.copy2(os.path.join(os.path.dirname(SRC_BIN), name), os.path.join(d, name))


def _tsv_rows(idf):
    """读索引数据行（cols 列表，丢掉表头与空行）。Read index rows (drop header/blank)."""
    rows = []
    for line in io.open(idf, encoding='utf-8').read().splitlines()[1:]:
        if line.strip():
            rows.append(line.split('\t'))
    return rows


def _case_no_newline_tail(tmp):
    """AA 卷末无换行（三种形态）：追加后增量条数 == 全量重建条数，行号无幻影。
    AA volume ending without a newline (three shapes): after appending, the incremental row
    count must equal a full rebuild's, with no phantom line numbers."""
    print('  -- AA 卷末无换行三种形态 --')
    seeds = {
        '有换行': '[2026-11-13 10:00:00] [测试] [甲] [皮特] 一\n'
                  '[2026-11-13 10:01:00] [测试] [乙] [皮特] 二\n',
        '无换行合法': '[2026-11-13 10:00:00] [测试] [甲] [皮特] 一\n'
                      '[2026-11-13 10:01:00] [测试] [乙] [皮特] 二',   # 合法条目，仅缺末换行
        '半行残渣': '[2026-11-13 10:00:00] [测试] [甲] [皮特] 一\n'
                    '[2026-11-13 10:01:00] [测试] [乙] [皮特] 二\n'
                    '[2026-11-13 10:02:00] [测试',                    # 崩溃残渣（无换行）
    }
    for label, seed in seeds.items():
        inc = os.path.join(tmp, 'aa_' + str(abs(hash(label)) % 9999))
        full = inc + '_full'
        for d in (inc, full):
            os.makedirs(d)
            _stage(d)
            io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8').write(CONF)
            io.open(os.path.join(d, '账卷.txt'), 'w', encoding='utf-8').write(seed)
        subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'], cwd=inc,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        r = subprocess.run([sys.executable, '-B', 'daybook_append.py', '账卷.txt',
                            '测试', '追加条目', '皮特', '新正文'],
                           cwd=inc, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        _ok('AA[%s] 追加 rc=0' % label, r.returncode == 0, (r.stderr or r.stdout)[-160:])
        pad_txt = r.stderr or ''
        if label == '有换行':
            _ok('AA[有换行] 不报「卷末行不完整」（本来就完整）',
                '卷末行不完整' not in pad_txt, pad_txt[-160:])
        else:
            _ok('AA[%s] 补换行时点名残渣行（卷名/行号/缺失字段）' % label,
                '卷末行不完整·已补换行' in pad_txt and '缺字段=' in pad_txt
                and '卷=账卷.txt' in pad_txt, pad_txt[-200:])
        r = subprocess.run([sys.executable, '-B', 'daybook.py', 'index'], cwd=inc,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        _ok('AA[%s] 增量索引 rc=0（非违例）' % label, r.returncode == 0,
            'rc=%d %s' % (r.returncode, (r.stderr or '')[-160:]))
        if label == '半行残渣':
            _ok('AA[半行残渣] 报告单列「卷末行不完整·已补换行」',
                '卷末行不完整·已补换行' in (r.stdout or ''),
                (r.stdout or '')[-200:])
            _ok('AA[半行残渣] 点名缺失字段（类别/标题/作者）',
                all(k in (r.stdout or '') for k in ('类别', '标题', '作者')),
                (r.stdout or '')[-200:])
        shutil.copy2(os.path.join(inc, '账卷.txt'), os.path.join(full, '账卷.txt'))
        subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'], cwd=full,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ri = _tsv_rows(os.path.join(inc, '索引', 'index_账.tsv'))
        rf = _tsv_rows(os.path.join(full, '索引', 'index_账.tsv'))
        _ok('AA[%s] 增量条数 == 全量重建条数（%d/%d）' % (label, len(ri), len(rf)),
            len(ri) == len(rf), 'incremental=%d full=%d' % (len(ri), len(rf)))
        _ok('AA[%s] 行号逐个一致（无幻影）' % label,
            [r[1] for r in ri] == [r[1] for r in rf],
            'inc=%s full=%s' % ([r[1] for r in ri], [r[1] for r in rf]))
        _ok('AA[%s] 追加条目独立成行（标题=追加条目，未粘在旧行尾）' % label,
            any(len(r) > 4 and r[4] == '追加条目' for r in ri),
            'titles=%s' % [r[4] if len(r) > 4 else '?' for r in ri])
        lines_in_vol = io.open(os.path.join(inc, '账卷.txt'), encoding='utf-8').read().count('\n') + 1
        _ok('AA[%s] 行号不超过卷内实际行数' % label,
            all(int(r[1]) <= lines_in_vol for r in ri),
            'max=%s lines=%d' % (max(int(r[1]) for r in ri) if ri else 0, lines_in_vol))


def _case_cli_root(tmp):
    """AB 根解析：conf 根 ≠ 脚本目录、从账本外调用 CLI —— 锁必须落在账本根，
    并发长条目 8/8 全存活。锁若按脚本目录/VOL 目录分裂，这里必红。
    AB root resolution: conf root ≠ script dir, CLI invoked from outside the ledger — the lock
    must land on the ledger root, and 8 concurrent long entries must all survive."""
    print('  -- AB CLI 账本根（conf 根 ≠ 脚本目录） --')
    led = os.path.join(tmp, 'ab_ledger')
    tool = os.path.join(led, '工具')
    os.makedirs(tool)
    _stage(tool)
    # conf 在工具/ 下，[index] root=.. ⇒ 账本根是 led（≠ 脚本目录 tool）
    io.open(os.path.join(tool, 'daybook.conf'), 'w', encoding='utf-8').write(
        '[volumes]\n子=子/子卷.txt\n\n[index]\nroot=..\nout_dir=索引\n')
    os.makedirs(os.path.join(led, '子'))
    volp = os.path.join(led, '子', '子卷.txt')
    io.open(volp, 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [测试] [起始] [皮特] 正文\n')
    cli = [sys.executable, '-B', os.path.join(tool, 'daybook_append.py'), volp,
           '测试', '长条目', '皮特', '长' * 3000]
    env = dict(os.environ)
    env.pop('DAYBOOK_HOME', None)
    env['DAYBOOK_ROOT'] = tool             # 显式指定 conf 目录（账本根仍由 [index] root 决定）
    holder = subprocess.Popen(
        [sys.executable, '-B', '-c', _CHILD_HOLD_AB, tool, led],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    held = os.path.join(led, 'held.flag')
    for _ in range(200):
        if os.path.exists(held):
            break
        time.sleep(0.02)
    if os.path.exists(held):
        t0 = time.time()
        app = subprocess.Popen(cli, cwd=tempfile.gettempdir(), env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)
        time.sleep(0.6)
        still = app.poll() is None
        io.open(os.path.join(led, 'release.flag'), 'w').write('1')
        out, err = app.communicate()
        elapsed = time.time() - t0
        holder.communicate()
        _ok('AB1 从账本外调用 CLI 被账本根锁挡住（未提前进临界区）',
            still and elapsed >= 0.5, 'still=%s elapsed=%.2fs' % (still, elapsed))
        _ok('AB1b CLI rc=0', app.returncode == 0, 'rc=%s %s' % (app.returncode, err[-120:]))
    else:
        holder.kill()
        _ok('AB1 持锁进程进入临界区', False, 'held.flag 未出现')
    try:
        os.remove(os.path.join(led, 'release.flag'))
    except OSError:
        pass
    # 一半 DAYBOOK_ROOT、一半 DAYBOOK_HOME：两条显式通道必须落到同一个 inode
    # Half via DAYBOOK_ROOT, half via DAYBOOK_HOME: both explicit channels must land on one inode.
    env_b = dict(env)
    env_b.pop('DAYBOOK_ROOT', None)
    env_b['DAYBOOK_HOME'] = tool
    procs = [subprocess.Popen(cli, cwd=tempfile.gettempdir(),
                              env=(env if i % 2 == 0 else env_b),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True) for i in range(8)]
    rcs = [p.wait() for p in procs]
    _ok('AB2 8 进程并发长条目全 rc=0（同根不分裂锁）', all(rc == 0 for rc in rcs), 'rcs=%s' % rcs)
    entries = io.open(volp, encoding='utf-8').read().count('[测试] [长条目]')
    _ok('AB3 并发 8 条长条目全存活（无丢更新）', entries == 9,
        'entries=%d（1 条持锁测试 + 8 条并发）' % entries)
    _ok('AB4 账本根锁件不落账本（无 .lock）',
        not [n for n in os.listdir(led) if n.endswith('.lock')], '')
    _ok('AB5 账本根解析与 daybook 同源（tools 有 ledger_root.py）',
        os.path.isfile(os.path.join(tool, 'ledger_root.py')), '')


def _case_cache_hash(tmp):
    """AC 作者缓存绑定内容哈希：等长改写后喂旧缓存必须红（不许按 size 复用）。
    AC The author cache is bound to the content hash: an old cache fed in after an
    equal-length rewrite must go red (a size-only hit is not allowed)."""
    print('  -- AC 作者缓存绑定内容哈希 --')
    d = os.path.join(tmp, 'ac')
    os.makedirs(d)
    _stage(d)
    io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8').write(CONF)
    vp = os.path.join(d, '账卷.txt')
    seed = '[2026-11-13 10:00:00] [测试] [甲] [皮特] ' + 'x' * 40 + '\n'
    io.open(vp, 'w', encoding='utf-8').write(seed)
    subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'], cwd=d,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stamp = json.load(io.open(os.path.join(d, '索引', '.head_stamp.json'), encoding='utf-8'))
    old_cache = stamp.get('author_scan') or {}
    old_hash = (old_cache.get('账') or {}).get('hash')
    r = subprocess.run([sys.executable, '-B', '-c', _CHILD_CACHE_CHECK, d,
                        json.dumps(old_cache)], cwd=d, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
    _ok('AC0 未改写时旧缓存（有已验哈希）判绿', r.stdout.strip() == 'GREEN',
        (r.stdout.strip() or r.stderr.strip())[-160:])
    # 等长改写：作者位换成合法的机器 id（20 字符），并从正文尾部删掉同样多的字节
    raw = io.open(vp, encoding='utf-8').read()
    new = raw.replace('[皮特]', '[ag-0123456789abcdef]')
    delta = len(new.encode('utf-8')) - len(raw.encode('utf-8'))
    assert delta > 0
    new = new.replace('x' * delta, '', 1)          # 从正文尾部抵消长度差（保持字节数不变）
    io.open(vp, 'w', encoding='utf-8').write(new)
    _ok('AC1 等长改写后字节数不变',
        len(io.open(vp, 'rb').read()) == len(raw.encode('utf-8')), '')
    r = subprocess.run([sys.executable, '-B', '-c', _CHILD_CACHE_CHECK, d,
                        json.dumps(old_cache)], cwd=d, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
    _ok('AC2 旧缓存（哈希不符）必须判红', r.stdout.strip() == 'RED',
        (r.stdout.strip() or r.stderr.strip())[-160:])


def _case_msg_consistency(tmp):
    """AD rc=3 时文案不得说「已写回」：违例/证据缺失是零落盘，作者红只能报「未写回」。
    AD with rc=3 the text must not claim a write-back: violation / lost evidence writes nothing,
    so an author-convention red can only be reported as "not written"."""
    print('  -- AD 违例态文案（已写回 vs 未写回） --')
    d = os.path.join(tmp, 'ad')
    os.makedirs(d)
    _stage(d)
    io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8').write(CONF)
    vp = os.path.join(d, '账卷.txt')
    io.open(vp, 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [测试] [甲] [ag-0123456789abcdef] ' + 'x' * 6000 + '\n'
        + '[2026-11-13 10:01:00] [测试] [乙] [ag-0123456789abcdef] ' + 'x' * 6000 + '\n')
    r = subprocess.run([sys.executable, '-B', 'daybook.py', 'baseline'], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    _ok('AD0 作者红认基线 ⇒ rc=0 且照认照写', r.returncode == 0, 'rc=%d' % r.returncode)
    _tamper_mid(vp, 0.5)
    r = _run(d)
    txt = r.stdout + r.stderr
    _ok('AD1 违例 + 作者红 ⇒ rc=3', r.returncode == 3, 'rc=%d' % r.returncode)
    _ok('AD2 文案明确「未写回」', '未写回' in txt, txt[-160:])
    _ok('AD3 不得谎称「已写回」', '已写回' not in txt, txt[-160:])


_CHILD_ROOT = r'''
import sys
sys.path.insert(0, sys.argv[1])
kind = sys.argv[2]
if kind == 'daybook':
    import daybook
    print(daybook.ledger_home())
elif kind == 'cli':
    import daybook_append as da
    da.HERE = sys.argv[1]
    print(da._cli_root())
elif kind == 'hook':
    import daybook_hook as dh
    dh.HERE = sys.argv[1]
    print(dh.ledger_home())
elif kind == 'mcp':
    import mcp_resources as mr
    mr.HERE = sys.argv[1]
    print(mr._root())
elif kind == 'orch':
    import volume_paths as vp
    vp.HERE = sys.argv[1]
    print(vp.resolve_root())
'''


def _case_five_roots(tmp):
    """AE 五个入口同源：同一 DAYBOOK_ROOT + conf 绝对 root ⇒ 五处落同目录；
    持账本根锁时 index / CLI / hook 三个写入口都被挡（并给出落点与耗时）。
    AE one resolver for five entries: same DAYBOOK_ROOT + absolute conf root ⇒ all five land
    on one directory; with the ledger root held, the index / CLI / hook write entries all block
    (lock point and elapsed shown for each)."""
    print('  -- AE 五个入口同源（锁落点 + 互斥耗时） --')
    base = os.path.join(tmp, 'ae')
    confd = os.path.join(base, 'conf')
    led = os.path.join(base, 'daybook')
    os.makedirs(confd)
    os.makedirs(led)
    # 只拷本包真实存在的件：盒内 daybook 包不含 MCP/司南件，那两项跳过而不是报错。
    # Copy only what this package really ships: the daybook box has no MCP/orch modules,
    # so those entries are skipped instead of erroring.
    present = []
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py',
                 'daybook_hook.py', 'mcp_resources.py', 'mcp_transport.py',
                 'volume_paths.py'):
        src = os.path.join(os.path.dirname(SRC_BIN), name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(confd, name))
            present.append(name)
    kinds = ['daybook', 'cli', 'hook']
    if 'mcp_resources.py' in present:
        kinds.append('mcp')
    if 'volume_paths.py' in present:
        kinds.append('orch')
    missing = sorted({'daybook', 'cli', 'hook', 'mcp', 'orch'}.difference(kinds))
    if missing:
        print('    [跳过] 本包缺 %s，AE 只测 %d 个入口' % ('、'.join(missing), len(kinds)))
    # 源树必须硬断言五个入口全部在场：否则源里真少一件时只会静默少测、依旧全绿，
    # 而 pack.py --verify 在「盒也少」时同样抓不到。
    # The source tree must assert all five entries are present: otherwise a real missing file
    # would silently shrink the suite and stay green, and pack.py --verify cannot catch it either
    # when the box is missing the same file.
    src_dir = os.path.dirname(os.path.abspath(SRC_BIN))
    if os.path.exists(os.path.join(src_dir, 'pack.py')):
        _ok('AE 源树五入口件齐全（skip 为空）', len(kinds) == 5 and not missing,
            'missing=%s' % missing)
    io.open(os.path.join(confd, 'daybook.conf'), 'w', encoding='utf-8').write(
        '[volumes]\n账=账卷.txt\n对话=对话卷.txt\n\n[index]\nroot=%s\nout_dir=索引\n' % led)
    io.open(os.path.join(led, '账卷.txt'), 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
    # 对话卷条目必须登记原件路径（HOOK-A 扫的是原件内容，不是登记行本身）
    # The dialog entry must register an original-file path (HOOK-A scans the original's
    # content, not the registry line itself).
    os.makedirs(os.path.join(led, '对话原件'))
    io.open(os.path.join(led, '对话原件', 'd1.txt'), 'w', encoding='utf-8').write(
        '讨论一下 决定 这件事\n')
    io.open(os.path.join(led, '对话卷.txt'), 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [聊] [甲] [皮特] 对话原件/d1.txt\nSHA256: deadbeef\n')
    io.open(os.path.join(confd, 'hook_a_关键词.txt'), 'w', encoding='utf-8').write(
        '[账] [追更] 决定\n')
    env = dict(os.environ)
    env.pop('DAYBOOK_HOME', None)
    env['DAYBOOK_ROOT'] = confd                 # 只用来找 conf
    subprocess.run([sys.executable, '-B', os.path.join(confd, 'daybook.py'), 'baseline'],
                   cwd=led, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    want = os.path.realpath(led)
    got = {}
    for kind in kinds:
        r = subprocess.run([sys.executable, '-B', '-c', _CHILD_ROOT, confd, kind],
                           cwd=led, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        got[kind] = (r.stdout.strip().splitlines() or [''])[-1]
        _ok('AE1 %s 根 = conf [index] root（%s）' % (kind, got[kind]),
            got[kind] == want, 'want=%s' % want)
    # 持锁：index / CLI / hook 都必须等（每个入口单独起一次持锁进程）
    ents = {
        'index': ([sys.executable, '-B', os.path.join(confd, 'daybook.py'), 'index'], led),
        'cli': ([sys.executable, '-B', os.path.join(confd, 'daybook_append.py'),
                 os.path.join(led, '账卷.txt'), '测试', '长条目', '皮特', '长' * 3000],
                tempfile.gettempdir()),
        'hook': ([sys.executable, '-B', os.path.join(confd, 'daybook_hook.py'),
                  os.path.join(led, '对话卷.txt'),
                  os.path.join(confd, 'hook_a_关键词.txt')], led),
    }
    if os.path.exists(os.path.join(confd, 'agent_message.py')):
        ents['inbox'] = ([sys.executable, '-B', '-c', _CHILD_INBOX, confd, confd], led)
    for name, (cmd, cwd) in ents.items():
        for f in ('release.flag', 'held.flag'):
            try:
                os.remove(os.path.join(led, f))
            except OSError:
                pass
        holder = subprocess.Popen([sys.executable, '-B', '-c', _CHILD_HOLD_AB, confd, led],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True)
        held = os.path.join(led, 'held.flag')
        for _ in range(200):
            if os.path.exists(held):
                break
            time.sleep(0.02)
        if not os.path.exists(held):
            holder.kill()
            _ok('AE2 %s 持锁进程进入临界区' % name, False, 'held.flag 未出现')
            continue
        t0 = time.time()
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        time.sleep(0.6)
        still = p.poll() is None
        io.open(os.path.join(led, 'release.flag'), 'w').write('1')
        out, err = p.communicate()
        elapsed = time.time() - t0
        holder.communicate()
        _ok('AE2 %s 被账本根锁挡住（rc=%s）' % (name, p.returncode),
            still and p.returncode == 0, 'still=%s elapsed=%.2fs %s'
            % (still, elapsed, (err or '')[-100:]))
        print('    [数据] AE 锁落点 %s=%s 耗时=%.2fs'
              % (name, got.get(name, got.get('daybook')), elapsed))
    print('    [数据] AE 锁落点：' + ' '.join('%s=%s' % (k, got[k]) for k in kinds))


_MATRIX_COPY = ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py',
                'daybook_hook.py', 'mcp_resources.py', 'mcp_transport.py', 'mcp_server.py',
                'mcp_tools.py', 'mcp_prompts.py', 'mcp_subscribe.py',
                'volume_paths.py', 'orchestrator.py', 'agent_registry.py', 'cross_ref.py',
                'task_volume.py', 'agent_lock.py', 'agent_heartbeat.py', 'agent_message.py',
                'daybook_multidx.py')


def _matrix_cmds(exedir, ledger, kinds):
    """矩阵用的真实入口命令（失败格要真的 rc=2，不能拿 traceback 充数）。
    Real entry commands for the matrix (a failing cell must really exit 2, not traceback)."""
    py = sys.executable
    want = {
        'daybook': [py, '-B', os.path.join(exedir, 'daybook.py'), 'index'],
        'cli': [py, '-B', os.path.join(exedir, 'daybook_append.py'),
                os.path.join(ledger, '账卷.txt'), '测试', '条目', '皮特', '正文'],
        'hook': [py, '-B', os.path.join(exedir, 'daybook_hook.py')],
        'mcp': [py, '-B', os.path.join(exedir, 'mcp_server.py')],
        'orch': [py, '-B', os.path.join(exedir, 'orchestrator.py'), 'alarm'],
    }
    return {k: want[k] for k in kinds}


def _matrix_lock(label, code, ledger, env, cwd, confd):
    """持账本根锁，写入口（含 inbox）必须都被挡住（每格实测，锁落点与耗时逐个打印）。
    Hold the ledger root and require every write entry (inbox included) to block (measured per
    cell; lock point and elapsed printed for each)."""
    cmds = _matrix_cmds(code, ledger, ('daybook', 'cli', 'hook'))
    names = ['daybook', 'cli', 'hook']
    if os.path.exists(os.path.join(code, 'agent_message.py')):
        cmds['inbox'] = [sys.executable, '-B', '-c', _CHILD_INBOX, code, confd]
        names.append('inbox')
    for name in names:
        for f in ('release.flag', 'held.flag'):
            try:
                os.remove(os.path.join(ledger, f))
            except OSError:
                pass
        holder = subprocess.Popen([sys.executable, '-B', '-c', _CHILD_HOLD_AB, code, ledger],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True)
        held = os.path.join(ledger, 'held.flag')
        for _ in range(200):
            if os.path.exists(held):
                break
            time.sleep(0.02)
        if not os.path.exists(held):
            holder.kill()
            holder.communicate()
            _ok('%s 持锁进程进入临界区（%s）' % (label, name), False, 'held.flag 未出现')
            continue
        t0 = time.time()
        p = subprocess.Popen(cmds[name], cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        time.sleep(0.35)
        still = p.poll() is None
        io.open(os.path.join(ledger, 'release.flag'), 'w').write('1')
        _o, err = p.communicate()
        elapsed = time.time() - t0
        holder.communicate()
        _ok('%s %s 被账本根锁挡住' % (label, name), still,
            'still=%s elapsed=%.2fs %s' % (still, elapsed, (err or '')[-100:]))
        print('    [数据] %s 锁落点 %s=%s 耗时=%.2fs'
              % (label, name, os.path.realpath(ledger), elapsed))


def _case_root_matrix(tmp):
    """AF 根解析矩阵：env（未设／指向 conf／指向无 conf）× conf root（空／相对／绝对）×
    启动方式（账本内／账本外／装好的入口）。成功格五入口同根且争同一把锁；失败格五入口
    全部 rc=2 且文案逐字一致。
    AF root matrix: env (unset / conf dir / no-conf dir) x conf root (empty / relative /
    absolute) x launch (inside the ledger / outside / installed entry). Working cells: all
    entries land on one root and contend on one lock. Failing cells: all exit 2 with one
    identical message."""
    print('  -- AF 根解析矩阵（env × conf root × 启动方式） --')
    py = sys.executable
    base = os.path.join(tmp, 'af')
    os.makedirs(base)
    code = os.path.join(base, 'code')
    os.makedirs(code)
    present = []
    for name in _MATRIX_COPY:
        sp = os.path.join(os.path.dirname(SRC_BIN), name)
        if os.path.exists(sp):
            shutil.copy2(sp, os.path.join(code, name))
            present.append(name)
    kinds = ['daybook', 'cli', 'hook']
    if 'mcp_resources.py' in present and 'mcp_server.py' in present:
        kinds.append('mcp')
    if 'volume_paths.py' in present and 'orchestrator.py' in present:
        kinds.append('orch')
    missing = sorted(set(('daybook', 'cli', 'hook', 'mcp', 'orch')) - set(kinds))
    print('    [跳过] %s；固定测 %d 个入口' % ('、'.join(missing) or '无', len(kinds)))
    inst = os.path.join(base, 'inst')
    os.makedirs(inst)
    for name in present:
        os.symlink(os.path.join(code, name), os.path.join(inst, name))
    other = os.path.join(base, 'elsewhere')
    os.makedirs(other)
    nc = os.path.join(base, 'noconf')
    os.makedirs(nc)
    ncell = n_ok = n_fail = 0
    for env_state in ('unset', 'conf', 'noconf'):
        for root_mode in ('empty', 'relative', 'absolute'):
            for start in ('inside', 'outside', 'installed'):
                ncell += 1
                cell = os.path.join(base, 'cell%02d' % ncell)
                confd = os.path.join(cell, 'conf')
                os.makedirs(confd)
                if root_mode == 'empty':
                    root_val, ledger = '', confd
                elif root_mode == 'relative':
                    root_val, ledger = 'ledger', os.path.join(confd, 'ledger')
                else:
                    root_val = os.path.join(cell, 'abs')
                    ledger = root_val
                os.makedirs(ledger, exist_ok=True)
                io.open(os.path.join(confd, 'daybook.conf'), 'w', encoding='utf-8').write(
                    '[volumes]\n账=账卷.txt\n对话=对话卷.txt\n\n[index]\nroot=%s\nout_dir=索引\n'
                    % root_val)
                io.open(os.path.join(ledger, '账卷.txt'), 'w', encoding='utf-8').write(
                    '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
                os.makedirs(os.path.join(ledger, '对话原件'), exist_ok=True)
                io.open(os.path.join(ledger, '对话原件', 'd1.txt'), 'w',
                        encoding='utf-8').write('讨论一下 决定 这件事\n')
                io.open(os.path.join(ledger, '对话卷.txt'), 'w', encoding='utf-8').write(
                    '[2026-11-13 10:00:00] [聊] [甲] [皮特] 对话原件/d1.txt\nSHA256: deadbeef\n')
                io.open(os.path.join(confd, 'hook_a_关键词.txt'), 'w',
                        encoding='utf-8').write('[账] [追更] 决定\n')
                # 无参 hook 从账本根取关键词表（root 可与 conf 目录不同）
                io.open(os.path.join(ledger, 'hook_a_关键词.txt'), 'w',
                        encoding='utf-8').write('[账] [追更] 决定\n')
                env = dict(os.environ)
                env.pop('DAYBOOK_ROOT', None)
                env.pop('DAYBOOK_HOME', None)
                if env_state == 'conf':
                    env['DAYBOOK_ROOT'] = confd
                elif env_state == 'noconf':
                    env['DAYBOOK_ROOT'] = nc
                cwd = ledger if start == 'inside' else other
                exedir = inst if start == 'installed' else code
                label = 'AF(%s/%s/%s)' % (env_state, root_mode, start)
                expect_ok = (env_state == 'conf') or (
                    env_state == 'unset' and start == 'inside' and root_mode == 'empty')
                if expect_ok:
                    n_ok += 1
                    want = os.path.realpath(ledger)
                    got = {}
                    for kind in kinds:
                        r = subprocess.run([sys.executable, '-B', '-c', _CHILD_ROOT,
                                            exedir, kind], cwd=cwd, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           universal_newlines=True)
                        got[kind] = (r.stdout.strip().splitlines() or [''])[-1]
                    _ok('%s 五入口同根' % label,
                        all(v == want for v in got.values()),
                        ' | '.join('%s=%s' % (k, got[k]) for k in kinds))
                    print('    [数据] %s 根: %s' % (label, ' '.join(
                        '%s=%s' % (k, got[k]) for k in kinds)))
                    _matrix_lock(label, code, ledger, env, cwd, confd)
                    # [index] root 非空（相对/绝对）时，orch 的三条主路径必须 rc=0：
                    # 二次解析会把账本根当 conf 目录，卷表变空、全部 rc=2。
                    # With a non-empty [index] root, three orch entry paths must exit 0; a
                    # second resolution would treat the ledger root as the conf dir, leaving
                    # the volume table empty and failing.
                    if os.path.exists(os.path.join(exedir, 'orchestrator.py')):
                        orch = os.path.join(exedir, 'orchestrator.py')
                        for sub, needle in (('alarm', ''),
                                            ('digest --limit 0', '部.账'),
                                            ('digest --limit 0 --push 甲', '')):
                            r = subprocess.run([py, '-B', orch] + sub.split(), cwd=cwd,
                                               env=env, stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               universal_newlines=True)
                            blob = (r.stdout or '') + (r.stderr or '')
                            _ok('%s orch %s rc=0' % (label, sub), r.returncode == 0,
                                'rc=%d %s' % (r.returncode, (r.stderr or '')[-80:]))
                            if needle:
                                _ok('%s orch %s 读到卷表（%s）' % (label, sub, needle),
                                    needle in (r.stdout or ''), (r.stdout or '')[-100:])
                            if '--push' in sub:
                                _ok('%s orch %s 未把账本根当 conf（无「未找到」）' % (label, sub),
                                    '未找到 daybook.conf' not in blob, blob[-120:])
                else:
                    n_fail += 1
                    rcs, msgs = {}, {}
                    for kind, cmd in _matrix_cmds(exedir, ledger, kinds).items():
                        r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, universal_newlines=True)
                        rcs[kind] = r.returncode
                        found = [ln.strip() for ln in (r.stderr or '').splitlines()
                                 if '未找到 daybook.conf' in ln]
                        msgs[kind] = found[0] if found else ''
                    _ok('%s 五入口 rc=2' % label, all(v == 2 for v in rcs.values()),
                        'rcs=%s' % rcs)
                    uniq = set(msgs.values())
                    _ok('%s 文案逐字一致' % label,
                        all(msgs.values()) and len(uniq) == 1,
                        ' | '.join('%s=%s' % (k, msgs[k][:70]) for k in kinds))
                    if msgs:
                        print('    [数据] %s 文案: %s' % (label, list(uniq)[0]))
    print('    [数据] AF 实跑：成功 %d 格 / 失败 %d 格（共 %d 格，计数取自判据自身）'
          % (n_ok, n_fail, ncell))


_HOME_STATIC = (('daybook.py', 'take_home('), ('daybook_append.py', 'take_home('),
                ('daybook_hook.py', 'take_home('), ('mcp_server.py', 'take_home('),
                ('orchestrator.py', "'--home'"))


def _case_home_flag(tmp):
    """AI 统一旗标 --home：六个入口都认，且只用来定位 conf（env 清空、cwd 在账本外）。
    AI the unified --home flag: all six entries accept it and use it only to locate conf
    (env cleared, cwd outside the ledger)."""
    print('  -- AI --home 统一旗标（六入口） --')
    d = os.path.dirname(os.path.abspath(SRC_BIN))
    base = os.path.join(tmp, 'ai')
    confd = os.path.join(base, 'conf')
    outside = os.path.join(base, 'outside')
    os.makedirs(confd)
    os.makedirs(outside)
    io.open(os.path.join(confd, 'daybook.conf'), 'w', encoding='utf-8').write(
        '[volumes]\n账=账卷.txt\n对话=对话卷.txt\n[index]\nroot=\n')
    io.open(os.path.join(confd, '账卷.txt'), 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
    os.makedirs(os.path.join(confd, '对话原件'))
    io.open(os.path.join(confd, '对话原件', 'd1.txt'), 'w', encoding='utf-8').write(
        '讨论一下 决定 这件事\n')
    io.open(os.path.join(confd, '对话卷.txt'), 'w', encoding='utf-8').write(
        '[2026-11-13 10:00:00] [聊] [甲] [皮特] 对话原件/d1.txt\n')
    kw = os.path.join(confd, 'hook_a_关键词.txt')
    io.open(kw, 'w', encoding='utf-8').write('[账] [追更] 决定\n')
    env = dict(os.environ)
    env.pop('DAYBOOK_ROOT', None)
    env.pop('DAYBOOK_HOME', None)
    py = sys.executable

    def run(cmd, **kw):
        return subprocess.run(cmd, cwd=outside, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, **kw)

    r = run([py, '-B', os.path.join(d, 'daybook.py'), '--home=' + confd, 'baseline'])
    _ok('AI daybook 认 --home=DIR（baseline rc=0）', r.returncode == 0,
        'rc=%d %s' % (r.returncode, (r.stderr or '')[-100:]))
    r = run([py, '-B', os.path.join(d, 'daybook.py'), '--home', confd, 'index'])
    _ok('AI daybook 认 --home DIR（index rc=0）', r.returncode == 0, 'rc=%d' % r.returncode)
    r = run([py, '-B', os.path.join(d, 'daybook_append.py'), '--home=' + confd,
             os.path.join(confd, '账卷.txt'), '测试', '旗标', '皮特', '正文'])
    _ok('AI append 认 --home（rc=0 且落条）',
        r.returncode == 0 and '旗标' in io.open(os.path.join(confd, '账卷.txt'),
                                              encoding='utf-8').read(),
        'rc=%d %s' % (r.returncode, (r.stderr or '')[-80:]))
    r = run([py, '-B', os.path.join(d, 'daybook_hook.py'), '--home=' + confd])
    _ok('AI hook 认 --home（rc=0 且追更）',
        r.returncode == 0 and '决定' in io.open(os.path.join(confd, '账卷.txt'),
                                               encoding='utf-8').read(),
        'rc=%d %s' % (r.returncode, (r.stderr or '')[-80:]))
    if os.path.exists(os.path.join(d, 'mcp_server.py')):
        try:
            r = run([py, '-B', os.path.join(d, 'mcp_server.py'), '--home=' + confd],
                    stdin=subprocess.DEVNULL, timeout=15)
            ok = r.returncode == 0 and ('root=%s' % os.path.realpath(confd)) in (r.stderr or '')
            _ok('AI mcp 认 --home（启动自检 root=conf）', ok,
                'rc=%d %s' % (r.returncode, (r.stderr or '')[-80:]))
        except subprocess.TimeoutExpired:
            _ok('AI mcp 认 --home（启动自检 root=conf）', False, '超时未退出')
    if os.path.exists(os.path.join(d, 'orchestrator.py')):
        r = run([py, '-B', os.path.join(d, 'orchestrator.py'), '--home=' + confd, 'alarm'])
        _ok('AI orch 认 --home（alarm rc=0）', r.returncode == 0,
            'rc=%d %s' % (r.returncode, (r.stderr or '')[-80:]))
    for fn, needle in _HOME_STATIC:
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            continue
        _ok('AI %s 静态接受 --home' % fn, needle in io.open(p, encoding='utf-8').read(), needle)
    shim = os.path.join(os.path.dirname(d), 'packaging', 'cli_shim.py')
    if os.path.exists(shim):
        stext = io.open(shim, encoding='utf-8').read()
        _ok('AI cli_shim 接受 --home', '--home' in stext, '')
        _ok('AI cli_shim 的 --home 无值即报错（不静默回落）',
            '需要一个目录参数' in stext, '')
        _ok('AI cli_shim 与产品共用 ENV_VARS 常量',
            'from ledger_root import ENV_VARS' in stext, '')
    # --home 无值 ⇒ 各入口 rc=2（吞掉当没给是禁止的）
    for fn in ('daybook.py', 'daybook_append.py', 'daybook_hook.py', 'mcp_server.py'):
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            continue
        r = run([py, '-B', p, '--home'])
        _ok('AI %s 的 --home 无值 ⇒ rc=2' % fn, r.returncode == 2,
            'rc=%d %s' % (r.returncode, (r.stderr or '')[:80]))
    # --help rc=0 · mcp 未知参数 rc=2
    for fn in ('daybook_append.py', 'daybook_hook.py', 'mcp_server.py'):
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            continue
        r = run([py, '-B', p, '--help'])
        _ok('AI %s --help rc=0' % fn, r.returncode == 0,
            'rc=%d %s' % (r.returncode, (r.stderr or '')[:60]))
    if os.path.exists(os.path.join(d, 'mcp_server.py')):
        r = run([py, '-B', os.path.join(d, 'mcp_server.py'), '--bogus'])
        _ok('AI mcp 未知参数 ⇒ rc=2（不许照常启动）', r.returncode == 2,
            'rc=%d %s' % (r.returncode, (r.stderr or '')[:60]))
    if os.path.exists(os.path.join(d, 'orchestrator.py')):
        # orch 的 --home 只支持放在子命令前（保留），但 help 必须写明位置
        # --home only works before the subcommand (kept), but the help must say where it goes
        r = run([py, '-B', os.path.join(d, 'orchestrator.py'), '--help'])
        _ok('AI orch --help rc=0 且写明 --home 须在子命令前',
            r.returncode == 0 and '子命令之前' in (r.stdout or ''),
            'rc=%d %s' % (r.returncode, (r.stdout or '')[-60:]))
    # 两个环境变量都设 ⇒ HOME 胜（与 shim 同一条线）
    a = os.path.join(base, 'envA')
    b = os.path.join(base, 'envB')
    for dd, led_name in ((a, 'ledA'), (b, 'ledB')):
        os.makedirs(dd)
        io.open(os.path.join(dd, 'daybook.conf'), 'w', encoding='utf-8').write(
            '[index]\nroot=%s\n' % led_name)
        os.makedirs(os.path.join(dd, led_name))
    env2 = dict(env)
    env2['DAYBOOK_HOME'] = a
    env2['DAYBOOK_ROOT'] = b
    got = {}
    for kind in ('daybook', 'cli', 'hook', 'mcp', 'orch'):
        if kind == 'mcp' and not os.path.exists(os.path.join(d, 'mcp_server.py')):
            continue
        if kind == 'orch' and not os.path.exists(os.path.join(d, 'orchestrator.py')):
            continue
        r = subprocess.run([py, '-B', '-c', _CHILD_ROOT, d, kind], cwd=outside,
                           env=env2, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        got[kind] = (r.stdout.strip().splitlines() or [''])[-1]
    want_a = os.path.realpath(os.path.join(a, 'ledA'))
    _ok('AI 两 env 同设 ⇒ 六入口都取 DAYBOOK_HOME', got and all(v == want_a for v in got.values()),
        ' | '.join('%s=%s' % (k, v) for k, v in got.items()))
    # [index] root 相对/绝对两种非空格：orch 三条主路径（体检／卷列表／推送主路径）必须 rc=0。
    # 账本根被当 conf 再解析时，卷表为空、alarm 与 digest 都会 rc≠0。
    # Cells with a non-empty relative/absolute [index] root: three orch paths (alarm, volume
    # list, push main path) must exit 0. Re-parsing the ledger root as conf empties the table.
    if not os.path.exists(os.path.join(d, 'orchestrator.py')):
        return
    for mode in ('relative', 'absolute'):
        cdir = os.path.join(base, 'root_' + mode)
        os.makedirs(cdir)
        if mode == 'relative':
            rval, led = 'ledger', os.path.join(cdir, 'ledger')
        else:
            rval, led = os.path.join(cdir, 'absled'), os.path.join(cdir, 'absled')
        os.makedirs(led)
        io.open(os.path.join(cdir, 'daybook.conf'), 'w', encoding='utf-8').write(
            '[volumes]\n账=账卷.txt\n\n[index]\nroot=%s\nout_dir=索引\n' % rval)
        io.open(os.path.join(led, '账卷.txt'), 'w', encoding='utf-8').write(
            '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
        for sub, needle in (('alarm', ''),
                            ('digest --limit 0', '部.账'),
                            ('digest --limit 0 --push 甲', '')):
            r = run([py, '-B', os.path.join(d, 'orchestrator.py'), '--home=' + cdir] + sub.split())
            blob = (r.stdout or '') + (r.stderr or '')
            _ok('AI root=%s orch %s rc=0' % (mode, sub), r.returncode == 0,
                'rc=%d %s' % (r.returncode, (r.stderr or '')[-80:]))
            if needle:
                _ok('AI root=%s orch %s 读到卷表（%s）' % (mode, sub, needle),
                    needle in (r.stdout or ''), (r.stdout or '')[-100:])
            if '--push' in sub:
                _ok('AI root=%s orch %s 未把账本根当 conf' % (mode, sub),
                    '未找到 daybook.conf' not in blob, blob[-120:])
    # 只读安装目录：不得 makedirs、不得建锁件；alarm/digest 必须 rc=0
    # Read-only install dir: no makedirs, no lock artifact; alarm/digest must exit 0
    ro = os.path.join(base, 'ro_pkg')
    os.makedirs(ro)
    for name in _MATRIX_COPY:
        src = os.path.join(d, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(ro, name))
    os.chmod(ro, 0o555)
    try:
        for sub in ('alarm', 'digest'):
            r = run([py, '-B', os.path.join(ro, 'orchestrator.py'), '--home=' + cdir, sub])
            _ok('AI 只读安装目录跑 %s ⇒ rc=0（不 makedirs／不建锁件）' % sub,
                r.returncode == 0, 'rc=%d %s' % (r.returncode, (r.stderr or '')[-100:]))
        _ok('AI 只读安装目录未被写入（无新增件）',
            not [n for n in os.listdir(ro) if n not in _MATRIX_COPY and n != '__pycache__'],
            '新增=%s' % [n for n in os.listdir(ro) if n not in _MATRIX_COPY][:5])
    finally:
        os.chmod(ro, 0o755)


def _case_pad_notice(tmp):
    """AG pad_notice 五种输入：有换行／无换行但合法／半行残渣／只有时间戳／二进制垃圾。
    每种都要给可读结论且不崩（残渣必须点名缺失字段）。
    AG pad_notice on five inputs: trailing newline / no newline but valid / half-line residue /
    timestamp only / binary garbage. Each must give a readable verdict and never crash (a
    residue line must name its missing fields)."""
    print('  -- AG pad_notice 五种输入 --')
    sys.path.insert(0, os.path.dirname(SRC_BIN))
    import daybook_append as da
    d = os.path.join(tmp, 'ag')
    os.makedirs(d)
    cases = [
        ('有换行', '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n'.encode('utf-8'), False, ''),
        ('无换行合法', '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文'.encode('utf-8'), True,
         '缺字段=无'),
        ('半行残渣', '[2026-11-13 10:02:00] [测试'.encode('utf-8'), True, '缺字段=类别、标题、作者'),
        ('只有时间戳', '[2026-11-13 10:00:00]'.encode('utf-8'), True, '缺字段=类别、标题、作者'),
        ('二进制垃圾', b'\xff\xfe\x00\x01abc', True, '缺字段=时间'),
    ]
    for i, (label, blob, need, contains) in enumerate(cases):
        p = os.path.join(d, '卷%d.txt' % i)
        io.open(p, 'wb').write(blob)
        crash = ''
        try:
            got_need, notice = da.pad_notice(p)
        except Exception as exc:
            got_need, notice = None, ''
            crash = '%s: %s' % (type(exc).__name__, exc)
        _ok('AG[%s] 不崩且判断正确' % label, not crash and got_need == need,
            crash or 'need=%s notice=%r' % (got_need, notice[:80]))
        if need:
            _ok('AG[%s] 文案可读（卷名/行号/缺字段）' % label,
                notice.startswith('★ 卷末行不完整·已补换行') and '卷=' in notice
                and '行=' in notice and contains in notice, notice[:120])
    # 不知道账本根就不写：append_one(root=None) 必须 rc=2 且一个字节都不动
    # No root means no write: append_one(root=None) must return 2 and leave the file untouched.
    p = os.path.join(d, '无根卷.txt')
    io.open(p, 'w', encoding='utf-8').write('[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
    before = io.open(p, 'rb').read()
    rc = da.append_one(p, '测试', '无根', '正文', author='皮特')
    after = io.open(p, 'rb').read()
    _ok('AG 无账本根 ⇒ append_one rc=2 且不写', rc == 2 and before == after,
        'rc=%r changed=%s' % (rc, before != after))


_CHILD_INBOX = r'''import sys
sys.path.insert(0, sys.argv[1])
import agent_message as am
am._append_inbox({'from': 'A', 'to': 'B', 'type': 'notify', 'content': 'x'}, root=sys.argv[2])
'''


_CHILD_HOLD_AB = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import safeio
root = sys.argv[2]
with safeio.locked(root):
    open(os.path.join(root, 'held.flag'), 'w').write('1')
    while not os.path.exists(os.path.join(root, 'release.flag')):
        time.sleep(0.02)
'''

_CHILD_CACHE_CHECK = r'''
import io, json, os, sys
sys.path.insert(0, os.getcwd())
import daybook as db
conf = db.load_conf(os.path.join(os.getcwd(), 'daybook.conf'))
cache = json.loads(sys.argv[2])
rows = db.check_authors(conf, os.getcwd(), cache=cache)   # 不传 verified ⇒ 旧缓存不可复用
print('GREEN' if all(ok for _v, _p, ok, _d in rows) else 'RED')
'''


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

        # H 删游标后等长替换 ⇒ 封存仍在，仍判违例（rc=3），不是 5
        orig_h = io.open(vol, 'rb').read()
        os.remove(cp)
        _tamper_mid(vol, 0.55)
        r = _run(work)
        txt = r.stdout + r.stderr
        _ok('H 删游标+等长替换 ⇒ rc=3（封存在即判违例）', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('H 报证据缺失（游标丢失）', '证据缺失' in txt and '游标' in txt)
        _ok('H 不得判未变', '未变·跳过' not in txt)
        _ok('H 不写回游标', not os.path.exists(cp))
        _log('H', r)
        r = _run(work)
        _ok('H 复跑仍 3（不得洗成 5）', r.returncode == 3, 'rc=%d' % r.returncode)
        r = _base(work)
        _ok('H 违例态认基线被拒 ⇒ rc=3（删游标→5→认基线 的洗白路径已封）',
            r.returncode == 3, 'rc=%d' % r.returncode)
        io.open(vol, 'wb').write(orig_h)   # 复原后认基线，供 I 用干净状态
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

        # V5 删游标+等长改写：封存这位证人还在 ⇒ 必须判 3（不是 5），且零落盘
        # V5 delete cursor + equal-length rewrite: the seal witness is still present ⇒ 3, not 5,
        # and still zero write. (delete-cursor → 5 → baseline → 0 would be a laundering path.)
        orig_v5 = io.open(vol, 'rb').read()
        cp_v5 = io.open(cp, 'rb').read()
        os.remove(cp)
        _tamper_mid(vol, 0.60)
        idx_before = _snapshot(os.path.join(work, '索引'))
        r = _run(work)
        idx_after = _snapshot(os.path.join(work, '索引'))
        _ok('V5 删游标+等长改写 ⇒ rc=3（封存在即判违例）', r.returncode == 3, 'rc=%d' % r.returncode)
        _ok('V5 rc=3 不可信即零落盘', idx_before == idx_after,
            '差异=%s' % (_snap_diff(idx_before, idx_after),))
        r = _run(work, 'baseline')
        _ok('V5 违例态认基线被拒 ⇒ rc=3（不得把篡改认成新基线）', r.returncode == 3,
            'rc=%d' % r.returncode)
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
        _case_no_newline_tail(work)
        _case_cli_root(work)
        _case_cache_hash(work)
        _case_msg_consistency(work)
        _case_five_roots(work)
        _case_root_matrix(work)
        _case_pad_notice(work)
        _case_write_paths(work)
        _case_home_flag(work)
        _case_tail_no_truncate(work)
        _case_lock_assert(work)
        _case_push_load_bearing(work)
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
    print('PASS: A–AL 三十组用例全绿')
    return 0


if __name__ == '__main__':
    sys.exit(main())
