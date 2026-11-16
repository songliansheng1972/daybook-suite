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
"""
import sys

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
    A bare `RuntimeError` (safeio's refusal text) becomes `RuntimeFailure` (6): never a traceback.
    A bare `OSError` (an OS-level failure outside entry-time config checks) also becomes 6:
    an entry never dumps a stack at the user."""
    try:
        return fn()
    except DaybookError as exc:
        errs = [exc] + (list(collect() or []) if collect else [])
        top = worst(errs)
        sys.stderr.write('★ 运行失败（rc=%d）：%s\n' % (exit_code(top), top))
        return exit_code(top)
    except (RuntimeError, OSError) as exc:
        errs = ([RuntimeFailure('%s: %s' % (type(exc).__name__, exc)
                                if not isinstance(exc, RuntimeError) else str(exc))]
                + (list(collect() or []) if collect else []))
        top = worst(errs)
        sys.stderr.write('★ 运行失败（rc=%d）：%s\n' % (exit_code(top), top))
        return exit_code(top)
