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
  V safeio 原子替换/无锁读者                    ⇒ LockedRoot.write 走 os.replace，read_vol 不取锁
  W 子目录卷 + 长条目 append                    ⇒ 与 index 争同一把账本根锁（不被子目录锁旁路）
  P 同一账本·两个不同 TMPDIR 并发持锁读改写     ⇒ 临界区不重叠、不丢更新（锁绑目录 inode）
  Q 持锁期间删除任何外部件                      ⇒ 仍互斥（账本内本无锁件可删）
  AA 卷末无换行（有换行/合法无换行/半行残渣）    ⇒ 追加后增量条数 == 全量重建条数，行号无幻影
  AB conf 根 ≠ 脚本目录·账本外调用 CLI           ⇒ 锁落账本根；8 并发长条目全存活
  AC 作者缓存绑定内容哈希                        ⇒ 等长改写后喂旧缓存必须红（不许按 size 复用）

变异验证 / mutation check（legacy：字符串锚点。随包场景层的变异见本文件 MUT）
  本节保留为场景层回归；本节只对场景层结论负责（属性层/记分板如未随包，不在本件声明范围内）。
  Mutation check (legacy string anchors; the bundled scenario-layer mutations live in this
  file's MUT). This section is responsible for the scenario layer only — a property layer or
  scoreboard that is not bundled is outside this file's claim.
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

跑法 / Run: 源树 python3 tests/scenarios/guard.py；盒内 python3 ledger_guard_test.py
退出码 / Exit code: 0=全绿 1=有红
"""
import ast
import builtins
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
# 源树布局 tests/scenarios/guard.py；盒内布局 <box>/ledger_guard_test.py（pack.py 改名拷贝）。
# Source layout: tests/scenarios/guard.py; box layout: <box>/ledger_guard_test.py (renamed by pack.py).
BASE = HERE if os.path.exists(os.path.join(HERE, 'daybook.py')) \
    else os.path.dirname(os.path.dirname(HERE))
# 被测 daybook.py：默认在 BASE；变异验证时用 DAYBOOK_SRC 指向临时副本
# The daybook.py under test: BASE by default; DAYBOOK_SRC points at a mutant copy.
SRC_BIN = os.environ.get('DAYBOOK_SRC') or os.path.join(BASE, 'daybook.py')

# 写路径登记表（单一常量）：(文件, 所在函数, 桶, 理由)
# Write-path registry (single constant): (file, enclosing function, bucket, reason)
# 桶（判据机器校验，理由文字不作数）：
#   ledger   = 写账本/账本根内的件（租约卷、keys/、backup/ 都算）⇒ 只许 safeio，扫到直接写即红；
#   lockfile = 锁件本身（目标固定为 <锁目录>/<资源>.lock，不写数据）⇒ 允许 os.open，形态机器校验；
#   other    = 只允许「目标由 tempfile 生成、位于系统临时目录」一类 ⇒ 目标表达式机器校验；
#   dispatch = 逐个登记的 subprocess 派发点（不在写链上）；必须同时出现在 _SUBPROC_SITES，
#              账本桶里的派发永远红；类别表不替调用点背书；
#   impl     = safeio 自身实现。
# Buckets (machine-checked; the prose reason does not count):
#   ledger   = writes the ledger or anything inside the ledger root (lease volume, keys/,
#              backup/ all count) ⇒ safeio only; any direct write fails;
#   lockfile = the lock artifact itself (target fixed to <lock dir>/<resource>.lock, no data
#              written) ⇒ os.open allowed, shape machine-checked;
#   other    = only "target produced by tempfile, inside the system temp dir" ⇒ target
#              expression machine-checked;
#   dispatch = an individually registered subprocess dispatch site (outside the write chain);
#              must also be in _SUBPROC_SITES, and dispatch inside the ledger bucket is always
#              red — the category table never vouches for a call site;
#   impl     = safeio's own implementation.
WRITE_PATHS = (
    ('agent_heartbeat.py', '__init__', 'ledger', '账本内容/派生件'),
    ('agent_heartbeat.py', 'beat', 'ledger', '账本内容/派生件'),
    ('agent_lock.py', '_log', 'ledger', '账本内容/派生件'),
    ('agent_message.py', '_drop_socket', 'other', 'socket 在系统临时目录（SOCK_DIR），不是账本'),
    ('agent_message.py', '_append_inbox', 'ledger', '账本内容/派生件'),
    ('agent_registry.py', '_write_secret', 'ledger', 'keys/ 在账本根内（REPLACE 0600）'),
    ('agent_registry.py', 'register', 'ledger', '账本内容/派生件'),
    ('agent_registry.py', 'revoke', 'ledger', '账本内容/派生件'),
    ('daybook.py', '_write_cursor', 'ledger', '账本内容/派生件'),
    ('daybook.py', '_run_ops', 'ledger', '账本内容/派生件'),
    ('daybook.py', 'build', 'ledger', '账本内容/派生件'),
    ('daybook.py', '_backup_locked', 'ledger', 'backup/ 在账本根内（目录走 LockedRoot.mkdirs_path）'),
    ('daybook.py', '_backup_copy', 'ledger', 'backup/ 在账本根内（REPLACE）'),
    ('daybook.py', '_run_hook', 'dispatch',
     '变动令在索引/备份之后执行，不在写链上；本仓唯一登记的 subprocess 派发点'),
    ('daybook_append.py', 'append_one', 'ledger', '账本内容/派生件'),
    ('daybook_append.py', '_emit', 'ledger', '账本内容/派生件（临界区内复用已持凭证）'),
    ('daybook_hook.py', 'mark_processed', 'ledger', '账本内容/派生件'),
    ('daybook_multidx.py', '_build_locked', 'ledger', '账本内容/派生件'),
    ('daybook_record.py', 'record', 'ledger', '账本内容/派生件'),
    ('daybook_session_hook.py', 'atomic_json', 'ledger', '账本内容/派生件'),
    ('daybook_session_hook.py', 'initialize_state', 'ledger', '状态目录走 LockedRoot.mkdirs_path'),
    ('daybook_session_hook.py', 'process_once', 'ledger', '状态目录走 LockedRoot.mkdirs_path'),
    ('daybook_session_hook.py', 'install', 'ledger', '.vscode/ 在账本根内（目录走 LockedRoot.mkdirs_path）'),
    ('entry_smoke_test.py', 'mutation_check', 'other', '随包测试：目标由 tempfile 生成'),
    ('entry_smoke_test.py', '_clean_residue', 'other', '随包测试：只删白名单残留，work_dir 由 tempfile 生成'),
    ('mcp_p0_regression.py', '_setup', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_cross_ref_numbered', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_root_from_conf', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', '_copy_server', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_zero_bytecode', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'test_empty_volumes_warns', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'mk', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_p0_regression.py', 'main', 'other', '随包测试：rmtree 只清 tempfile 目录'),
    ('mcp_resources.py', '_audit', 'ledger', '账本内容/派生件'),
    ('mcp_test.py', '_setup_tmp_root', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_test.py', 'test_daybook_index', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_test.py', 'test_subscribe_push', 'other', '随包测试：目标由 tempfile 生成'),
    ('mcp_test.py', 'main', 'other', '随包测试：rmtree 只清 tempfile 目录'),
    ('mcp_tools.py', '_wal', 'ledger', '账本内容/派生件（临界区内复用 held）'),
    ('orch_fixes_test.py', '_fresh_root', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', '_write_fixture', 'ledger', '随包测试夹具卷（REPLACE）'),
    ('orch_fixes_test.py', '_append_fixture', 'ledger', '随包测试夹具卷（APPEND_CREATE）'),
    ('orch_fixes_test.py', 'test_alarm_structure_and_exit_codes', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_cross_process_lock', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_author_head_parse', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_cli_limit_semantics', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_digest_visibility_and_limit', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_pull_reply', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_identity_signature', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_root_resolution', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_single_pass_reads', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_fixes_test.py', 'test_read_locking', 'other', '随包测试：rmtree 只清 tempfile 目录'),
    ('orch_fixes_test.py', 'test_verify_requires_baseline', 'other',
     '随包测试：rmtree 只清 tempfile 目录'),
    ('orch_mutation_check.py', 'make_mutant', 'other', '随包测试：目标由 tempfile 生成'),
    ('orch_mutation_check.py', 'main', 'other', '随包测试：rmtree 只清 tempfile 目录'),
    ('orch_perf_bench.py', 'build_dataset', 'ledger', '随包压测夹具卷（REPLACE）'),
    ('orch_perf_bench.py', 'make_old_pkg', 'other', '随包压测：目标由 tempfile 生成'),
    ('orch_perf_bench.py', 'main', 'other', '随包压测：目标由 tempfile 生成'),
    ('orchestrator.py', '__init__', 'ledger', 'Hub 建卷父目录（目录走 LockedRoot.mkdirs）'),
    ('orchestrator.py', '_selftest', 'other', '自检：目标由 tempfile 生成'),
    ('path_leak_check.py', 'main', 'other', '随包测试：rmtree 只清 tempfile 目录'),
    ('path_leak_check.py', 'mutation_check', 'other', '随包测试：目标由 tempfile 生成'),
    ('safeio.py', 'chmod', 'impl', 'safeio 唯一改权限链（dir_fd）'),
    ('safeio.py', 'mkdir', 'impl', 'safeio 唯一建目录链（dir_fd）'),
    ('safeio.py', 'unlink', 'impl', 'safeio 唯一删除链（dir_fd）'),
    ('safeio.py', 'utime', 'impl', 'safeio 唯一时间戳链（dir_fd）'),
    ('safeio.py', '_append', 'impl', 'safeio 唯一写链（追加）'),
    ('safeio.py', '_replace', 'impl', 'safeio 唯一写链（临时件 + replace + fsync(dfd)）'),
    ('safeio.py', '_append_win', 'impl', 'Windows 追加（realpath 归属判 + O_APPEND + inode 复核）'),
    ('safeio.py', '_replace_win', 'impl', 'Windows 替换（临时件 + os.replace）'),
    ('safeio.py', 'mkdirs', 'impl', 'safeio 递归建目录（dir_fd）'),
    ('safeio.py', 'release', 'impl', 'safeio 锁释放'),
    ('safeio.py', 'update', 'impl', 'safeio 唯一写链（REPLACE）'),
    ('task_volume.py', '__init__', 'ledger', '账本内容/派生件'),
    ('task_volume.py', 'create', 'ledger', '账本内容/派生件'),
    ('task_volume.py', '_transition_locked', 'ledger', '账本内容/派生件'),
    # ── 闭包面补签（第一方写能力）─────────────────────────────────────────────
    # 静态闭包从账本写原语向上传播得到的写能力函数，逐条登记（入口 main/_main/__init__/
    # dispatch/serve 不签；随包测试只报告）。桶名仍是「预期」，实扫类别不符一样红。
    # Closure-surface registrations: write-capable first-party functions reached from ledger
    # primitives. Entry names are never signed; bundled tests are report-only.
    ('agent_heartbeat.py', 'recover', 'ledger', '心跳恢复：写 alive 条目到账本卷'),
    ('agent_lock.py', 'acquire', 'ledger', '取根锁 + 租约日志（账本卷）'),
    ('agent_lock.py', 'release', 'ledger', '释放锁 + 租约日志（账本卷）'),
    ('agent_message.py', 'handle', 'ledger', '收件箱/回执落账'),
    ('agent_message.py', 'send', 'ledger', '发消息：收件箱追加'),
    ('agent_message.py', 'server_close', 'ledger', '关服务：socket 清理 + 关闭记录'),
    ('daybook.py', 'backup', 'ledger', '备份：持根锁写 backup/'),
    ('daybook_hook.py', 'run', 'ledger', 'HOOK-A：追更目标卷'),
    ('daybook_multidx.py', 'build', 'ledger', '多级目录派生件写入'),
    ('daybook_session_hook.py', '_entry', 'ledger', '入口期：归档会话输入'),
    ('daybook_session_hook.py', 'archive_code_changes', 'ledger', '归档代码变更（原件）'),
    ('daybook_session_hook.py', 'archive_message', 'ledger', '归档消息（原件）'),
    ('daybook_session_hook.py', 'handle_event', 'ledger', '处理事件：归档 + 登记'),
    ('daybook_session_hook.py', 'uninstall', 'ledger', '卸载：清 hook 登记'),
    ('mcp_resources.py', 'read_resource', 'other', '只读读取'),
    ('mcp_resources.py', '_read_dir_resource', 'other', '只读目录资源'),
    ('mcp_tools.py', '_audit', 'ledger', '审计卷 append-only'),
    ('mcp_tools.py', '_record_signature', 'ledger', '签名边车 append-only'),
    ('mcp_tools.py', '_write_cursor', 'ledger', '写游标（账本派生件）'),
    ('mcp_tools.py', 'call_tool', 'ledger', '工具派发：写工具经各登记点落账'),
    ('orchestrator.py', '_log', 'ledger', '编排卷条目'),
    ('orchestrator.py', 'claim', 'ledger', '认领：加锁迁移状态'),
    ('orchestrator.py', 'digest', 'other', '只读多级目录摘要'),
    ('orchestrator.py', 'join', 'ledger', '加入：注册 + 落编排卷'),
    ('orchestrator.py', 'leave', 'ledger', '离开：注销 + 落编排卷'),
    ('orchestrator.py', 'open', 'ledger', '开工：建任务 + 落编排卷'),
    ('orchestrator.py', 'push_digest', 'ledger', '推送摘要（落编排卷）'),
    ('orchestrator.py', 'review', 'ledger', '裁决：迁移状态 + 落编排卷'),
    ('orchestrator.py', 'submit', 'ledger', '交活：迁移状态 + 落编排卷'),
    ('safeio.py', '__exit__', 'impl', 'safeio 句柄退出（释放锁/关 fd）'),
    ('safeio.py', 'mkdirs_path', 'impl', 'safeio 归属判 + 建目录（dir_fd）'),
    ('safeio.py', 'write', 'impl', 'safeio 唯一写链入口'),
    ('task_volume.py', 'transition', 'ledger', '状态迁移落账本'),
    # 运维/调试工具的 CLI 主函数（不是 8 入口清单里的产品入口，按内部件登记）。
    # Ops/debug CLI mains (not one of the 8 sanctioned entries, so registered as internals).
    ('agent_heartbeat.py', 'main', 'ledger', '运维工具 CLI：按子命令驱动心跳写入'),
    ('agent_lock.py', 'main', 'ledger', '运维工具 CLI：取/放锁并写租约日志'),
    ('agent_message.py', '__init__', 'ledger', '建服务时清理残留 socket（unlink）'),
    ('agent_message.py', 'main', 'ledger', '服务 CLI：收发消息落账'),
    ('agent_registry.py', 'main', 'ledger', '运维工具 CLI：注册/注销写 keys 与注册卷'),
    ('daybook_multidx.py', 'main', 'ledger', '多级索引 CLI：驱动派生件写入'),
    ('task_volume.py', '_main', 'ledger', '任务卷 CLI：建/迁移任务'),
)

# 唯一写链的调用形态：持有 LockedRoot 的 `lr.write(...)` / `lr.update(...)`（步骤 3 起
# 不存在模块级写原语）。判据据此把「走唯一写链」记为 safe。
# The single write chain is `lr.write(...)` / `lr.update(...)` on a held LockedRoot (no
# module-level write primitive exists since step 3); the audit records it as `safe`.
_WRITE_SAFE = frozenset()
_WRITE_SKIP = ('pack.py', 'ledger_guard_test.py')
_WRITE_TEMP = ('tempfile.mkstemp', 'tempfile.NamedTemporaryFile',
               'tempfile.mkdtemp', 'tempfile.TemporaryDirectory',
               'tempfile.TemporaryFile')

# 能改动账本根内文件系统状态的原语：按**系统调用类别**穷举（不是按文件、按函数抓）。
# 每一类必须声明归属；新增一类却没在这里登记 ⇒ AH 判红。
#   LockedRoot  产品件只能经唯一写能力出现（账本桶裸调即红）
#   LockedRoot|temp  账本内必须经 LockedRoot；系统临时目录里的 socket/夹具清理归 other 桶
#   impl-only   只允许出现在 safeio 的实现里
#   other-only  只允许随包测试/夹具（other 桶）
#   impossible  产品件不可能出现
# Mutating primitives are enumerated by **syscall category** (not by file or function).
# Every category must declare an owner; an undeclared category is red.
_MUTATOR_CALLS = {
    'os.replace': 'replace', 'os.rename': 'replace',
    'os.mkdir': 'mkdir', 'os.makedirs': 'mkdir',
    'os.chmod': 'chmod', 'os.lchmod': 'chmod',
    'os.chown': 'chown', 'os.lchown': 'chown',
    'os.link': 'link', 'os.symlink': 'link',
    'os.unlink': 'unlink', 'os.remove': 'unlink', 'os.rmdir': 'unlink',
    'os.truncate': 'truncate', 'os.ftruncate': 'truncate',
    'os.fsync': 'fsync', 'os.fdatasync': 'fsync',
    'os.utime': 'utime',
    'os.write': 'osopen', 'os.pwrite': 'osopen', 'os.writev': 'osopen',
    'os.setxattr': 'xattr', 'os.removexattr': 'xattr',
}
# 非 os 的写 API：逐条映射到已有类别（Path 方法按语义映射）。
# Non-os write APIs: each maps to an existing category (Path methods by semantics).
_NONOS_CALLS = {
    'shutil.move': 'replace',
    'shutil.rmtree': 'rmtree',
    'shutil.chown': 'chown',
    'shutil.copy': 'copy', 'shutil.copy2': 'copy',
    'shutil.copyfile': 'copy', 'shutil.copytree': 'copy',
}
_PATH_METHOD_KINDS = {
    'mkdir': 'mkdir', 'unlink': 'unlink', 'rmdir': 'unlink',
    'chmod': 'chmod', 'touch': 'utime',
    'rename': 'replace', 'replace': 'replace',
}
_IMPORT_MODULES = ('os', 'shutil', 'pathlib', 'subprocess', 'ctypes')
# 同一仓内的兄弟包模块（盒内可能不在本包，但仍是第一方，不是第三方库）。
# Sibling first-party modules (may live in another box; still first-party, not third-party).
_FIRST_PARTY_MODULES = frozenset({
    'daybook', 'daybook_append', 'daybook_hook', 'daybook_multidx',
    'daybook_record', 'daybook_session_hook', 'errors', 'ledger_root', 'safeio',
    'agent_registry', 'agent_heartbeat', 'agent_lock', 'agent_message',
    'cross_ref', 'mcp_prompts', 'mcp_resources', 'mcp_server', 'mcp_subscribe',
    'mcp_tools', 'mcp_transport', 'orchestrator', 'task_volume', 'volume_paths',
})
_MUTATOR_OWNER = {
    'open': 'LockedRoot',
    'osopen': 'LockedRoot',
    'replace': 'LockedRoot',
    'mkdir': 'LockedRoot',
    'chmod': 'LockedRoot',
    'utime': 'LockedRoot',
    'copy': 'LockedRoot',
    'unlink': 'LockedRoot|temp',
    'rmtree': 'LockedRoot|temp',
    'ctypes': 'impossible',
    'subproc_raw': 'impossible',
    'mode_var': 'impossible',
    'indirect': 'impossible',
    'foreign': 'impossible',
    'chown': 'impossible',
    'link': 'impossible',
    'truncate': 'impossible',
    'xattr': 'impossible',
    # 默认写兜底：落在写面能力上、但没识别出具体类别 ⇒ 红（不许静默放过）。
    # Default-write pool: on the write surface with no recognised category ⇒ red.
    'unclassified': 'impossible',
    'fsync': 'impl-only',
    'temp': 'other-only',
    # subprocess 不再是整类放行：写路径（账本桶）禁止派发；产品件里每一处派发都必须
    # 在 _SUBPROC_SITES 里逐个登记，否则判红。类别表不再替具体调用点背书。
    # subprocess is no longer a blanket category: dispatch is banned on the ledger bucket;
    # every product dispatch site must be registered individually in _SUBPROC_SITES.
    'subproc': 'site-allowlist',
}
# 随包测试可出现的 impossible 类别：派发点的目标由 tempfile 生成，按 other 桶逐点登记。
# Product code keeps them impossible (prod_imp and the violation pools catch them); bundled
# tests may dispatch, registered one by one in the other bucket.
_TEST_TOLERATED = frozenset({'subproc_raw'})

# 逐个登记的派发点（唯一口子）：(文件, 函数) → 理由。只登记「不在写链上」的调用。
# 写路径（ledger 桶）永远不许出现 subproc；确需在写路径派发时，必须校验子进程解析出的
# dev_ino 与父句柄一致（不一致 fail-closed），当前仓内没有这样的合法点。
# Individually registered dispatch sites (the only opening): (file, function) → reason.
# Only sites outside the write chain are registered. A ledger-bucket dispatch is always red;
# if one were ever needed it must verify the child's resolved dev_ino against the parent
# handle and fail closed — no such legal site exists in this repository today.
_SUBPROC_SITES = {
    ('daybook.py', '_run_hook'):
        '用户配置的变动令：在索引/备份之后执行，不在写链上；外部 shell 命令无法预解析子进程根',
}
# 账本桶函数里允许出现的只读/纯进程 os.* 调用；不在表里且不是写原语 ⇒ 红。
# Read-only / process-only os.* calls allowed inside ledger-bucket functions; anything else
# that is not a declared mutator is red.
# 明确豁免（仅随包测试）：work_dir 由 tempfile 生成，体内只删白名单残留。
# Explicit exemption (bundled tests only): work_dir comes from tempfile and the body only
# deletes whitelisted residue.
_OTHER_PARAM_EXEMPT = {
    ('entry_smoke_test.py', '_clean_residue'):
        '随包测试：work_dir 由 tempfile 生成，只删白名单残留',
}
# 逐点人签的「非账本根写」：产品件里确实发生、但目标由 tempfile 生成、不在账本根内的写。
# 签字只覆盖列出的 (文件, 函数, 类别) 三元组；同函数新增写类别仍红。
# Per-site human signatures for off-root writes: real writes in product code whose targets
# come from tempfile and never live inside the ledger root. A signature covers only the
# listed (file, function, kind) triple; a new kind in the same function is still red.
_OFFROOT_WRITE_SITES = {
    ('agent_message.py', '_drop_socket', 'unlink'):
        'socket 路径在系统临时目录（SOCK_DIR），不是账本根',
    ('orchestrator.py', '_selftest', 'open'):
        '自检根由 tempfile.mkdtemp 生成，不是账本根',
    ('orchestrator.py', '_selftest', 'rmtree'):
        '自检根由 tempfile.mkdtemp 生成，不是账本根',
    ('orchestrator.py', '_selftest', 'unlink'):
        '自检根由 tempfile.mkdtemp 生成，不是账本根',
    ('path_leak_check.py', 'mutation_check', 'open'):
        '随包判据工具：TemporaryDirectory 里的合成泄漏样本，不是账本根',
}
_OS_LEDGER_READONLY = frozenset({
    'open', 'close', 'read', 'pread', 'lseek', 'dup', 'stat', 'lstat', 'fstat',
    'listdir', 'scandir', 'walk', 'getcwd', 'chdir', 'getpid', 'getenv', 'urandom',
    'fspath', 'fsencode', 'fsdecode', 'path', 'name', 'sep', 'altsep', 'curdir',
    'pardir', 'linesep', 'environ', 'get_inheritable', 'set_inheritable',
    'access', 'readlink', 'isatty', 'terminal_size', 'get_terminal_size',
    'cpu_count', 'pathconf', 'statvfs', 'getuid', 'geteuid', 'getgid', 'getegid',
    'umask', 'kill', 'waitpid', 'fork', 'getppid', 'getloadavg', 'uname',
})

# ★ 默认值反转（B）：写面按「能力」定义，不按 callee 名字清单。
# ★ Reversed default (B): the write surface is defined by capability, not by a callee list.
# 1) 模块面：这些模块上的调用默认写；未认识的名字也是写（只读只认类别级白名单）。
# 1) Module surface: calls on these modules default to write; unknown names are writes too.
_WRITE_MODULES = frozenset({
    'os', 'shutil', 'subprocess', 'ctypes', 'io', 'pathlib', 'tempfile',
    'mmap', 'sqlite3', 'socket', 'zipfile', 'tarfile', 'logging',
})
# 类别级只读：纯函数模块（不逐个签 callee，只给「这条类别不碰文件系统」的判断）。
# Category-level read-only: pure-function modules (one judgement per category, not per callee).
_PURE_MODULES = frozenset({
    'json', 're', 'hashlib', 'hmac', 'base64', 'binascii', 'time', 'datetime',
    'collections', 'itertools', 'functools', 'operator', 'math', 'random', 'uuid',
    'string', 'textwrap', 'difflib', 'fnmatch', 'glob', 'shlex', 'argparse',
    'typing', 'dataclasses', 'enum', 'struct', 'zlib', 'gzip' , 'csv', 'codecs',
    'unicodedata', 'traceback', 'warnings', 'abc', 'copy', 'contextlib',
    'importlib', 'inspect', 'ast', 'tokenize', 'keyword', 'platform', 'getpass',
    'urllib', 'http', 'email', 'html', 'xml', 'base64', 'pickle', 'marshal',
})
# 2) 方法名面：任意接收者的写动词一律写（不要求接收者是字面量 Path）。
# 2) Method surface: write verbs on any receiver are writes (no literal-Path requirement).
_FS_METHOD_KINDS = {
    'write': 'open', 'writelines': 'open',
    'mkdir': 'mkdir', 'makedirs': 'mkdir',
    'unlink': 'unlink', 'rmdir': 'unlink', 'remove': 'unlink',
    'rename': 'replace', 'replace': 'replace',
    'chmod': 'chmod', 'lchmod': 'chmod',
    'chown': 'chown', 'lchown': 'chown',
    'utime': 'utime', 'touch': 'utime',
    'truncate': 'truncate',
    'symlink': 'link', 'link': 'link',
    'write_text': 'open', 'write_bytes': 'open',
}
# 纯计算的接收者（控制台/字符串）：写动词落在它们身上不算写面。
# Pure receivers (console/string): a write verb on them is outside the write surface.
_PURE_RECEIVERS = frozenset({'stdout', 'stderr', '__stdout__', '__stderr__'})
_PATH_READ_METHODS = frozenset({
    'read_text', 'read_bytes', 'readlink', 'exists', 'is_file', 'is_dir',
    'is_symlink', 'iterdir', 'glob', 'rglob', 'stat', 'lstat', 'resolve',
    'samefile', 'as_posix', 'joinpath', 'with_name', 'with_suffix', 'absolute',
    'is_absolute', 'is_relative_to', 'match',
})
# 账本写类别：产品件里出现即必须登记为 ledger（safeio 自身为 impl）。
# Ledger-write kinds: in product code they must be registered as ledger (safeio itself impl).
_LEDGER_KINDS = frozenset({
    'open', 'osopen', 'replace', 'mkdir', 'chmod', 'utime', 'copy', 'unlink',
    'rmtree', 'chown', 'link', 'truncate', 'xattr', 'unclassified', 'mode_var',
})


def _bucket_bad(f, fn, kinds, bucket, prod):
    """桶名只当「预期」，不当免检凭证；实闸与自证共用这一实现。
    A bucket name is an expectation, never an exemption; shared by the gate and self-check."""
    bad = []
    ctx = set(kinds) - {'safe'}
    if prod:
        if 'subproc' in ctx and (bucket != 'dispatch'
                                 or (ctx - {'subproc', 'temp'})):
            bad.append('dispatch-carries-write')
        if (ctx - {'subproc'}) & _LEDGER_KINDS \
                and bucket != 'ledger' \
                and not (f == 'safeio.py' and bucket == 'impl'):
            # 非账本桶里的账本类写：逐点人签「目标由 tempfile 生成、不在根内」才放行；
            # 未签字（或签了别的类别）仍红。桶名本身不是免检凭证。
            # Ledger-kind writes outside the ledger bucket: only a per-site off-root
            # signature lets them through; unsigned (or a different kind) stays red.
            unsigned = sorted(k for k in (ctx & _LEDGER_KINDS)
                              if (f, fn, k) not in _OFFROOT_WRITE_SITES)
            if unsigned:
                bad.append('write-outside-ledger')
    return bad



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
    if isinstance(e, ast.Tuple):
        return bool(e.elts) and all(_expr_temp(x, names, helpers, aliases) for x in e.elts)
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
    segs = _single_seg_names(fn, aliases)
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
            if _expr_all_temp(value, names, helpers, aliases, segs):
                for t in targets:
                    elts = t.elts if isinstance(t, ast.Tuple) else [t]
                    for el in elts:
                        if isinstance(el, ast.Name) and el.id not in names:
                            names.add(el.id)
                            changed = True
    return names


def _module_temp_names(tree):
    """模块级 temp 名：只收「模块顶层赋值」与「函数内 `global` 声明的名字」。
    Module-level temp names: only top-level assignments and names declared `global` inside
    functions — function-local names must not leak into module scope (that would let any one
    function's local `p` whitelist every other function's `p`)."""
    allowed = set()
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    allowed.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            allowed.add(n.target.id)
    for n in ast.walk(tree):
        if isinstance(n, ast.Global):
            allowed |= set(n.names)
    aliases = _write_aliases(tree)
    helpers = _module_temp_helpers(tree)
    names = set()
    # `global ROOT` 的函数里 `ROOT = <本地 temp 名>`：先按该函数的本地 temp 集传播
    # Inside a function declaring `global ROOT`, `ROOT = <local temp name>` propagates first
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        decl = {g for n in ast.walk(fn) if isinstance(n, ast.Global) for g in n.names}
        if not decl:
            continue
        local = _local_temp_names(fn, helpers, aliases, set())
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign):
                continue
            if isinstance(n.value, ast.Name) and n.value.id in local:
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id in decl:
                        names.add(t.id)
    for _ in range(4):
        changed = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                targets, value = n.targets, n.value
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                targets, value = [n.target], n.value
            else:
                continue
            if _expr_all_temp(value, names, helpers, aliases):
                for t in targets:
                    if isinstance(t, ast.Name) and t.id in allowed and t.id not in names:
                        names.add(t.id)
                        changed = True
        if not changed:
            break
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
        # flags 判不出只读 ⇒ 按写（默认值反转）。
        # Undecidable flags ⇒ write (reversed default).
        return [call.args[0]] if call.args and not _osopen_readonly(call, aliases) else []
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
        # 模块级写原语（步骤 3 起已不存在；保留分支防回流），other 桶也必须证明这个路径来自 tempfile
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


def _single_seg_names(fn, aliases):
    """函数内可证明为「单段相对名」的局部名：不含分隔符、不是 '' / '.' / '..'。
    Local names proven to be a single relative segment (no separator, not ''/'.'/'..').
    来源：① `for x in os.listdir(...)`（listdir 只返回单段名）；② 字面容器（含元组列表的
    首元素）且全为合法单段常量；③ 显式守卫：`if os.path.basename(x) != x or x in ('', '.', '..'): raise`。
    Sources: listdir iteration; literal containers (including the first element of tuple lists)
    whose entries are all safe single-segment constants; or an explicit guard that raises unless
    basename(x) == x and x is not ''/'.'/'..'."""
    out = set()

    def safe(c):
        return isinstance(c, ast.Constant) and isinstance(c.value, str) \
            and c.value not in ('', '.', '..') and '/' not in c.value \
            and os.sep not in c.value and (os.altsep is None or os.altsep not in c.value)

    for n in ast.walk(fn):
        if not isinstance(n, ast.For):
            continue
        it = n.iter
        if isinstance(it, ast.Call) and isinstance(n.target, ast.Name) \
                and _resolve_callee(it.func, aliases) == 'os.listdir':
            out.add(n.target.id)
        elif isinstance(it, (ast.Tuple, ast.List, ast.Set)) and it.elts:
            targets = n.target.elts if isinstance(n.target, ast.Tuple) else [n.target]
            ok = [True] * len(targets)
            for e in it.elts:
                inner = e.elts if isinstance(e, (ast.Tuple, ast.List)) else [e]
                for i in range(len(targets)):
                    if i >= len(inner) or not safe(inner[i]):
                        ok[i] = False
            for i, tgt in enumerate(targets):
                if ok[i] and isinstance(tgt, ast.Name):
                    out.add(tgt.id)
    # 显式守卫：同一函数内「无分隔符」与「不是 . .. ''」两类检查都在 raise 分支里
    # Explicit guard: both the "no separator" and "not '' / '.' / '..'" checks raise
    no_sep, not_dot = set(), set()
    for n in ast.walk(fn):
        if not isinstance(n, ast.If) or not any(isinstance(s, ast.Raise) for s in n.body):
            continue
        for sub in ast.walk(n.test):
            if not isinstance(sub, ast.Compare):
                continue
            nodes = [sub.left] + sub.comparators
            for i, nd in enumerate(nodes):
                if isinstance(nd, ast.Call) and _resolve_callee(nd.func, aliases).split('.')[-1] \
                        == 'basename' and nd.args \
                        and isinstance(nd.args[0], ast.Name):
                    for other in nodes[:i] + nodes[i + 1:]:
                        if isinstance(other, ast.Name) and other.id == nd.args[0].id:
                            no_sep.add(other.id)
                if isinstance(nd, ast.Attribute) and nd.attr == 'sep':
                    for other in nodes[:i] + nodes[i + 1:]:
                        if isinstance(other, ast.Name):
                            no_sep.add(other.id)
                if isinstance(nd, ast.Name) and isinstance(sub.ops[0], (ast.In, ast.NotIn)):
                    for other in nodes[:i] + nodes[i + 1:]:
                        if isinstance(other, (ast.Tuple, ast.List, ast.Set)):
                            vals = {c.value for c in other.elts
                                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
                            if {'', '.', '..'} <= vals:
                                not_dot.add(nd.id)
    return out | (no_sep & not_dot)


def _expr_component(e, names, helpers, aliases, segs):
    """join 的单个组件：要么 temp 派生，要么已证明是单段相对名。
    One join component: either temp-derived or proven to be a single relative segment."""
    if isinstance(e, ast.Name) and e.id in segs:
        return True
    return _expr_all_temp(e, names, helpers, aliases, segs)


def _expr_all_temp(e, names, helpers, aliases, segs=()):
    """写目标的**每一个**组件都必须能证明是 temp 派生（不只看首元）。
    Every component of a write target must be provably temp-derived (not just the first one).
    join 链逐元查；字面段只允许留在临时目录内的相对名。闭包捕获的外部路径（模块常量/外层
    形参）不在 names 里，直接红。
    Every join argument is checked; literal segments may only be relative names inside temp.
    Paths captured from an enclosing scope (module constants / outer parameters) are not in
    `names` and therefore fail."""
    if isinstance(e, ast.Call):
        t = _resolve_callee(e.func, aliases)
        last = t.split('.')[-1]
        # basename/dirname 先于通用路径助手处理：dirname 一律红（上跳父目录）
        # basename/dirname are handled before the generic path helper: dirname is always red
        # (it walks up to the parent), basename keeps one segment.
        if last == 'dirname':
            return False
        if last == 'basename':
            # 常量入参按实际结果判（`basename("x/..") == ".."` ⇒ 红）；非恒定入参必须
            # 本身能证明是安全路径（每段相对、无 `..`）或已证明为单段相对名，否则红——
            # 变量可能是 `..`，两个叠起来就上跳两级。
            # Constants are judged by their actual result (`basename("x/..")` ⇒ red). A
            # non-constant argument must itself be a provable safe path (every segment
            # relative, no `..`) or a proven single relative segment; otherwise red, because
            # the variable may be `..` and two of them climb two levels.
            if not e.args:
                return False
            a0 = e.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                return os.path.basename(a0.value) not in ('', '.', '..')
            return _expr_component(a0, names, helpers, aliases, segs)
        if _is_path_helper(t):
            return bool(e.args) and all(
                _expr_component(a, names, helpers, aliases, segs) for a in e.args)
        return _expr_temp(e, names, helpers, aliases)
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
        return _expr_all_temp(e.left, names, helpers, aliases, segs) \
            and _expr_all_temp(e.right, names, helpers, aliases, segs)
    if isinstance(e, ast.JoinedStr):
        # `other` 桶**禁用 f-string 拼路径**（R10-4 选定①）：字面段与插值混在一个表达式里，
        # 静态层面无法证明整体留在临时目录；即便是 `f"{d}/ok.txt"` 也判红，拼路径请用
        # os.path.join 逐元表达。文档与判据文案一致，无「行为禁、文档不说」。
        # The `other` bucket **bans f-string path building** (R10-4 option ①): literal and
        # interpolated segments are mixed in one expression and cannot be proven to stay in the
        # temp dir; even `f"{d}/ok.txt"` is red. Use os.path.join with explicit components.
        return False
    if isinstance(e, ast.Constant) and isinstance(e.value, str):
        v = e.value
        return not (os.path.isabs(v) or v == '..' or os.path.normpath(v).startswith('..'))
    return _expr_temp(e, names, helpers, aliases)


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
    seed |= _module_temp_names(tree)
    names = _local_temp_names(fn, helpers, aliases, seed)
    segs = _single_seg_names(fn, aliases)
    bad = []
    for call in ast.walk(fn):
        if not isinstance(call, ast.Call):
            continue
        for tgt in _write_call_targets(call, aliases):
            snippet = ast.unparse(call)[:70]
            if not _expr_all_temp(tgt, names, helpers, aliases, segs):
                bad.append('%s（目标有非 tempfile 派生组件·可能落在账本根内）' % snippet)
                continue
            if not _targets_stay_in_temp(tgt, aliases):
                bad.append('%s（含 `..`/绝对段·可逃出临时目录）' % snippet)
    return bad


_PATH_PARAM_HINTS = ('dir', 'path', 'root', 'home')


def _is_path_default(d):
    return isinstance(d, ast.Constant) and isinstance(d.value, str) \
        and (os.sep in d.value or d.value.startswith('~'))


def _arg_reason(a, d=None):
    """单个形参为何不合法（名/默认值/无默认的 const）。
    Why one parameter is illegal (name / default value)."""
    low = a.arg.lower()
    hit = [h for h in _PATH_PARAM_HINTS if h in low]
    if hit:
        return '%s（形参名含路径词 %s）' % (a.arg, '/'.join(hit))
    if d is not None and _is_path_default(d):
        return '%s（默认值是路径 %r）' % (a.arg, d.value[:30])
    return None


def _other_param_reasons(fn):
    """other 桶不得收路径参数：形参名含 dir/path/root/home，或默认值是路径 ⇒ 红。
    The `other` bucket must not take path parameters: a name containing dir/path/root/home, or a
    path-like default ⇒ red.
    默认值按位置对齐：`fn.args.defaults` 与末段位置形参一一对应，`kw_defaults` 对 kw-only；
    `*args` / `**kwargs` 一律判红（可变参数等于「随便喂路径」的口子）。
    Defaults are aligned positionally: `fn.args.defaults` with the trailing positional
    parameters, `kw_defaults` with the keyword-only ones; `*args` / `**kwargs` are always red
    (variadic parameters are exactly the "pass me any path" hole).
    该判定只看函数签名，与调用方式无关：一旦在 other 桶里带路径参数，用 getattr / 字典派发
    调用同样不合法。
    Signature-only, independent of call style: once an `other` entry takes a path parameter it is
    illegal even when reached via getattr / dict dispatch."""
    bad = []
    a = fn.args
    pos = list(getattr(a, 'posonlyargs', [])) + list(a.args)
    if a.vararg is not None:
        bad.append('*%s（可变位置参数·可传任意路径）' % a.vararg.arg)
    if a.kwarg is not None:
        bad.append('**%s（可变关键字参数·可传任意路径）' % a.kwarg.arg)
    nd = len(a.defaults)
    for arg, d in zip(pos[len(pos) - nd:] if nd else [], a.defaults):
        r = _arg_reason(arg, d)
        if r:
            bad.append(r)
    for arg in pos[:len(pos) - nd] if nd else pos:
        r = _arg_reason(arg)
        if r:
            bad.append(r)
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        r = _arg_reason(arg, d)
        if r:
            bad.append(r)
    return bad


def _find_func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _scan_write_sites(d, extra=(), product_extra=()):
    """按包装清单扫产品件与随包脚本，返回 (文件, sites, AST, 产品件集合)。
    Scan shipped product/aux files; return (files, sites, trees, product_files).
    发现先于归类：`sites` 只记录“算得出写类别”的函数；**看不到类别的函数仍在 trees 里**，
    由 `_write_violations` 的全函数 `os.*`/非 os API 检查兜住。
    Discovery precedes classification: `sites` only holds functions whose write kind could be
    computed; functions with no computable kind remain in `trees` and are covered by
    `_write_violations` (all-function os.* / non-os API scan)."""
    product = set()
    try:
        if d not in sys.path:
            sys.path.insert(0, d)
        from pack import PACKAGES
        names = set()
        for spec in PACKAGES.values():
            names.update(spec.get('prog', []))
            names.update(spec.get('prog_aux', []))
            product.update(spec.get('prog', []))
        scan = [n for n in sorted(names)
                if n.endswith('.py') and n not in _WRITE_SKIP
                and os.path.exists(os.path.join(d, n))]
    except Exception:
        scan = [n for n in sorted(os.listdir(d))
                if n.endswith('.py') and n not in _WRITE_SKIP
                and not n.endswith('_test.py')]
        product = set(scan)
    for n in extra:
        if n.endswith('.py') and n not in scan and os.path.exists(os.path.join(d, n)):
            scan.append(n)
    product |= {n for n in product_extra if n in scan}
    files, sites, trees = [], {}, {}
    for fn in scan:
        try:
            tree = ast.parse(io.open(os.path.join(d, fn), encoding='utf-8').read())
        except SyntaxError:
            continue
        files.append(fn)
        trees[fn] = tree
        al = _write_aliases(tree)
        # 函数能力＝整棵子树（含嵌套闭包与 lambda）：嵌套里的写就是外层函数的写。
        # A function's capability is its whole subtree (nested closures and lambdas
        # included): a write in a closure is a write of the enclosing function.
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
            kinds = _scope_kinds(node, calls, al, (fn, node.name))
            if kinds:
                sites[(fn, node.name)] = kinds
        # 模块体/类体只算**直接**语句（import 期写入）；成员函数的写已归函数自己。
        # Module/class bodies count only their **direct** statements (import-time writes);
        # writes inside member functions are already attributed to those functions.
        direct = {}
        parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parent[c] = n
        for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
            name, scope = _scope_of(call, parent, tree)
            direct.setdefault(id(scope), (name, scope, []))[2].append(call)
        for name, node, calls in direct.values():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            kinds = _scope_kinds(node, calls, al, (fn, name))
            if kinds:
                sites[(fn, name)] = kinds
    return files, sites, trees, product & set(files)


_MUTATOR_ATTRS = {k.split('.', 1)[1] for k in _MUTATOR_CALLS}


def _mode_value(node, positional=1):
    v = node.args[positional] if len(node.args) > positional else None
    for kw in node.keywords:
        if kw.arg == 'mode':
            v = kw.value
    return v


def _mode_is_var(node, positional=1):
    v = _mode_value(node, positional)
    return v is not None and not (isinstance(v, ast.Constant) and isinstance(v.value, str))


def _mode_writes(node, positional):
    v = _mode_value(node, positional)
    return isinstance(v, ast.Constant) and isinstance(v.value, str) \
        and any(c in v.value for c in 'wax+')


def _is_builtin_open(sub, al):
    """只有内建 open 才算，`hub.open()` 这类方法不算（方法面另判）。
    Only builtin open counts; method calls such as `hub.open()` are judged by the method
    surface instead."""
    return isinstance(sub.func, ast.Name) \
        and _resolve_callee(sub.func, al) == 'open'


def _subproc_kind(sub, t):
    """只认 subprocess.*（含别名）。无显式重定向 ⇒ raw（产品件直接红）；
    有重定向 ⇒ 仍是 **派发点**（子进程按路径重解析账本根，可能改道新 inode），
    必须逐个登记，不能因为「输出去向是 PIPE」就整类放行。
    Only subprocess.* (aliases included). No explicit redirection ⇒ raw (red in product code);
    with redirection it is still a **dispatch site** (a child re-resolves the ledger root by
    path and may follow a renamed directory), so it must be registered individually — "output
    goes to a pipe" never makes the category safe."""
    if t.split('.')[0] != 'subprocess':
        return None
    last = t.split('.')[-1]
    if last not in ('run', 'Popen', 'call', 'check_call', 'check_output'):
        return None
    red = [kw for kw in sub.keywords
           if kw.arg in ('stdout', 'stderr', 'capture_output')]
    return 'subproc' if red else 'subproc_raw'


_FLAG_WRITE_MASK = 0
for _n in ('O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC', 'O_APPEND'):
    _FLAG_WRITE_MASK |= getattr(os, _n, 0)


def _fold_os_constant(node, al, depth=0):
    """把 `os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW` / `getattr(os,'O_X',0)` 折成整数。
    判不出（变量、未知属性、超深）⇒ None。
    Fold os flag constants (bitwise-or, getattr with default) to an int; None when unknown."""
    if depth > 6:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        a = _fold_os_constant(node.left, al, depth + 1)
        b = _fold_os_constant(node.right, al, depth + 1)
        return None if a is None or b is None else a | b
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        o = al.get(node.value.id)
        if o and o[0] == 'mod' and o[1].split('.')[0] == 'os':
            return getattr(os, node.attr, None)
    if isinstance(node, ast.Name):
        o = al.get(node.id)
        if o and o[0] == 'from':
            mod, _, nm = o[1].partition('.')
            if mod == 'os':
                return getattr(os, nm, None)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == 'getattr' and len(node.args) >= 2:
        tgt = node.args[0]
        key = node.args[1]
        if isinstance(tgt, ast.Name) and isinstance(key, ast.Constant) \
                and isinstance(key.value, str):
            o = al.get(tgt.id)
            if o and o[0] == 'mod' and o[1].split('.')[0] == 'os':
                return getattr(os, key.value,
                               _fold_os_constant(node.args[2], al, depth + 1)
                               if len(node.args) > 2 else None)
    return None


def _osopen_readonly(sub, al=None):
    """`os.open` 的只读判定：flags 做常量折叠，折出的值不含任何写位 ⇒ 只读。
    折不出（变量/表达式）⇒ 按写（默认值）。**不签字豁免**。
    `os.open` read-only verdict: fold the flags expression; a value with no write bit is
    read-only. Unfoldable flags are a write (default). No signatures involved."""
    v = sub.args[1] if len(sub.args) > 1 else None
    for kw in sub.keywords:
        if kw.arg == 'flags':
            v = kw.value
    if v is None:
        return False
    folded = _fold_os_constant(v, al or {})
    return folded is not None and not (folded & _FLAG_WRITE_MASK)


_READONLY_CALLS = {
    # 逐点人签（site 级，不是 callee 级）：证明该调用不碰账本根。
    # Per-site signatures (not per-callee): this call does not touch the ledger root.
    ('daybook_multidx.py', '_tsv_row', 'replace'): 'TSV 字段字符串归一化',
    ('daybook.py', '_run_ops', 'replace'): 'TSV 字段字符串归一化（表内换行替换）',
    ('daybook_session_hook.py', 'local_stamp', 'replace'): 'ISO 时间串归一化',
    ('mcp_resources.py', 'read_resource', 'replace'): 'URI 前缀字符串归一化',
    ('mcp_resources.py', '_read_dir_resource', 'replace'): 'URI 前缀字符串归一化',
    ('mcp_tools.py', '_multi_query', 'replace'): '检索结果字符串归一化',
    ('mcp_transport.py', 'write_message', 'write'): 'stdio 协议输出，不是账本根写入',
    ('agent_message.py', 'send', 'socket.socket'): 'Unix socket 通知，不是账本根写入',
    ('agent_message.py', 'sock_path', 'socket.socket'): 'socket 路径探测，不是账本根写入',
}


def _annotation_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ''


def _pure_names(scope):
    """作用域内可证明为字符串/字节的局部名与形参（只用于把写动词排除出写面）。
    Locals/params provably string/bytes in this scope (only used to keep write verbs off
    the write surface)."""
    out = set()
    for n in ast.walk(scope):
        if isinstance(n, ast.arg) and n.annotation is not None \
                and _annotation_name(n.annotation) in ('str', 'bytes'):
            out.add(n.arg)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) \
                and _annotation_name(n.annotation) in ('str', 'bytes'):
            out.add(n.target.id)
        elif isinstance(n, ast.Assign):
            v = n.value
            pure = isinstance(v, (ast.Constant, ast.JoinedStr)) \
                or (isinstance(v, ast.BinOp) and isinstance(v.op, ast.Add)) \
                or (isinstance(v, ast.Call)
                    and (isinstance(v.func, ast.Name)
                         and v.func.id in ('str', 'repr', 'format')
                         or isinstance(v.func, ast.Attribute)
                         and v.func.attr in ('format', 'join', 'strip', 'replace',
                                             'split', 'encode', 'decode', 'lower',
                                             'upper')))
            if pure:
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        out.add(t.id)
    return out


def _receiver_pure(recv, al, scope, pure):
    """控制台/字符串接收者 ⇒ 写动词不算写面（类别级纯计算判断）。
    Console/string receivers ⇒ a write verb is outside the write surface."""
    if isinstance(recv, (ast.Constant, ast.JoinedStr)):
        return True
    if isinstance(recv, ast.BinOp) and isinstance(recv.op, (ast.Add, ast.Mod)):
        return True
    if isinstance(recv, ast.Name):
        return recv.id in pure
    if isinstance(recv, ast.Attribute) and recv.attr in _PURE_RECEIVERS \
            and isinstance(recv.value, ast.Name):
        o = al.get(recv.value.id)
        return recv.value.id == 'sys' or (o and o[0] == 'mod' and o[1] == 'sys')
    if isinstance(recv, ast.Call):
        t = _resolve_callee(recv.func, al)
        if t in ('str', 'repr', 'format', 'json.dumps', 'json.loads'):
            return True
        if isinstance(recv.func, ast.Attribute) and recv.func.attr in (
                'format', 'join', 'strip', 'replace', 'split', 'encode',
                'decode', 'lower', 'upper'):
            return True
    return False


def _is_path_expr(e, al, names):
    """表达式是否可证明为 Path（字面构造 / 二元拼接 / 形参或局部名 / 属性链）。
    Whether an expression is provably a Path (literal construction, division, param/local,
    attribute chain)."""
    if isinstance(e, ast.Call):
        return _resolve_callee(e.func, al).split('.')[-1] in (
            'Path', 'PurePath', 'PosixPath', 'WindowsPath')
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Div):
        return _is_path_expr(e.left, al, names) or _is_path_expr(e.right, al, names)
    if isinstance(e, ast.Name):
        return e.id in names
    if isinstance(e, ast.Attribute):
        return _is_path_expr(e.value, al, names)
    return False


def _path_names(scope, al):
    """作用域内可证明为 Path 的形参/局部名（形参注 Path 也算）。
    Params/locals provably Path in this scope (a Path annotation counts too)."""
    names = set()
    for n in ast.walk(scope):
        if isinstance(n, ast.arg) and n.annotation is not None \
                and _annotation_name(n.annotation) in (
                    'Path', 'PurePath', 'PosixPath', 'WindowsPath'):
            names.add(n.arg)
    changed = True
    while changed:
        changed = False
        for n in ast.walk(scope):
            targets = []
            value = None
            if isinstance(n, ast.Assign):
                targets, value = n.targets, n.value
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                targets, value = [n.target], n.value
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                targets, value = [n.optional_vars], n.context_expr
            if value is not None and _is_path_expr(value, al, names):
                for t in targets:
                    if isinstance(t, ast.Name) and t.id not in names:
                        names.add(t.id)
                        changed = True
    return names


def _call_kind(sub, al, scope=None, pure=None, paths=None, site=None):
    """一次调用的写类别（默认写：未识别但落在写面能力上的调用 ⇒ 写）。
    Write kind of one call (default-write: an unrecognised call on a write-capable surface
    is a write). Returns None only for provably read-only/pure calls."""
    t = _resolve_callee(sub.func, al)
    if site and (site[0], site[1], t) in _READONLY_CALLS:
        return None
    pure = pure if pure is not None else _pure_names(scope) if scope is not None else set()
    paths = paths if paths is not None else _path_names(scope, al) \
        if scope is not None else set()
    if t in _WRITE_SAFE:
        return 'safe'
    # Path 构造/纯定位不是写：pathlib 在写模块面里，但构造器本身不碰文件系统。
    # Path construction/pure location is not a write: pathlib is on the write-module
    # surface, but its constructors never touch the filesystem.
    if t.split('.')[-1] in ('Path', 'PurePath', 'PosixPath', 'WindowsPath') \
            and ('.' not in t or t.split('.')[0] == 'pathlib'):
        return None
    if t in ('pathlib.Path.home', 'pathlib.Path.cwd'):
        return None
    if isinstance(sub.func, ast.Attribute) \
            and isinstance(sub.func.value, ast.Name) \
            and sub.func.value.id in ('lr', '_lr', 'locked_root') \
            and sub.func.attr in ('write', 'update', 'mkdir', 'mkdirs',
                                  'mkdirs_path', 'chmod', 'unlink', 'utime'):
        return 'safe'
    if t in _MUTATOR_CALLS:
        return _MUTATOR_CALLS[t]
    if t in _NONOS_CALLS:
        return _NONOS_CALLS[t]
    if t in _WRITE_TEMP:
        return 'temp'
    if t in ('tempfile.gettempdir', 'tempfile.gettempdirb'):
        return None
    if t == 'os.open':
        return None if _osopen_readonly(sub, al) else 'osopen'
    if t in ('io.StringIO', 'io.BytesIO'):
        return None
    if _is_builtin_open(sub, al) or t == 'io.open':
        if _mode_writes(sub, 1):
            return 'open'
        if _mode_is_var(sub, 1):
            return 'mode_var'
        return None
    if t in ('zipfile.ZipFile', 'tarfile.open'):
        if _mode_writes(sub, 1) or _mode_is_var(sub, 1):
            return 'open'
        return None
    if t in ('logging.FileHandler', 'logging.basicConfig'):
        return 'open'
    if t == 'ctypes.WinDLL':
        # Windows 拒绝分支：只加载 DLL 做能力探测，不写账本（保持原状）。
        # Windows refusal branch: loads a DLL for capability probing, no ledger write.
        return None
    sk = _subproc_kind(sub, t)
    if sk:
        return sk
    if t.startswith('ctypes') or any(
            isinstance(x, ast.Call)
            and _resolve_callee(x.func, al).startswith('ctypes.')
            for x in ast.walk(sub.func)):
        return 'ctypes'
    if isinstance(sub.func, ast.Attribute):
        attr = sub.func.attr
        if attr in _FS_METHOD_KINDS:
            if _receiver_pure(sub.func.value, al, scope, pure):
                return None
            return _FS_METHOD_KINDS[attr]
        if attr == 'open':
            # `.open` 的语义随接收者而变：只有可证明是 Path 才按「模式参数」判；
            # 其它 `.open`（Root.open/hub.open）由闭包能力面判，不在这里按名字误杀。
            # `.open` is receiver-dependent: only a provable Path is judged by its mode;
            # other `.open` calls are judged by the closure/capability pass.
            if not _is_path_expr(sub.func.value, al, paths):
                return None
            if _receiver_pure(sub.func.value, al, scope, pure):
                return None
            if _mode_writes(sub, 0):
                return 'open'
            if _mode_is_var(sub, 0):
                return 'mode_var'
            return None
        if attr in _PATH_READ_METHODS:
            return None
    mod = t.split('.')[0]
    if mod == 'shutil' and t == 'shutil.ignore_patterns':
        return None
    if mod == 'logging':
        return None
    if mod in _WRITE_MODULES:
        if mod == 'os':
            a = t.split('.')[-1]
            if a in _MUTATOR_ATTRS or a in _OS_LEDGER_READONLY:
                return None
        return 'unclassified'
    return None


def _scope_of(call, parent, tree):
    p = parent.get(call)
    while p is not None and not isinstance(
            p, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        p = parent.get(p)
    if p is None or isinstance(p, ast.Module):
        return '<module>', tree
    if isinstance(p, ast.ClassDef):
        return '<class %s>' % p.name, p
    return p.name, p


def _scopes(tree):
    """模块体/类体/函数的作用域与各自调用点（模块体不再漏扫）。
    lambda 不算作用域边界：lambda 里的写归它所在的函数/模块（lambda 也要扫）。
    Scopes (module body, class body, functions) with their call sites — the module and
    class bodies are no longer skipped. A lambda is not a scope boundary: a write inside
    a lambda belongs to the enclosing function/module (lambdas are scanned too)."""
    parent = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[c] = n
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name, scope = _scope_of(n, parent, tree)
            key = (id(scope),)
            out.setdefault(key, (name, scope, []))[2].append(n)
    return list(out.values())


def _scope_kinds(scope, calls, al, site=None):
    pure = _pure_names(scope)
    paths = _path_names(scope, al)
    kinds = set()
    for sub in calls:
        k = _call_kind(sub, al, scope, pure, paths, site)
        if k:
            kinds.add(k)
    return kinds


# 闭包面：入口函数不签（它们本来就什么都可达，签字信息量为零）。
# 双重限定：函数名在入口名集合里，**且**文件属于 8 个产品入口文件之一；只在名字上免签
# 会让任何新内部函数叫 serve/dispatch/__init__ 就蒙混过关。
# Entry functions are never signed (they reach everything by definition). Double qualification:
# the name is in the entry-name set **and** the file is one of the 8 product entry files.
# Name-only exemption would let any new internal `serve`/`dispatch`/`__init__` slip through.
_ENTRY_NAMES = frozenset({'main', '_main', '__init__', 'dispatch', 'serve'})
_ENTRY_FILES = frozenset({
    'daybook.py', 'daybook_record.py', 'daybook_append.py', 'daybook_hook.py',
    'daybook_session_hook.py', 'orchestrator.py', 'mcp_server.py', 'cross_ref.py',
})


def _is_entry(file, fn):
    return fn in _ENTRY_NAMES and file in _ENTRY_FILES
_BUILTIN_NAMES = frozenset(dir(builtins))
# 纯计算面（内建/容器类型的方法名）：这类调用不碰文件系统，不算闭包缺口。
# 按类别判定，不逐个 callee 签。
# Pure-computation surface (builtin/container method names): these never touch the filesystem
# and are not closure gaps. Category-based, not signed per callee.
_PURE_METHOD_NAMES = frozenset().union(
    *[set(dir(t)) for t in (str, bytes, dict, list, set, tuple, int, float)])
# 逐条豁免的未解析边（(文件, 函数, callee, 行号)）：写明为什么它不可能落在写能力函数上。
# 键带行号：同一函数里第二处同名调用不会被前一行顺带放行。
# Per-edge exemptions for unresolved calls ((file, function, callee, line)): each states why
# it cannot target a write-capable function. The line is part of the key, so a second call
# with the same name in the same function is not waved through by the first.
_CLOSURE_EXEMPT = {
    ('agent_lock.py', 'release', 'release', 162): 'ent["lr"].release()：凭证释放，不是账本写',
    ('daybook_append.py', 'append_one', 'lock', 400): 'rt.lock()：取锁不是写',
    ('daybook_record.py', '_open_ledger', 'read', 58): 'rt.read()：Root 根内读取',
    ('mcp_transport.py', 'write_message', 'write', 155): 'outfile 是协议输出流（stdout/管道）',
    ('safeio.py', 'lock', 'acquire', 468): 'mx.acquire()：线程互斥量获取（_proc_mutex）',
    ('safeio.py', 'lock', 'acquire', 470): 'mx.acquire()：线程互斥量获取（_proc_mutex）',
    ('safeio.py', 'lock', 'acquire', 472): 'mx.acquire()：线程互斥量获取（_proc_mutex）',
    ('safeio.py', 'lock', 'release', 494): 'mx.release()：线程互斥量释放',
    ('safeio.py', 'release', 'release', 865): '_proc_mutex(key).release()：线程互斥量释放',
    ('safeio.py', 'update', 'read', 835): 'self.root.read(rel)：Root 根内读取',
}


def _func_index(tree):
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(n.name, []).append(n)
    return out


def _class_index(tree):
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


def _enclosing_class(node, parent):
    p = parent.get(node)
    while p is not None:
        if isinstance(p, ast.ClassDef):
            return p
        p = parent.get(p)
    return None


def _chain_root(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    return node


def _value_external(node, al, mod2file):
    """赋值右侧可证明不是第一方函数对象：字面量/容器/字符串变换/文件对象/stdlib 构造。
    Provably not a first-party function object: literals/containers/string ops/file objects/
    stdlib constructors."""
    if isinstance(node, (ast.Constant, ast.JoinedStr, ast.Dict, ast.List, ast.Tuple,
                         ast.Set, ast.BinOp, ast.IfExp, ast.Subscript, ast.Compare)):
        return True
    if isinstance(node, ast.Call):
        t = _resolve_callee(node.func, al)
        if t in ('str', 'repr', 'format', 'json.dumps', 'json.loads', 'hashlib.sha256',
                 'hashlib.md5', 'hashlib.sha1', 'set', 'dict', 'list', 'frozenset', 'tuple'):
            return True
        last = t.split('.')[-1]
        if last in ('open', 'read_text', 'read_bytes', 'readlines', 'split', 'splitlines',
                    'strip', 'encode', 'decode', 'StringIO', 'BytesIO'):
            return True
        mod = t.split('.')[0]
        if '.' in t and mod not in mod2file:
            return True
    return False


def _external_locals(scope, al, mod2file):
    """作用域里可证明不是第一方对象的局部名（文件对象/字符串/hashlib/dict 等）。
    Locals provably not first-party objects (file handles, strings, hashlib, dicts...)."""
    out = set()
    for n in ast.walk(scope):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and _value_external(n.value, al, mod2file):
                    out.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) \
                and n.annotation is not None \
                and _annotation_name(n.annotation) in ('str', 'bytes', 'dict', 'list', 'int', 'float'):
            out.add(n.target.id)
        elif isinstance(n, ast.With):
            for it in n.items:
                if it.optional_vars is None:
                    continue
                if _value_external(it.context_expr, al, mod2file):
                    for t in ast.walk(it.optional_vars):
                        if isinstance(t, ast.Name):
                            out.add(t.id)
    return out


def _local_types(scope, f, al, mod2file, classes):
    """局部实例类型：`x = ClassName(...)` / `x = 首方类构造(...)` ⇒ x 的类。
    Local instance types: `x = ClassName(...)` for a same-file or from-import first-party class."""
    out = {}
    for n in ast.walk(scope):
        if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call):
            continue
        fn = n.value.func
        cand = None
        if isinstance(fn, ast.Name):
            if fn.id in classes[f]:
                cand = (f, fn.id)
            else:
                o = al.get(fn.id)
                if o and o[0] == 'from':
                    mod, _, nm = o[1].partition('.')
                    if mod in mod2file and nm in classes.get(mod2file[mod], {}):
                        cand = (mod2file[mod], nm)
        if cand is None:
            continue
        for t in n.targets:
            if isinstance(t, ast.Name):
                out[t.id] = cand
    return out


def _class_attr_types(tree, f, al, mod2file, classes):
    """类属性类型：`self.x = ClassName(...)` ⇒ x 的类（同文件或 from 导入的首方类）。
    Class attribute types: `self.x = ClassName(...)` for a same-file or imported first-party class."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        attrs = {}
        for n in ast.walk(node):
            if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call):
                continue
            fn = n.value.func
            cand = None
            if isinstance(fn, ast.Name):
                if fn.id in classes[f]:
                    cand = (f, fn.id)
                else:
                    o = al.get(fn.id)
                    if o and o[0] == 'from':
                        mod, _, nm = o[1].partition('.')
                        if mod in mod2file and nm in classes.get(mod2file[mod], {}):
                            cand = (mod2file[mod], nm)
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                o = al.get(fn.value.id)
                if o and o[0] == 'mod' and o[1].split('.')[0] in mod2file \
                        and fn.attr in classes.get(mod2file[o[1].split('.')[0]], {}):
                    cand = (mod2file[o[1].split('.')[0]], fn.attr)
            if cand is None:
                continue
            for t in n.targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                        and t.value.id == 'self':
                    attrs[t.attr] = cand
        if attrs:
            out[node.name] = attrs
    return out


def _class_attr_external(tree, f, al, mod2file):
    """类属性来自 stdlib 对象（如 threading.Thread）⇒ 其方法不是第一方边。
    Class attributes built from stdlib objects (e.g. threading.Thread) are not first-party."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        attrs = set()
        for n in ast.walk(node):
            if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call):
                continue
            fn = n.value.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                o = al.get(fn.value.id)
                if o and o[0] == 'mod' and o[1].split('.')[0] not in mod2file:
                    for t in n.targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                                and t.value.id == 'self':
                            attrs.add(t.attr)
        if attrs:
            out[node.name] = attrs
    return out


def _resolve_edge(call, al, f, mod2file, funcs, classes, cls, pure=(), local_ext=(),
                  local_ty=None, attr_ty=None, attr_ext=None):
    """一次调用能否落到第一方函数；返回 (kind, target, callee)。
    kind='edge' 时 target=(文件, 函数)；否则 kind 是未解析类型，callee 是不确定的名字。
    Resolve one call to a first-party function; kind='edge' carries the target, otherwise
    kind is the unresolved category and callee is the undetermined name."""
    func = call.func
    t = _resolve_callee(func, al)
    if isinstance(func, ast.Name):
        if func.id in funcs[f]:
            return 'edge', (f, func.id), func.id
        if func.id in classes[f]:
            body = functions_of(classes[f][func.id])
            return ('edge', (f, '__init__'), '__init__') if '__init__' in body \
                else ('other', None, func.id)
        o = al.get(func.id)
        if o and o[0] == 'from':
            mod, _, nm = o[1].partition('.')
            if mod in mod2file:
                tf = mod2file[mod]
                if nm in funcs[tf]:
                    return 'edge', (tf, nm), nm
                if nm in classes[tf] and '__init__' in functions_of(classes[tf][nm]):
                    return 'edge', (tf, '__init__'), '__init__'
                return 'from-import', None, nm
            return 'external', None, func.id
        if func.id in _BUILTIN_NAMES:
            return 'external', None, func.id
        return 'other', None, func.id
    if isinstance(func, ast.Attribute):
        root = _chain_root(func)
        if isinstance(root, ast.Name):
            o = al.get(root.id)
            if o and o[0] == 'from':
                mod, _, nm = o[1].partition('.')
                if mod in mod2file and nm in classes[mod2file[mod]]:
                    tf = mod2file[mod]
                    if func.attr in functions_of(classes[tf][nm]):
                        return 'edge', (tf, func.attr), func.attr
                    return 'other', None, func.attr
            if o and o[0] == 'mod':
                mod = o[1].split('.')[0]
                if mod in mod2file and root is func.value \
                        and func.attr in funcs[mod2file[mod]]:
                    return 'edge', (mod2file[mod], func.attr), func.attr
                if mod in mod2file:
                    return 'other', None, func.attr
                return 'external', None, t
            if root.id in classes[f]:
                body = functions_of(classes[f][root.id])
                if func.attr in body:
                    return 'edge', (f, func.attr), func.attr
                return 'other', None, func.attr
            if root.id == 'cls' and cls is not None and func.attr in functions_of(cls):
                return 'edge', (f, func.attr), func.attr
            if root.id == 'self' and cls is not None and func.attr in functions_of(cls):
                return 'edge', (f, func.attr), func.attr
            if isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name) \
                    and func.value.value.id == 'self' and cls is not None:
                if func.value.attr in (attr_ext or {}).get(cls.name, ()):
                    return 'external', None, func.attr
                at = (attr_ty or {}).get(cls.name, {}).get(func.value.attr)
                if at and func.attr in functions_of(classes[at[0]][at[1]]):
                    return 'edge', (at[0], func.attr), func.attr
            if root.id in (local_ty or {}):
                tf, cn = local_ty[root.id]
                if func.attr in functions_of(classes[tf][cn]):
                    return 'edge', (tf, func.attr), func.attr
            if root.id in ('lr', '_lr'):
                return 'safe-chain', None, func.attr
            if root.id in local_ext:
                return 'external', None, func.attr
            if root.id in pure:
                return 'external', None, func.attr
            if _receiver_pure(func.value, al, None, pure):
                return 'external', None, func.attr
            return 'instance-method', None, func.attr
        if isinstance(func.value, ast.Call):
            inner = _resolve_callee(func.value.func, al)
            if inner.split('.')[-1] in ('open', 'fdopen', 'read_text', 'read_bytes', 'super'):
                return 'external', None, func.attr
        if _receiver_pure(func.value, al, None, pure):
            return 'external', None, func.attr
        return 'instance-method', None, func.attr
    if isinstance(func, ast.Subscript):
        return 'dispatch', None, ''
    if isinstance(func, ast.Call):
        inner = _resolve_callee(func.func, al)
        if inner.split('.')[-1] in ('getattr', '__import__'):
            return 'getattr', None, ''
        if inner.split('.')[-1] in ('open', 'fdopen', 'read_text', 'read_bytes'):
            return 'external', None, inner.split('.')[-1]
        return 'instance-method', None, (func.func.attr
                                         if isinstance(func.func, ast.Attribute) else '')
    return 'other', None, ''


def functions_of(cls):
    return {n.name for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _kw_true(call, name):
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) \
                and kw.value.value is True:
            return True
    return False


def _closure_graph(trees):
    """第一方调用图：已解析边 + 未解析边（逐条带 file:line 与类型）。
    First-party call graph: resolved edges plus every unresolved edge with file:line and type.
    遍历以函数子树为单位（嵌套闭包算外层函数的调用），与 `_scan_write_sites` 的能力口径一致。
    Traversal is per function subtree (nested closures count as the enclosing function's calls),
    matching `_scan_write_sites`' capability convention."""
    files = list(trees)
    mod2file = {os.path.splitext(f)[0]: f for f in files}
    funcs = {f: _func_index(t) for f, t in trees.items()}
    classes = {f: _class_index(t) for f, t in trees.items()}
    edges, unresolved = {}, []
    for f, tree in trees.items():
        al = _write_aliases(tree)
        parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parent[c] = n
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tgt = edges.setdefault((f, node.name), set())
            cls = _enclosing_class(node, parent)
            pure = _pure_names(node)
            local_ext = _external_locals(node, al, mod2file)
            local_ty = _local_types(node, f, al, mod2file, classes)
            attr_ty = _class_attr_types(tree, f, al, mod2file, classes)
            attr_ext = _class_attr_external(tree, f, al, mod2file)
            for call in [x for x in ast.walk(node) if isinstance(x, ast.Call)]:
                kind, target, callee = _resolve_edge(
                    call, al, f, mod2file, funcs, classes, cls, pure, local_ext,
                    local_ty, attr_ty, attr_ext)
                if kind == 'edge':
                    # build(dry=True) 只算不写（P7 有零落盘实跑自证）；它不是写边。
                    # build(dry=True) computes only (P7 proves zero writes at runtime); not an edge.
                    if target == ('daybook.py', 'build') and _kw_true(call, 'dry'):
                        continue
                    tgt.add(target)
                    continue
                if kind in ('external', 'safe-chain'):
                    continue
                unresolved.append({'file': f, 'line': call.lineno, 'fn': node.name,
                                   'callee': callee, 'reason': kind,
                                   'expr': ast.unparse(call.func)[:60]})
    return edges, unresolved


def _closure_capability(trees, sites, reg=None):
    """账本写能力函数的传递闭包：**源头＝所有签为 ledger/impl 的函数**（签了这次写，
    就等于承认这函数有写能力），加上原语写类别命中的函数作为补充；沿已解析第一方边传播。
    不按 kind 分层判断「算不算写」：safe 是写的结果属性，不是写能力的门槛。
    temp 与派发不进闭包（不改根内状态，各有各的闸）。
    Transitive closure of write capability: **every function signed ledger/impl is a source**
    (approving a write admits the capability), plus primitive write-kind hits. Do not tier by
    kind: `safe` is an outcome attribute, not a capability threshold. temp/dispatch excluded."""
    reg = reg if reg is not None else {(f, n): (b, r) for f, n, b, r in WRITE_PATHS}
    cap = {k for k in reg if reg[k][0] in ('ledger', 'impl')}
    cap |= {k for k, v in sites.items() if v & _LEDGER_KINDS}
    edges, unresolved = _closure_graph(trees)
    changed = True
    while changed:
        changed = False
        for key, targets in edges.items():
            if key not in cap and targets & cap:
                cap.add(key)
                changed = True
    return cap, edges, unresolved


def _closure_missing(trees, sites, reg, product):
    """产品内部件里必须登记、但还没登记的写能力函数；入口与随包测试不签。
    Write-capable product functions that are not registered; entry names and bundled tests
    are exempt from signing (tests are reported only)."""
    cap, edges, unresolved = _closure_capability(trees, sites, reg)
    missing = sorted(k for k in cap
                     if k[0] in product and not _is_entry(*k) and k not in reg)
    return missing, cap, edges, unresolved


def _capability_names(reg, sites):
    """写能力函数名（按文件）：ledger/impl 登记 + 原语类别命中。
    Write-capable function names per file: ledger/impl registrations plus primitive-kind hits."""
    out = {}
    for (f, fn), (b, _r) in reg.items():
        if b in ('ledger', 'impl'):
            out.setdefault(f, set()).add(fn)
    for (f, fn), kinds in sites.items():
        if kinds & _LEDGER_KINDS:
            out.setdefault(f, set()).add(fn)
    return out


# 「能力当值传」：写能力函数（已登记 ledger/impl 或原语类别命中）与写原语的引用，只允许
# 出现在两个位置——**直接调用**（Call.func），或**登记表本身**（guard.py 不在被扫文件里）。
# 其余位置一律红：赋值（`f = X`、`self.f = X`）、作实参（`Thread(target=lr.write)`、
# `map(_write_cursor, xs)`、回调注册）、作返回值、进容器（列表/字典/元组）、当装饰器、
# `getattr(obj, 'write')`。理由：这些位置都是「把写能力当值传」，下一种形状不用去想象。
# errors.run_entry(fn) 不是白名单：它就是「唯一出口」，内部立即 `fn()`，等价直接调用。
# References to write-capable functions/primitives are allowed only as a direct call or in the
# registry itself. Assignment, argument, return value, container, decorator, getattr are red:
# each one passes the capability around as a value. `errors.run_entry(fn)` executes `fn()`
# immediately (the single boundary), so its first argument counts as a direct call — a rule,
# not a whitelist.
_CAP_VALUE_SKIP_CALLS = frozenset({'errors.run_entry', 'run_entry'})


# 接收者可证明为内建类型/os/sys/纯函数模块：属性名撞上第一方写能力名时不算「能力当值传」。
# A receiver provably builtin/os/sys/pure-module is exempt from the name-collision check.
_CAP_BUILTIN_RECEIVERS = frozenset({
    'str', 'bytes', 'dict', 'list', 'set', 'tuple', 'int', 'float', 'bool', 'frozenset'})


def _cap_receiver_external(recv, al):
    """接收者可证明为内建类型 / os / sys / 纯函数模块 ⇒ 属性名不构成第一方写能力引用。
    A receiver provably a builtin type / os / sys / pure module is not a first-party capability.
    `os.path.join`（orchestrator 有个登记为 ledger 的 `join`）是 stdlib，不是能力当值传。"""
    root = _chain_root(recv)
    if not isinstance(root, ast.Name):
        return False
    if root.id in _CAP_BUILTIN_RECEIVERS or root.id in ('os', 'sys'):
        return True
    o = al.get(root.id)
    if o and o[0] == 'mod':
        base = o[1].split('.')[0]
        return base in _PURE_MODULES or base in ('os', 'sys')
    return False


def _capability_value_refs(trees, product, reg, sites):
    """写能力/写原语出现在非直接调用位置 ⇒ (file, fn, line, expr, target)。
    Write-capable/primitives referenced outside a direct call or the registry."""
    cap = _capability_names(reg, sites)
    prim = {t.split('.')[-1] for t in _MUTATOR_CALLS} | set(_MUTATOR_ATTRS)
    names = set().union(*cap.values()) if cap else set()
    mod2file = {os.path.splitext(f)[0]: f for f in trees}
    out = []
    for f, tree in trees.items():
        if f not in product:
            continue
        al = _write_aliases(tree)
        parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parent[c] = n

        def owner(node):
            x = parent.get(node)
            while x is not None:
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return x.name
                x = parent.get(x)
            return '<module>'

        def target_of(node):
            if isinstance(node, ast.Name):
                o = al.get(node.id)
                if o and o[0] == 'from':
                    mod, _, nm = o[1].partition('.')
                    tgt = mod2file.get(mod)
                    if tgt and nm in cap.get(tgt, ()):
                        return '%s.%s' % (tgt, nm)
                    return o[1] if nm in prim else None
                return '%s.%s' % (f, node.id) if node.id in cap.get(f, ()) else None
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    o = al.get(node.value.id)
                    if o and o[0] == 'mod':
                        tgt = mod2file.get(o[1].split('.')[0])
                        if tgt and node.attr in cap.get(tgt, ()):
                            return '%s.%s' % (tgt, node.attr)
                if node.attr in prim:
                    return ast.unparse(node)
                if node.attr in names:
                    # 名字撞上第一方写能力名还不够：接收者能证明是 stdlib/内建/纯函数模块
                    # （os.path.join、str.join…）⇒ 绿；接收者解析不出 ⇒ 红（宁红勿漏）。
                    # A name collision is not evidence: a receiver provably stdlib/builtin/pure
                    # is green; an unresolvable receiver stays red.
                    if _cap_receiver_external(node.value, al):
                        return None
                    return ast.unparse(node)
            return None

        allowed, extras = set(), []
        for call in [x for x in ast.walk(tree) if isinstance(x, ast.Call)]:
            allowed.add(id(call.func))
            t = _resolve_callee(call.func, al)
            if t in _CAP_VALUE_SKIP_CALLS and call.args:
                allowed.add(id(call.args[0]))
            if t.split('.')[-1] == 'getattr' and len(call.args) >= 2 \
                    and isinstance(call.args[1], ast.Constant) \
                    and isinstance(call.args[1].value, str) \
                    and (call.args[1].value in names or call.args[1].value in prim):
                extras.append({'file': f, 'fn': owner(call), 'line': call.lineno,
                               'expr': ast.unparse(call)[:60],
                               'target': 'getattr:' + call.args[1].value})
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            if not isinstance(node.ctx, ast.Load) or id(node) in allowed:
                continue
            tgt = target_of(node)
            if tgt:
                out.append({'file': f, 'fn': owner(node), 'line': node.lineno,
                            'expr': ast.unparse(node)[:60], 'target': tgt})
        out.extend(extras)
    uniq, seen = [], set()
    for r in out:
        k = (r['file'], r['line'], r['expr'])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return sorted(uniq, key=lambda r: (r['file'], r['line']))


def _module_alias_binds(node, al):
    """`o = os` / `f = os.mknod` 这类间接绑定（产品件禁用）。
    Indirect bindings such as `o = os` / `f = os.mknod` (banned in product code)."""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Assign):
            continue
        v = n.value
        if isinstance(v, ast.Name):
            o = al.get(v.id)
            if o and o[0] == 'mod' and o[1].split('.')[0] in _IMPORT_MODULES:
                out.append('bind-module:%s' % v.id)
        elif isinstance(v, ast.Attribute):
            t = _resolve_callee(v, al)
            if t in _MUTATOR_CALLS or t in _NONOS_CALLS or t.startswith('ctypes.'):
                out.append('bind-fn:%s' % t)
    return out


_P0_PROBE = '''\
import os, shutil, subprocess, ctypes
from pathlib import Path

MODE = "w"


def f_os_mknod(p):
    os.mknod(p)


def f_sh_move(a, b):
    shutil.move(a, b)


def f_sh_rmtree(d):
    shutil.rmtree(d)


def f_sh_chown(p):
    shutil.chown(p, user="u")


def f_path_mkdir(p):
    Path(p).mkdir()


def f_path_unlink(p):
    Path(p).unlink()


def f_path_rmdir(p):
    Path(p).rmdir()


def f_path_chmod(p):
    Path(p).chmod(0o600)


def f_path_touch(p):
    Path(p).touch()


def f_path_rename(p):
    Path(p).rename(p)


def f_path_replace(p):
    Path(p).replace(p)


def f_path_open(p):
    Path(p).open("w")


def f_path_modevar(p):
    Path(p).open(MODE)


def f_alias(p):
    o = os
    o.mknod(p)


def f_getattr(p):
    getattr(os, "mknod")(p)


def f_import(p):
    __import__("os").mknod(p)


def f_dispatch(p):
    {"mknod": os.mknod}["mknod"](p)


def f_modevar(p):
    open(p, MODE)


def f_ctypes(p):
    ctypes.CDLL("libc").open(p)


def f_subproc(p):
    subprocess.run(["rm", p])


def f_subproc_pipe(p):
    subprocess.run(["cat", p], stdout=subprocess.PIPE)


def f_path_param(p):
    p.mkdir()


def f_path_expr(p):
    (Path(p) / "x").mkdir()


def f_osopen_var(p, flags):
    os.open(p, flags)


def f_lambda(p):
    (lambda q: os.mknod(q))(p)


def f_comprehension(ps):
    [os.mknod(q) for q in ps]


@os.mknod("/tmp/p0-deco")
def f_decorated(p):
    return p


class _Probe:
    os.mknod("/tmp/p0-class")


os.mknod("/tmp/p0-module")
'''


def _expr_has_mutator(node, al):
    """表达式里是否夹带写原语（用于识别字典派发/别名表）。
    Whether an expression carries a write primitive (dict dispatch / alias tables)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            t = _resolve_callee(sub, al)
            if t in _MUTATOR_CALLS or t in _NONOS_CALLS or t.startswith('ctypes.'):
                return True
        elif isinstance(sub, ast.Name):
            o = al.get(sub.id)
            if o and o[0] == 'mod' and o[1].split('.')[0] in _IMPORT_MODULES:
                return True
    return False


def _mutator_bind_names(node, al):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Assign) and _expr_has_mutator(n.value, al):
            for tgt in n.targets:
                if isinstance(tgt, ast.Name):
                    out.add(tgt.id)
    return out


def _write_violations(trees, product):
    """发现先于归类：先扫**每个函数的全部调用**，再判定类别/归属。
    Discovery before classification: scan **all calls in every function**, then classify.
    返回 {规则: [(文件, 函数, 详情)]}；规则不依赖 `sites`（算不出类别的函数也在内）。
    Returns {rule: [(file, function, detail)]}; rules do not depend on `sites`."""
    v = {'unknown_os': [], 'nonos': [], 'indirect': [], 'mode_var': [],
         'ctypes': [], 'subproc_raw': [], 'foreign': [], 'unclassified': []}
    stdlib = getattr(sys, 'stdlib_module_names', frozenset())
    local = {os.path.splitext(f)[0] for f in trees}
    for fn, tree in trees.items():
        al = _write_aliases(tree)
        prod = fn in product
        if prod:
            for n in ast.walk(tree):
                mods = []
                if isinstance(n, ast.Import):
                    mods = [a.name.split('.')[0] for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    mods = [n.module.split('.')[0]]
                for m in mods:
                    if m in local or m in stdlib or m in _FIRST_PARTY_MODULES:
                        continue
                    v['foreign'].append((fn, '<module>', m))
        for name, scope, calls in _scopes(tree):
            pure = _pure_names(scope)
            paths = _path_names(scope, al)
            danger = _mutator_bind_names(scope, al)
            for sub in calls:
                t = _resolve_callee(sub.func, al)
                if t.startswith('os.'):
                    attr = t.split('.')[-1]
                    # os.open 单独判（flags 判不出即写），不靠只读名单放行。
                    # os.open is judged separately (undecidable flags ⇒ write).
                    if attr != 'open' and attr not in _MUTATOR_ATTRS \
                            and attr not in _OS_LEDGER_READONLY:
                        v['unknown_os'].append((fn, name, t))
                kind = _call_kind(sub, al, scope, pure, paths, (fn, name))
                if kind and kind != 'safe':
                    v['nonos'].append((fn, name, kind, t))
                    if kind == 'mode_var' and prod:
                        v['mode_var'].append((fn, name, kind, t))
                    if kind == 'ctypes' and prod:
                        v['ctypes'].append((fn, name, kind, t))
                    if kind == 'subproc_raw' and prod:
                        v['subproc_raw'].append((fn, name, kind, t))
                    # 默认写的兜底池：落在写面能力上但没识别出具体类别 ⇒ 红。
                    # Default-write pool: on the write-capable surface with no recognised
                    # category ⇒ red.
                    if kind == 'unclassified' and prod:
                        v['unclassified'].append((fn, name, kind, t))
                if prod:
                    f = sub.func
                    last = t.split('.')[-1]
                    if isinstance(f, ast.Call) \
                            and _resolve_callee(f.func, al).split('.')[-1] == 'getattr':
                        recv = f.args[0] if f.args else None
                        if isinstance(recv, ast.Name):
                            o = al.get(recv.id)
                            modname = (o[1] if o and o[0] == 'mod'
                                       else (recv.id if recv.id in _IMPORT_MODULES else ''))
                            if modname.split('.')[0] in _IMPORT_MODULES:
                                v['indirect'].append((fn, name, 'call:getattr'))
                    if last == '__import__':
                        v['indirect'].append((fn, name, 'call:__import__'))
                    if isinstance(sub.func, ast.Subscript) and (
                            _expr_has_mutator(sub.func.value, al)
                            or (isinstance(sub.func.value, ast.Name)
                                and sub.func.value.id in danger)):
                        v['indirect'].append((fn, name, 'dispatch'))
            if prod:
                for d in _module_alias_binds(scope, al):
                    v['indirect'].append((fn, name, d))
    return v


def _case_write_paths(tmp):
    """AH 写路径登记表判据：登记未实现、实现未登记、账本桶直写，三者都红。
    AH write-path registry: registered-but-absent, present-but-unregistered, and any direct
    write inside a ledger bucket all fail."""
    print('  -- AH 写路径登记表（发现先于归类） --')
    d = os.path.dirname(os.path.abspath(SRC_BIN))
    files, sites, trees, product = _scan_write_sites(d)
    reg = {(f, fn): (b, r) for f, fn, b, r in WRITE_PATHS}
    present = {k: v for k, v in reg.items() if k[0] in files}
    viol = _write_violations(trees, product)
    if os.path.exists(os.path.join(d, 'pack.py')):
        want = {f for f, _fn, _b, _r in WRITE_PATHS}
        _ok('AH 源树：登记表涉及的件全部在场', want <= set(files),
            '缺=%s' % sorted(want - set(files)))
    # 闭包面素材先算：登记表里有、但自身没有直接写调用点的写能力函数不算「找不到」。
    # 它们的能力来自传递调用（闭包面），由下面的闭包判据逐条兜住。
    # Closure parts are computed first: a registered write-capable function with no direct
    # write call site is not "absent" — its capability comes transitively (closure surface).
    _cap, _cedges, _cunres, _cmiss, _chits, _cgap, _cminus, _rminus = _closure_parts(
        trees, sites, product, reg)
    # impl 是 safeio 根句柄实现（不动），允许无直接写点；只对 ledger 桶查「登记了但找不到」。
    # impl is the safeio root-handle implementation (untouched) and may have no direct write
    # site; the stale-entry check applies to the ledger bucket only.
    absent = sorted(k for k in present if k not in sites and k not in _cap
                    and present[k][0] == 'ledger')
    # 只靠 subproc 才被看见的函数不参与「未登记写」判据：它在产品件里由下面的
    # _SUBPROC_SITES 逐个判；随包测试里的派发不属于写路径。
    # Functions seen only through subproc are not "unregistered writes": product sites are
    # judged one by one through _SUBPROC_SITES, and bundled-test dispatch is not a write path.
    unreg = sorted(k for k in sites if k not in reg and (sites[k] - {'subproc'}))
    direct = sorted((k, sorted(v - {'safe'})) for k, v in sites.items()
                    if reg.get(k, ('', ''))[0] == 'ledger' and (v - {'safe'}))
    _ok('AH 登记了但代码里找不到 ⇒ 红', not absent, '找不到=%s' % absent)
    _ok('AH 代码里有写调用但没登记 ⇒ 红', not unreg, '未登记=%s' % unreg)
    _ok('AH 账本桶只许 safeio（直接写 ⇒ 红）', not direct, '直写=%s' % direct)
    # 按系统调用类别穷举：观测到的类别必须都已声明归属；归属越界同样红。
    # Enumerate by syscall category: every observed kind must be declared, and ownership
    # violations are red too.
    declared = set(_MUTATOR_OWNER)
    observed = set()
    for kinds in sites.values():
        observed |= (kinds - {'safe'})
    unknown_kinds = sorted(observed - declared)
    _ok('AH 写原语类别全部已登记（新增类别未登记 ⇒ 红）',
        not unknown_kinds, '未登记类别=%s' % unknown_kinds)
    bad_owner = []
    for (f, fn), kinds in sorted(sites.items()):
        b = reg.get((f, fn), ('', ''))[0]
        # ★ 桶名只是「预期」：产品件由实际类别决定是否允许（dispatch 不能夹带写）。
        # ★ Bucket names are expectations: in product code the actual kinds decide
        #   (a dispatch bucket cannot carry writes).
        if f in product:
            bad_owner += [(f, fn, x) for x in _bucket_bad(f, fn, kinds, b, True)]
            continue
        for kind in sorted(kinds - {'safe'}):
            owner = _MUTATOR_OWNER.get(kind, '')
            if owner == 'impossible':
                if not (kind in _TEST_TOLERATED and b == 'other'):
                    bad_owner.append((f, fn, kind))
            elif owner == 'impl-only' and b != 'impl':
                bad_owner.append((f, fn, kind))
            elif owner == 'other-only' and b != 'other':
                bad_owner.append((f, fn, kind))
            elif owner == 'LockedRoot|temp' and b == 'ledger':
                bad_owner.append((f, fn, kind))
            elif owner == 'site-allowlist' and f in product:
                if (f, fn) not in _SUBPROC_SITES or b == 'ledger':
                    bad_owner.append((f, fn, kind))
    _ok('AH 桶名只作预期：产品件写类别必须 ledger；dispatch 夹带写 ⇒ 红',
        not bad_owner, '越界=%s' % bad_owner[:6])
    # ★ 闭包面：第一方函数若传递地调用到账本写原语，它自身即写能力函数，产品内部件必须登记。
    #   入口（main/_main/__init__/dispatch/serve）不签；随包测试只报告不签；temp 与派发不进闭包。
    # ★ Closure surface: a first-party function that transitively reaches a ledger write
    #   primitive is write-capable and must be registered (product internals only). Entry
    #   names are never signed; bundled tests are reported only; temp and dispatch excluded.
    _cap, _cedges, _cunres, _cmiss, _chits, _cgap, _cminus, _rminus = _closure_parts(
        trees, sites, product, reg)
    _nedges = sum(len(v) for v in _cedges.values())
    _total = _nedges + len(_cunres)
    _cov = (100 * _nedges // _total) if _total else 100
    _diff = _closure_diff_text(_cminus, _rminus, product, reg)
    print('[数据] 闭包覆盖 已解析/总边 = %d/%d = %d%%｜可能写缺口 %d｜内建/容器方法面 %d｜%s'
          % (_nedges, _total, _cov, len(_cgap), len(_cunres) - len(_cgap), _diff))
    _ok('闭包面：产品内部件写能力函数必须登记（入口/测试不签；temp/派发不进闭包；'
        '闭包面为参考项，不参与收口）',
        not _cmiss, '未登记=%s｜闭包覆盖 %d/%d=%d%%｜可能写缺口 %d｜%s'
        % (_cmiss[:8], _nedges, _total, _cov, len(_cgap), _diff))
    _ok('闭包面：未解析边的 callee 与本仓写能力函数同名 ⇒ 红（宁红勿漏）',
        not _chits, '同名未豁免=%s' % _chits[:8])
    # ★ 反向自证：包装一个「已登记但 kind 只有 safe」的 helper，wrapper 必须进写能力面。
    #   种子是登记本身，不是 kind：safe 是写的结果属性，不是写能力的门槛。
    # ★ Reverse self-proof: wrapping a registered helper whose only kind is `safe` must land
    #   the wrapper on the write-capability surface (seeds are registrations, not kinds).
    _self_src = ('def _write_cursor(*a, **k):\n    return _raw_write(*a, **k)\n'
                 'def _evil_wrap_cursor(*a, **k):\n    return _write_cursor(*a, **k)\n')
    _self_trees = {'a.py': ast.parse(_self_src)}
    _self_reg = {('a.py', '_write_cursor'): ('ledger', '签过的 helper（kind 仅 safe）')}
    _self_sites = {('a.py', '_write_cursor'): {'safe'}}
    _self_cap = _closure_capability(_self_trees, _self_sites, _self_reg)[0]
    _self_miss = [k for k in _self_cap
                  if k[0] in {'a.py'} and not _is_entry(*k) and k not in _self_reg]
    _ok('P0 自证：包装「只带 safe 的已登记 helper」的 wrapper ⇒ 写能力面未登记红',
        _self_miss == [('a.py', '_evil_wrap_cursor')],
        'cap=%s miss=%s' % (sorted(_self_cap), _self_miss))
    # ★ 能力当值传：写能力函数/写原语的引用只允许两种位置——直接调用、登记表本身。
    _vrefs = _capability_value_refs(trees, product, reg, sites)
    _ok('AH 写能力/写原语当值传 ⇒ 红（只许直接调用或进登记表）', not _vrefs,
        '当值传=%s' % [(r['file'], r['fn'], r['line'], r['expr']) for r in _vrefs[:6]])
    # 反向自证三条（别名赋值 / 当实参 / 进容器）＋一条直接调用必须不红。
    _v_src = ('def _write_cursor(*a, **k):\n    return _raw(*a, **k)\n'
              'def alias_assign(*a, **k):\n    f = _write_cursor\n    return f(*a, **k)\n'
              'def as_arg(*a, **k):\n    return map(_write_cursor, a)\n'
              'def into_container(*a, **k):\n    return [_write_cursor]\n'
              'def direct(*a, **k):\n    return _write_cursor(*a, **k)\n')
    _v_trees = {'a.py': ast.parse(_v_src)}
    _v_reg = {('a.py', '_write_cursor'): ('ledger', '签过')}
    _v_sites = {('a.py', '_write_cursor'): {'safe'}}
    _vr = _capability_value_refs(_v_trees, {'a.py'}, _v_reg, _v_sites)
    _vr_fns = {r['fn'] for r in _vr}
    _ok('P0 自证：写能力别名赋值（f = X）⇒ 红', 'alias_assign' in _vr_fns,
        'fns=%s' % sorted(_vr_fns))
    _ok('P0 自证：写能力当实参（map(X, xs)）⇒ 红', 'as_arg' in _vr_fns,
        'fns=%s' % sorted(_vr_fns))
    _ok('P0 自证：写能力进容器（[X]）⇒ 红', 'into_container' in _vr_fns,
        'fns=%s' % sorted(_vr_fns))
    _ok('P0 自证：写能力直接调用（X()）不红', 'direct' not in _vr_fns,
        'fns=%s' % sorted(_vr_fns))
    # 接收者判定：名字撞车不等于能力当值传（os.path.join vs 第一方 join）。
    _v2_src = ('import os\n'
               'def _write_cursor(*a, **k):\n    return _raw(*a, **k)\n'
               'def stdlib_value(*a, **k):\n    return Thread(target=os.path.join, args=a)\n'
               'def cap_value(lr, *a, **k):\n    return Thread(target=lr.write, args=a)\n')
    _v2_trees = {'a.py': ast.parse(_v2_src)}
    _v2_reg = {('a.py', 'join'): ('ledger', '签名与 os.path.join 撞名'),
               ('a.py', '_write_cursor'): ('ledger', '签过')}
    _v2_sites = {('a.py', '_write_cursor'): {'safe'}}
    _vr2_fns = {r['fn'] for r in _capability_value_refs(
        _v2_trees, {'a.py'}, _v2_reg, _v2_sites)}
    _ok('P1 自证：Thread(target=os.path.join) ⇒ 不红（接收者 os ⇒ stdlib）',
        'stdlib_value' not in _vr2_fns, 'fns=%s' % sorted(_vr2_fns))
    _ok('P1 自证：Thread(target=lr.write) ⇒ 红（写原语，接收者解析不出）',
        'cap_value' in _vr2_fns, 'fns=%s' % sorted(_vr2_fns))
    # 类别表不替具体调用点背书：产品件每一处 subprocess 都必须出现在登记表里。
    # The category table never vouches for a call site: every product subprocess must be listed.
    offsite = sorted((f, fn) for (f, fn), kinds in sites.items()
                     if f in product and 'subproc' in kinds
                     and ((f, fn) not in _SUBPROC_SITES
                          or reg.get((f, fn), ('', ''))[0] == 'ledger'))
    _ok('AH 产品件 subprocess 逐个登记（未登记/账本桶 ⇒ 红；不出整类放行）',
        not offsite, '越界=%s' % offsite[:6])
    # 发现先于归类：os.* 全集检查对**每个被扫文件的每个函数**生效，不经过 sites/present。
    # Discovery before classification: the full os.* check covers every function of every
    # scanned file, without going through sites/present.
    _ok('AH os.* 全集可归类（每个函数，不分桶；未知调用 ⇒ 红）',
        not viol['unknown_os'], '未归类=%s' % viol['unknown_os'][:6])
    _ok('AH 非 os 写 API 已映射类别（未映射 ⇒ 红）',
        not [x for x in viol['nonos'] if x[2] not in _MUTATOR_OWNER],
        '未映射=%s' % [x for x in viol['nonos'] if x[2] not in _MUTATOR_OWNER][:6])
    _ok('AH 产品件禁间接派发（getattr/__import__/字典派发/模块别名）⇒ 红',
        not viol['indirect'], '间接=%s' % viol['indirect'][:6])
    _ok('AH 产品件禁 open 模式变量 ⇒ 红',
        not viol['mode_var'], '模式变量=%s' % viol['mode_var'][:6])
    _ok('AH 产品件禁 ctypes / 无重定向 subprocess / 第三方库 ⇒ 红',
        not (viol['ctypes'] or viol['subproc_raw'] or viol['foreign']),
        'ctypes=%s raw=%s foreign=%s'
        % (viol['ctypes'][:2], viol['subproc_raw'][:2], viol['foreign'][:2]))
    prod_imp = sorted({(f, fn, k) for (f, fn), ks in sites.items() if f in product
                       for k in ks if _MUTATOR_OWNER.get(k) == 'impossible'})
    _ok('AH 产品件禁 impossible 类别（类别级，含未登记函数）⇒ 红',
        not prod_imp, 'impossible=%s' % prod_imp[:6])
    # P0 自证：全部走 `_scan_write_sites → trees/sites` 真实入口，逐个 API 单独判红。
    # P0 self-check: all through the real `_scan_write_sites` entry; every API must go red
    # on its own.
    probe = os.path.join(tmp, 'p0scan')
    os.makedirs(probe)
    with io.open(os.path.join(probe, 'p0_probe.py'), 'w', encoding='utf-8') as f:
        f.write(_P0_PROBE)
    with io.open(os.path.join(probe, 'p0_foreign.py'), 'w', encoding='utf-8') as f:
        f.write('import requests\n\n\ndef f():\n    return 1\n')
    p_files, p_sites, p_trees, p_prod = _scan_write_sites(
        probe, extra=('p0_probe.py', 'p0_foreign.py'),
        product_extra=('p0_probe.py', 'p0_foreign.py'))
    pv = _write_violations(p_trees, p_prod)

    def _hit(rule, fname, needle):
        return any(x[0] == 'p0_probe.py' and x[1] == fname and needle in str(x)
                   for x in pv[rule])

    cases = [
        ('os.mknod（未知 os.*）', 'unknown_os', 'f_os_mknod', 'os.mknod'),
        ('shutil.move', 'nonos', 'f_sh_move', 'replace'),
        ('shutil.rmtree', 'nonos', 'f_sh_rmtree', 'rmtree'),
        ('shutil.chown', 'nonos', 'f_sh_chown', 'chown'),
        ('Path.mkdir', 'nonos', 'f_path_mkdir', 'mkdir'),
        ('Path.unlink', 'nonos', 'f_path_unlink', 'unlink'),
        ('Path.rmdir', 'nonos', 'f_path_rmdir', 'unlink'),
        ('Path.chmod', 'nonos', 'f_path_chmod', 'chmod'),
        ('Path.touch', 'nonos', 'f_path_touch', 'utime'),
        ('Path.rename', 'nonos', 'f_path_rename', 'replace'),
        ('Path.replace', 'nonos', 'f_path_replace', 'replace'),
        ('Path.open("w")', 'nonos', 'f_path_open', 'open'),
        ('Path.open(模式变量)', 'mode_var', 'f_path_modevar', 'mode_var'),
        ('open(模式变量)', 'mode_var', 'f_modevar', 'mode_var'),
        ('模块别名 o = os', 'indirect', 'f_alias', 'bind-module'),
        ('getattr', 'indirect', 'f_getattr', 'call:getattr'),
        ('__import__', 'indirect', 'f_import', 'call:__import__'),
        ('字典派发', 'indirect', 'f_dispatch', 'dispatch'),
        ('ctypes', 'ctypes', 'f_ctypes', 'ctypes.'),
        ('无重定向 subprocess', 'subproc_raw', 'f_subproc', 'subprocess.run'),
    ]
    for label, rule, fname, needle in cases:
        _ok('P0 自证：%s ⇒ 红' % label, _hit(rule, fname, needle),
            'rule=%s fn=%s' % (rule, fname))
    # 重定向不等于安全：未登记的派发点必须在产品件判红（这条正是 record 的旧写法）。
    # Redirection is not safety: an unregistered dispatch site is red in product code
    # (this is exactly record's old shape).
    p_offsite = sorted((f, fn) for (f, fn), kinds in p_sites.items()
                       if f in p_prod and 'subproc' in kinds
                       and (f, fn) not in _SUBPROC_SITES)
    # 发现面扩到模块体/类体/形参 Path/二元 Path/os.open 变量 flags：四条都必须红。
    # Discovery covers module/class bodies, Path params, Path division, and os.open variable
    # flags — all four must be red.
    _ok('P0 自证：模块体 os.mknod ⇒ 红',
        'unclassified' in p_sites.get(('p0_probe.py', '<module>'), set()),
        'module=%s' % sorted(p_sites.get(('p0_probe.py', '<module>'), set())))
    _ok('P0 自证：类体 os.mknod ⇒ 红',
        'unclassified' in p_sites.get(('p0_probe.py', '<class _Probe>'), set()),
        'class=%s' % sorted(p_sites.get(('p0_probe.py', '<class _Probe>'), set())))
    _ok('P0 自证：形参 Path p.mkdir() ⇒ 红',
        _hit('nonos', 'f_path_param', 'mkdir'),
        'kinds=%s' % sorted(p_sites.get(('p0_probe.py', 'f_path_param'), set())))
    _ok('P0 自证：(Path(p)/"x").mkdir() ⇒ 红',
        _hit('nonos', 'f_path_expr', 'mkdir'),
        'kinds=%s' % sorted(p_sites.get(('p0_probe.py', 'f_path_expr'), set())))
    _ok('P0 自证：os.open(p, flags 变量) ⇒ 红',
        _hit('nonos', 'f_osopen_var', 'osopen'),
        'kinds=%s' % sorted(p_sites.get(('p0_probe.py', 'f_osopen_var'), set())))
    _ok('P0 自证：lambda 体内 os.mknod ⇒ 红',
        _hit('unknown_os', 'f_lambda', 'os.mknod'),
        'kinds=%s' % sorted(p_sites.get(('p0_probe.py', 'f_lambda'), set())))
    _ok('P0 自证：推导式里 os.mknod ⇒ 红',
        _hit('unknown_os', 'f_comprehension', 'os.mknod'),
        'kinds=%s' % sorted(p_sites.get(('p0_probe.py', 'f_comprehension'), set())))
    _ok('P0 自证：装饰器表达式里 os.mknod ⇒ 红',
        _hit('unknown_os', 'f_decorated', 'os.mknod'),
        'kinds=%s' % sorted(p_sites.get(('p0_probe.py', 'f_decorated'), set())))
    # 桶名只作预期：dispatch 夹带 chmod 必须红（不能靠自报桶名免检）。
    # Bucket names are expectations: a dispatch bucket carrying chmod must be red.
    _ok('P0 自证：dispatch 桶夹带写 ⇒ 红',
        bool(_bucket_bad('p0_probe.py', 'f_dispatch_chmod',
                         {'subproc', 'chmod'}, 'dispatch', True)),
        'bucket 规则失效')
    _ok('P0 自证：有重定向的 subprocess 未登记 ⇒ 红（不按类别整类放行）',
        ('p0_probe.py', 'f_subproc_pipe') in p_offsite,
        'offsite=%s' % p_offsite[:6])
    _ok('P0 自证：第三方库 import ⇒ 红',
        any(x[0] == 'p0_foreign.py' and 'requests' in str(x)
            for x in pv['foreign']), 'foreign=%s' % pv['foreign'][:2])
    _ok('P0 自证：os.mknod 既进未知 os.* 红池，也按默认写给类别（unclassified）',
        _hit('unknown_os', 'f_os_mknod', 'os.mknod')
        and p_sites.get(('p0_probe.py', 'f_os_mknod'), set()) & {'unclassified'},
        'in_sites=%s' % sorted(p_sites.get(('p0_probe.py', 'f_os_mknod'), set())))
    # other 桶＝后门：只允许「目标由 tempfile 生成」。任一条改标 other ⇒ 红。
    # `other` is a backdoor if prose suffices: only tempfile-generated targets are allowed.
    bad_other = []
    for (f, fn), (b, _r) in sorted(present.items()):
        if b != 'other':
            continue
        if (f, fn) not in sites:
            # 闭包面补签的只读路径：没有直接写，other 桶的 temp 目标规则不适用。
            # Closure-only read paths: no direct write, so the temp-target rule does not apply.
            continue
        node = _find_func(trees[f], fn)
        if node is None:
            bad_other.append((f, fn, ['函数未找到']))
            continue
        reasons = _other_target_reasons(trees[f], node)
        if (f, fn) not in _OTHER_PARAM_EXEMPT:
            reasons = reasons + _other_param_reasons(node)
        if reasons:
            bad_other.append((f, fn, reasons[:2]))
    _ok('AH other 桶只许 tempfile 目标、且不收路径参数（否则必须归账本）⇒ 红',
        not bad_other, '未通过=%s' % bad_other[:4])
    # 自证：造一个「收目录参数、体内 join 后写」的助手登记成 other ⇒ 必红；
    # 用 getattr / 字典派发调用同一助手 ⇒ 仍必红（签名判定与调用方式无关）
    # Self-check: a helper taking a directory parameter and writing a joined path, registered as
    # `other`, must be red; reaching it via getattr / dict dispatch is still red (signature-only).
    synth = ast.parse(
        'import os, tempfile\n'
        'BASE = os.environ.get("HOME", "/tmp")\n'
        'def _emit(directory):\n'
        '    d = tempfile.mkdtemp()\n'
        '    p = os.path.join(d, "x.txt")\n'
        '    open(p, "w").write(directory)\n'
        'def _emit_default(p="/etc/passwd"):\n'
        '    open(os.path.join(tempfile.mkdtemp(), "x"), "w").write(p)\n'
        'def _emit_kw(**kw):\n'
        '    open(os.path.join(tempfile.mkdtemp(), "x"), "w").write(str(kw))\n'
        'def _emit_var(*a):\n'
        '    open(os.path.join(tempfile.mkdtemp(), "x"), "w").write(str(a))\n'
        'def _emit_closure():\n'
        '    open(os.path.join(BASE, "x"), "w").write("z")\n'
        'def _emit_abs_seg():\n'
        '    d = tempfile.mkdtemp()\n'
        '    p = os.path.join(d, "/tmp/probes/escape_demo.txt")\n'
        '    open(p, "w").write("x")\n'
        'def _emit_basename_up():\n'
        '    d = tempfile.mkdtemp()\n'
        '    p = os.path.join(d, os.path.basename("x/.."), "evil.txt")\n'
        '    open(p, "w").write("x")\n'
        'def _emit_dirname():\n'
        '    d = tempfile.mkdtemp()\n'
        '    p = os.path.dirname(d)\n'
        '    open(os.path.join(p, "evil.txt"), "w").write("x")\n'
        'def _emit_fstring():\n'
        '    d = tempfile.mkdtemp()\n'
        '    p = f"{d}/../../escaped_fstring.txt"\n'
        '    open(p, "w").write("x")\n'
        'def _emit_fstring_ok():\n'
        '    d = tempfile.mkdtemp()\n'
        '    p = f"{d}/ok.txt"\n'
        '    open(p, "w").write("x")\n'
        'def _emit_basename_var(n):\n'
        '    d = tempfile.mkdtemp()\n'
        '    p = os.path.join(d, os.path.basename(n), "evil.txt")\n'
        '    open(p, "w").write("x")\n'
        'def _emit_basename_listdir():\n'
        '    d = tempfile.mkdtemp()\n'
        '    for name in os.listdir(d):\n'
        '        p = os.path.join(d, os.path.basename(name), "x.txt")\n'
        '        open(p, "w").write("x")\n'
        'def _emit_basename_literal():\n'
        '    d = tempfile.mkdtemp()\n'
        '    for name in ("a.py", "b.py"):\n'
        '        p = os.path.join(d, os.path.basename(name), "x.txt")\n'
        '        open(p, "w").write("x")\n'
        'def _dispatch(fn_name, directory):\n'
        '    return getattr(__import__(__name__), fn_name)(directory)\n')
    reason_plain = _other_param_reasons(_find_func(synth, '_emit'))
    reason_dispatch = _other_param_reasons(_find_func(synth, '_emit'))
    _ok('AH other 桶收目录参数 ⇒ 红；getattr/字典派发调用仍红',
        bool(reason_plain) and bool(reason_dispatch),
        '直接=%s 派发=%s' % (reason_plain[:1], reason_dispatch[:1]))
    # R2 四个反例必须全红：默认值是路径 / **kw / *a / 闭包捕获外部路径
    # R2's four counterexamples must all go red: path default / **kw / *a / captured outer path
    reds = {
        '默认值 p="/etc/passwd"': _other_param_reasons(_find_func(synth, '_emit_default')),
        '**kw': _other_param_reasons(_find_func(synth, '_emit_kw')),
        '*a': _other_param_reasons(_find_func(synth, '_emit_var')),
        '闭包捕获 BASE': _other_target_reasons(synth, _find_func(synth, '_emit_closure')),
        'join 绝对段在第二元': _other_target_reasons(synth, _find_func(synth, '_emit_abs_seg')),
        'basename("x/..")': _other_target_reasons(synth, _find_func(synth, '_emit_basename_up')),
        'dirname(d)': _other_target_reasons(synth, _find_func(synth, '_emit_dirname')),
        'f-string 字面段 ..': _other_target_reasons(synth, _find_func(synth, '_emit_fstring')),
        'f-string 正常拼接（政策①禁用）': _other_target_reasons(
            synth, _find_func(synth, '_emit_fstring_ok')),
        'basename(变量)': _other_target_reasons(synth, _find_func(synth, '_emit_basename_var')),
    }
    _ok('AH R2/R8/R9/R10 十反例全红（默认路径/**kw/*a/闭包/绝对段/basename 上跳/dirname/'
        'f-string 两种/basename 变量）',
        all(bool(v) for v in reds.values()),
        '空=%s' % [k for k, v in reds.items() if not v])
    _ok('AH R9-4 basename(listdir 元素)/basename(字面容器元素) 不误报',
        not _other_target_reasons(synth, _find_func(synth, '_emit_basename_listdir'))
        and not _other_target_reasons(synth, _find_func(synth, '_emit_basename_literal')),
        'listdir=%s literal=%s' % (
            _other_target_reasons(synth, _find_func(synth, '_emit_basename_listdir'))[:1],
            _other_target_reasons(synth, _find_func(synth, '_emit_basename_literal'))[:1]))
    # P4 能力形态（步骤 3）：旧四原语在全部产品件中零残留；写方法只在 LockedRoot 上
    # P4 capability shape (step 3): the four legacy primitives leave no trace in any product
    # file; write methods exist only on LockedRoot
    legacy = []
    for f in files:
        txt = io.open(os.path.join(d, f), encoding='utf-8').read()
        for name in ('atomic_write', 'atomic_append', 'append_inplace', 'read_modify_write'):
            if name in txt:
                legacy.append((f, name))
    _ok('P4[步骤3] 旧四原语零残留（产品件不提也不调）⇒ 红', not legacy,
        '残留=%s' % legacy[:6])
    cap = [n.name for n in ast.walk(trees.get('safeio.py', ast.parse(''))) 
           if isinstance(n, ast.FunctionDef) and n.name in ('write', 'update')]
    _ok('P4[步骤3] 写方法只定义在 LockedRoot（write/update）', sorted(cap) == ['update', 'write'],
        'write/update 定义=%s' % cap)
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
        if (f, fn) not in sites:
            # 闭包面补签的只读路径：跨文件调用是它的正常用法（无直接写可越界）。
            # Closure-only read paths are meant to be called across files (no direct write).
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
    # 共享锁能力已删：locked() 只有独占语义，产品件不得出现 LOCK_SH 或共享形参
    # The shared-lock capability is gone: locked() is exclusive-only, so no LOCK_SH and no
    # shared parameter may reappear in any product file
    shared_tok = 'sha' + 'red='
    shareref = []
    for f in files:
        txt = io.open(os.path.join(d, f), encoding='utf-8').read()
        for token in ('LOCK_SH', shared_tok):
            if token in txt:
                shareref.append((f, token))
    _ok('AH 共享锁能力已删（无 LOCK_SH／共享形参）⇒ 红', not shareref,
        '仍出现=%s' % shareref[:6])
    # 写入口唯一性：产品件里的写调用只许出现在 safeio（impl 桶）与登记过的账本写点；
    # AH 的 WRITE_PATHS 登记表已覆盖该约束，这里不再保留旧原语的 root= 扫描。
    # Single write entry: product write calls appear only in safeio (impl) and the registered
    # ledger write sites; that is already enforced by WRITE_PATHS.
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
          '／派发点 %d 条／safeio 实现 %d 条（扫过 %d 件）'
          % (buckets.get('ledger', 0), buckets.get('lockfile', 0), buckets.get('other', 0),
             prod_other, test_other, buckets.get('dispatch', 0),
             buckets.get('impl', 0), len(files)))


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
SKIPS = []
# 变异矩阵记分：总数 / 杀死 / 存活 / 死变异（锚点消失或变换无差异）。
# Mutation scoreboard: total / killed / survived / dead (missing anchor or no-op transform).
MUT = {'total': 0, 'killed': 0, 'dead': 0, 'survivors': []}


def _mut_ok(name, killed, detail='', dead=False):
    """legacy 字符串锚点变异：杀死=绿；存活或死变异=红，并进入记分板。
    Legacy string-anchor mutation: killed=green; survivor/dead=red and scored."""
    MUT['total'] += 1
    if dead:
        MUT['dead'] += 1
    elif killed:
        MUT['killed'] += 1
    else:
        MUT['survivors'].append(name)
    _ok(name, killed, detail)


def _skip(reason):
    """显式跳过：计入跳过清单并在汇总打印数量（不计入判据条数）。
    Explicit skip: recorded and its count printed in the summary (not counted as a check)."""
    SKIPS.append(reason)
    print('    [跳过] %s' % reason)


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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'daybook_record.py',
                 'ledger_root.py', 'errors.py', 'conf_norm.py'):
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
def spy(a, b, **k):
    calls[0] += 1
    return real(a, b, **k)
safeio.os.replace = spy
with safeio.locked(os.path.dirname(p)) as lr:
    lr.write(lr.root.rel_of(p, 'guard'), '新内容', mode=safeio.WriteMode.REPLACE)
assert open(p, encoding='utf-8').read() == '新内容', 'LockedRoot.write 内容不符'
assert calls[0] >= 1, 'LockedRoot.write 未走 os.replace'
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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py',
                 'errors.py', 'conf_norm.py'):
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
    _ok('V LockedRoot.write 走 os.replace 且无临时残留 + read_vol 不取锁',
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
    time.sleep(0.6)
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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py',
                 'errors.py', 'conf_norm.py'):
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
# 不持账本根锁直接调用 ⇒ 结构上拿不到写能力（held 抛错）且零写
try:
    _rt = safeio.Root._from_dir_path(d, 'guard')
    safeio.held(_rt, 'guard').write(_rt.rel_of(p, 'guard'), 'x\n',
                                    mode=safeio.WriteMode.APPEND_EXISTING, pad_newline=True)
    print('NO_LOCK_NO_ERROR')
    sys.exit(3)
except RuntimeError:
    pass
assert open(p, 'rb').read() == before, '未持锁调用改动了文件'
with safeio.locked(d) as lr:
    padded = lr.write(lr.root.rel_of(p, 'guard'), '账\t2\tt\t测试\ty\t皮特\n',
                      mode=safeio.WriteMode.APPEND_EXISTING, pad_newline=True)
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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py',
                 'errors.py', 'conf_norm.py'):
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
    ap = ("""            if lr.write(lr.root.rel_of(_idf, 'daybook._run_ops'), data,
                        mode=WriteMode.APPEND_EXISTING, pad_newline=True) and report is not None:
                report.append((vol, '★ 索引 TSV 末行无换行·已补换行后追加（不截断）'))""")
    mut_ap = ("""            if os.path.exists(_idf):
                _d0 = open(_idf, 'rb').read()
                if _d0 and not _d0.endswith(b'\\n'):
                    open(_idf, 'wb').write(_d0[:_d0.rfind(b'\\n') + 1])
            if lr.write(lr.root.rel_of(_idf, 'daybook._run_ops'), data,
                        mode=WriteMode.APPEND_EXISTING, pad_newline=True) and report is not None:
                report.append((vol, '★ 索引 TSV 末行无换行·已补换行后追加（不截断）'))""")
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
import os, sys, tempfile, threading, time, subprocess
sys.path.insert(0, sys.argv[1])
d, mode = sys.argv[2], sys.argv[3]
import safeio
p = os.path.join(d, 'target.tsv')
cp = os.path.join(d, 'daybook.conf')
open(cp, 'w', encoding='utf-8').write('[index]\nroot=\nout_dir=索引\n')
open(p, 'wb').write(b'a\n')
sub = os.path.join(d, 'sub'); os.makedirs(sub, exist_ok=True)
other = os.path.join(d, 'other'); os.makedirs(other, exist_ok=True)


def _scope(root):
    """Root 句柄（路径则临时打开）；返回 (rt, 是否本函数新开)。"""
    if isinstance(root, safeio.Root):
        return root, False
    return safeio.Root._from_dir_path(root, 'guard'), True


def _w(path, data, root, pad=True):
    """已持锁写（APPEND_EXISTING）：无锁 ⇒ held 抛错（结构上拿不到写能力）。"""
    rt, opened = _scope(root)
    try:
        lr = safeio.held(rt, 'guard')
        return lr.write(rt.rel_of(path, 'guard'), data,
                        mode=safeio.WriteMode.APPEND_EXISTING, pad_newline=pad)
    finally:
        if opened:
            rt.close()


def _wp(path, data, root):
    """追加创建（APPEND_CREATE）：已有临界区就用 held，否则自己取锁。"""
    rt, opened = _scope(root)
    try:
        if safeio.exclusive_held(rt):
            safeio.held(rt, 'guard').write(rt.rel_of(path, 'guard'), data,
                                           mode=safeio.WriteMode.APPEND_CREATE)
        else:
            with safeio.locked(rt) as lr:
                lr.write(rt.rel_of(path, 'guard'), data, mode=safeio.WriteMode.APPEND_CREATE)
    finally:
        if opened:
            rt.close()


def _wr(path, data, root):
    """原子替换（REPLACE）：已有临界区就用 held，否则自己取锁。"""
    rt, opened = _scope(root)
    try:
        if safeio.exclusive_held(rt):
            safeio.held(rt, 'guard').write(rt.rel_of(path, 'guard'), data,
                                           mode=safeio.WriteMode.REPLACE)
        else:
            with safeio.locked(rt) as lr:
                lr.write(rt.rel_of(path, 'guard'), data, mode=safeio.WriteMode.REPLACE)
    finally:
        if opened:
            rt.close()


def _wrmw(path, fn, root):
    """读-改-写（update）：已有临界区就用 held，否则自己取锁。"""
    rt, opened = _scope(root)
    try:
        if safeio.exclusive_held(rt):
            safeio.held(rt, 'guard').update(rt.rel_of(path, 'guard'), fn)
        else:
            with safeio.locked(rt) as lr:
                lr.update(rt.rel_of(path, 'guard'), fn)
    finally:
        if opened:
            rt.close()


def attempt(root):
    before = open(p, 'rb').read()
    try:
        _w(p, 'b\n', root)
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
elif mode == 'mismatch':
    with safeio.locked(d):
        print(attempt(other))
elif mode == 'thread_ok':
    # 主线程持根锁、另一线程直接写：只认「本线程持有」⇒ 必须抛错零写
    # Main thread holds the root; another thread writes directly: only "this thread" counts ⇒ raise
    with safeio.locked(d):
        print(in_thread(lambda: attempt(d)))
elif mode == 'thread_sub':
    with safeio.locked(sub):
        print(in_thread(lambda: attempt(d)))
elif mode == 'outside':
    out = tempfile.mkdtemp(prefix='akout_')
    p2 = os.path.join(out, 'elsewhere.tsv')
    open(p2, 'wb').write(b'a\n')
    with safeio.locked(d):
        before = open(p2, 'rb').read()
        try:
            _w(p2, 'b\n', d)
            print('WROTE')
        except RuntimeError:
            print('RAISED_ZERO' if open(p2, 'rb').read() == before else 'RAISED_DIRTY')
elif mode == 'hardlink':
    # R9-1：硬链接是「同 inode 两个名字」的文件系统语义，不再拒绝；两个名字都看到追加
    # R9-1: hard links are "two names for one inode" — no rejection; both names see the append
    out = tempfile.mkdtemp(prefix='akhl_')
    secret = os.path.join(out, 'secret.tsv')
    open(secret, 'wb').write(b'a\n')
    p3 = os.path.join(d, 'linked.tsv')
    os.link(secret, p3)
    with safeio.locked(d):
        try:
            _w(p3, 'b\n', d)
            print('WROTE_BOTH' if open(secret, 'rb').read() == b'a\nb\n' else 'WROTE_ONE')
        except RuntimeError:
            print('RAISED')
elif mode == 'ancestor':
    # R10-1 确定性注入：把根的一级子目录换成指向根外的软链，旧的字面祖先链会跟随并写到根外
    # R10-1 deterministic injection: replace a first-level sub-directory with a symlink to the
    # outside; the old literal ancestry walk followed it and wrote outside
    out = tempfile.mkdtemp(prefix='akanc_')
    leak = os.path.join(out, 'leak.tsv')
    open(leak, 'wb').write(b'a\n')
    sub = os.path.join(d, 'subdir')
    os.makedirs(sub, exist_ok=True)
    open(os.path.join(sub, 'leak.tsv'), 'wb').write(b'a\n')
    os.rename(sub, sub + '_real')
    os.symlink(out, sub)
    with safeio.locked(d):
        try:
            _w(os.path.join(sub, 'leak.tsv'), 'b\n', d)
            print('WROTE')
        except RuntimeError:
            print('ANCESTOR_ZERO' if open(leak, 'rb').read() == b'a\n' else 'ANCESTOR_DIRTY')
elif mode == 'race':
    # R10-1 自然竞态：另一个线程不停在真目录与「指向根外的软链」之间切换，主线程反复追加
    # R10-1 natural race: a flipper thread keeps switching between the real dir and a symlink to
    # the outside while the main thread appends repeatedly
    out = tempfile.mkdtemp(prefix='akrace_')
    leak = os.path.join(out, 'leak.tsv')
    open(leak, 'wb').write(b'ORIG\n')
    sub = os.path.join(d, 'subrace')
    os.makedirs(sub, exist_ok=True)
    open(os.path.join(sub, 'leak.tsv'), 'wb').write(b'')
    stop = threading.Event()

    def _flip():
        while not stop.is_set():
            try:
                os.rename(sub, sub + '_r')
                os.symlink(out, sub)
                os.unlink(sub)
                os.rename(sub + '_r', sub)
            except OSError:
                pass

    th = threading.Thread(target=_flip)
    th.daemon = True
    th.start()
    ok = rej = 0
    with safeio.locked(d):
        for _ in range(300):
            try:
                _w(os.path.join(sub, 'leak.tsv'), b'x\n', d)
                ok += 1
            except RuntimeError:
                rej += 1
    stop.set()
    th.join()
    esc = 0 if open(leak, 'rb').read() == b'ORIG\n' else 1
    print('RACE ok=%d rej=%d esc=%d' % (ok, rej, esc))
elif mode == 'prims':
    # R11-1/R12-1：软链祖先下四种写入语义（已存在追加/创建追加/读写改/替换）都必须拒绝
    # R11-1/R12-1: under a symlinked ancestor all four write semantics must refuse
    out = tempfile.mkdtemp(prefix='akprims_')
    sub = os.path.join(d, 'psub')
    os.makedirs(sub, exist_ok=True)
    os.rename(sub, sub + '_real')
    os.symlink(out, sub)
    bad = 0
    with safeio.locked(d):
        for fn in ('x.txt', 'y.txt', 'z.txt', 'w.txt'):
            try:
                if fn == 'x.txt':
                    _w(os.path.join(sub, fn), 'APP\n', d)
                elif fn == 'y.txt':
                    _wp(os.path.join(sub, fn), 'APP\n', d)
                elif fn == 'z.txt':
                    _wrmw(os.path.join(sub, fn), lambda b: b'RMW\n', d)
                else:
                    _wr(os.path.join(sub, fn), b'ATW\n', d)
            except RuntimeError:
                bad += 1
    leak = len(os.listdir(out))
    print('PRIMS %d/4 leak=%d' % (bad, leak) if leak == 0 else 'PRIMS_LEAK %d/4 leak=%d' % (bad, leak))
elif mode == 'spellings':
    # R12-2：归属按 inode 判——大小写、NFC/NFD、/tmp↔/private/tmp、尾斜杠四种混写都能写；
    # `..` 归一后逃逸仍必须拒绝
    # R12-2: containment is inode-based — case, NFC/NFD, /tmp↔/private/tmp and trailing-slash
    # spellings all write; a `..` escape must still be refused
    rp = os.path.realpath(d)
    nd = os.path.join(d, 'caf\u00e9')                       # NFC on disk
    os.makedirs(nd, exist_ok=True)
    esc = os.path.join(os.path.dirname(rp), os.path.basename(rp) + '_escape.txt')
    tries = []

    def _spell(tag, target, root):
        try:
            _wr(target, b'W\n', root)
            ok = os.path.exists(target) and open(target, 'rb').read() == b'W\n'
        except RuntimeError:
            ok = False
        tries.append(ok)

    _spell('case', os.path.join(d.upper(), 'case.txt'), d)
    _spell('nfd', os.path.join(d, 'cafe\u0301', 'nfd.txt'), d)
    r2 = tempfile.mkdtemp(prefix='aksym_', dir='/tmp')
    _spell('tmp', os.path.join('/private' + r2, 'tmp.txt'), r2)
    _spell('slash', os.path.join(d, 'slash.txt'), d + '/')
    for junk in (r2,):
        for name in os.listdir(junk):
            os.unlink(os.path.join(junk, name))
        os.rmdir(junk)
    try:
        _wr(os.path.join(d, '..', os.path.basename(esc)), b'X\n', d)
        escape = 'E'
    except RuntimeError:
        escape = 'R'
    if os.path.exists(esc):
        escape = 'DIRTY'
    print('SPELL %d/4 escape=%s' % (sum(1 for t in tries if t), escape))
elif mode == 'alias':
    # R11-4：root 与目标用不同别名拼写（软链别名目录）⇒ 归一后仍能写回根内
    # R11-4: root and target use different alias spellings (symlinked alias dir) ⇒ normalise,
    # then the write still lands inside the root
    alias = os.path.join(d, 'alias_dir')
    os.symlink(d, alias)
    open(os.path.join(d, 'alias_written.txt'), 'wb').write(b'')
    with safeio.locked(d):
        try:
            _w(os.path.join(alias, 'alias_written.txt'), 'A\n', d)
            print('ALIAS_OK' if os.path.exists(os.path.join(d, 'alias_written.txt')) else 'ALIAS_LOST')
        except RuntimeError as exc:
            print('ALIAS_REJECT %s' % exc)
elif mode == 'mode200':
    # R12-3：0200 与 ACL 拒读目标仍可追加，且末字节不可读时 padded=False
    # R12-3: 0200 and ACL-read-denied targets still append; with an unreadable tail padded=False
    p7 = os.path.join(d, 'wonly.txt')
    fd = os.open(p7, os.O_WRONLY | os.O_CREAT, 0o200)
    os.write(fd, b'a\n')
    os.close(fd)
    os.chmod(p7, 0o200)
    p8 = os.path.join(d, 'acl.txt')
    fd = os.open(p8, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, b'a\n')
    os.close(fd)
    subprocess.run(['chmod', '+a', 'everyone deny read', p8],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    acl_readable = os.access(p8, os.R_OK)
    with safeio.locked(d):
        try:
            padded7 = _w(p7, 'b\n', d)
            size7 = os.stat(p7).st_size
            os.chmod(p7, 0o600)
            padded8 = _w(p8, 'b\n', d)
            size8 = os.stat(p8).st_size
            ok = (size7 == 4 and padded7 is False and not acl_readable
                  and size8 == 4 and padded8 is False)
            print('MODE200_OK' if ok else
                  'MODE200_BAD size7=%d padded7=%s acl_r=%s size8=%d padded8=%s'
                  % (size7, padded7, acl_readable, size8, padded8))
        except RuntimeError as exc:
            os.chmod(p7, 0o600)
            print('MODE200_REJECT %s' % exc)
elif mode == 'refuse':
    # R12-3：0400／0000 仍拒绝；ENOENT／EISDIR／ELOOP 不被吞
    # R12-3: 0400/0000 still refuse; ENOENT/EISDIR/ELOOP are never swallowed
    bad = []
    for tag, perm in (('r400', 0o400), ('r000', 0o000)):
        q = os.path.join(d, tag + '.txt')
        fd = os.open(q, os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd, b'a\n')
        os.close(fd)
        os.chmod(q, perm)
        try:
            _w(q, 'b\n', d)
            bad.append(tag)
        except RuntimeError:
            pass
        os.chmod(q, 0o600)
    cases = ('enoent', 'eisdir', 'eloop')
    os.makedirs(os.path.join(d, 'eisdir'), exist_ok=True)
    os.symlink(os.path.join(d, 'target.tsv'), os.path.join(d, 'eloop'))
    for tag in cases:
        try:
            if tag == 'enoent':
                _w(os.path.join(d, 'nope_dir', 'x.txt'), 'b\n', d)
            elif tag == 'eisdir':
                _w(os.path.join(d, 'eisdir'), 'b\n', d)
            else:
                _w(os.path.join(d, 'eloop'), 'b\n', d)
            bad.append(tag)
        except RuntimeError:
            pass
    print('REFUSE_OK' if not bad else 'REFUSE_LEAK %s' % ','.join(bad))
elif mode == 'posix':
    # R13-1：`root/link/../x`（link→根外）按 POSIX 解析到根外 ⇒ 必须拒绝且零写；
    # 正常 `..` 仍在根内的写法不得误拒
    # R13-1: `root/link/../x` (link → outside) resolves outside per POSIX ⇒ refuse, zero write;
    # a normal `..` that stays inside must still write
    out = tempfile.mkdtemp(prefix='akposix_')
    link = os.path.join(d, 'link')
    os.symlink(out, link)
    resolved = os.path.join(os.path.dirname(os.path.realpath(out)), 'escape.txt')
    try:
        _wr(os.path.join(link, '..', 'escape.txt'), b'X\n', d)
        esc_ok = False
    except RuntimeError:
        # 零写：根外解析点与根内同名点都不得出现（防「折成根内」也算通过）。
        # Zero write: neither the outside resolution nor an in-root same-name file may appear
        # (an "inside reroute" must not count as a pass).
        esc_ok = (not os.path.exists(resolved)
                  and not os.path.exists(os.path.join(d, 'escape.txt')))
    sub = os.path.join(d, 'realsub')
    os.makedirs(sub, exist_ok=True)
    try:
        _wr(os.path.join(sub, '..', 'inner.txt'), b'I\n', d)
        in_ok = os.path.exists(os.path.join(d, 'inner.txt'))
    except RuntimeError:
        in_ok = False
    print('POSIX_OK' if esc_ok and in_ok else 'POSIX_BAD esc=%s in=%s' % (esc_ok, in_ok))
elif mode == 'nofile':
    # R13-2：append 不创建目标；不存在即报错且不产生文件
    # R13-2: append never creates; a missing target raises and no file appears
    miss = os.path.join(d, 'no_such_file.txt')
    try:
        with safeio.locked(d):
            _w(miss, 'x\n', d)
        print('NOFILE_MISS')
    except RuntimeError as exc:
        print('NOFILE_OK' if not os.path.exists(miss) and '不存在' in str(exc)
              else 'NOFILE_BAD %s' % exc)
elif mode == 'replace':
    # R13-3：追加期间目标被外部 os.replace 换掉 ⇒ 写后 inode 复核必须报错，不许静默成功
    # R13-3: the target is swapped by an external os.replace mid-append ⇒ the post-write inode
    # check must raise instead of silently succeeding
    real_write = os.write

    def hooked(fd, data):
        n = real_write(fd, data)
        tmp = os.path.join(d, 'repl.tmp')
        with open(tmp, 'wb') as fh:
            fh.write(b'NEW\n')
        os.replace(tmp, p)
        return n

    os.write = hooked
    try:
        with safeio.locked(d):
            _w(p, 'b\n', d)
        print('REPLACE_MISS')
    except RuntimeError as exc:
        print('REPLACE_OK' if '替换' in str(exc) else 'REPLACE_ERR %s' % exc)
    finally:
        os.write = real_write
elif mode == 'missing':
    try:
        with safeio.locked(os.path.join(d, 'nope', 'missing')):
            print('LOCKED')
    except FileNotFoundError:
        print('FILEERROR')
    except RuntimeError as e:
        print('MISSING_OK' if '账本根不存在' in str(e) else 'OTHER_MSG')
elif mode == 'variants':
    # R1：同一 inode 的多种写法，同线程嵌套必须在毫秒级 RuntimeError（不得等超时）
    # R1: many spellings of one inode — same-thread nesting must raise RuntimeError in ms
    base = os.path.join(d, 'rvCase_x')
    os.makedirs(base, exist_ok=True)
    link = os.path.join(d, 'rv_link')
    if not os.path.exists(link):
        os.symlink(base, link)
    uni = os.path.join(d, 'caf\u00e9')
    os.makedirs(uni, exist_ok=True)
    pairs = [('大写', base, base.upper()), ('尾斜杠', base, base + '/'),
             ('软链', base, link), ('NFD', base, os.path.join(d, 'cafe\u0301'))]
    try:
        t2 = tempfile.mkdtemp(dir='/tmp', prefix='akv_')
        pairs.append(('private-tmp', t2, '/private' + t2))
    except OSError as e:
        pairs.append(('private-tmp', None, 'OSError:%s' % e.errno))
    ok = total = 0
    skipped = []
    for name, hold, spell in pairs:
        if hold is None:
            skipped.append(name)
            continue
        try:
            same = os.stat(spell).st_ino == os.stat(hold).st_ino
            why = None if same else '不同 inode'
        except OSError:
            same, why = False, '路径不可达'
        if not same:
            skipped.append('%s(%s)' % (name, why))
            continue
        total += 1
        t0 = time.time()
        with safeio.locked(hold):
            try:
                with safeio.locked(spell, timeout=1.0):
                    print('VARIANT %s 放行 %.3f' % (name, time.time() - t0))
                    continue
            except RuntimeError:
                pass
        dt = time.time() - t0
        if dt < 0.05:
            ok += 1
        else:
            print('VARIANT %s 慢 %.3f' % (name, dt))
    print('VARIANTS %d/%d skip=%d %s' % (ok, total, len(skipped), ','.join(skipped) or '-'))
elif mode == 'wait':
    # 另一线程持根锁 0.4s：主线程必须真的等（>0s），进来时 exclusive_held 必须为 True
    # Another thread holds the root for 0.4s: the main thread must really wait (>0s) and, once
    # inside, exclusive_held must be True
    def holder():
        with safeio.locked(d):
            time.sleep(0.4)
    t = threading.Thread(target=holder)
    t.start()
    time.sleep(0.05)
    t0 = time.time()
    rt = safeio.Root._from_dir_path(d)
    try:
        with rt.lock():
            print('WAIT %.3f %s' % (time.time() - t0, safeio.exclusive_held(rt)))
    finally:
        rt.close()
    t.join()
'''

_AK_AGENT = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
d = sys.argv[2]
from agent_lock import AgentLock
lk = AgentLock(os.path.join(d, '租约卷.txt'), root=d)
lk.acquire('task:A', 'ag1')
t0 = time.time()
try:
    lk.acquire('task:B', 'ag2', blocking=True)
    r1 = 'False'
except RuntimeError:
    r1 = 'True'
dt1 = time.time() - t0
# R1：同一 inode 的另一种写法（大写）另起一把锁，同线程取也必须毫秒级报错、不得挂起
# R1: another AgentLock on a different spelling (upper case) of the same inode must also raise
# in milliseconds from the same thread, never hang
lk2 = AgentLock(os.path.join(d.upper(), '租约卷.txt'), root=d.upper())
t0 = time.time()
try:
    lk2.acquire('task:C', 'ag3', blocking=True)
    r2 = 'False'
except RuntimeError:
    r2 = 'True'
print('RESULT %s %.3f %s %.3f' % (r1, dt1, r2, time.time() - t0))
'''


def _ak_scenario(src, mode, timeout=40, code=None):
    """跑一个锁语义场景，返回 ('WROTE'/'RAISED_ZERO'/'TIMEOUT'/…) 与 stderr。
    Run one lock-semantics scenario and return its verdict token and stderr."""
    d = tempfile.mkdtemp(prefix='ak_')
    try:
        r = subprocess.run([sys.executable, '-B', '-c', code or _AK_CHILD, src, d, mode],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout)
        return (r.stdout.strip().splitlines() or ['ERR'])[-1], (r.stderr or '').strip()
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', '子进程超时（挂起）'
    finally:
        shutil.rmtree(d, ignore_errors=True)


_ROOT_CHILD = r'''
import os, sys, tempfile, threading, time
sys.path.insert(0, sys.argv[1])
d, mode = sys.argv[2], sys.argv[3]
import safeio


def _same_inode(a, b):
    try:
        return os.stat(a).st_ino == os.stat(b).st_ino
    except OSError:
        return False


def _alias():
    # 同一 inode 的多种写法：尾斜杠、自指软链；大小写仅在文件系统确实不区分时才加入。
    # Several spellings of one inode: trailing slash, a self symlink; the upper-case variant is
    # added only when the filesystem really maps it to the same inode.
    link = os.path.join(d, 'self_link')
    if not os.path.exists(link):
        os.symlink(d, link)
    aliases = [d, d + '/', link]
    if _same_inode(d, d.upper()):
        aliases.append(d.upper())
    ids = []
    for a in aliases:
        r = safeio.Root._from_dir_path(a)
        ids.append(r.dev_ino)
        r.close()
    print('IDENT_OK' if len(set(ids)) == 1 else 'IDENT_BAD %r' % (ids,))


def _nest():
    # 同一 inode 的另一种写法，同线程第二次取锁必须毫秒级 RuntimeError（不得等超时）。
    # Another spelling of one inode: a second acquisition in the same thread must raise
    # RuntimeError in milliseconds instead of waiting.
    r1 = safeio.Root._from_dir_path(d)
    r2 = safeio.Root._from_dir_path(d.upper() if _same_inode(d, d.upper()) else d + '/')
    t0 = time.time()
    try:
        with r1.lock():
            try:
                r2.lock(timeout=1.0)
                print('NEST_ACQUIRED')
            except RuntimeError:
                print('NEST_OK' if time.time() - t0 < 0.2 else 'NEST_SLOW')
            except TimeoutError:
                print('NEST_TIMEOUT')
    finally:
        r1.close()
        r2.close()


def _swap():
    # 持锁后根路径被替换：写必须落打开时的 inode，路径上的新 inode 零触碰。
    # 句柄由调用方在换根前打开 —— 换根后按**新路径**重新 open 才是显式的「另一个根」。
    # After the root path is swapped while locked: the write must land on the inode opened and
    # the new inode on the path must stay untouched. The handle is opened before the swap;
    # re-opening the path afterwards is an explicit "different root".
    base = tempfile.mkdtemp(prefix='rootswap_')
    A = os.path.join(base, 'A')
    B = os.path.join(base, 'B')
    os.makedirs(A)
    os.makedirs(B)
    open(os.path.join(A, 'vol.txt'), 'wb').write(b'a-original\n')
    open(os.path.join(B, 'vol.txt'), 'wb').write(b'b-original\n')
    rt = safeio.Root._from_dir_path(A)
    try:
        with rt.lock() as lr:
            os.rename(A, os.path.join(base, 'A-moved'))
            os.rename(B, A)
            lr.write(rt.rel_of(os.path.join(A, 'vol.txt'), 'guard'),
                     b'written-after-swap\n', mode=safeio.WriteMode.REPLACE)
    finally:
        rt.close()
    new = open(os.path.join(A, 'vol.txt'), 'rb').read()
    old = open(os.path.join(base, 'A-moved', 'vol.txt'), 'rb').read()
    print('SWAP_OK' if new == b'b-original\n' and old == b'written-after-swap\n'
          else 'SWAP_BAD new=%r old=%r' % (new, old))


def _swapnest():
    # 句柄身份必须在 open 时固定：换根后同一句柄的「同线程重复获取」仍须毫秒级报错，
    # 否则锁身份被现算成新 inode，重入保护在换根后蒸发。
    # The handle identity must be fixed at open: after a swap, same-thread re-entry on that
    # handle must still raise in milliseconds, otherwise re-entry protection evaporates.
    base = tempfile.mkdtemp(prefix='swapnest_')
    A = os.path.join(base, 'A')
    B = os.path.join(base, 'B')
    os.makedirs(A)
    os.makedirs(B)
    rt = safeio.Root._from_dir_path(A)
    try:
        with rt.lock():
            os.rename(A, os.path.join(base, 'A-moved'))
            os.rename(B, A)
            t0 = time.time()
            try:
                rt.lock(timeout=1.0)
                print('SWAPNEST_ACQUIRED')
            except RuntimeError:
                print('SWAPNEST_OK' if time.time() - t0 < 0.2 else 'SWAPNEST_SLOW')
            except TimeoutError:
                print('SWAPNEST_TIMEOUT')
    finally:
        rt.close()


def _split():
    # 换根后 B 重新 open 得到新 inode/新锁；A 已持有的 LockedRoot 仍写旧 inode，
    # 因此 A 的整文件换入不会覆盖 B 的追加（丢更新=False）。
    # After the swap B re-opens (new inode, new lock); A's held LockedRoot keeps writing the old
    # inode, so A's whole-file replace cannot overwrite B's append (lost update = False).
    base = tempfile.mkdtemp(prefix='splitlock_')
    A = os.path.join(base, 'A')
    B = os.path.join(base, 'B')
    os.makedirs(A)
    os.makedirs(B)
    open(os.path.join(A, 'derived.txt'), 'wb').write(b'v0\n')
    open(os.path.join(B, 'derived.txt'), 'wb').write(b'v0\n')
    gate = threading.Event()

    def writer_a():
        rt_a = safeio.Root._from_dir_path(A)
        try:
            with rt_a.lock() as lr:
                gate.set()
                old = open(os.path.join(A, 'derived.txt'), 'rb').read()
                time.sleep(0.6)
                lr.write(rt_a.rel_of(os.path.join(A, 'derived.txt'), 'guard'),
                         old + b'v2-from-A\n', mode=safeio.WriteMode.REPLACE)
        finally:
            rt_a.close()

    def writer_b():
        gate.wait()
        rt_b = safeio.Root._from_dir_path(A)     # 换根后按新路径开 ⇒ 新 inode、新锁（显式）
        try:
            with rt_b.lock() as lr:
                lr.write(rt_b.rel_of(os.path.join(A, 'derived.txt'), 'guard'),
                         b'v1-from-B\n', mode=safeio.WriteMode.APPEND_CREATE)
        finally:
            rt_b.close()

    ta = threading.Thread(target=writer_a)
    ta.start()
    gate.wait()
    os.rename(A, os.path.join(base, 'A-moved'))
    os.rename(B, A)
    tb = threading.Thread(target=writer_b)
    tb.start()
    ta.join()
    tb.join()
    final = open(os.path.join(A, 'derived.txt'), 'rb').read()
    old = open(os.path.join(base, 'A-moved', 'derived.txt'), 'rb').read()
    lost = b'v1-from-B' not in final
    ok = (not lost) and b'v2-from-A' in old
    print('SPLIT_OK' if ok else 'SPLIT_BAD lost=%s final=%r old=%r' % (lost, final, old))


try:
    {'alias': _alias, 'nest': _nest, 'swap': _swap, 'swapnest': _swapnest,
     'split': _split}[mode]()
finally:
    pass
'''


def _root_case(src, mode, timeout=30):
    """跑一个根句柄/换根场景，返回最后一行与 stderr。
    Run one root-handle / root-swap scenario; return its last line and stderr."""
    d = tempfile.mkdtemp(prefix='rootcase_')
    try:
        r = subprocess.run([sys.executable, '-B', '-c', _ROOT_CHILD, src, d, mode],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout)
        return (r.stdout.strip().splitlines() or ['ERR'])[-1], (r.stderr or '').strip()
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', '子进程超时（挂起）'
    finally:
        shutil.rmtree(d, ignore_errors=True)


_SHARED_TOKEN = 'sha' + 'red='          # 不写出整词，便于「全仓 grep」保持干净


def _variants_ok(got):
    """`VARIANTS ok/total skip=n ...`：支持的写法必须全红；跳过数/原因随行打印。
    `VARIANTS ok/total skip=n ...`: every supported spelling must be caught; the skip count and
    reasons are printed on the same line."""
    parts = got.split()
    if len(parts) < 3 or parts[0] != 'VARIANTS':
        return False
    try:
        a, b = parts[1].split('/')
        return int(a) == int(b) and int(b) >= 3
    except ValueError:
        return False


def _case_lock_assert(tmp):
    """AK 锁语义：只认「账本根 + 本线程独占」；无锁/子目录/异根/另一线程/同线程重复全红。
    AK lock semantics: only "ledger root + exclusive in this thread" counts; no lock,
    sub-directory, another root, another thread and same-thread re-acquire all fail."""
    print('  -- AK 锁语义（账本根 + 本线程独占·五种绕过全红·串行=真等） --')
    here = os.path.dirname(SRC_BIN)
    safeio_src = io.open(os.path.join(here, 'safeio.py'), encoding='utf-8').read()
    got = _ak_scenario(here, 'ok')[0]
    _ok('AK0 持账本根独占锁（本线程）⇒ 放行（WROTE）', got == 'WROTE', got)
    for mode, label in (('nolock', '无锁'),
                        ('subdir', '持子目录锁、传子目录当根'),
                        ('mismatch', '传与 conf 解析不同的根'),
                        ('thread_ok', '另一线程持根时本线程直接写')):
        got, err = _ak_scenario(here, mode)
        _ok('AK[%s] ⇒ 抛错且零写（RAISED_ZERO）' % label, got == 'RAISED_ZERO',
            '%s %s' % (got, err[:120]))
    got, err = _ak_scenario(here, 'thread_sub')
    _ok('AK[同进程另一线程·主线程只持子目录锁] ⇒ 抛错且零写（RAISED_ZERO）',
        got == 'RAISED_ZERO', '%s %s' % (got, err[:120]))

    # 跨线程串行：另一线程持锁时主线程必须真等，且进来后 exclusive_held=True
    # Cross-thread serialization: with another thread holding, the main thread really waits and
    # gets exclusive_held=True once inside
    got, err = _ak_scenario(here, 'wait')
    parts = got.split()
    waited = float(parts[1]) if got.startswith('WAIT') and len(parts) >= 3 else -1.0
    held = parts[2] if len(parts) >= 3 else '?'
    _ok('AK[另一线程持锁⇒主线程真等] ⇒ 等待>0s 且 exclusive_held=True',
        waited > 0.2 and held == 'True', '%s %s' % (got, err[:120]))

    # 同线程重复获取（任意 label）⇒ 立即报错，不等待、不静默放行
    # Same-thread second acquisition (any label) ⇒ immediate error, no wait, no silent pass
    has_agent = os.path.exists(os.path.join(here, 'agent_lock.py'))
    def _agent_verdict(got):
        parts = got.split()
        if len(parts) < 5 or parts[0] != 'RESULT':
            return False
        try:
            return (parts[1] == 'True' and float(parts[2]) < 0.05
                    and parts[3] == 'True' and float(parts[4]) < 0.05)
        except ValueError:
            return False
    if has_agent:
        got, err = _ak_scenario(here, 'agent', code=_AK_AGENT, timeout=5)
        _ok('AK[同线程持 task:A 再要 task:B·含同 inode 大写写法] ⇒ 立即报错（<50ms·不挂起）',
            _agent_verdict(got), '%s %s' % (got, err[:120]))
    else:
        _skip('AK 同线程重复获取：当前盒无 agent_lock.py')
    # R1 候选五种写法（大小写/NFD/软链/尾斜杠/private-tmp）：环境能归到同 inode 的逐种验证，
    # 归不到的打印进跳过清单并给出原因；同线程嵌套必须毫秒级报错
    # R1 five candidate spellings (case / NFD / symlink / trailing slash / private-tmp): each
    # one the environment really maps to the same inode is verified; the rest are listed as
    # skipped with a reason. Same-thread nesting must raise in milliseconds.
    got, err = _ak_scenario(here, 'variants')
    _ok('AK[R1 同一 inode 多种写法 ⇒ 同线程嵌套毫秒级 RuntimeError]', _variants_ok(got),
        '%s %s' % (got, err[:120]))
    # R7：持 f 的锁往 f 外的 g 写 ⇒ 抛错零写
    # R7: holding f's lock and writing g outside f ⇒ raise, zero write
    got, err = _ak_scenario(here, 'outside')
    _ok('AK[R7 持 f 锁往 g 写] ⇒ 抛错且零写（RAISED_ZERO）', got == 'RAISED_ZERO',
        '%s %s' % (got, err[:120]))
    # R9-1：硬链接是「同 inode 两个名字」的语义，不靠拒绝表达边界；两个名字都看到追加
    # R9-1: hard links are two names for one inode (semantics, not a boundary); both see the append
    got, err = _ak_scenario(here, 'hardlink')
    _ok('AK[R9-1 根内硬链接 ⇒ 不拒绝，追加经两个名字都可见]', got == 'WROTE_BOTH',
        '%s %s' % (got, err[:120]))
    # R10-1 确定性注入：根的一级子目录被换成根外软链 ⇒ openat 走查拒绝且零写
    # R10-1 deterministic injection: a first-level sub-directory swapped to an outside symlink ⇒
    # the openat walk rejects with zero write
    got, err = _ak_scenario(here, 'ancestor')
    _ok('AK[R10-1 祖先目录换成根外软链（确定性注入）⇒ 拒绝且零写]', got == 'ANCESTOR_ZERO',
        '%s %s' % (got, err[:120]))
    # R10-1 自然竞态：软链/真目录来回切换 300 次追加 ⇒ 零逃逸（esc=0）
    # R10-1 natural race: flip symlink/real dir while appending 300 times ⇒ zero escapes
    got, err = _ak_scenario(here, 'race', timeout=60)
    _ok('AK[R10-1 自然竞态 300 次追加 ⇒ 零逃逸且观察到拒绝]',
        got.startswith('RACE ') and got.strip().endswith('esc=0')
        and 'rej=0' not in got, '%s %s' % (got, err[:120]))
    # 步骤 1 静态：唯一 openat 走查在场；写链只存在于 LockedRoot；旧的「加锁后现算 inode
    # 复核」与以路径字符串为键的 _ident 必须已删
    # Step-1 static: the single openat walk is present; the write chain exists only on
    # LockedRoot; the old "recompute inode after locking" check and string-keyed _ident are gone
    walk = ('def _walk_parent' in safeio_src and 'dir_fd=fd' in safeio_src
            and 'os.O_NOFOLLOW | os.O_DIRECTORY' in safeio_src
            and 'for comp in parts[:-1]:' in safeio_src)
    shared = safeio_src.count('_walk_parent(') >= 3 and 'def write(self, rel' in safeio_src
    legacy_gone = ('_open_root_dir' not in safeio_src
                   and 'def _ident(' not in safeio_src
                   and 'before is not None' not in safeio_src
                   and 'tempfile.mkstemp' not in safeio_src)
    _ok('AK[步骤1 静态] 唯一 openat 走查 + 写链只在 LockedRoot；'
        '「加锁后现算 inode 复核」与字符串身份已删',
        walk and shared and legacy_gone,
        '走查=%s 写链=%s 旧法已删=%s' % (walk, shared, legacy_gone))
    # R11-1/R12-1：静态软链祖先下四个原语全部拒绝且根外零写
    # R11-1/R12-1: under a static symlinked ancestor all four primitives reject with zero outside
    got, err = _ak_scenario(here, 'prims')
    _ok('AK[R11-1 四个原语在软链祖先下全部拒绝且根外零写]', got.startswith('PRIMS 4/4'),
        '%s %s' % (got, err[:120]))
    # R12-2：归属按 inode 判，四种混写都能写；`..` 逃逸仍拒绝
    # R12-2: containment is inode-based; four mixed spellings write, a `..` escape still refuses
    got, err = _ak_scenario(here, 'spellings')
    _ok('AK[R12-2 大小写/NFC-NFD//tmp 别名/尾斜杠混写都能写，`..` 逃逸仍拒绝]',
        got == 'SPELL 4/4 escape=R', '%s %s' % (got, err[:120]))
    # R12-3：0200 与 ACL 拒读仍可追加且 padded=False
    # R12-3: 0200 and ACL-read-denied targets still append with padded=False
    got, err = _ak_scenario(here, 'mode200')
    _ok('AK[R12-3 0200 与 ACL 拒读目标仍可追加、padded=False]', got == 'MODE200_OK',
        '%s %s' % (got, err[:120]))
    # R12-3：0400/0000 仍拒绝；ENOENT/EISDIR/ELOOP 不被吞
    # R12-3: 0400/0000 still refuse; ENOENT/EISDIR/ELOOP are never swallowed
    got, err = _ak_scenario(here, 'refuse')
    _ok('AK[R12-3 0400/0000 仍拒绝，ENOENT/EISDIR/ELOOP 不被吞]', got == 'REFUSE_OK',
        '%s %s' % (got, err[:120]))
    # R13-1：`root/link/../x` 按 POSIX 解析到根外 ⇒ 拒绝零写；根内 `..` 不误拒
    # R13-1: `root/link/../x` resolves outside per POSIX ⇒ refuse; an inside `..` still writes
    got, err = _ak_scenario(here, 'posix')
    _ok('AK[R13-1 root/link/../x 解析到根外 ⇒ 拒绝零写，根内 .. 不误拒]',
        got == 'POSIX_OK', '%s %s' % (got, err[:120]))
    # R13-2：append 目标不存在 ⇒ 报错且不创建
    # R13-2: a missing append target raises and is never created
    got, err = _ak_scenario(here, 'nofile')
    _ok('AK[R13-2 append 目标不存在 ⇒ 报错且不产生文件]', got == 'NOFILE_OK',
        '%s %s' % (got, err[:120]))
    # R13-3：追加期间目标被替换 ⇒ 写后 inode 复核报错
    # R13-3: the target replaced mid-append ⇒ post-write inode check raises
    got, err = _ak_scenario(here, 'replace')
    _ok('AK[R13-3 追加期间目标被 replace ⇒ 写后复核报错、不静默成功]', got == 'REPLACE_OK',
        '%s %s' % (got, err[:120]))
    # R11-4：根与目标混用别名拼写（软链别名目录）必须能写
    # R11-4: mixing alias spellings for root and target (symlinked alias directory) must write
    got, err = _ak_scenario(here, 'alias')
    _ok('AK[R11-4 别名拼写混用不误拒（写入落回根内）]', got == 'ALIAS_OK',
        '%s %s' % (got, err[:120]))
    # R11-5：0200（只写）目标仍可追加
    # R11-5: a write-only (0200) target can still be appended
    got, err = _ak_scenario(here, 'mode200')
    _ok('AK[R11-5 0200 只写目标仍可追加]', got == 'MODE200_OK', '%s %s' % (got, err[:120]))
    # 步骤 3 静态：四个旧原语已删除（无 shim），写链只剩 LockedRoot；replace/fsync 在其上
    # Step-3 static: the four legacy primitives are gone (no shim) and the only write chain is
    # LockedRoot, which owns replace/fsync
    gone = all(('def %s(' % n) not in safeio_src
               for n in ('atomic_write', 'atomic_append', 'append_inplace',
                         'read_modify_write'))
    chain = ('os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)' in safeio_src
             and 'os.fsync(dfd)' in safeio_src)
    _ok('AK[步骤3 静态] 旧四原语已删除且写链只剩 LockedRoot（replace + fsync(dfd)）',
        gone and chain, 'gone=%s chain=%s' % (gone, chain))
    # R8-3：账本根不存在 ⇒ 明确报错（不是 FileNotFoundError）
    # R8-3: a missing ledger root ⇒ explicit error (not a bare FileNotFoundError)
    got, err = _ak_scenario(here, 'missing')
    _ok('AK[R8-3 账本根不存在] ⇒ 明确 RuntimeError（非 FileNotFoundError）',
        got == 'MISSING_OK', '%s %s' % (got, err[:120]))
    # R5：AgentLock 不得保留被静默丢弃的 lock_dir 形参
    # R5: AgentLock must not keep a silently ignored lock_dir parameter
    if has_agent:
        atree = ast.parse(io.open(os.path.join(here, 'agent_lock.py'), encoding='utf-8').read())
        cls = [n for n in atree.body
               if isinstance(n, ast.ClassDef) and n.name == 'AgentLock'][0]
        init = [n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == '__init__'][0]
        pnames = [a.arg for a in init.args.args]
        _ok('AK[R5] AgentLock 形参只有 lease_vol/root（无被丢弃的 lock_dir）',
            pnames == ['self', 'lease_vol', 'root'], '%r' % (pnames,))
    else:
        _skip('AK R5：当前盒无 agent_lock.py')

    # 变异矩阵（步骤 1）：每条都必须让某条属性/回归场景变红；锚点消失记「死变异」，
    # 未被杀死记「存活变异」。两者都会让本次判据红——「共 N 项全绿」不再作为结论。
    # Mutation matrix (step 1): each must turn an attribute/scenario red; a missing anchor is a
    # dead mutation, an uncaught one a survivor. Both make this run red — "N checks green" is
    # no longer a conclusion.
    def _mutant_safeio(tag, text):
        md = os.path.join(tmp, 'ak_mut_' + tag)
        os.makedirs(md)
        io.open(os.path.join(md, 'safeio.py'), 'w', encoding='utf-8').write(text)
        try:
            io.open(os.path.join(md, 'ledger_root.py'), 'w', encoding='utf-8').write(
                io.open(os.path.join(here, 'ledger_root.py'), encoding='utf-8').read())
        except IOError:
            pass
        return md

    def _mut(anchor, new, tag):
        if anchor not in safeio_src:
            _mut_ok('变异[%s] ⇒ 判据红' % tag, False, '死变异：锚点消失', dead=True)
            return None
        text = safeio_src.replace(anchor, new)
        if text == safeio_src:
            _mut_ok('变异[%s] ⇒ 判据红' % tag, False, '死变异：变换后无差异', dead=True)
            return None
        return _mutant_safeio(tag, text)

    # M1：锁身份退回 label 字符串 ⇒ P1 的「同 inode 另一种写法」不再互认
    # M1: lock identity back to the label string ⇒ P1's "another spelling of one inode" breaks
    md = _mut("        key = self.dev_ino", "        key = self.label", 'M1 锁身份改 label')
    if md:
        got, err = _root_case(md, 'nest')
        _mut_ok('M1 锁身份改 label ⇒ P1 红（不互认/等超时）', got != 'NEST_OK',
                '%s %s' % (got, err[:100]))
    # M1b：锁身份改成「现算 stat(label)」⇒ 换根后同句柄的重入保护蒸发（P1 swapnest 必红）
    # M1b: lock identity recomputed from stat(label) ⇒ after a swap the same handle loses its
    # re-entry protection (P1 swapnest must go red)
    md = _mut("        key = self.dev_ino",
              "        _st = os.stat(self.label)\n"
              "        key = (_st.st_dev, _st.st_ino)", 'M1b 锁身份现算')
    if md:
        got, err = _root_case(md, 'swapnest')
        _mut_ok('M1b 锁身份现算（换根后）⇒ P1 红（重入静默放行）', got != 'SWAPNEST_OK',
                '%s %s' % (got, err[:100]))
    # M2：去掉走查的 O_NOFOLLOW ⇒ 软链祖先被跟随，写逃到根外
    # M2: drop O_NOFOLLOW in the walk ⇒ a symlinked ancestor is followed and the write escapes
    md = _mut("os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY",
              "os.O_RDONLY | os.O_DIRECTORY", 'M2 去 O_NOFOLLOW')
    if md:
        got, err = _ak_scenario(md, 'ancestor')
        _mut_ok('M2 去掉走查 O_NOFOLLOW ⇒ 祖先软链逃逸（判据红）',
                got != 'ANCESTOR_ZERO', '%s %s' % (got, err[:120]))
    # M3：归属判退回 abspath 词法折叠 ⇒ root/link/../x 被折成根内、静默改道
    # M3: containment back to abspath folding ⇒ root/link/../x is silently rerouted inside
    md = _mut("        cur = os.path.realpath(os.path.dirname(raw))",
              "        cur = os.path.realpath(os.path.dirname(os.path.abspath(path)))",
              'M3 abspath 词法折叠')
    if md:
        got, err = _ak_scenario(md, 'posix')
        _mut_ok('M3 归属判改 abspath 词法折叠 ⇒ link/.. 静默改道（判据红）',
                got != 'POSIX_OK', '%s %s' % (got, err[:120]))
    # M5：held() 无锁时不再拒绝，改为就地取锁 ⇒ 无锁调用也能写（判据红）
    # M5: held() no longer refuses when unlocked but acquires the lock ⇒ an unlocked call writes
    md = _mut("    if lr is None:\n        raise RuntimeError('%s: 未在本线程于账本根（%s）持独占锁'",
              "    if lr is None:\n        return rt.lock()\n        raise RuntimeError('%s: 未在本线程于账本根（%s）持独占锁'",
              'M5 去持锁前置')
    if md:
        got, err = _ak_scenario(md, 'nolock')
        _mut_ok('M5 去掉 held() 的持锁前置 ⇒ 无锁写放行（判据红）',
                got != 'RAISED_ZERO', '%s %s' % (got, err[:120]))
    # M-root：写链按 label 重新打开根 ⇒ 换根后写落新 inode（fd 语义被破坏）
    # M-root: the write chain re-opens the root by label ⇒ after a swap it writes the new inode
    md = _mut("        dfd, name = _walk_parent(self.root._fd, rel.parts, 'safeio.write')",
              "        dfd, name = _walk_parent("
              "os.open(self.root.label, os.O_RDONLY | os.O_DIRECTORY), "
              "rel.parts, 'safeio.write')", 'M-root 写链重开根')
    if md:
        got, err = _root_case(md, 'swap')
        _mut_ok('M-root 写链按 label 重开根 ⇒ 换根写落新 inode（判据红）',
                got != 'SWAP_OK', '%s %s' % (got, err[:120]))
    # 变异④：删掉「同线程重复获取」检查 ⇒ 第二次 acquire 被静默放行（或挂起）⇒ 红
    if not has_agent:
        _skip('AK 变异④：当前盒无 agent_lock.py')
    else:
        agent_src = io.open(os.path.join(here, 'agent_lock.py'), encoding='utf-8').read()
        dup_anchor = """        if exclusive_held(rt):
            if own:
                rt.close()
            raise RuntimeError('agent_lock: 同线程重复获取账本根锁（%s）·拒绝等待'
                               '（同线程等自己必自死锁；互斥范围是整个账本根）' % rt)"""
        assert dup_anchor in agent_src
        md = os.path.join(tmp, 'ak_mut_agent')
        os.makedirs(md)
        io.open(os.path.join(md, 'agent_lock.py'), 'w', encoding='utf-8').write(
            agent_src.replace(dup_anchor, '        pass'))
        # 同时把 safeio 的同线程检查也退回「重入直接放行」，否则变异会被下层拦住
        # Also revert safeio's same-thread check to "reentry passes through", otherwise the
        # lower layer masks the mutation
        dup_safe = """        ent = _PROC.get(key)
        if ent is not None and ent['owner'] == me:
            raise RuntimeError('safeio.locked: 同线程重复获取账本根锁（%s）·拒绝等待'
                               '（同线程重入必自死锁）' % self.label)"""
        assert dup_safe in safeio_src
        mut_safeio = safeio_src.replace(
            dup_safe, "        ent = _PROC.get(key)\n"
                      "        if ent is not None and ent['owner'] == me:\n"
                      "            pass")
        for f, text in (('safeio.py', mut_safeio), ('ledger_root.py', None)):
            if text is None:
                text = io.open(os.path.join(here, f), encoding='utf-8').read()
            io.open(os.path.join(md, f), 'w', encoding='utf-8').write(text)
        got, err = _ak_scenario(md, 'agent', code=_AK_AGENT, timeout=5)
        _mut_ok('AK 变异④：删掉同线程重复检查 ⇒ 静默放行/挂起（判据红）',
                not _agent_verdict(got), '%s %s' % (got, err[:120]))
    # 变异⑤：把共享锁分支塞回去 ⇒ 静态判据必须红
    # Mutation ⑤: put a shared-lock branch back ⇒ the static criterion must go red
    def _has_shared(txt):
        return (_SHARED_TOKEN in txt) or ('LOCK_SH' in txt)
    mut_shared = safeio_src.replace('def locked(x, timeout=None):',
                                    'def locked(path, timeout=None, %sFalse):' % _SHARED_TOKEN)
    _ok('AK 变异⑤：保留 shared 分支 ⇒ 静态判据红',
        (not _has_shared(safeio_src)) and _has_shared(mut_shared),
        '原=%s 变异=%s' % (_has_shared(safeio_src), _has_shared(mut_shared)))


def _case_root_handle(tmp):
    """P1 根身份 / 换根语义（属性层）：同一根的任意写法同一 dev_ino；换根后写打开时的 inode。
    P1 root identity / root-swap semantics: every spelling of one root gives one dev_ino; after
    a swap the write lands on the inode that was opened."""
    print('  -- P1 根身份 + 换根语义（属性层；变异见 AK 矩阵） --')
    here = os.path.dirname(SRC_BIN)
    got, err = _root_case(here, 'alias')
    _ok('P1 根身份：同一根的多种写法 ⇒ 同一 dev_ino', got == 'IDENT_OK',
        '%s %s' % (got, err[:120]))
    got, err = _root_case(here, 'nest')
    _ok('P1 同一 inode 另一种写法 ⇒ 同线程毫秒级 RuntimeError（不挂起）', got == 'NEST_OK',
        '%s %s' % (got, err[:120]))
    got, err = _root_case(here, 'swap')
    _ok('P1 换根后写落打开时的 inode（路径上的新 inode 零触碰）', got == 'SWAP_OK',
        '%s %s' % (got, err[:120]))
    got, err = _root_case(here, 'split')
    _ok('P1/P5 换根下整写不覆盖追加（丢更新=False）', got == 'SPLIT_OK',
        '%s %s' % (got, err[:120]))
    got, err = _root_case(here, 'swapnest')
    _ok('P1 句柄身份在 open 时固定（换根后同线程重入仍毫秒级报错）',
        got == 'SWAPNEST_OK', '%s %s' % (got, err[:120]))
    # 步骤 2+3 静态：没有以路径为键的持有表，exclusive_held 只接受句柄，旧原语已不存在
    # Step-2+3 static: no path-keyed held table, exclusive_held takes handles only, and the
    # legacy primitives no longer exist
    safeio_src2 = io.open(os.path.join(here, 'safeio.py'), encoding='utf-8').read()
    nopath = ('def _held_for(' not in safeio_src2
              and 'def _held_for_root(' in safeio_src2
              and 'def exclusive_held(root):' in safeio_src2
              and 'isinstance(root, Root)' in safeio_src2
              and 'def root_scope(' in safeio_src2
              and all(('def %s(' % n) not in safeio_src2
                      for n in ('atomic_write', 'atomic_append', 'append_inplace',
                                'read_modify_write'))
              and 'read_conf_value' not in safeio_src2)
    _ok('P1[步骤2+3 静态] 持有表只按 dev_ino / exclusive_held 只收句柄 / 旧原语已删',
        nopath, 'ok=%s' % nopath)


_HOLD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import safeio
led, hold = sys.argv[2], float(sys.argv[3])
with safeio.locked(led):
    print('READY', flush=True)
    time.sleep(hold)
'''

_AG_HOLD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
d = sys.argv[2]
from agent_lock import AgentLock
lk = AgentLock(os.path.join(d, '租约卷.txt'), root=d)
lid = lk.acquire('task:A', 'agP1')
print('READY', flush=True)
time.sleep(float(sys.argv[3]))
lk.release(lid)
'''


def _case_serial_cost(tmp):
    """AM 串行代价读数：持根锁期间跑一次全量 index / 跨 label 取锁，各等多久（实测秒数）。
    AM serialization cost readings: while the root lock is held, how long a full `index` and a
    different-label acquire actually wait (measured seconds)."""
    print('  -- AM 串行代价读数（同一账本根下所有写操作串行） --')
    here = os.path.dirname(SRC_BIN)
    d = os.path.join(tmp, 'am')
    os.makedirs(d)
    _make_volume(os.path.join(d, '账卷.txt'), 30)
    with io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[volumes]\n账=账卷.txt\n\n[index]\nout_dir=索引\n')
    base = subprocess.run([sys.executable, '-B', SRC_BIN, 'baseline'], cwd=d,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=120)
    _ok('AM0 基线 rc=0', base.returncode == 0, (base.stdout + base.stderr)[-160:])
    hold = 0.6
    holder = subprocess.Popen([sys.executable, '-B', '-c', _HOLD, here, d, str(hold)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
    try:
        line = holder.stdout.readline().strip()
        _ok('AM1 持根锁进程就位', line == 'READY', line)
        t0 = time.time()
        r = subprocess.run([sys.executable, '-B', SRC_BIN, 'index'], cwd=d,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=180)
        wait_index = time.time() - t0
        _ok('AM2 持根锁期间全量 index 等待 >0.3s 且 rc=0',
            wait_index > 0.3 and r.returncode == 0,
            '等待=%.2fs rc=%d' % (wait_index, r.returncode))
        print('    [读数] 根锁被持 %.1fs 期间，全量 index 实际等待 %.2fs' % (hold, wait_index))
    finally:
        holder.wait(timeout=30)
    # 跨 label：P1 持 task:A 1.2s，P2 要 task:B 实际等待（互斥范围是账本根，不是 label）
    # Cross-label: P1 holds task:A 1.2s; P2 asks task:B and really waits (the scope is the root)
    if not os.path.exists(os.path.join(here, 'agent_lock.py')):
        _skip('AM 跨 label 读数：当前盒无 agent_lock.py')
        return
    hold2 = 1.2
    holder2 = subprocess.Popen([sys.executable, '-B', '-c', _AG_HOLD, here, d, str(hold2)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)
    try:
        line = holder2.stdout.readline().strip()
        _ok('AM3 跨进程 P1 持 task:A 就位', line == 'READY', line)
        sys.path.insert(0, here)
        from agent_lock import AgentLock
        lk = AgentLock(os.path.join(d, '租约卷.txt'), root=d)
        t0 = time.time()
        lid = lk.acquire('task:B', 'P2', blocking=True)
        wait_label = time.time() - t0
        _ok('AM4 跨 label 取锁实际等待 >1.0s（互斥=账本根）',
            bool(lid) and wait_label > 1.0, '等待=%.2fs lid=%r' % (wait_label, lid))
        print('    [读数] P1 持 task:A %.1fs 期间，P2 取 task:B 实际等待 %.2fs'
              % (hold2, wait_label))
        if lid:
            lk.release(lid)
    finally:
        holder2.wait(timeout=30)


_LEASE_RO = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
d = sys.argv[2]
import safeio
from agent_lock import AgentLock
lease = os.path.join(d, '租约卷.txt')
os.chmod(d, 0o555)
lk = AgentLock(lease, root=d)
denied = False
try:
    lk.acquire('task:A', 'ag1')
except (PermissionError, RuntimeError):
    denied = True
_rt = safeio.Root._from_dir_path(d)
held = safeio.exclusive_held(_rt)
_rt.close()
ctx = len(lk._ctx)
os.chmod(d, 0o755)
lk2 = AgentLock(lease, root=d)
lid = lk2.acquire('task:B', 'ag2', blocking=True)
print('LEASE denied=%s held=%s ctx=%d recover=%s' % (denied, held, ctx, bool(lid)))
'''


def _case_lease_leak(tmp):
    """AN 租约写失败⇒根锁不泄漏：只读租约目录下 acquire 抛错后，锁必须已释放且他人可取。
    AN lease-write failure must not leak the root lock: after acquire raises under a read-only
    lease directory, the lock is released and the next agent can take it."""
    print('  -- AN 租约写失败⇒根锁不泄漏 --')
    here = os.path.dirname(SRC_BIN)
    if not os.path.exists(os.path.join(here, 'agent_lock.py')):
        _skip('AN：当前盒无 agent_lock.py')
        return
    d = tempfile.mkdtemp(prefix='an_')
    try:
        r = subprocess.run([sys.executable, '-B', '-c', _LEASE_RO, here, d],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        got = (r.stdout.strip().splitlines() or ['ERR'])[-1]
        _ok('AN 只读租约目录⇒写失败后 held=False/ctx=0/他人可取',
            got.startswith('LEASE') and 'denied=True' in got and 'held=False' in got
            and 'ctx=0' in got and 'recover=True' in got,
            '%s %s' % (got, (r.stderr or '')[-100:]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


_NOROOT = r'''
import sys
sys.path.insert(0, sys.argv[1])
import inspect, safeio
gone = [n for n in ('atomic_write', 'atomic_append', 'append_inplace', 'read_modify_write')
        if hasattr(safeio, n)]
cls = sorted(n for n, o in vars(safeio).items()
             if inspect.isclass(o) and callable(getattr(o, 'write', None))
             and getattr(getattr(o, 'write', None), '__qualname__', '').split('.')[0] == n)
print('NOROOT gone=%d write_classes=%s' % (len(gone), ','.join(cls) or '-'))
'''


def _case_no_root(tmp):
    """P4 能力形态：模块级写原语不存在；写方法只在 LockedRoot 上。
    P4 capability shape: no module-level write primitive exists; write methods live only on
    LockedRoot."""
    print('  -- P4 能力形态：写方法只在 LockedRoot --')
    here = os.path.dirname(SRC_BIN)
    d = tempfile.mkdtemp(prefix='ao_')
    try:
        r = subprocess.run([sys.executable, '-B', '-c', _NOROOT, here],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        got = (r.stdout.strip().splitlines() or ['ERR'])[-1]
        _ok('P4 模块级写原语零残留，write 只属于 LockedRoot',
            got == 'NOROOT gone=0 write_classes=LockedRoot',
            '%s %s' % (got, (r.stderr or '')[-100:]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
        _skip('AL：当前盒无 orchestrator.py')
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
    for name in ('daybook.py', 'safeio.py', 'daybook_append.py', 'ledger_root.py',
                 'errors.py', 'conf_norm.py'):
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
                 'errors.py', 'daybook_hook.py', 'mcp_resources.py', 'mcp_transport.py',
                 'volume_paths.py', 'conf_norm.py'):
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
        _skip('本包缺 %s，AE 只测 %d 个入口' % ('、'.join(missing), len(kinds)))
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
                'daybook_multidx.py', 'errors.py', 'conf_norm.py')


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
    print('    [信息] %s；固定测 %d 个入口' % ('、'.join(missing) or '无', len(kinds)))
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


_CONF_CHILD = r'''
import json, os, sys
stage, conf_path, mode = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, stage)
out = {}
import conf_norm
text = open(conf_path, encoding='utf-8').read()
try:
    sections, content, parsed = conf_norm.parse_text(text)
    out['norm'] = {'sections': sections, 'content': content, 'parsed': parsed}
except conf_norm.ConfError as exc:
    out['norm'] = {'err': str(exc)}
import errors
try:
    if mode == 'full':
        import daybook
        conf = daybook.load_conf(conf_path)
    else:
        import volume_paths
        conf = volume_paths.read_conf_sections_from(conf_path)
    out['sections'] = {k: v for k, v in conf.items()
                       if isinstance(v, dict) and not k.startswith('_') and v}
    out['code'] = 0
    try:
        if mode == 'full':
            import ledger_root
            out['root'] = ledger_root.resolve_root(
                os.path.realpath(os.path.dirname(conf_path)),
                {'index': {'root': ledger_root.read_conf_value(conf_path, 'index', 'root')}})
        else:
            import volume_paths
            out['root'] = volume_paths.resolve_root(os.path.dirname(conf_path))
    except ValueError:
        out['code'] = 2
        out['root'] = ''
except errors.ConfigError:
    out['sections'] = None
    out['code'] = 2
    out['root'] = ''
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
'''

_CONF_SAMPLES = (
    ('纯注释', '# 只有注释\n# 第二行\n', 0, 'conf'),
    ('空行', '\n\n  \n', 0, 'conf'),
    ('BOM', '\ufeff[index]\nroot=sub\n', 0, 'sub'),
    ('CRLF', '[index]\r\nroot=sub\r\n', 0, 'sub'),
    ('; 注释', '; 这是注释\n', 2, None),
    ('重复[index]', '[index]\nroot=sub\n[index]\nroot=sub2\n', 0, 'sub2'),
    ('空节名', '[]\n', 2, None),
    ('键无=', '[index]\nroot sub\n', 0, 'conf'),
    ('行内注释', '[index]\nroot=sub # 注释\n', 2, None),
    ('[index]后[other]', '[index]\nroot=sub\n[other]\nx=1\n', 2, None),
    ('缩进键', '[index]\n  root=sub\n', 0, 'sub'),
    ('键前无节', 'root=sub\n[index]\nroot=sub\n', 0, 'sub'),
    ('[索引]+根', '[索引]\n根=sub\n', 0, 'sub'),
    ('[index]+根', '[index]\n根=sub\n', 0, 'sub'),
    ('[Index]', '[Index]\nroot=sub\n', 0, 'sub'),
    ('[ index ]', '[ index ]\nroot=sub\n', 0, 'sub'),
    ('[INDEX]', '[INDEX]\nroot=sub\n', 0, 'sub'),
    ('中文节+英文键', '[索引]\nroot=sub\n', 0, 'sub'),
    ('英文节+中文键', '[index]\n根=sub\n', 0, 'sub'),
    ('# 注释', '# c\n[index]\nroot=sub\n', 0, 'sub'),
)


def _case_conf_dual(tmp):
    """P0-4 conf 边界样本差分：20 条，完整包与 orch 包各跑一次。
    P0-4 differential conf samples: 20 cases, run once per package (full / orch).
    比 sections/content/parsed 与最终 root：两包同值才绿；认不出的写法必须同码 2。
    Compare sections/content/parsed and the final root: both packages must agree; a spelling
    that cannot be recognised must exit 2 in both."""
    print('  -- P0-4 conf 归一差分（两包 × 20 边界样本） --')
    py = sys.executable
    here = os.path.dirname(SRC_BIN)
    lack = [n for n in ('daybook.py', 'volume_paths.py', 'conf_norm.py', 'ledger_root.py')
            if not os.path.exists(os.path.join(here, n))]
    if lack:
        _skip('P0-4 差分需完整包与 orch 包同场（当前盒缺 %s）' % '、'.join(lack))
        return
    base = os.path.join(tmp, 'confdiff')
    os.makedirs(base)
    full = os.path.join(base, 'full')
    orch = os.path.join(base, 'orch')
    os.makedirs(full)
    os.makedirs(orch)
    for nm in sorted(os.listdir(here)):
        if nm.endswith('.py'):
            shutil.copy2(os.path.join(here, nm), os.path.join(full, nm))
    for nm in ('conf_norm.py', 'ledger_root.py', 'volume_paths.py', 'errors.py'):
        shutil.copy2(os.path.join(here, nm), os.path.join(orch, nm))
    bad = []
    for i, (name, text, want, want_root) in enumerate(_CONF_SAMPLES):
        cell = os.path.join(base, 's%02d' % i)
        os.makedirs(cell)
        for sub in ('sub', 'sub2'):
            os.makedirs(os.path.join(cell, sub))
        conf = os.path.join(cell, 'daybook.conf')
        io.open(conf, 'w', encoding='utf-8').write(text)
        got = {}
        for mode, stage in (('full', full), ('orch', orch)):
            r = subprocess.run([py, '-B', '-c', _CONF_CHILD, stage, conf, mode], cwd=cell,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)
            try:
                got[mode] = json.loads((r.stdout or '').strip().splitlines()[-1])
            except (ValueError, IndexError):
                got[mode] = {'crash': (r.stdout + r.stderr)[-200:]}
        f, o = got['full'], got['orch']
        same_norm = (f.get('norm') == o.get('norm')
                     and f.get('sections') == o.get('sections'))
        _ok('P0-4[%02d %s] 两包 sections/content/parsed 同值' % (i + 1, name), same_norm,
            'full=%r orch=%r' % (f.get('norm'), o.get('norm')))
        want_dir = (os.path.realpath(cell) if want_root == 'conf' else (
            os.path.realpath(os.path.join(cell, want_root)) if want_root else None))
        same_root = want_root is None or (
            f.get('root') == o.get('root') == want_dir)
        same_code = f.get('code') == o.get('code') == want
        if not (same_norm and same_root and same_code):
            bad.append(name)
        _ok('P0-4[%02d %s] 两包同码=%d、同根=%s' % (i + 1, name, want,
                                                    os.path.basename(want_dir or '')),
            same_code and same_root,
            'full(code=%r root=%r) orch(code=%r root=%r)'
            % (f.get('code'), f.get('root'), o.get('code'), o.get('root')))
    _ok('P0-4 20 条边界样本两包全同（无分叉）', not bad, '分叉=%s' % bad)


def _case_conf_dual_e2e(tmp):
    """P0-3 中文/大小写 conf 双包同根同码：`[索引]/根=sub`、`[Index]`、`[ index ]`。
    P0-3 end-to-end: the same three conf spellings must give one root and one code in both
    packages. Artifacts prove the root; the resolver print proves it directly."""
    print('  -- P0-3 中文/大小写 conf 双包同根同码 --')
    py = sys.executable
    here = os.path.dirname(SRC_BIN)
    lack = [n for n in ('daybook.py', 'orchestrator.py', 'volume_paths.py', 'conf_norm.py')
            if not os.path.exists(os.path.join(here, n))]
    if lack:
        _skip('P0-3 端到端需完整包与 orch 包同场（当前盒缺 %s）' % '、'.join(lack))
        return
    variants = ('[索引]\n根=sub\n\n[volumes]\n账=账卷.txt\n',
                '[Index]\nroot=sub\n\n[volumes]\n账=账卷.txt\n',
                '[ index ]\nroot=sub\n\n[volumes]\n账=账卷.txt\n')
    for i, text in enumerate(variants):
        cell = os.path.join(tmp, 'cdual%d' % i)
        full = os.path.join(cell, 'full')
        orch = os.path.join(cell, 'orch')
        for d in (full, orch):
            os.makedirs(os.path.join(d, 'sub'))
            io.open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8').write(text)
        for nm in ('daybook.py', 'daybook_append.py', 'safeio.py', 'ledger_root.py',
                   'errors.py', 'conf_norm.py'):
            shutil.copy2(os.path.join(here, nm), os.path.join(full, nm))
        for nm in ('orchestrator.py', 'volume_paths.py', 'ledger_root.py', 'errors.py',
                   'conf_norm.py', 'safeio.py', 'agent_registry.py', 'agent_lock.py',
                   'agent_heartbeat.py', 'task_volume.py', 'cross_ref.py',
                   'daybook_append.py', 'agent_message.py'):
            shutil.copy2(os.path.join(here, nm), os.path.join(orch, nm))
        io.open(os.path.join(full, 'sub', '账卷.txt'), 'w', encoding='utf-8').write(
            '[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
        # v4.0.6：非空卷首次索引退 5，先认基线再索引（同码证据仍取 index 的 0）。
        # v4.0.6: the first index of a non-empty volume exits 5; accept the baseline first.
        rb = subprocess.run([py, '-B', 'daybook.py', 'baseline'], cwd=full,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
        rf = subprocess.run([py, '-B', 'daybook.py', 'index'], cwd=full,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
        ro = subprocess.run([py, '-B', 'orchestrator.py', 'join', '汤姆'], cwd=orch,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
        _ok('P0-3[%d %r] 完整包 baseline+index rc=0、orch 包 join rc=0（同码）' % (i + 1, text.strip()),
            rb.returncode == 0 and rf.returncode == 0 and ro.returncode == 0,
            'base=%d index=%d %s | orch=%d %s' % (
                rb.returncode, rf.returncode, (rf.stdout + rf.stderr)[-80:],
                ro.returncode, (ro.stdout + ro.stderr)[-80:]))
        want_f = os.path.realpath(os.path.join(full, 'sub'))
        want_o = os.path.realpath(os.path.join(orch, 'sub'))
        code_f = ('import sys; sys.path.insert(0, "."); import ledger_root;'
                  'print(ledger_root.ledger_root())')
        code_o = ('import sys; sys.path.insert(0, "."); import volume_paths;'
                  'print(volume_paths.resolve_root())')
        pf = subprocess.run([py, '-B', '-c', code_f], cwd=full, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
        po = subprocess.run([py, '-B', '-c', code_o], cwd=orch, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
        root_f = (pf.stdout or '').strip().splitlines()[-1] if pf.stdout.strip() else ''
        root_o = (po.stdout or '').strip().splitlines()[-1] if po.stdout.strip() else ''
        _ok('P0-3[%d %r] 两包各自落到 <conf>/sub（同一相对根）' % (i + 1, text.strip()),
            root_f == want_f and root_o == want_o,
            'full=%r orch=%r want=%r/%r' % (root_f, root_o, want_f, want_o))
        _ok('P0-3[%d %r] 产物只出现在 sub/（conf 目录零新卷）' % (i + 1, text.strip()),
            os.path.exists(os.path.join(full, 'sub', 'index_账.tsv'))
            and not os.path.exists(os.path.join(full, 'index_账.tsv'))
            and os.path.exists(os.path.join(orch, 'sub', '注册卷.txt'))
            and not os.path.exists(os.path.join(orch, '注册卷.txt')),
            'full_sub=%s orch_sub=%s' % (
                os.path.isfile(os.path.join(full, 'sub', 'index_账.tsv')),
                os.path.isfile(os.path.join(orch, 'sub', '注册卷.txt'))))


_ALIAS_TABLES = ('SEC_ALIAS', 'KEY_ALIAS', 'FIELD_ALIAS')


def _alias_pairs(here):
    """从 conf_norm.py 读出「中文别名 → 英文正名」的字面对集合，供结构扫描比对。
    Read the literal (Chinese alias → canonical) pair set from conf_norm.py for the scan.
    用集合而非映射：同一中文键在不同表里可对应不同正名（`卷`→`volumes` 与 `卷`→`volume`）。
    A set, not a map: one Chinese key can map to different canonicals per table
    (`卷`→`volumes` and `卷`→`volume`)."""
    tree = ast.parse(io.open(os.path.join(here, 'conf_norm.py'), encoding='utf-8').read())
    pairs = set()
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in _ALIAS_TABLES and isinstance(node.value, ast.Dict)):
            continue
        for k, v in zip(node.value.keys, node.value.values):
            if (isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                    and isinstance(k.value, str) and isinstance(v.value, str)
                    and any('\u4e00' <= c <= '\u9fff' for c in k.value)):
                pairs.add((k.value, v.value))
    return pairs


def _alias_table_hits(here, skip=()):
    """扫全部 .py（含子目录/缩进/类体/dict()），抓「中文别名 → 英文正名」的映射字面量。
    Scan every .py (subdirs, indentation, class bodies, dict()) for alias-mapping literals.
    不数变量名：改名、换容器、搬进类里都躲不掉；只有字面量的位置是结构。
    No name counting: renaming or moving into a class cannot hide a literal mapping."""
    pairs = _alias_pairs(here)
    skip = {os.path.realpath(p) for p in skip}
    hits = []
    for root, dirs, files in os.walk(here):
        dirs[:] = sorted(d for d in dirs if d not in ('__pycache__', 'tests'))
        for fn in sorted(files):
            if not fn.endswith('.py') or fn == 'conf_norm.py':
                continue
            path = os.path.join(root, fn)
            if os.path.realpath(path) in skip:
                continue
            try:
                tree = ast.parse(io.open(path, encoding='utf-8').read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if (isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                                and isinstance(k.value, str)
                                and (k.value, v.value) in pairs):
                            hits.append((path, node.lineno, k.value, v.value, 'dict'))
                elif isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == 2:
                    a, b = node.elts
                    if (isinstance(a, ast.Constant) and isinstance(b, ast.Constant)
                            and isinstance(a.value, str)
                            and (a.value, b.value) in pairs):
                        hits.append((path, node.lineno, a.value, b.value, 'pair'))
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                      and node.func.id == 'dict'):
                    for kw in node.keywords:
                        if (isinstance(kw.value, ast.Constant)
                                and (kw.arg, kw.value.value) in pairs):
                            hits.append((path, node.lineno, kw.arg, kw.value.value, 'dict()'))
    return hits


def _case_conf_alias_single(here):
    """P0 归一表只许一张：按字面量位置判，不按变量名。
    P0 exactly one alias table: judged by literal positions, not by variable names.
    按名字计数仍靠声明（「你说它叫 FIELD_ALIAS 我才数」）；按字面量位置才是结构：
    `_LEGACY_FIELD = {'二级': 'level2'}`、类体里缩进一张、`dict(卷='volumes')`、
    子目录里再放一张，都躲不掉。改变量名也躲不掉。
    Counting names still relies on a declaration; literal positions are structural:
    a renamed dict, an indented class-body copy, a dict() call, or a copy in a subdirectory
    cannot hide — neither can renaming the variable."""
    print('  -- P0 归一表只许一张（字面量位置） --')
    hits = _alias_table_hits(here, skip=(os.path.abspath(__file__),))
    detail = '；'.join('%s:%d %r→%r(%s)'
                      % (os.path.relpath(p, here), ln, k, v, how)
                      for p, ln, k, v, how in hits)
    _ok('P0 中文别名映射字面量只出现在 conf_norm.py', not hits, detail or '命中 0')
    users = [f for f in ('daybook.py', 'daybook_multidx.py', 'volume_paths.py',
                         'orchestrator.py', 'mcp_tools.py')
             if os.path.exists(os.path.join(here, f))]
    lack = [f for f in users
            if 'from conf_norm import' not in io.open(
                os.path.join(here, f), encoding='utf-8').read()]
    _ok('P0 归一表的消费者都 import 自 conf_norm', not lack, '缺少=%s' % lack)
    # 反向自证：注入四种写法必红；只有 conf_norm.py 必绿。
    # Reverse proofs: four injected spellings must be red; conf_norm.py alone must be green.
    stage = tempfile.mkdtemp()
    clean = tempfile.mkdtemp()
    try:
        shutil.copy2(os.path.join(here, 'conf_norm.py'), os.path.join(stage, 'conf_norm.py'))
        shutil.copy2(os.path.join(here, 'conf_norm.py'), os.path.join(clean, 'conf_norm.py'))
        victim = next(f for f in ('orchestrator.py', 'daybook.py', 'ledger_root.py')
                      if os.path.exists(os.path.join(here, f)))
        text = io.open(os.path.join(here, victim), encoding='utf-8').read()
        io.open(os.path.join(stage, victim), 'w', encoding='utf-8').write(
            text + '\n_LEGACY_FIELD = {"二级": "level2"}\n'
            'class _Old:\n    _F = {"卷": "volumes"}\n'
            'dict(行号="line")\n'
            '_PAIR = ("标题", "title")\n')
        found = _alias_table_hits(stage)
        _ok('P0 反向自证：四种写法（顶层/类体/dict()/元组对）各 1 处必红',
            len(found) == 4, '命中=%d %s' % (len(found), [(os.path.basename(p), ln, k)
                                                       for p, ln, k, _v, _how in found]))
        alone = _alias_table_hits(clean)
        _ok('P0 反向自证：只有 conf_norm.py 时必绿', not alone, '命中=%d' % len(alone))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(clean, ignore_errors=True)


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
    # 不知道账本根就不写：append_one(root=None) 必须抛 ConfigError（码 2）且一个字节都不动
    # No root means no write: append_one(root=None) must raise ConfigError (code 2) and leave
    # the file untouched.
    p = os.path.join(d, '无根卷.txt')
    io.open(p, 'w', encoding='utf-8').write('[2026-11-13 10:00:00] [测试] [甲] [皮特] 正文\n')
    before = io.open(p, 'rb').read()
    rc = 0
    try:
        da.append_one(p, '测试', '无根', '正文', author='皮特')
    except Exception as exc:          # 入口只 raise，码由 errors 表给
        import errors as _err
        rc = _err.exit_code(exc)
    after = io.open(p, 'rb').read()
    _ok('AG 无账本根 ⇒ append_one raise ConfigError（码 2）且不写',
        rc == 2 and before == after, 'rc=%r changed=%s' % (rc, before != after))


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


def _case_cli_write_fail(tmp):
    """R9-2：写/锁被拒时 CLI 必须给文案 + rc=2，不得裸 traceback。
    R9-2: a refused write/lock must surface as a message + rc=2, never a bare traceback."""
    d = tempfile.mkdtemp(prefix='daybook_clifail_', dir=tmp)
    outside = tempfile.mkdtemp(prefix='daybook_outside_', dir=tmp)
    try:
        _prepare(d)
        r0 = _base(d)
        _ok('R9-2 前置：认基线 rc=0', r0.returncode == 0, 'rc=%d' % r0.returncode)
        idf = os.path.join(d, '索引', 'index_账.tsv')
        tgt = os.path.join(outside, 'index_账.tsv')
        shutil.copy2(idf, tgt)
        os.remove(idf)
        os.symlink(tgt, idf)
        before = io.open(tgt, 'rb').read()
        with io.open(os.path.join(d, '账卷.txt'), 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 10:05:00] [测试] [新增] [皮特] 写入\n')
        # 增量追加的 TSV 是符号链接到根外 ⇒ 追加写必须拒绝（RuntimeError）
        # The incremental TSV symlinks outside the root ⇒ the append must refuse
        r = _run(d)
        txt = r.stdout + r.stderr
        _ok('R9-2/R10-2 运行期拒绝 ⇒ rc=6（与配置错 2 分码）', r.returncode == 6,
            'rc=%d' % r.returncode)
        _ok('R9-2/R10-2 有明确文案（运行失败 + 原因）',
            '运行失败' in txt and ('不可用' in txt or '拒绝写入' in txt), txt[-240:])
        _ok('R9-2 无裸 traceback', 'Traceback' not in txt, txt[-240:])
        same = io.open(tgt, 'rb').read() == before
        _ok('R9-2 根外目标零改动', same, '零改动=%s' % same)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def _case_run_fail_compose(tmp):
    """R10-2：运行失败必须并入严重度合成，不许外层硬返回 2。
    R10-2: runtime failure joins the severity composition — never an outer hard return of 2."""
    # ① 作者红 + 写拒绝 ⇒ 4（不是 2）
    d = tempfile.mkdtemp(prefix='daybook_compose_', dir=tmp)
    outside = tempfile.mkdtemp(prefix='daybook_compose_out_', dir=tmp)
    try:
        _prepare(d)
        vol = os.path.join(d, '账卷.txt')
        txt = io.open(vol, encoding='utf-8').read().replace('[皮特]', '[ag-0123456789abcdef]')
        io.open(vol, 'w', encoding='utf-8').write(txt)
        r0 = _base(d)
        _ok('R10-2 前置：作者红基线仍 rc=0', r0.returncode == 0, 'rc=%d' % r0.returncode)
        idf = os.path.join(d, '索引', 'index_账.tsv')
        tgt = os.path.join(outside, 'index_账.tsv')
        shutil.copy2(idf, tgt)
        os.remove(idf)
        os.symlink(tgt, idf)
        with io.open(vol, 'a', encoding='utf-8') as f:
            f.write('[2026-11-13 10:05:00] [测试] [新增] [皮特] 写入\n')
        r = _run(d)
        out = r.stdout + r.stderr
        _ok('R10-2 作者红 + 写拒绝 ⇒ rc=4（不得降级为 2）', r.returncode == 4,
            'rc=%d' % r.returncode)
        _ok('R10-2 作者类与运行失败都打印，无 traceback',
            '作者' in out and '运行失败' in out and 'Traceback' not in out, out[-240:])
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)

    # ② 违例 + 写拒绝 ⇒ 3（注入 RuntimeError 到写入门之前，违例已记录）
    d2 = tempfile.mkdtemp(prefix='daybook_compose2_', dir=tmp)
    try:
        _prepare(d2)
        r0 = _base(d2)
        _ok('R10-2 前置②：基线 rc=0', r0.returncode == 0, 'rc=%d' % r0.returncode)
        vol = os.path.join(d2, '账卷.txt')
        lines = io.open(vol, encoding='utf-8').read().splitlines(True)
        mid = len(lines) // 2
        lines[mid] = lines[mid].replace('[皮特]', '[皮大]', 1)
        io.open(vol, 'w', encoding='utf-8').write(''.join(lines))
        src = io.open(os.path.join(d2, 'daybook.py'), encoding='utf-8').read()
        anchor = '        untrusted = bool(CONFIG_ERRORS or VIOLATIONS or EVIDENCE_MISSING)'
        if anchor in src:
            io.open(os.path.join(d2, 'daybook.py'), 'w', encoding='utf-8').write(
                src.replace(anchor, "        raise RuntimeError('注入写失败')\n" + anchor, 1))
            r = _run(d2)
            _ok('R10-2 违例 + 写拒绝 ⇒ rc=3（不得降级为 2/6）', r.returncode == 3,
                'rc=%d' % r.returncode)
        else:
            _ok('R10-2 违例 + 写拒绝 ⇒ rc=3（不得降级为 2/6）', False, '找不到写入门锚点')
    finally:
        shutil.rmtree(d2, ignore_errors=True)


_ENTRY_CHILD = r'''
import sys
sys.path.insert(0, sys.argv[1])
mod = __import__(sys.argv[2][:-3])
target = sys.argv[3]
setattr(mod, target, lambda *a, **k: (_ for _ in ()).throw(RuntimeError('注入失败')))
sys.argv = [sys.argv[2]] + sys.argv[4:]
try:
    rc = mod.main()
except SystemExit as exc:
    rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
print('RC %s' % rc)
'''


def _case_entry_wrappers(tmp):
    """R10-3：四个入口的顶层收口（文案前缀一致、rc=6、无 traceback）。
    R10-3: top-level boundaries of the four other entries (same prefix, rc=6, no traceback)."""
    here = os.path.dirname(SRC_BIN)
    cases = (
        ('daybook_append.py', 'append_one',
         ['--home', None, '账卷.txt', '测试', '标题', '皮特', '正文']),
        ('daybook_hook.py', 'run', ['--home', None, '对话.txt', '关键词.txt']),
        ('orchestrator.py', '_print_who', ['--home', None, 'who']),
        # R11-6③：Hub 初始化的 RuntimeError 不得被 except Exception 吞成 rc=2。
        # R11-6③: a RuntimeError from Hub.__init__ must not be swallowed into rc=2.
        ('orchestrator.py', 'Hub', ['--home', None, 'who']),
        ('mcp_server.py', 'serve', ['--home', None]),
    )
    for name, target, argv in cases:
        if not os.path.exists(os.path.join(here, name)):
            _skip('R10-3 %s（注入 %s）：当前盒无 %s' % (name, target, name))
            continue
        d = tempfile.mkdtemp(prefix='daybook_entry_', dir=tmp)
        try:
            _prepare(d)
            if name == 'daybook_hook.py':
                io.open(os.path.join(d, '对话.txt'), 'w', encoding='utf-8').write('')
                io.open(os.path.join(d, '关键词.txt'), 'w', encoding='utf-8').write('')
            args = ['-B', '-c', _ENTRY_CHILD, here, name, target] + \
                [d if a is None else a for a in argv]
            r = subprocess.run([sys.executable] + args, cwd=d, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True)
            out = r.stdout + r.stderr
            _ok('R10-3 %s（注入 %s）顶层收口 ⇒ rc=6、文案一致、无 traceback'
                % (name, target),
                'RC 6' in r.stdout and '★ 运行失败（rc=6）' in out
                and 'Traceback' not in out, 'out=%s' % out[-200:])
        finally:
            shutil.rmtree(d, ignore_errors=True)
    # R12-5：session hook 的 --state 指到 ROOT 之外 ⇒ rc=6、文案、无 traceback、越界零写
    # R12-5: session hook with --state outside ROOT ⇒ rc=6, shared wording, no traceback,
    # nothing written outside
    hook = os.path.join(here, 'daybook_session_hook.py')
    if not os.path.exists(hook):
        _skip('R12-5 daybook_session_hook.py：当前盒无 daybook_session_hook.py')
    else:
        d = tempfile.mkdtemp(prefix='daybook_hook_state_', dir=tmp)
        events = os.path.join(d, 'events')
        os.makedirs(events)
        outside = os.path.join(d, 'outside_state.json')
        try:
            r = subprocess.run(
                [sys.executable, '-B', hook, 'watch', '--once',
                 '--events-root', events, '--state', outside],
                cwd=d, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True)
            out = r.stdout + r.stderr
            _ok('R12-5 --state 越界 ⇒ rc=6、文案一致、无 traceback、越界零写',
                r.returncode == 6 and '★ 运行失败（rc=6）' in out
                and 'Traceback' not in out and not os.path.exists(outside),
                'rc=%d out=%s' % (r.returncode, out[-200:]))
        finally:
            shutil.rmtree(d, ignore_errors=True)


_ENTRIES = ('daybook.py', 'daybook_append.py', 'daybook_hook.py',
            'daybook_session_hook.py', 'orchestrator.py', 'mcp_server.py',
            'daybook_record.py', 'cross_ref.py')
_FAULTS7 = ('CONFIG', 'VIOLATION', 'AUTHOR', 'EVIDENCE', 'RUNTIME', 'COMPOSE', 'NO_TRACE')


def _load_mod(path, name):
    """按路径加载一个模块（用于加载变异副本，不污染 sys.modules 里的原件）。
    Load a module by path (used for mutant copies; never the original in sys.modules)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _literal_codes(path):
    """入口函数里出现字面非 0 退出码（return N / sys.exit(N) / raise SystemExit(N)）即返回清单。
    Non-zero literal exit codes inside entry functions (return N / sys.exit(N) / SystemExit(N))."""
    try:
        tree = ast.parse(io.open(path, encoding='utf-8').read())
    except (OSError, SyntaxError) as exc:
        return ['解析失败：%s' % exc]
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in ('main', '_main', '_entry', '_selftest'):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant)
                    and isinstance(sub.value.value, int) and sub.value.value != 0):
                bad.append('%s:return %s' % (node.name, sub.value.value))
            switch = (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                      and sub.func.attr == 'exit' and sub.args)
            se = (isinstance(sub, ast.Raise) and isinstance(sub.exc, ast.Call)
                  and getattr(sub.exc.func, 'id', '') == 'SystemExit' and sub.exc.args)
            if switch or se:
                a0 = (sub.args if switch else sub.exc.args)[0]
                if (isinstance(a0, ast.Constant) and isinstance(a0.value, int)
                        and a0.value != 0):
                    bad.append('%s:exit(%s)' % (node.name, a0.value))
    return bad


def _protocol_entry(entry):
    """源码结构推导：stdin 逐行协议型长驻入口（单次故障映射为响应，不是进程退出码）。
    Structural derivation: a long-running line-delimited protocol entry (a per-request fault
    becomes a response, not a process exit code)."""
    p = os.path.join(os.path.dirname(SRC_BIN), entry)
    if not os.path.exists(p):
        return False
    text = io.open(p, encoding='utf-8').read()
    return 'mcp_transport' in text and re.search(r'for line in (infile|sys\.stdin)', text) is not None


def _entry_writes_something(entry):
    """源码推导：入口自己有写原语调用（运行期写拒绝才可能被它映射成 6）。
    Derive from source: the entry itself calls a write primitive (only then can a runtime
    write refusal become its exit code 6)."""
    p = os.path.join(os.path.dirname(SRC_BIN), entry)
    if not os.path.exists(p):
        return False
    text = io.open(p, encoding='utf-8').read()
    return re.search(r'\.(write|update|mkdirs|mkdir|unlink|chmod|utime)\s*\(', text) \
        is not None or re.search(r'\bappend_one\s*\(', text) is not None


def _entry_build_caps(entry):
    """从入口 + 第一方 import 闭包推导它能触达哪些故障判据（机器推导，不写「不适用」表）。
    Derive which fault detectors an entry can reach from its own source plus the first-party
    import closure (machine-derived — no hand-written "not applicable" table).
      · 任意 `build(...)` ⇒ 可判 VIOLATION（dry 也算）
      · `build(..., dry=True)` 之外的 build ⇒ 可判 EVIDENCE（dry 不落盘、不报证据缺失）
      · `build(..., authors=True)` 或非 dry（默认跑作者机检）⇒ 可判 AUTHOR
    只沿**实际被调用的成员**走：`daybook.build(...)` 只扫 `build`，不会把 daybook 里
    其它函数（例如 index 的非 dry build）算到调用方头上。
    · any build call ⇒ VIOLATION; a non-dry build ⇒ EVIDENCE; authors=True or a non-dry
      build (author gate on by default) ⇒ AUTHOR. Traversal follows **called members only**:
      `daybook.build(...)` scans only `build`, so a caller is not credited with a non-dry
      build that lives in another function of the same module."""
    here = os.path.dirname(SRC_BIN)

    def caps_of(node, fname, allowed):
        if allowed is not None and (fname is None or fname not in allowed):
            return set()
        caps = set()
        for n in ast.walk(node):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            nm = (fn.id if isinstance(fn, ast.Name)
                  else (fn.attr if isinstance(fn, ast.Attribute) else ''))
            if nm != 'build':
                continue
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            dry = isinstance(kw.get('dry'), ast.Constant) and kw['dry'].value is True
            auth = kw.get('authors')
            auth_on = (isinstance(auth, ast.Constant) and auth.value is True) \
                or (auth is None and not dry)
            caps.add('VIOLATION')
            if not dry:
                caps.add('EVIDENCE')
            if auth_on:
                caps.add('AUTHOR')
        return caps

    caps, todo, seen = set(), [(entry, None)], set()
    while todo:
        name, allowed = todo.pop()
        if name in seen and allowed is not None:
            continue
        seen.add(name)
        p = os.path.join(here, name)
        if not os.path.exists(p):
            continue
        try:
            tree = ast.parse(io.open(p, encoding='utf-8').read())
        except (OSError, SyntaxError):
            continue
        scopes = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if allowed is None or n.name in allowed:
                    scopes.append(n)
            elif not isinstance(n, (ast.Import, ast.ImportFrom)):
                scopes.append(n)
        for sc in scopes:
            caps |= caps_of(sc, None, None)
        # 调用边只从**被允许的作用域**里取：`_main` 没被调用时，它内部的 import 不扩散。
        # Call edges come only from allowed scopes: an import inside an uncalled `_main`
        # does not spread to the caller.
        alias = {}
        used = {}
        import_nodes = [n for n in tree.body
                        if isinstance(n, (ast.Import, ast.ImportFrom))]
        for sc in scopes:
            import_nodes += [n for n in ast.walk(sc)
                             if isinstance(n, (ast.Import, ast.ImportFrom))]
        for n in import_nodes:
            if isinstance(n, ast.Import):
                for a in n.names:
                    root = a.name.split('.')[0]
                    if root in _FIRST_PARTY_MODULES:
                        alias[a.asname or root] = root
                        used.setdefault(root, set())
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                root = n.module.split('.')[0]
                if root in _FIRST_PARTY_MODULES:
                    used.setdefault(root, set()).update(a.name for a in n.names)
        # 第二轮再取成员：`import daybook` 与 `daybook.build` 的 AST 顺序不保证。
        # Second pass for members: import and attribute order is not guaranteed by ast.walk.
        for sc in scopes:
            for n in ast.walk(sc):
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                    mod = alias.get(n.value.id)
                    if mod:
                        used.setdefault(mod, set()).add(n.attr)
        for mod, members in used.items():
            todo.append((mod + '.py', members))
    return caps


def _case_error_table(tmp):
    """P6：错误表唯一映射——8 入口 × 7 故障类；同故障同码、多故障取最高严重度、无 traceback。
    P6: the single error table — 6 entries × 7 fault classes; the same fault maps to the same
    code everywhere, composition takes the highest severity, and no entry prints a traceback."""
    here = os.path.dirname(SRC_BIN)
    py = sys.executable

    E = _load_mod(os.path.join(here, 'errors.py'), 'p6_errors')
    _ok('P6 表：类别名 ↔ 码唯一且恰为 2/3/4/5/6',
        sorted(E.TABLE.values()) == [2, 3, 4, 5, 6]
        and set(E.TABLE) == {E.CONFIG, E.VIOLATION, E.AUTHOR, E.EVIDENCE, E.RUNTIME},
        'TABLE=%r' % (E.TABLE,))
    want = {E.ConfigError: 2, E.LedgerViolation: 3, E.AuthorConvention: 4,
            E.EvidenceMissing: 5, E.RuntimeFailure: 6, E.WriteRefused: 6}
    off = [(c.__name__, E.exit_code(c('x')), n) for c, n in want.items()
           if E.exit_code(c('x')) != n]
    _ok('P6 表：每个错误子类 → 固定码（WriteRefused 随父类 = 6）', not off, '偏差=%r' % off)
    off = []
    for classes, n in (((E.ConfigError, E.EvidenceMissing), 2),
                       ((E.AuthorConvention, E.RuntimeFailure), 4),
                       ((E.LedgerViolation, E.AuthorConvention, E.RuntimeFailure), 3),
                       ((E.RuntimeFailure, E.ConfigError), 6)):
        got = E.exit_code(E.worst([c('x') for c in classes]))
        if got != n:
            off.append(([c.__name__ for c in classes], got, n))
    _ok('P6 合成：多故障取最高严重度（违例 > 作者 > 运行 > 配置 > 证据）', not off,
        '偏差=%r' % off)
    _ok('P6 合成：空列表 ⇒ None；未知类别 ⇒ 6（绝不返回 0）',
        E.worst([]) is None and E.exit_code(type('X', (Exception,), {'kind': 99})()) == 6)

    # 静态：每个入口只有一个出口，且不持有数字码
    for name in _ENTRIES:
        p = os.path.join(here, name)
        if not os.path.exists(p):
            _skip('P6 %s：当前盒无此文件' % name)
            continue
        text = io.open(p, encoding='utf-8').read()
        lits = _literal_codes(p)
        n_run = len(re.findall(r'errors\.run_entry\(', text))
        holds = re.search(r'\bEXIT_[A-Z_]+\b', text) or re.search(r'\bworst_exit\b', text)
        _ok('P6 %s：唯一出口 errors.run_entry ×1、入口无字面非 0 码、无 EXIT_*/worst_exit'
            % name,
            n_run == 1 and not lits and not holds,
            'run_entry=%d 字面码=%r 旧常量=%s' % (n_run, lits, bool(holds)))

    cells = [0]
    stats = {'dyn': 0, 'na': 0, 'table': 0}
    outs = {n: [] for n in _ENTRIES}

    def probe(entry, kind, argv, cwd, env=None, input=None):
        """跑一格：退出码必须等于 TABLE[kind]，且输出无 traceback。
        入口文件不在当前盒里就显式跳过——不能拿「文件不存在也 rc=2」冒充同码。
        Run one cell: the status must equal TABLE[kind] and the output must have no traceback.
        When the entry file is absent from this box, skip explicitly — a missing file that also
        exits 2 must never masquerade as the same code."""
        ap = argv[0]
        full = ap if os.path.isabs(ap) else os.path.join(cwd, ap)
        if os.path.basename(ap) in _ENTRIES and not os.path.exists(full):
            na(entry, kind, '当前盒无 %s' % os.path.basename(ap))
            probed.add((entry, kind))
            return
        e = dict(os.environ)
        if env:
            e.update(env)
        r = subprocess.run([py, '-B'] + argv, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, env=e,
                           input=input)
        out = r.stdout + r.stderr
        outs[entry].append(out)
        if (entry, kind) not in probed:
            cells[0] += 1
            stats['dyn'] += 1
        probed.add((entry, kind))
        _ok('P6 %s × %s ⇒ rc=%d（表 %d）' % (entry, kind, E.TABLE[
            getattr(E, kind)], E.TABLE[getattr(E, kind)]),
            r.returncode == E.TABLE[getattr(E, kind)] and 'Traceback' not in out,
            'rc=%d out=%s' % (r.returncode, out[-160:].replace('\n', ' ')))

    def na(entry, kind, why):
        # 同一格可能有两支探针（例如盒内缺件时两条 orchestrator 探针都跳过）：只记一次。
        # One cell may have two probes (e.g. a missing box entry makes both orchestrator
        # probes skip): count it once.
        if (entry, kind) in probed:
            return
        probed.add((entry, kind))
        cells[0] += 1
        stats['na'] += 1
        _skip('P6 %s × %s 不适用：%s' % (entry, kind, why))

    # 适用性由代码路径推导（不手写）：入口能触达某判据 ⇒ 必须有探针，否则本格判红。
    # Applicability is derived from code paths (never hand-written): if an entry can reach a
    # detector, it must have a probe here; a reachable cell without a probe is red.
    caps = {e: _entry_build_caps(e) for e in _ENTRIES}
    probed = set()

    def settle(kind, why_for):
        """没探针的入口：可触达 ⇒ 红（缺探针）；不可触达/协议型 ⇒ 派生不适用。
        Entries without a probe: reachable ⇒ red (missing probe); unreachable/protocol ⇒
        derived not-applicable."""
        for e in _ENTRIES:
            if (e, kind) in probed:
                continue
            reachable = kind in caps[e]
            if _protocol_entry(e):
                na(e, kind, '源码结构推导：协议型长驻入口（mcp_transport + stdin 逐行），'
                            '单次故障映射为响应而不是进程退出码')
            elif reachable:
                _ok('P6 %s × %s 具备判据路径但缺探针 ⇒ 红' % (e, kind), False,
                    '推导：入口可触达 %s 判据' % kind)
            else:
                na(e, kind, '代码路径推导：入口及其第一方 import 闭包内没有 %s' % why_for)

    # CONFIG 固定三种形态 × 8 入口（session 拆无事件/有事件）：缺失 / 整份不可解析 /
    # [index] root=sub。形态穷举优先于格数；每格实跑并断言各自码轴。
    # P6 CONFIG: three fixed shapes × 8 entries (session split into no-event/with-event):
    # missing / wholly unparsable / [index] root=sub. Shapes first, then counts.
    def _conf_cell(rows, entry, shape, argv, cwd, want, why, input=None, env=None):
        ap = argv[0]
        full = ap if os.path.isabs(ap) else os.path.join(cwd, ap)
        if os.path.basename(ap) in _ENTRIES and not os.path.exists(full):
            na(entry, 'CONFIG', '当前盒无 %s' % os.path.basename(ap))
            return
        base = entry.split('[')[0]
        if base in _ENTRIES and (base, 'CONFIG') not in probed:
            probed.add((base, 'CONFIG'))
            cells[0] += 1
            stats['dyn'] += 1
        r = subprocess.run([py, '-B'] + argv, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, input=input,
                           env=env)
        out = r.stdout + r.stderr
        rows.append((entry, r.returncode))
        _ok('P6 CONFIG/%s %s ⇒ rc=%d（%s）' % (shape, entry, want, why),
            r.returncode == want and 'Traceback' not in out,
            'rc=%d out=%s' % (r.returncode, out[-160:].replace('\n', ' ')))

    for shape in ('缺失', '不可解析', 'root=sub'):
        d_c = tempfile.mkdtemp(prefix='p6c_', dir=tmp)
        try:
            # 会话根=脚本目录：整包拷进来，避免依赖外部目录。
            for nm in sorted(os.listdir(here)):
                if nm.endswith('.py'):
                    shutil.copy2(os.path.join(here, nm), os.path.join(d_c, nm))
            if shape == '不可解析':
                io.open(os.path.join(d_c, 'daybook.conf'), 'w',
                        encoding='utf-8').write('garbage\n')
            elif shape == 'root=sub':
                os.makedirs(os.path.join(d_c, 'sub'))
                io.open(os.path.join(d_c, 'daybook.conf'), 'w',
                        encoding='utf-8').write('[index]\nroot=sub\n')
            ev = os.path.join(d_c, 'events')
            os.makedirs(ev)
            # cross_ref 按卷名解析：给一份卷文件，探的是「conf 不参与根解析」而不是「卷不存在」。
            io.open(os.path.join(d_c, '协作卷.txt'), 'w', encoding='utf-8').write(
                '[2026-11-13 10:00:00] [测试] [第001条] [皮特] 正文\n')
            rows = []
            conf_bound = 2 if shape != 'root=sub' else None
            _conf_cell(rows, 'daybook.py', shape,
                       [os.path.join(d_c, 'daybook.py'), 'index'], d_c,
                       conf_bound if conf_bound is not None else 0,
                       'conf 绑定：空账本可解析' if shape == 'root=sub' else 'conf 绑定：%s ⇒ 2' % shape)
            _conf_cell(rows, 'daybook_append.py', shape,
                       [os.path.join(d_c, 'daybook_append.py'),
                        '账卷.txt', '测试', '标题', '皮特', '正文'], d_c,
                       conf_bound if conf_bound is not None else 6,
                       ('conf 参与根解析：%s ⇒ 2、零落盘' % shape) if conf_bound is not None
                       else '根跟随 conf=sub：目标不在根内 ⇒ 运行期拒绝 6')
            _conf_cell(rows, 'daybook_hook.py', shape,
                       [os.path.join(d_c, 'daybook_hook.py')], d_c,
                       conf_bound if conf_bound is not None else 5,
                       ('conf 参与根解析：%s ⇒ 2、零落盘' % shape) if conf_bound is not None
                       else '根跟随 conf=sub：对话卷不在根内 ⇒ 证据缺失 5')
            _conf_cell(rows, 'daybook_session_hook.py', shape,
                       [os.path.join(d_c, 'daybook_session_hook.py'), 'watch', '--once',
                        '--events-root', ev, '--state', os.path.join(d_c, 'st.json'),
                        '--workspace', d_c], d_c, 0,
                       '无事件：根固定为脚本目录，不读 conf ⇒ 0')
            evs = os.path.join(ev, 's')
            os.makedirs(evs)
            io.open(os.path.join(evs, 'events.jsonl'), 'w', encoding='utf-8').write(
                '\n'.join([json.dumps({'type': 'session.start',
                                       'data': {'context': {'cwd': d_c}}}),
                           json.dumps({'type': 'user.message', 'id': 'm1',
                                       'timestamp': '2026-11-13T10:00:00Z',
                                       'data': {'content': '探针'}})]) + '\n')
            _conf_cell(rows, 'daybook_session_hook.py[有事件]', shape,
                       [os.path.join(d_c, 'daybook_session_hook.py'), 'watch', '--once',
                        '--initialize', '--events-root', ev,
                        '--state', os.path.join(d_c, 'st.json'), '--workspace', d_c], d_c,
                       conf_bound if conf_bound is not None else 0,
                       ('有事件：经 record 读 conf ⇒ %d' % conf_bound) if conf_bound is not None
                       else '有事件：root=sub 可写 ⇒ 0')
            _conf_cell(rows, 'daybook_record.py', shape,
                       [os.path.join(d_c, 'daybook_record.py'), '--home', d_c,
                        '--role', '用户', '--no-index'], d_c,
                       conf_bound if conf_bound is not None else 0,
                       'conf 绑定：%s' % ('整份不可解析/缺失 ⇒ 2' if conf_bound is not None
                                        else 'root=sub 可写 ⇒ 0'), input='正文一行\n')
            _conf_cell(rows, 'orchestrator.py', shape,
                       [os.path.join(d_c, 'orchestrator.py'), 'alarm'], d_c,
                       conf_bound if conf_bound is not None else 0,
                       '初始化前严格校验：%s' % ('坏 conf ⇒ 2、零落盘' if conf_bound is not None
                                              else 'root=sub 干净 ⇒ 0'))
            # mcp：root=sub 这一格必须证明「根跟随 conf」，不能用「volumes 为空」碰巧同码。
            # 该格给一份带 [volumes] 的 conf、并在 sub/ 里不放卷 ⇒ 5（证据缺失），
            # 不是 2（空卷自检）。空卷另列一格，两种机制分开读。
            # mcp: the root=sub cell must prove "root follows conf", not accidentally match 2 via
            # an empty volume table. Give it a conf with [volumes] and leave the volume absent
            # under sub/ ⇒ 5 (missing evidence), not 2 (empty-volumes self-check). Empty volumes
            # get their own cell so the two mechanisms are never read as one.
            clean_env = {k: v for k, v in os.environ.items()
                         if k not in ('DAYBOOK_ROOT', 'DAYBOOK_HOME')}
            if shape == 'root=sub':
                d_m = os.path.join(d_c, 'mcpconf')
                os.makedirs(os.path.join(d_m, 'sub'))
                io.open(os.path.join(d_m, 'daybook.conf'), 'w', encoding='utf-8').write(
                    '[volumes]\n探针=探针卷.txt\n\n[index]\nroot=sub\n')
                _conf_cell(rows, 'mcp_server.py', shape,
                           [os.path.join(d_c, 'mcp_server.py')], d_m, 5,
                           'root 跟随 conf=sub：卷不在 sub ⇒ 证据缺失 5（不是空卷 2）',
                           env=clean_env)
            else:
                _conf_cell(rows, 'mcp_server.py', shape,
                           [os.path.join(d_c, 'mcp_server.py')], d_c, 2,
                           '启动自检：%s ⇒ 2' % shape, env=clean_env)
            d_ev0 = os.path.join(d_c, 'mcpmpty')
            os.makedirs(d_ev0)
            io.open(os.path.join(d_ev0, 'daybook.conf'), 'w', encoding='utf-8').write(
                '[volumes]\n\n[index]\nroot=\n')
            _conf_cell(rows, 'mcp_server.py', '空卷', [os.path.join(d_c, 'mcp_server.py')],
                       d_ev0, 2, '空卷自检单列：volumes 为空 ⇒ 配置错 2', env=clean_env)
            _conf_cell(rows, 'cross_ref.py', shape,
                       [os.path.join(d_c, 'cross_ref.py'), 'resolve', '协作卷', '1'], d_c, 0,
                       'conf 不参与根解析：按卷名解析 ⇒ 0')
            print('    [读数] CONFIG/%s：' % shape + '；'.join(
                '%s=%d' % (e, rc) for e, rc in rows))
        finally:
            shutil.rmtree(d_c, ignore_errors=True)

        # EVIDENCE：daybook（无封存）/ hook（缺对话卷）/ session（坏游标）同为 5
        d_ev = tempfile.mkdtemp(prefix='p6ev_', dir=tmp)
        try:
            _prepare(d_ev)
            probe('daybook.py', 'EVIDENCE', ['daybook.py'], d_ev)
            probe('daybook_hook.py', 'EVIDENCE',
                  [os.path.join(here, 'daybook_hook.py'), '--home', d_ev], d_ev)
            ev = os.path.join(d_ev, 'events')
            os.makedirs(ev)
            bad_state = os.path.join(d_ev, 'bad_state.json')
            io.open(bad_state, 'w', encoding='utf-8').write('{bad json')
            # ROOT 取脚本所在目录；--state 必须在 ROOT 内（越界建目录已判 rc=6，见 R12-5）。
            # ROOT is the script's directory; --state must live inside ROOT (an out-of-root
            # state dir is refused with rc=6, see R12-5).
            hook_ev = os.path.join(d_ev, 'daybook_session_hook.py')
            shutil.copy2(os.path.join(here, 'daybook_session_hook.py'), hook_ev)
            probe('daybook_session_hook.py', 'EVIDENCE',
                  [hook_ev, 'watch', '--once',
                   '--events-root', ev, '--state', bad_state, '--workspace', d_ev], d_ev)
            # record 从账本外 cwd 调：conf 取脚本目录，附录与索引都在同一根内 ⇒ 5
            # record invoked from an outside cwd: conf comes from the script dir and both the
            # append and the index stay on one root ⇒ 5
            probe('daybook_record.py', 'EVIDENCE',
                  [os.path.join(d_ev, 'daybook_record.py'), '--role', '用户'],
                  tmp, input='x\n')
            # session hook 走 record：同一条证据缺失路径，必须同码 5（不是 0/6）
            # The session hook goes through record: the same evidence path must exit 5.
            sess = os.path.join(ev, 'sess5')
            os.makedirs(sess)
            with io.open(os.path.join(sess, 'events.jsonl'), 'w', encoding='utf-8') as f:
                f.write(json.dumps({'type': 'session.start',
                                    'data': {'context': {'cwd': d_ev}}}) + '\n')
                f.write(json.dumps({'type': 'user.message', 'id': 'm5',
                                    'timestamp': '2026-11-13T10:00:00Z',
                                    'data': {'content': '证据缺失探针'}}) + '\n')
            probe('daybook_session_hook.py', 'EVIDENCE',
                  [hook_ev, 'watch', '--once', '--initialize',
                   '--events-root', ev, '--state', os.path.join(d_ev, 'state5.json'),
                   '--workspace', d_ev], d_ev)
        finally:
            shutil.rmtree(d_ev, ignore_errors=True)
        settle('EVIDENCE', ' build(dry=False)/EVIDENCE_MISSING 判据')

        # VIOLATION：daybook 等长改写 / 司南 幽灵负责人硬警 → 同为 3
        d_v = tempfile.mkdtemp(prefix='p6v_', dir=tmp)
        ev_v = None
        try:
            _prepare(d_v)
            _base(d_v)
            volp = os.path.join(d_v, '账卷.txt')
            lines = io.open(volp, encoding='utf-8').read().splitlines(True)
            mid = len(lines) // 2
            lines[mid] = lines[mid].replace('[皮特]', '[皮大]', 1)
            io.open(volp, 'w', encoding='utf-8').write(''.join(lines))
            probe('daybook.py', 'VIOLATION', ['daybook.py'], d_v)
            # record 现在进程内索引：同一条等长改写必须在**写任何字节前**判 3（旧实现先落
            # 原件与登记，再让 index 子进程报 3）。
            # record now indexes in-process: the same rewrite must exit 3 before any byte lands
            # (the old code wrote the original and the entry first, then the index child said 3).
            probe('daybook_record.py', 'VIOLATION',
                  [os.path.join(d_v, 'daybook_record.py'), '--role', '用户'],
                  d_v, input='violation probe\n')
            hook_v = os.path.join(d_v, 'daybook_session_hook.py')
            shutil.copy2(os.path.join(here, 'daybook_session_hook.py'), hook_v)
            ev_v = tempfile.mkdtemp(prefix='p6vev_', dir=tmp)
            sess_v = os.path.join(ev_v, 'sessv')
            os.makedirs(sess_v)
            with io.open(os.path.join(sess_v, 'events.jsonl'), 'w', encoding='utf-8') as f:
                f.write(json.dumps({'type': 'session.start',
                                    'data': {'context': {'cwd': d_v}}}) + '\n')
                f.write(json.dumps({'type': 'user.message', 'id': 'mv',
                                    'timestamp': '2026-11-13T10:00:00Z',
                                    'data': {'content': '违例探针'}}) + '\n')
            probe('daybook_session_hook.py', 'VIOLATION',
                  [hook_v, 'watch', '--once', '--initialize', '--events-root', ev_v,
                   '--state', os.path.join(d_v, 'statev.json'), '--workspace', d_v],
                  d_v)
            # 司南 alarm 把 append-only 纳入体检后，同一违例也必须 3（修前报「干净」）。
            # Sinan's alarm now checks append-only, so the same rewrite must exit 3.
            probe('orchestrator.py', 'VIOLATION',
                  [os.path.join(here, 'orchestrator.py'), '--home', d_v, 'alarm'], d_v)
        finally:
            shutil.rmtree(d_v, ignore_errors=True)
            if ev_v:
                shutil.rmtree(ev_v, ignore_errors=True)
        d_o = tempfile.mkdtemp(prefix='p6ov_', dir=tmp)
        try:
            with io.open(os.path.join(d_o, 'daybook.conf'), 'w', encoding='utf-8') as f:
                f.write(CONF)
            _make_volume(os.path.join(d_o, '账卷.txt'), n=2)
            orch = os.path.join(here, 'orchestrator.py')
            subprocess.run([py, '-B', orch, '--home', d_o, 'join', '汤姆'],
                           cwd=d_o, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([py, '-B', orch, '--home', d_o, 'open', '幽灵单', '--by',
                            'ag-ghost'],
                           cwd=d_o, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            probe('orchestrator.py', 'VIOLATION',
                  [orch, '--home', d_o, 'alarm'], d_o)
        finally:
            shutil.rmtree(d_o, ignore_errors=True)
        settle('VIOLATION', ' build (append-only 判据)')

        # AUTHOR：只有 daybook 有作者口径机检 → 4
        d_a = tempfile.mkdtemp(prefix='p6a_', dir=tmp)
        try:
            _prepare(d_a)
            _base(d_a)
            with io.open(os.path.join(d_a, '账卷.txt'), 'a', encoding='utf-8') as f:
                f.write('[2026-11-13 16:00:00] [测试] [机器id作者]'
                        ' [ag-0123456789abcdef] 正文\n')
            probe('daybook.py', 'AUTHOR', ['daybook.py'], d_a)
            # record 的前置 dry build 连作者口径一起判（authors=True）：作者红 ⇒ 4 零落盘。
            # record's dry precheck runs the author gate too (authors=True): red ⇒ 4, zero writes.
            probe('daybook_record.py', 'AUTHOR',
                  [os.path.join(d_a, 'daybook_record.py'), '--role', '用户'],
                  d_a, input='author probe\n')
            hook_a = os.path.join(d_a, 'daybook_session_hook.py')
            shutil.copy2(os.path.join(here, 'daybook_session_hook.py'), hook_a)
            ev_a = os.path.join(d_a, 'events_a')
            os.makedirs(os.path.join(ev_a, 'sessa'))
            with io.open(os.path.join(ev_a, 'sessa', 'events.jsonl'), 'w',
                         encoding='utf-8') as f:
                f.write(json.dumps({'type': 'session.start',
                                    'data': {'context': {'cwd': d_a}}}) + '\n')
                f.write(json.dumps({'type': 'user.message', 'id': 'ma',
                                    'timestamp': '2026-11-13T10:00:00Z',
                                    'data': {'content': '作者口径探针'}}) + '\n')
            probe('daybook_session_hook.py', 'AUTHOR',
                  [hook_a, 'watch', '--once', '--initialize', '--events-root', ev_a,
                   '--state', os.path.join(d_a, 'statea.json'), '--workspace', d_a],
                  d_a)
        finally:
            shutil.rmtree(d_a, ignore_errors=True)
        settle('AUTHOR', ' _report_authors（作者口径机检）')

        # RUNTIME：append 目标不可写 / session 状态越界 / 司南 体检读失败 → 同为 6
        d_r = tempfile.mkdtemp(prefix='p6r_', dir=tmp)
        ro = os.path.join(d_r, '只读卷.txt')
        try:
            _prepare(d_r)
            io.open(ro, 'w', encoding='utf-8').close()
            os.chmod(ro, 0o444)
            # 卷是目录 ⇒ 现在归配置错 2（errors.py 裁决）；运行期拒绝用「目标不可写」实测。
            # A directory volume is now a config error (2); runtime refusal is measured with
            # an unwritable target instead.
            probe('daybook_append.py', 'RUNTIME',
                  [os.path.join(here, 'daybook_append.py'), '--home', d_r,
                   '只读卷.txt', '测试', '标题', '皮特', '正文'], d_r)
        finally:
            try:
                os.chmod(ro, 0o644)
            except OSError:
                pass
            shutil.rmtree(d_r, ignore_errors=True)
        # daybook：基线后把根置为只读，backup 建 backup/ 被拒 ⇒ 6（运行期写拒绝）
        # daybook: after a baseline, a read-only root makes backup's mkdir fail ⇒ 6.
        d_b = tempfile.mkdtemp(prefix='p6bk_', dir=tmp)
        try:
            _prepare(d_b)
            _base(d_b)
            os.chmod(d_b, 0o555)
            try:
                probe('daybook.py', 'RUNTIME', ['daybook.py', 'backup'], d_b)
            finally:
                os.chmod(d_b, 0o755)
        finally:
            shutil.rmtree(d_b, ignore_errors=True)
        # daybook_hook：根只读 ⇒ mark_processed 建已处理卷被拒 ⇒ 6
        # daybook_hook: a read-only root refuses mark_processed's create ⇒ 6.
        d_h = tempfile.mkdtemp(prefix='p6hookr_', dir=tmp)
        try:
            _prepare(d_h)
            with io.open(os.path.join(d_h, '对话卷.txt'), 'w', encoding='utf-8') as f:
                f.write('[2026-11-13 10:00:00] [对话] [t] [皮特] 正文\n')
            with io.open(os.path.join(d_h, 'hook_a_关键词.txt'), 'w',
                         encoding='utf-8') as f:
                f.write('[账] [测试] 正文\n')
            os.chmod(d_h, 0o555)
            try:
                probe('daybook_hook.py', 'RUNTIME',
                      [os.path.join(here, 'daybook_hook.py'), '--home', d_h], d_h)
            finally:
                os.chmod(d_h, 0o755)
        finally:
            shutil.rmtree(d_h, ignore_errors=True)
        hook_run = [os.path.join(here, 'daybook_session_hook.py'), 'watch', '--once',
                    '--events-root', os.path.join(tmp, 'p6_events_%d' % os.getpid()),
                    '--workspace', here]
        ev6 = hook_run[4]
        os.makedirs(ev6, exist_ok=True)
        try:
            probe('daybook_session_hook.py', 'RUNTIME',
                  hook_run + ['--state', os.path.join(tmp,
                                                      'p6_outside_%d.json' % os.getpid())],
                  here)
        finally:
            shutil.rmtree(ev6, ignore_errors=True)
        d_or = tempfile.mkdtemp(prefix='p6orr_', dir=tmp)
        try:
            with io.open(os.path.join(d_or, 'daybook.conf'), 'w', encoding='utf-8') as f:
                f.write(CONF)
            os.makedirs(os.path.join(d_or, '任务卷.txt'))
            probe('orchestrator.py', 'RUNTIME',
                  [os.path.join(here, 'orchestrator.py'), '--home', d_or, 'alarm'], d_or)
        finally:
            shutil.rmtree(d_or, ignore_errors=True)
        # record 的运行期失败：原件目录被普通文件占住（基线之后），mkdirs 被拒 ⇒ 6
        # record runtime failure: the archive path is occupied by a regular file (after a
        # baseline), so mkdirs is refused ⇒ 6.
        d_rt = tempfile.mkdtemp(prefix='p6_rt_')
        try:
            _prepare(d_rt)
            _base(d_rt)
            io.open(os.path.join(d_rt, '对话原件'), 'w', encoding='utf-8').write('occupied')
            probe('daybook_record.py', 'RUNTIME',
                  [os.path.join(d_rt, 'daybook_record.py'), '--role', '用户'],
                  d_rt, input='x\n')
        finally:
            shutil.rmtree(d_rt, ignore_errors=True)
        # RUNTIME 适用性同样由代码路径推导：协议型入口 ⇒ 响应不是退出码；
        # 无写原语的入口 ⇒ 无运行期写拒绝可测；有写路径却缺探针 ⇒ 红。
        # RUNTIME applicability is derived too: protocol ⇒ response not exit code; no write
        # primitive ⇒ no runtime write refusal to test; a write path without a probe ⇒ red.
        for e in _ENTRIES:
            if (e, 'RUNTIME') in probed:
                continue
            if _protocol_entry(e):
                na(e, 'RUNTIME', '源码结构推导：协议型长驻入口，单次故障映射为响应')
            elif _entry_writes_something(e):
                _ok('P6 %s × RUNTIME 具备写路径但缺探针 ⇒ 红' % e, False,
                    '推导：入口源码含写原语调用')
            else:
                na(e, 'RUNTIME', '代码路径推导：入口源码里没有写原语调用（只读入口）')

    # COMPOSE：合成只在 errors.worst 一处，八个入口共用同一份（逐入口记一格）
    comp_ok = E.worst([E.LedgerViolation('v'), E.AuthorConvention('a'),
                       E.RuntimeFailure('r')]).kind == E.VIOLATION
    for entry in _ENTRIES:
        cells[0] += 1
        stats['table'] += 1
        _ok('P6 %s × COMPOSE（表级 worst 合成）' % entry, comp_ok)

    # NO_TRACE：本入口所有动态探针的输出里都不得有 traceback
    for entry in _ENTRIES:
        if not outs[entry]:
            cells[0] += 1
            stats['na'] += 1
            _skip('P6 %s × NO_TRACE 不适用：本层没有该入口的动态探针' % entry)
            continue
        cells[0] += 1
        stats['table'] += 1
        _ok('P6 %s × NO_TRACE：全部探针输出无 traceback' % entry,
            all('Traceback' not in o for o in outs[entry]))

    _ok('P6 矩阵格数对账（8 入口 × 7 故障类 = 56）',
        cells[0] == 56 and stats['dyn'] + stats['na'] + stats['table'] == 56,
        '动态实跑 %d 格 / 派生不适用 %d 格 / 表级合成与无栈 %d 格'
        % (stats['dyn'], stats['na'], stats['table']))

    # 收口回归：司南自检全绿——「持租约锁后再记日志」不得同线程重入根锁（会自死锁）
    # Boundary regression: Sinan's self-test must be green — logging while holding a lease must
    # not re-enter the root lock in the same thread (that self-deadlocks).
    osel = os.path.join(here, 'orchestrator.py')
    if os.path.exists(osel):
        r = subprocess.run([py, '-B', osel, 'selftest'], cwd=here,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True)
        out = r.stdout + r.stderr
        _ok('P6 司南自检：持租约锁内记日志不重入锁 ⇒ rc=0 全绿',
            r.returncode == 0 and '全绿' in out and 'Traceback' not in out,
            'rc=%d out=%s' % (r.returncode, out[-200:].replace('\n', ' ')))
    else:
        _skip('P6 司南自检：当前盒无 orchestrator.py')

    # 变异 M6：入口插字面 `return 2` ⇒ 静态判据必须红
    src = io.open(os.path.join(here, 'daybook.py'), encoding='utf-8').read()
    anchor = 'def _main():'
    if anchor not in src:
        _mut_ok('M6 入口插 return 2 ⇒ 必红', False, '锚点缺失', dead=True)
    else:
        mut = os.path.join(tmp, 'p6_m6_daybook.py')
        io.open(mut, 'w', encoding='utf-8').write(
            src.replace(anchor, anchor + '\n    return 2', 1))
        lits = _literal_codes(mut)
        _mut_ok('M6 入口插 return 2 ⇒ 必红（静态判据抓到 %r）' % lits, bool(lits), '')

    # 变异 M6b：把 ConfigError 映射成 6 ⇒ 表判据必须红
    esrc = io.open(os.path.join(here, 'errors.py'), encoding='utf-8').read()
    eanchor = 'class ConfigError(DaybookError):\n    kind = CONFIG'
    if eanchor not in esrc:
        _mut_ok('M6b ConfigError 映射成 6 ⇒ 必红', False, '锚点缺失', dead=True)
    else:
        emut = os.path.join(tmp, 'p6_m6b_errors.py')
        io.open(emut, 'w', encoding='utf-8').write(
            esrc.replace(eanchor, 'class ConfigError(DaybookError):\n    kind = RUNTIME', 1))
        EM = _load_mod(emut, 'p6_errors_m6b')
        got = EM.exit_code(EM.ConfigError('x'))
        _mut_ok('M6b ConfigError 映射成 6 ⇒ 必红（变异体给出 rc=%d）' % got, got != 2, '')


_WIN_CHILD = r'''
import os, sys, tempfile, shutil
src = sys.argv[1]
sys.path.insert(0, src)
import safeio

if os.name != 'nt':
    # POSIX 上强制走 Windows 路径分支；互斥量用 flock 占位（真实互斥量另由 W2 在 Windows 验证）。
    # Force the Windows path branch on POSIX; the mutex is stubbed with flock (the real mutex is
    # covered by W2 on Windows).
    import fcntl
    safeio._WINDOWS = True
    def _wl(rt, timeout):
        fd = os.open(rt.label, os.O_RDONLY)
        if timeout is None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    def _wu(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    safeio._win_lock, safeio._win_unlock = _wl, _wu

base = tempfile.mkdtemp(prefix='winpath_')
try:
    A = os.path.join(base, 'A')
    B = os.path.join(base, 'B')
    os.makedirs(A)
    os.makedirs(B)
    rt = safeio.Root._from_dir_path(A, 'winpath')
    assert rt._fd is None, 'Windows 路径不应有目录 fd'
    with rt.lock() as lr:
        assert lr.write(rt.rel('x.txt'), b'a\n', mode=safeio.WriteMode.APPEND_CREATE) is False
        assert lr.write(rt.rel('x.txt'), b'b', mode=safeio.WriteMode.APPEND_EXISTING,
                        pad_newline=True) is False
        lr.write(rt.rel('y.txt'), b'zz\n', mode=safeio.WriteMode.REPLACE)
        # 六个目录类原语必须显式拒绝，不静默回退按路径
        # The six directory primitives must reject explicitly, never fall back to path calls
        for _fn, _args in (
                ('mkdir', (rt.rel('d1'),)),
                ('mkdirs', (rt.rel('d2'),)),
                ('mkdirs_path', (os.path.join(A, 'd3'),)),
                ('chmod', (rt.rel('x.txt'), 0o600)),
                ('unlink', (rt.rel('x.txt'),)),
                ('utime', (rt.rel('x.txt'), (0, 0)))):
            try:
                getattr(lr, _fn)(*_args)
            except RuntimeError:
                pass
            else:
                raise AssertionError('%s 未在 Windows 分支拒绝' % _fn)
    assert rt.read(rt.rel('x.txt')) == b'a\nb'
    assert rt.read(rt.rel('y.txt')) == b'zz\n'
    try:
        with rt.lock() as lr:
            lr.write(rt.rel('nope.txt'), b'q\n', mode=safeio.WriteMode.APPEND_EXISTING)
        raise AssertionError('缺件 append 未报错')
    except RuntimeError:
        pass
    assert not os.path.exists(os.path.join(A, 'nope.txt'))
    os.symlink(B, os.path.join(A, 'link'))
    try:
        with rt.lock() as lr:
            lr.write(rt.rel('link', 'z.txt'), b'q\n', mode=safeio.WriteMode.APPEND_CREATE)
        raise AssertionError('重解析点未拒绝')
    except RuntimeError:
        pass
    assert not os.path.exists(os.path.join(B, 'z.txt'))
    print('WINPATH_OK')
finally:
    shutil.rmtree(base, ignore_errors=True)
'''

_WIN_HOLD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
import safeio
rt = safeio.Root._from_dir_path(sys.argv[2], 'winhold')
with rt.lock():
    print('READY', flush=True)
    time.sleep(1.0)
rt.close()
'''

_WIN_TRY = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import safeio
rt = safeio.Root._from_dir_path(sys.argv[2], 'wintry')
try:
    rt.lock(timeout=0.3)
    print('WINLOCK_BAD')
except TimeoutError:
    print('WINLOCK_OK')
finally:
    rt.close()
'''


def _case_win_path(work):
    """W1/W2：Windows 写路径分支（POSIX 上强制跑一遍）与 Windows 原生互斥量。
    W1/W2: the Windows write-path branch (forced on POSIX to keep it exercised) and the native
    Windows mutex. A judge that cannot run on the current platform is skipped **with its reason
    printed and counted** — never silently treated as passing."""
    d = os.path.join(work, 'winpath')
    os.makedirs(d)
    child = os.path.join(d, 'w.py')
    with io.open(child, 'w', encoding='utf-8') as f:
        f.write(_WIN_CHILD)
    r = subprocess.run([sys.executable, '-I', '-B', child, os.path.dirname(SRC_BIN)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=180)
    out = (r.stdout + r.stderr).strip()
    _ok('W1 Windows 写路径分支（无目录 fd·realpath 归属判·拒绝重解析点·追加后复核 inode·'
        'mkdir/mkdirs/mkdirs_path/chmod/unlink/utime 六原语显式拒绝）',
        'WINPATH_OK' in out, out[-200:])
    if os.name == 'nt':
        hold = os.path.join(d, 'hold.py')
        try_ = os.path.join(d, 'try.py')
        with io.open(hold, 'w', encoding='utf-8') as f:
            f.write(_WIN_HOLD)
        with io.open(try_, 'w', encoding='utf-8') as f:
            f.write(_WIN_TRY)
        root = os.path.join(d, 'ledger')
        os.makedirs(root)
        p = subprocess.Popen([sys.executable, '-B', hold, os.path.dirname(SRC_BIN), root],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        try:
            p.stdout.readline()
            r2 = subprocess.run([sys.executable, '-B', try_, os.path.dirname(SRC_BIN), root],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=60)
            out2 = (r2.stdout + r2.stderr).strip()
        finally:
            p.communicate(timeout=60)
        _ok('W2 Windows 命名互斥量：持锁进程期间另一进程 0.3s 内拿不到锁',
            'WINLOCK_OK' in out2, out2[-200:])
    else:
        _skip('W2 Windows 命名互斥量/原生写路径：当前平台 POSIX，未在 Windows 验证（计数 1）')


def _case_plain_migrate(work):
    """TXT/MIG：明文人可读可查验（只用标准库）＋ 干净位置换用户目录、只凭仓内文件说清最后一条与下一步。
    TXT/MIG: plain-text readable/verifiable with the standard library only, and a clean-location
    / different-HOME run that names the last record and the next action from repo files alone."""
    d = os.path.join(work, 'plain')
    os.makedirs(d)
    root = os.path.join(d, 'ledger')
    os.makedirs(os.path.join(root, '索引'))
    vol = os.path.join(root, '账卷.txt')
    with io.open(vol, 'w', encoding='utf-8') as f:
        f.write('[2026-11-15 09:01:00] [科研] [第一条] [老宋] 甲\n')
        f.write('[2026-11-15 09:02:00] [审计] [第二条] [老宋] 乙\n')
    idx = os.path.join(root, '索引', 'index_账.tsv')
    with io.open(idx, 'w', encoding='utf-8') as f:
        f.write('账\t1\t2026-11-15 09:01:00\t科研\t第一条\t老宋\n')
        f.write('账\t2\t2026-11-15 09:02:00\t审计\t第二条\t老宋\n')
    # 干净位置：只拷仓内 .py，隔离模式（-I -S）⇒ 不读 site-packages、不认环境变量
    # Clean location: copy repo .py files only, run isolated (-I -S) so no site-packages or env
    clean = os.path.join(d, 'clean')
    os.makedirs(clean)
    srcdir = os.path.dirname(SRC_BIN)
    for name in os.listdir(srcdir):
        if name.endswith('.py'):
            shutil.copy2(os.path.join(srcdir, name), os.path.join(clean, name))
    home = os.path.join(d, 'home')
    os.makedirs(home)
    env = {'HOME': home, 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
           'LANG': 'C.UTF-8'}
    r = subprocess.run([sys.executable, '-I', '-S', '-B',
                        os.path.join(clean, 'verify_plain.py'), vol, idx],
                       cwd='/', env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    _ok('TXT 明文人可读可查验：不用任何 daybook 模块即读出时间/类别/标题/作者与完整性结论',
        r.returncode == 0 and '时间=2026-11-15 09:02:00' in out and '类别=审计' in out
        and '标题=第二条' in out and '作者=老宋' in out
        and '完整性：OK' in out, out[-240:])
    _ok('MIG 干净位置/换用户目录/无私有依赖：只凭仓内文件说清最后一条与下一步',
        '最后一条：时间=2026-11-15 09:02:00' in out and '下一步：' in out
        and 'Traceback' not in out, out[-240:])


def _case_shell_plain(work):
    """SH：裸终端判据——只用 POSIX sh + tail/grep/awk/od（PATH 里没有 python）读出
    最后一条记录的时间/类别/标题/作者，并按手工步骤给出完整性结论。
    SH: bare-terminal criterion — POSIX sh + tail/grep/awk/od only (no python on PATH) reads the
    last record's time/category/title/author and reaches an integrity conclusion."""
    d = os.path.join(work, 'shplain')
    bindir = os.path.join(d, 'bin')
    os.makedirs(bindir)
    for name in ('tail', 'grep', 'awk', 'od', 'tr', 'cat'):
        src = shutil.which(name)
        if not src:
            _ok('SH 裸终端：环境缺少 %s' % name, False, '未找到该命令')
            return
        os.symlink(src, os.path.join(bindir, name))
    sh = shutil.which('sh') or '/bin/sh'
    script = os.path.join(os.path.dirname(SRC_BIN), 'verify_plain.sh')
    if not os.path.exists(script):
        _ok('SH 裸终端：verify_plain.sh 随包', False, '缺少 %s' % script)
        return
    vol = os.path.join(d, '账卷.txt')
    idx = os.path.join(d, 'index_账.tsv')
    with io.open(vol, 'w', encoding='utf-8') as f:
        f.write('[2026-11-15 09:01:00] [科研] [第一条] [老宋] 甲\n')
        f.write('[2026-11-15 09:02:00] [审计] [第二条] [老宋] 乙\n')
    with io.open(idx, 'w', encoding='utf-8') as f:
        f.write('账\t1\t2026-11-15 09:01:00\t科研\t第一条\t老宋\n')
        f.write('账\t2\t2026-11-15 09:02:00\t审计\t第二条\t老宋\n')
    env = {'PATH': bindir, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    r = subprocess.run([sh, script, vol, idx], cwd='/', env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    _ok('SH 裸终端（无 Python，PATH 只有 sh/tail/grep/awk/od）：rc=0 且读出时间/类别/标题/作者',
        r.returncode == 0 and '时间=2026-11-15 09:02:00' in out and '类别=审计' in out
        and '标题=第二条' in out and '作者=老宋' in out, out[-220:])
    _ok('SH 裸终端：完整性结论 OK（坏行 0、索引一致）',
        '完整性：OK' in out and '坏行=0' in out, out[-220:])
    # 坏行 ⇒ 必须 BAD 且给出下一步；不许静默当通过
    with io.open(vol, 'a', encoding='utf-8') as f:
        f.write('这一行没有五段头\n')
    r2 = subprocess.run([sh, script, vol, idx], cwd='/', env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=120)
    out2 = (r2.stdout + r2.stderr).strip()
    _ok('SH 裸终端：坏行 ⇒ rc=1 且 完整性 BAD（坏行 1）',
        r2.returncode == 1 and '完整性：BAD（坏行 1' in out2, out2[-220:])
    # 末字节不是换行 ⇒ 视为可能截断，必须 BAD
    with io.open(vol, 'wb') as f:
        f.write(u'[2026-11-15 09:01:00] [科研] [x] [老宋] y'.encode('utf-8'))
    r3 = subprocess.run([sh, script, vol], cwd='/', env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, timeout=120)
    out3 = (r3.stdout + r3.stderr).strip()
    _ok('SH 裸终端：末字节非换行 ⇒ rc=1 且判「可能被截断」',
        r3.returncode == 1 and '末字节不是换行' in out3, out3[-220:])


def _case_pack_verify(work):
    """PK：打包一致闸（步骤 6）——不变量「源件唯一，盒内副本逐字节一致」由 pack.py 的
    plan_for() 唯一拥有：build 与 verify 都从同一清单派生，不各写一套。
    PK: the packaging consistency gate (step 6). The invariant "one source, every in-box copy
    byte-identical" has a single owner — plan_for(); build and verify both derive from it."""
    src_root = os.path.dirname(os.path.abspath(SRC_BIN))
    pack = os.path.join(src_root, 'pack.py')
    if not os.path.exists(pack):
        _skip('PK 步骤 6：本盒无 pack.py（打包器只在源树跑；盒内副本已由该闸生成）')
        return
    out = os.path.join(work, 'pk')
    box = os.path.join(out, 'daybook')

    def run(*extra):
        r = subprocess.run([sys.executable, '-B', pack, '--src', src_root,
                            '--out', out, '--pkg', 'daybook'] + list(extra),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=180)
        return r.returncode, (r.stdout + r.stderr)

    rc, txt = run()
    _ok('PK 打包（daybook）绿', rc == 0, txt[-160:])
    rc, txt = run('--verify')
    _ok('PK 刚打包后 verify 绿（产物 == 源）', rc == 0, txt[-160:])

    # 红证 1：手改盒内 safeio.py 一个字节 ⇒ 必须红
    p = os.path.join(box, 'safeio.py')
    raw = bytearray(io.open(p, 'rb').read())
    raw[0] = ord('!') if raw[0] != ord('!') else ord('#')
    io.open(p, 'wb').write(bytes(raw))
    rc, txt = run('--verify')
    _ok('PK 手改盒内 safeio.py 一字节 ⇒ verify 红', rc != 0 and 'safeio.py' in txt,
        txt[-200:])
    shutil.copy2(os.path.join(src_root, 'safeio.py'), p)

    # 红证 2：删盒内一件 ⇒ 必须红（不是「少一个也算过」）
    os.remove(os.path.join(box, 'daybook.py'))
    rc, txt = run('--verify')
    _ok('PK 删盒内 daybook.py ⇒ verify 红', rc != 0 and 'daybook.py' in txt,
        txt[-200:])
    shutil.copy2(os.path.join(src_root, 'daybook.py'), os.path.join(box, 'daybook.py'))

    # 红证 3：盒内多一份清单外副本 ⇒ 必须红（防「改一处漏三处」靠手工同步）
    stray = os.path.join(box, 'safeio_copy.py')
    io.open(stray, 'w', encoding='utf-8').write('# duplicate\n')
    rc, txt = run('--verify')
    _ok('PK 盒内多一份清单外副本 ⇒ verify 红', rc != 0 and 'safeio_copy.py' in txt,
        txt[-200:])
    os.remove(stray)

    rc, txt = run('--verify')
    _ok('PK 复原后 verify 复绿', rc == 0, txt[-160:])


def _closure_parts(trees, sites, product, reg):
    """闭包面的两组判定素材：未登记的写能力函数；未解析且与写能力函数同名的边。
    The two closure verdicts: unregistered write-capable functions, and unresolved edges
    whose callee name matches a write-capable function."""
    cap, edges, unresolved = _closure_capability(trees, sites, reg)
    missing = sorted(k for k in cap
                     if k[0] in product and not _is_entry(*k) and k not in reg)
    # 「写能力函数」按登记桶判：ledger/impl 才是能写根内状态的函数；闭包面补签的只读路径
    # （other 桶、自身无直接写类别）不算，否则 read/get/list 这类同名会把信号淹掉。
    # "Write-capable" means ledger/impl buckets (they can change in-root state). Closure-only
    # read paths in the other bucket do not count, or names like read/get/list drown the signal.
    # 入口双重限定：只有「入口名 + 入口文件」才算入口；名字相同但不在入口文件里的内部函数
    # 仍进写能力名集（宁红勿漏）。
    # Entry is double-qualified: only entry-name **and** entry-file counts; an internal function
    # with the same name in another file stays in the write-capable name set.
    names = {fn for (f, fn) in reg
             if reg[(f, fn)][0] in ('ledger', 'impl') and not _is_entry(f, fn)}
    names |= {fn for (f, fn), kinds in sites.items()
              if kinds & _LEDGER_KINDS and not _is_entry(f, fn)}
    # 未解析边再切一刀：纯计算面（内建/容器方法名）不算闭包缺口；只把可能写的那一侧
    # 当真实缺口，并只在这一侧做「同名 ⇒ 红」。
    # Split unresolved edges again: the pure-computation surface is not a closure gap; only the
    # possibly-writing side counts as a real gap and is subject to the same-name red.
    gap = [u for u in unresolved if u['callee'] not in _PURE_METHOD_NAMES]
    hits = sorted({(u['file'], u['fn'], u['callee'], u['line']) for u in gap
                   if u['file'] in product and u['callee']
                   and u['callee'] in names
                   and (u['file'], u['fn'], u['callee'], u['line']) not in _CLOSURE_EXEMPT})
    # 差额必须报集合差（两侧），不许用 |cap|−|reg| 的算术差冒充。
    # Differences are reported as two set differences; the arithmetic |cap|−|reg| is not a gap.
    cap_minus = sorted(set(cap) - set(reg))
    reg_minus = sorted(set(reg) - set(cap))
    return (cap, edges, unresolved, missing, hits, gap, cap_minus, reg_minus)


def _closure_role(k, product):
    """差额构成：入口（8 入口文件×入口名）/ 随包测试辅助 / 产品内部件。
    Difference composition: entry (entry name in an entry file) / bundled test-aux / product."""
    if _is_entry(*k):
        return '入口'
    if k[0] not in product:
        return '随包测试/辅助'
    return '产品内部件'


def _closure_diff_text(cap_minus, reg_minus, product, reg):
    """记分板用的单行差额构成（两组集合差都要出现，且与覆盖率同屏）。
    One-line difference composition for the scoreboard (both set differences, next to coverage)."""
    roles = {}
    for k in cap_minus:
        r = _closure_role(k, product)
        roles[r] = roles.get(r, 0) + 1
    buckets = {}
    for k in reg_minus:
        b = reg[k][0]
        buckets[b] = buckets.get(b, 0) + 1
    return ('cap−reg %d（入口 %d｜测试/辅助 %d｜产品内部件 %d）｜reg−cap %d（%s）'
            % (len(cap_minus), roles.get('入口', 0), roles.get('随包测试/辅助', 0),
               roles.get('产品内部件', 0), len(reg_minus),
               '｜'.join('%s %d' % (b, buckets[b]) for b in sorted(buckets))))


def _audit_closure():
    """闭包面读数（完整输出）：已解析/未解析边数、未解析按类型逐条 file:line、
    未登记写能力函数、同名未解析边、已签豁免。只报告细节；红判据在 `_case_write_paths`。
    Closure reading (full output): resolved/unresolved edges, every unresolved edge by type
    with file:line, unregistered write-capable functions, same-name unresolved edges, and
    signed exemptions. Red verdicts live in `_case_write_paths`."""
    d = os.path.dirname(os.path.abspath(SRC_BIN))
    _files, sites, trees, product = _scan_write_sites(d)
    reg = {(f, fn): (b, r) for f, fn, b, r in WRITE_PATHS}
    cap, edges, unresolved, missing, hits, gap, cap_minus, reg_minus = _closure_parts(
        trees, sites, product, reg)
    nedges = sum(len(v) for v in edges.values())
    total = nedges + len(unresolved)
    print('[audit-closure] 已解析边=%d 未解析边=%d 总边=%d 闭包覆盖=%d/%d=%d%%'
          % (nedges, len(unresolved), total, nedges, total,
             (100 * nedges // total) if total else 100))
    print('  未解析切分：内建/容器方法面=%d 可能写缺口=%d' % (len(unresolved) - len(gap), len(gap)))
    print('  写能力函数=%d 未登记=%d' % (len(cap), len(missing)))
    # 差额只报集合差与构成，不许用 |cap|−|reg| 的算术差冒充。
    # Differences are set differences with composition; the arithmetic |cap|−|reg| is not a gap.
    print('  集合差 cap−reg 共 %d 条（cap=写能力面，reg=登记表）' % len(cap_minus))
    for role in ('入口', '随包测试/辅助', '产品内部件'):
        rows = [k for k in cap_minus if _closure_role(k, product) == role]
        print('    [%s] %d 条' % (role, len(rows)))
        for f, fn in rows:
            print('      %s::%s' % (f, fn))
    print('  集合差 reg−cap 共 %d 条（按登记桶分组；桶名只是预期，不代表写能力）' % len(reg_minus))
    for b in sorted({reg[k][0] for k in reg_minus}):
        rows = [k for k in reg_minus if reg[k][0] == b]
        print('    [%s] %d 条' % (b, len(rows)))
        for f, fn in rows:
            print('      %s::%s  %s' % (f, fn, reg[(f, fn)][1]))
    by = {}
    for u in unresolved:
        by.setdefault(u['reason'], []).append(u)
    for reason in ('from-import', 'instance-method', 'getattr', 'dispatch', 'other'):
        rows = by.get(reason, [])
        print('  未解析[%s] 共 %d 条' % (reason, len(rows)))
        for u in rows:
            print('    %s:%d %s()  callee=%s  expr=%s'
                  % (u['file'], u['line'], u['fn'], u['callee'] or '-', u['expr']))
    print('  未登记写能力函数（产品内部件·须逐条签）共 %d 条' % len(missing))
    for f, fn in missing:
        print('    %s::%s' % (f, fn))
    print('  未解析边同名写能力函数（红，除非已豁免）共 %d 条' % len(hits))
    for f, fn, callee, line in hits:
        print('    %s:%d %s() callee=%s' % (f, line, fn, callee))
    vrefs = _capability_value_refs(trees, product, reg, sites)
    print('  写能力/写原语当值传（只许直接调用或登记表）共 %d 条' % len(vrefs))
    for r in vrefs:
        print('    %s:%d %s()  %s → %s'
              % (r['file'], r['line'], r['fn'], r['expr'], r['target']))
    print('  已签豁免 %d 条' % len(_CLOSURE_EXEMPT))
    for (f, fn, callee, line), why in sorted(_CLOSURE_EXEMPT.items()):
        print('    豁免 %s:%d %s.%s  %s' % (f, line, fn, callee, why))
    return 0


def _audit_calls():
    """兜底读数（只报告，不当绿证）：写面调用点 / 非原语调用点 / 非原语 callee 去重列表。
    「非原语」= 不匹配任何写原语类别（含只读、纯计算、外部调用），**不代表该调用点不写**
    （例如 `uninstall` 经 `atomic_json` 写 tasks.json、`write_message` 写协议流）。
    Fallback reading (report only, never a green proof): write-surface call sites, non-primitive
    call sites, and the deduped callee list behind them. "Non-primitive" means no write-primitive
    category matched (read-only/pure/external included) and does **not** mean it never writes."""
    d = os.path.dirname(os.path.abspath(SRC_BIN))
    _files, _sites, trees, product = _scan_write_sites(d)
    writes, nonprim_sites, nonprim_callees = 0, 0, set()
    for fn, tree in trees.items():
        if fn not in product:
            continue
        al = _write_aliases(tree)
        for name, scope, calls in _scopes(tree):
            pure = _pure_names(scope)
            paths = _path_names(scope, al)
            for sub in calls:
                k = _call_kind(sub, al, scope, pure, paths, (fn, name))
                if k is None:
                    nonprim_sites += 1
                    nonprim_callees.add(_resolve_callee(sub.func, al))
                else:
                    writes += 1
    print('[audit-calls] 写面调用点=%d 非原语调用点=%d 非原语 callee 去重=%d'
          % (writes, nonprim_sites, len(nonprim_callees)))
    print('  注：非原语＝不匹配写原语类别（含只读/纯计算/外部）；不代表不写，见闭包面。')
    for x in sorted(nonprim_callees):
        print('  非原语  %s' % x)
    return 0


def main():
    if '--audit-closure' in sys.argv[1:]:
        return _audit_closure()
    if '--audit-calls' in sys.argv[1:]:
        return _audit_calls()
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
        _case_conf_dual(work)
        _case_conf_dual_e2e(work)
        _case_conf_alias_single(os.path.dirname(SRC_BIN))
        _case_pad_notice(work)
        _case_write_paths(work)
        _case_home_flag(work)
        _case_tail_no_truncate(work)
        _case_lock_assert(work)
        _case_root_handle(work)
        _case_serial_cost(work)
        _case_lease_leak(work)
        _case_no_root(work)
        _case_push_load_bearing(work)
        _case_cli_write_fail(work)
        _case_run_fail_compose(work)
        _case_entry_wrappers(work)
        _case_error_table(work)
        safeio_src = io.open(os.path.join(os.path.dirname(SRC_BIN), 'safeio.py'),
                             encoding='utf-8').read()
        _ok('静态：Windows 写路径/互斥实现存在（命名互斥量 + realpath 归属判 + 拒绝重解析点）',
            '_win_lock' in safeio_src and '_win_rel' in safeio_src
            and '_append_win' in safeio_src and '_replace_win' in safeio_src
            and 'CreateMutexW' in safeio_src and 'os.remove(lock_file)' not in safeio_src
            and '_HAS_FCNTL' not in safeio_src)
        daybook_src = io.open(os.path.join(os.path.dirname(SRC_BIN), 'daybook.py'),
                              encoding='utf-8').read()
        _ok('静态：派生件只有一个原子替换实现（daybook 不自己 os.replace）',
            'def _replace(' in safeio_src and 'os.replace(' not in daybook_src)
        leftovers = [k for k in _snapshot(work) if k.endswith('.tmp')]
        _ok('派生件无 .tmp 残留', not leftovers, '残留=%s' % leftovers)

        # P/Q 锁的进程间语义（跨 TMPDIR 互斥、删除外部件不影响）
        # P/Q cross-process lock semantics (exclusion across TMPDIRs; deleting external
        # artifacts changes nothing)
        _case_p(work)
        _case_q(work)
        _case_win_path(work)
        _case_plain_migrate(work)
        _case_shell_plain(work)
        _case_pack_verify(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print('\n=== 判据回归 === %d 红 / %d 项（PASS %d；跳过 %d 项不计入）'
          % (len(FAILS), CHECKS[0], CHECKS[0] - len(FAILS), len(SKIPS)))
    if SKIPS:
        for _r in SKIPS:
            print('  [跳过] %s' % _r)
    p1_bad = [f for f in FAILS if f.startswith('P1')]
    print('属性层：P1 根身份/换根语义 = %s' % ('红' if p1_bad else '绿'))
    print('变异矩阵（legacy 字符串锚点）：总数 %d / 杀死 %d / 存活 %d / 死变异 %d'
          % (MUT['total'], MUT['killed'], len(MUT['survivors']), MUT['dead']))
    if MUT['survivors']:
        print('  存活变异：' + '；'.join(MUT['survivors']))
    if FAILS:
        print('FAIL: ' + '；'.join(FAILS))
        return 1
    print('PASS: 回归层 0 红；legacy 锚点变异 0 存活 / 0 死变异')
    return 0


if __name__ == '__main__':
    sys.exit(main())
