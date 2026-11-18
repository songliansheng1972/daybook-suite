#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""唯一错误表：错误类别 → 退出码。入口只负责 raise，`run_entry` 统一收口。
The single error table: error kind → exit code. Entries only raise; `run_entry` is the one
boundary that turns an error into a message + exit code.

判据（P6）：任何入口对同一故障类必须给出同一个码；多故障取最高严重度；任何入口都不打 traceback。
Criterion (P6): every entry maps the same fault class to the same code; multiple faults compose by
severity; no entry ever prints a traceback.

归类裁决（唯一，写在注释里，别处不再判断）/ The one classification ruling:
  · 入口期 的根/配置问题 = 2（ConfigError）
  · 运行期 的根被换/写拒绝 = 6（RuntimeFailure）
  · 账本被改写（append-only 违例）= 3（LedgerViolation）
  · 作者口径红（只报不拦之外的结果）= 4（AuthorConvention）
  · 证据缺失/基准缺失 = 5（EvidenceMissing）
  · 卷配置指向目录（conf 把卷写成目录）= 2（ConfigError）：这是配置错，不是运行期
    写拒绝；`daybook.py index/baseline` 与 `daybook_append.py` 必须同码，不许一个 2
    一个 6。运行期才出现的「目标不可写/权限/根被换」仍是 6。
  · `orchestrator.py alarm` 的码轴是**体检结论**：0 干净 / 3 有硬警；只有体检无法执行时
    才退故障码（坏 conf 2 / 运行期 6）。所以「卷配成目录」时 index/append 给 2、alarm 给 3
    不是同故障异码，而是两种码轴：一个是「这次操作失败」，一个是「体检发现硬警」。
  · `daybook_append.py` 的根解析与其余入口**同源**（`_cli_root → Root.open → ledger_root →
    read_conf_value`）：坏 conf 下严格解析先抛 ConfigError，rc=2 且零落盘。它「按显式路径写
    目标卷」不改变这一点——目标卷由参数给，根/conf 仍先过同一套语义。P6 的 CONFIG 坏 conf 格
    对 append 断言的也是 2。
  · `daybook_session_hook.py` 的根固定为脚本目录、`cross_ref.py` 按卷名解析：**conf 不参与
    根解析**，坏 conf 下 rc=0 是设计（P6 坏 conf 格断言 0）。这不代表「坏 conf 能写账本」——
    它们的写面不经过 conf 定位。
  · `daybook_multidx` 对已改写卷 rc=0 重建派生视图：**明示豁免**。`append-only` 是账本卷级
    不变量，只覆盖账本卷，不覆盖派生视图；别把这句套到 multidx 上。
  · conf 的归一与解析**只有一套**（`conf_norm`，完整包 / mcp / orch 同带一份）：节名键名
    统一 `strip + lower + 中文别名`（`[volumes]` 的键是卷名，保留大小写），`[索引]`／
    `[Index]`／`[ index ]`／`[INDEX]` 都是 `index`；归一后仍认不出的节名 ⇒ 2
    （「配置写错了」不得降级成「没配置」）。
  · `orchestrator.py alarm` 体检**只读开卷**：缺编排卷不建卷，报「账本未检查」（软警，rc 仍 0）；
    账本 append-only 违例仍走硬警 3。缺卷不是「干净」，也不会把缺卷读成空名册去判幽灵。
  · `mcp_server.py` 启动自检失败直接退出：volumes 为空 / 卷指向目录 ⇒ 2；登记卷缺失 /
    卷存在但不可读 ⇒ 5。绝不「服务起来了但每个工具都报错」。
  · A volume path that is a directory is a CONFIG error (2): both `daybook.py` and
    `daybook_append.py` must return 2 for the same conf. Only runtime refusals
    (unwritable target/permission/root swapped) stay 6.
  · `orchestrator.py alarm` has a **health-verdict axis**: 0 clean / 3 hard alarm; fault codes
    (bad conf 2 / runtime 6) only when the check cannot run. A volume-as-directory giving
    index/append 2 and alarm 3 is two axes, not one fault with two codes.
  · `daybook_append.py` resolves its root through the **same** `ledger_root` conf semantics as
    every other entry: a wholly unparsable conf raises ConfigError (2) before any write. Writing
    an explicit target volume does not change that; P6 asserts 2 for append under a bad conf.
  · `daybook_session_hook.py` (root fixed to the script directory) and `cross_ref.py` (by volume
    name) do not use conf for root resolution: rc=0 under a bad conf is by design (P6 asserts 0).
    Their write surface never depends on conf location. `daybook_multidx` rebuilding derived
    views (rc=0) is an explicit exemption: append-only covers ledger volumes, not derived views.
    Conf normalisation and parsing exist once (`conf_norm`, shipped by all three packages):
    names are `strip + lower + Chinese alias`; a section still unknown after normalisation is a
    config error (2). `orchestrator.py alarm` opens volumes read-only and reports "ledger not
    checked" instead of creating a missing one. `mcp_server.py` refuses to start sick: empty
    volumes / a volume pointing at a directory ⇒ 2; a missing or unreadable volume ⇒ 5.
"""
import sys


def warn(msg):
    """best-effort 失败必须可见：统一告警出口（stderr，不改退出码）。
    A best-effort failure must stay visible: the one warning exit (stderr, never changes rc)."""
    sys.stderr.write('warning: %s\n' % msg)


CONFIG = 2
VIOLATION = 3
AUTHOR = 4
EVIDENCE = 5
RUNTIME = 6

# 唯一映射表 / the only mapping table
TABLE = {
    CONFIG: 2,
    VIOLATION: 3,
    AUTHOR: 4,
    EVIDENCE: 5,
    RUNTIME: 6,
}

# 多故障合成：数字大的先赢；证据缺失最轻
# Composition: higher severity wins; missing evidence is the lightest.
_SEVERITY = {
    VIOLATION: 5,
    AUTHOR: 4,
    RUNTIME: 3,
    CONFIG: 2,
    EVIDENCE: 1,
}


class DaybookError(Exception):
    """所有入口错误的基类；`kind` 决定退出码，子类只固定 kind。
    Base class of every entry error; `kind` decides the exit code and subclasses only fix it."""
    kind = RUNTIME


class ConfigError(DaybookError):
    kind = CONFIG


class LedgerViolation(DaybookError):
    kind = VIOLATION


class AuthorConvention(DaybookError):
    kind = AUTHOR


class EvidenceMissing(DaybookError):
    kind = EVIDENCE


class RuntimeFailure(DaybookError):
    kind = RUNTIME


class WriteRefused(RuntimeFailure):
    """写原语拒绝（根不一致/越界/替换/无锁）——运行期，不是配置错。
    A write-primitive refusal (root mismatch/escape/replaced/no lock) — runtime, not config."""


def exit_code(err):
    """错误 → 退出码（表里没有就当运行失败，绝不返回 0）。
    Error → exit code (unknown kinds are runtime failures; never 0)."""
    code = getattr(err, 'kind', RUNTIME)
    return TABLE.get(code, RUNTIME)


def worst(errs):
    """多故障合成：按严重度取最高；空列表返回 None。
    Compose multiple faults by severity; returns None for an empty list."""
    errs = [e for e in errs if e is not None]
    if not errs:
        return None
    return max(errs, key=lambda e: _SEVERITY.get(getattr(e, 'kind', RUNTIME), 0))


def run_entry(fn, collect=None):
    """唯一出口：跑入口函数；`DaybookError` 合成后打印一条文案并返回码。
    The single boundary: run the entry; compose `DaybookError`s, print one message, return code.
    `collect` 用于入口在运行中收集到的其它错误（如 build 的全局清单）。
    `collect` supplies other errors gathered during the run (e.g. build's global lists).
    裸 `RuntimeError`（safeio 的拒绝文案）在这里归为 `RuntimeFailure`（6），不打 traceback。
    裸 `OSError`（目标不可读写等入口期之外的系统错）同样归 6：入口绝不把栈甩给用户。
    裸 `ValueError` / `TypeError`（参数解析漏网：int()/索引/类型错）也归 6，绝不让 traceback 出栈；
    但参数解析本身应主动抛 `ConfigError`（2），这里只是最后一道兜底。
    A bare `RuntimeError` (safeio's refusal text) becomes `RuntimeFailure` (6): never a traceback.
    A bare `OSError` (an OS-level failure outside entry-time config checks) also becomes 6.
    A bare `ValueError` / `TypeError` (a parse slip: int()/subscript/type) is likewise 6 so no stack
    escapes; argument parsing should still raise `ConfigError` (2) deliberately — this is the net."""
    try:
        return fn()
    except DaybookError as exc:
        errs = [exc] + (list(collect() or []) if collect else [])
        top = worst(errs)
        sys.stderr.write('★ 运行失败（rc=%d）：%s\n' % (exit_code(top), top))
        return exit_code(top)
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        errs = ([RuntimeFailure(str(exc) if isinstance(exc, RuntimeError)
                                else '%s: %s' % (type(exc).__name__, exc))]
                + (list(collect() or []) if collect else []))
        top = worst(errs)
        sys.stderr.write('★ 运行失败（rc=%d）：%s\n' % (exit_code(top), top))
        return exit_code(top)
