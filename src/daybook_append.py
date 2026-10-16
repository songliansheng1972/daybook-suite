#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""Daybook · 并发写入器（多写者安全）
Daybook · concurrent writer (multi-writer safe)
原理：O_APPEND + 单次 write ≤ PIPE_BUF ⇒ POSIX 保证原子 ⇒ 无需锁。
Principle: O_APPEND + single write ≤ PIPE_BUF ⇒ POSIX guarantees atomicity ⇒ no lock needed.
用法：
Usage:
  python3 daybook_append.py <卷文件> <类> <标题> <作者> "正文"   # 标准条目（作者必填）· standard entry (author required)
  python3 daybook_append.py <卷文件> <类> <标题> "正文"           # 兼容（作者默认"未标"）· compatible (author defaults to "未标")
  echo "正文" | python3 daybook_append.py <卷文件> [<类> <标题> <作者>]
所有写者对同一卷并发调用都安全（每条必须 ≤ PIPE_BUF）。
Concurrent calls by all writers to the same volume are safe (each entry must be ≤ PIPE_BUF).
PIPE_BUF 由 os.pathconf(path, 'PC_PIPE_BUF') 动态探测：
PIPE_BUF is probed dynamically via os.pathconf(path, 'PC_PIPE_BUF'):
  Linux 通常 4096，macOS 通常 512。探测失败退保守值 4096。
  Linux is typically 4096, macOS typically 512. On probe failure fall back to the conservative value 4096.
作者 ID 红线：每条必带作者，可审可验可追。
Author ID iron rule: every entry must carry an author, auditable, verifiable and traceable.
"""
import os, sys, time, io

FALLBACK_LIMIT = 4096          # POSIX PIPE_BUF 之保守值（探测失败兜底）· conservative POSIX PIPE_BUF value (fallback on probe failure)
PROMPT_TEMPLATE = '★ 本条超 {limit} 字节：POSIX 只保证 ≤ PIPE_BUF 之单次 write 原子。请拆条或改用加锁写入。\n'


def get_pipe_buf(path):
    """探测目标文件系统的 PIPE_BUF（POSIX 原子写阈值）。
    Probe the target filesystem's PIPE_BUF (the POSIX atomic-write threshold).
    文件存在则探文件本身；不存在则探其所在目录（同分区即同阈值）。
    If the file exists, probe the file itself; otherwise probe its directory (same partition ⇒ same threshold).
    探测失败（不支持 PC_PIPE_BUF 或路径不存在）退保守值 4096。
    On probe failure (PC_PIPE_BUF unsupported or path missing), fall back to the conservative value 4096."""
    try:
        target = path if os.path.exists(path) else (os.path.dirname(path) or os.curdir)
        return os.pathconf(target, 'PC_PIPE_BUF')
    except (OSError, ValueError):
        return FALLBACK_LIMIT


def append_one(path, kind, title, msg, author='未标', to=None):
    """原子追加一条。to 为收件人列表或字符串·写入 [致=...] 段·不填即广播。
    Atomically append one entry. `to` is a recipient list or string · writes a [致=...] segment · broadcasts when omitted.
    格式：[时间] [类] [标题] [作者] [致=汤姆,老宋] 正文
    Format: the tokens above plus the body text.

    多写者并发安全：O_APPEND + 单次 write ≤ PIPE_BUF ⇒ POSIX 原子。
    Multi-writer safe: O_APPEND + single write ≤ PIPE_BUF ⇒ POSIX atomic.
    作者 ID 红线：必填·可审可验可追。
    Author ID iron rule: required · auditable, verifiable and traceable.
    收件人寻址（F1·跨 AI 消息平台）：to 字段·逗号分隔多收件人。
    Recipient addressing (F1 · cross-AI messaging platform): `to` field · comma-separated multiple recipients.
    """
    limit = get_pipe_buf(path)
    now = time.strftime('%Y-%m-%d %H:%M:%S')  # W-75 修⑥：分钟⇒秒（心跳 alive 判定需秒级）· W-75 fix ⑥: minutes ⇒ seconds (heartbeat alive check needs second resolution)
    head = '[%s] [%s] [%s] [%s] ' % (now, kind, title, author)
    if to:
        if isinstance(to, (list, tuple)):
            to_str = ','.join(to)
        else:
            to_str = str(to)
        head += '[致=%s] ' % to_str
    tail = '\n\n'
    body = msg.rstrip('\n')
    rec = head + body + tail
    b = rec.encode('utf-8')
    if len(b) > limit:
        # W-75 修③：超 PIPE_BUF 不再拒写，走 safeio.locked 加锁路径 · W-75 fix ③: over PIPE_BUF is no longer rejected; go through the safeio.locked path
        sys.stderr.write('★ 超限 %d 字节·走加锁写入路径\n' % len(b))
        from safeio import locked as _safe_locked
        with _safe_locked(path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, b)
            finally:
                os.close(fd)
        return 0
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, b)           # ★ 单次 write，O_APPEND ⇒ 原子 · ★ single write, O_APPEND ⇒ atomic
    finally:
        os.close(fd)
    return 0


def check_pipe_buf(path):
    """打印目标路径所在文件系统的 PIPE_BUF，供部署前置检查。
    Print the PIPE_BUF of the filesystem holding the target path, for pre-deployment checks."""
    limit = get_pipe_buf(path)
    print('路径: %s' % path)
    print('PIPE_BUF: %d 字节' % limit)
    if sys.platform == 'darwin':
        print('系统: macOS（典型 512，APFS 实测此值）')
    elif sys.platform.startswith('linux'):
        print('系统: Linux（典型 4096）')
    else:
        print('系统: %s' % sys.platform)
    print('提示: 跨平台安全阈值建议 ≤ %d；超此值请拆条或加锁写入。' % limit)
    return 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ('--check', '-c'):
        path = sys.argv[2] if len(sys.argv) >= 3 else os.curdir
        return check_pipe_buf(path)
    if len(sys.argv) < 3:
        print(__doc__); return 1
    path = sys.argv[1]
    # 支持三种用法：· Three forms are supported:
    #   卷 类 标题 作者 "正文"   # 5 参标准（作者必填）· 5-arg standard (author required)
    #   卷 类 标题 "正文"        # 4 参（作者默认"未标"）· 4-arg (author defaults to "未标")
    #   卷 "正文"                # 2 参旧格式（类=聊，标题=作者，作者=未标）· 2-arg legacy format (kind=聊, title=author, author=未标)
    if len(sys.argv) >= 6:
        kind, title, author, msg = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    elif len(sys.argv) == 5:
        kind, title, author, msg = sys.argv[2], sys.argv[3], '未标', sys.argv[4]
    elif len(sys.argv) == 4:
        # 旧格式：第二参为标题，类默认"聊"，作者"未标" · legacy format: second arg is the title, kind defaults to "聊", author "未标"
        kind, title, author, msg = '聊', sys.argv[2], '未标', sys.argv[3]
    else:
        # 仅 path + 类：从 stdin 读正文 · path + kind only: read the body from stdin
        kind, title, author, msg = sys.argv[2], '', '未标', sys.stdin.read()
    if not msg.strip():
        sys.stderr.write('空消息，未写。\n'); return 1
    return append_one(path, kind, title, msg, author)


if __name__ == '__main__':
    sys.exit(main())
