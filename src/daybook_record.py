#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""保存一条逐字消息/代码原件，并把其路径与摘要登记到 DAYBOOK。
Save one verbatim message/code original and register its path and digest into DAYBOOK.

单根单凭证（P0）：归档、登记、索引全部在**同一把账本根锁、同一个 Root 句柄**内完成，
不再派发任何子进程。写路径禁止 subprocess：派发出去的子进程会按路径重新解析账本根，
根被 rename 后会改道新 inode；改进程内以后 `append_one(..., root=rt)` 与
`daybook.build(conf, rt)` 复用同一句柄（`held(rt)`），换根不可能改道。
Single root, one credential (P0): archiving, registration and indexing all happen inside one
lock on one Root handle, with no subprocess dispatch. A child re-resolves the root by path and
would follow a renamed directory to a new inode; in-process `append_one(..., root=rt)` and
`daybook.build(conf, rt)` reuse the same handle (`held(rt)`), so a rename cannot reroute it.

先判后写（P0）：写任何字节之前先跑一次 `build(..., dry=True, authors=True)`，把
配置错(2)/违例(3)/证据缺失(5)/作者红(4) 一次判掉；非零退出必须零落盘。
Judge before writing (P0): before the first byte, a dry build decides 2/3/4/5; a non-zero
exit lands nothing.
"""
import argparse
import hashlib
import os
import sys
import time

import errors
import daybook
import daybook_append

HERE = os.path.dirname(os.path.abspath(__file__))


def _open_ledger(root=None, conf_path=None):
    """解析 (conf, Root, 是否本次新开)。显式 Root 句柄优先：身份是 inode，不按路径重开。
    Resolve (conf, Root, opened_here). An explicit Root handle wins: identity is the inode
    and it is never reopened by path."""
    from safeio import Root, as_root

    if root is not None:
        rt, opened = as_root(root, 'daybook_record.record')
        # conf 经根句柄读：根被 rename 后读到的仍是旧 inode 里的 conf，不跟同名新目录。
        # Read the conf through the handle: after a rename this still reads the original
        # inode instead of a newly-created same-named directory.
        try:
            raw = rt.read(rt.rel('daybook.conf'))
        except (OSError, RuntimeError) as exc:
            raise errors.ConfigError('账本根内没有可读的 daybook.conf（%s）：%s'
                                     % (rt.label, exc))
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise errors.ConfigError('daybook.conf 不是 UTF-8（%s）：%s' % (rt.label, exc))
        return daybook.parse_conf(text, rt.label,
                                  os.path.join(rt.label, 'daybook.conf')), rt, opened

    from ledger_root import locate, not_found_message, resolve_root
    if conf_path is None:
        _conf_dir, conf_path = locate(HERE)
        if conf_path is None:
            raise errors.ConfigError(not_found_message(_conf_dir))
    conf = daybook.load_conf(conf_path)
    try:
        root_path = resolve_root(os.path.dirname(os.path.abspath(conf_path)), conf)
        rt = Root._from_dir_path(root_path, 'daybook_record.record')
    except (ValueError, RuntimeError) as exc:
        raise errors.ConfigError(str(exc))
    return conf, rt, True


def _precheck(daybook, conf, rt, update_index):
    """写前判据：一次 dry build 把 2/3/4/5 判完；非零 ⇒ 一个字节都不落。
    Pre-write gate: one dry build decides 2/3/4/5; non-zero lands nothing."""
    if not update_index:
        return
    daybook.build(conf, rt, dry=True, authors=True)
    errs = []
    if daybook.CONFIG_ERRORS:
        errs.append(errors.ConfigError('卷配置错误 %d 处' % len(daybook.CONFIG_ERRORS)))
    if daybook.VIOLATIONS:
        errs.append(errors.LedgerViolation('append-only 违例 %d 处'
                                           % len(daybook.VIOLATIONS)))
    if daybook.EVIDENCE_MISSING:
        errs.append(errors.EvidenceMissing('派生证据缺失 %d 处（请先认基线）'
                                           % len(daybook.EVIDENCE_MISSING)))
    if daybook.AUTHOR_RED:
        errs.append(errors.AuthorConvention('作者口径红'))
    top = errors.worst(errs)
    if top is not None:
        raise top


def record(role, title, content, stamp=None, update_index=True, root=None,
           conf_path=None):
    if not content:
        raise ValueError('拒绝记录空内容')
    from safeio import WriteMode, locked

    conf, rt, opened = _open_ledger(root, conf_path)
    try:
        archive_dir = os.path.join(rt, '对话原件')
        stamp = stamp or time.strftime('%Y%m%d_%H%M%S')
        digest = hashlib.sha256(content).hexdigest()
        safe_title = ''.join(
            ch if ch.isalnum() or ch in '-_' else '_' for ch in title
        ).strip('_')[:48] or '未命名'
        name = '%s_%s_%s_%s.txt' % (stamp, role, safe_title, digest[:12])
        archive_path = os.path.join(archive_dir, name)
        relative_path = os.path.relpath(archive_path, os.fspath(rt))

        with locked(rt) as lr:
            # 先判后写：违例/配置错/证据缺失/作者红 在这里就结束，零落盘。
            # Judge before writing: violations/config/evidence/author-red end here, zero writes.
            _precheck(daybook, conf, rt, update_index)

            # 每个原件都是独立的 UTF-8 产物；统一走 LockedRoot.write(REPLACE)。
            # Each original is a separate UTF-8 artifact written through LockedRoot.write(REPLACE).
            lr.mkdirs_path(archive_dir, 'daybook_record.archive_dir')
            lr.write(rt.rel_of(archive_path, 'daybook_record.archive'), content,
                     mode=WriteMode.REPLACE)

            entry_title = '%s %s' % (role, stamp)
            reference = '%s\nSHA256: %s' % (relative_path, digest)
            volume_path = os.path.join(rt, '对话卷.txt')
            try:
                # 进程内登记：复用同一句柄与已持凭证（held(rt)），不派发子进程。
                # In-process registration: same handle, same held token; no child process.
                daybook_append.append_one(volume_path, '对话', entry_title,
                                          '记录器', reference, root=rt)
            except BaseException:
                # 登记失败 ⇒ 撤回原件：非零退出必须零落盘。
                # Registration failed ⇒ withdraw the original: a non-zero exit lands nothing.
                try:
                    lr.unlink(rt.rel_of(archive_path, 'daybook_record.rollback'))
                except Exception as exc:
                    errors.warn('登记失败后撤回原件失败（%s）：%s' % (archive_path, exc))
                raise

            index_output = ''
            if update_index:
                # 进程内索引：同一 Root、同一凭证（build 检测到已持锁即复用 held(rt)）。
                # In-process index: same Root and credential (build reuses held(rt)).
                _per, _total, report = daybook.build(conf, rt)
                index_output = ''.join('  %s: %s\n' % (v, w) for v, w in report)
                errs = []
                if daybook.CONFIG_ERRORS:
                    errs.append(errors.ConfigError('卷配置错误'))
                if daybook.VIOLATIONS:
                    errs.append(errors.LedgerViolation('append-only 违例'))
                if daybook.EVIDENCE_MISSING:
                    errs.append(errors.EvidenceMissing('派生证据缺失'))
                if daybook.AUTHOR_RED:
                    errs.append(errors.AuthorConvention('作者口径红'))
                top = errors.worst(errs)
                if top is not None:
                    # 前置校验已判过同一批故障；走到这里说明写后状态漂移（不应发生）。
                    # The precheck already judged these classes; reaching here means the state
                    # drifted after the write (should not happen).
                    raise top
            return relative_path, digest, index_output
    finally:
        if opened:
            rt.close()


def main():
    """统一出口：run_entry 收口所有 OSError/ValueError/TypeError，不打 traceback。
    Unified boundary: run_entry owns every OSError/ValueError/TypeError — no traceback."""
    return errors.run_entry(_main)


def _main():
    from ledger_root import take_home
    argv, home, herr = take_home(sys.argv[1:])
    if herr:
        raise errors.ConfigError(herr)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True,
                        choices=('用户', '助手', '实验代码'))
    parser.add_argument('--title', default='对话')
    parser.add_argument('--timestamp',
                        help='原始时间，格式 YYYYMMDD_HHMMSS；用于历史补录')
    parser.add_argument('--no-index', action='store_true',
                        help='批量补录时暂不更新索引')
    args = parser.parse_args(argv)
    content = sys.stdin.buffer.read()
    if args.timestamp:
        try:
            time.strptime(args.timestamp, '%Y%m%d_%H%M%S')
        except ValueError:
            raise errors.ConfigError('--timestamp 格式必须是 YYYYMMDD_HHMMSS：%r'
                                     % args.timestamp)
    # --home 是「conf 所在目录」，账本根仍由 conf 的 [index] root 决定（与 daybook.py 同源）。
    # --home is the conf directory; the ledger root still comes from conf's [index] root.
    conf_path = None
    if home:
        from ledger_root import locate, not_found_message
        _conf_dir, conf_path = locate(home)
        if conf_path is None:
            raise errors.ConfigError(not_found_message(_conf_dir))
    try:
        path, digest, index_output = record(
            args.role, args.title, content, args.timestamp, not args.no_index,
            conf_path=conf_path)
    except errors.DaybookError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise errors.RuntimeFailure('记录失败：%s' % exc)
    print('原件已保存：%s' % path)
    print('SHA256：%s' % digest)
    print(index_output, end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
