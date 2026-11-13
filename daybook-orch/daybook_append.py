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
  python3 daybook_append.py <卷文件> <类> <标题> <作者> "正文" --name=显示名
                                                              # 作者位＝注册表 id·显示名只作附注
                                                              # author slot = registry id · display name is annotation only
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
★ 唯一落盘入口：CLI 与 MCP 都走本件 append_one，不许各自拼行。
★ Single landing entry: both the CLI and MCP go through append_one; no one formats lines elsewhere.
★ 作者单一来源：注册表 id（ag-<16 hex>）；显示名只写 [名=…] 附注，不顶 id 位。
★ Single author source: the registry id (ag-<16 hex>); display names are only a [name=…] annotation.
★ 同卷口径机检：check_author_consistency() 抓「id / 显示名 / 未标」混用。
★ Per-volume convention check: check_author_consistency() flags id/display/unmarked mixtures.
"""
import io, os, re, sys, time

FALLBACK_LIMIT = 4096          # POSIX PIPE_BUF 之保守值（探测失败兜底）· conservative POSIX PIPE_BUF value (fallback on probe failure)
PROMPT_TEMPLATE = '★ 本条超 {limit} 字节：POSIX 只保证 ≤ PIPE_BUF 之单次 write 原子。请拆条或改用加锁写入。\n'

# ── 作者口径（单一来源＝注册表 id）────────────────────────────
# ── Author convention (single source = registry id). ──
AUTHOR_ID_RE = re.compile(r'^ag-[0-9a-f]{16}$')          # 注册表 id 形态 · registry-id shape
AUTHOR_PLACEHOLDERS = frozenset(('', '未标', '_', '（未标）'))  # 未标占位 · unmarked placeholders
ENTRY_NO_RE = re.compile(r'^#\d+$')                      # 可选的 [#N] 条号前缀 · optional [#N] entry number
REG_BRACKET_RE = re.compile(r'\[([^\]]*)\]')


def _head_tokens(line):
    """取行首连续的 [..] 段（遇到正文即停）。返回 token 列表。
    Take the leading [..] tokens of a line (stop at the body). Returns the token list."""
    tokens, rest = [], line
    while rest.startswith('['):
        end = rest.find(']')
        if end < 0:
            break
        tokens.append(rest[1:end])
        rest = rest[end + 1:].lstrip(' ')
    return tokens


def classify_author(author):
    """作者口径归类：id / 显示名 / 未标。
    Classify an author value: id / display / unmarked."""
    a = (author or '').strip()
    if a in AUTHOR_PLACEHOLDERS:
        return '未标'
    if AUTHOR_ID_RE.match(a):
        return 'id'
    return '显示名'


def check_author_consistency(path):
    """机检：同一卷内 author 字段必须同一口径，混用即报红。
    Machine check: one author convention per volume; mixing conventions is red.
    返回 (ok, detail)；detail = {kinds, samples, summary}。
    Returns (ok, detail); detail = {kinds, samples, summary}.
    只认四段条目头（[时间][类][标题][作者]）；旧三段条目无作者位，不参与判定。
    Only 4-part entry heads ([time][tag][title][author]) count; legacy 3-part heads have no author slot."""
    entries = []
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            for ln, line in enumerate(f, 1):
                tokens = _head_tokens(line)
                if tokens and ENTRY_NO_RE.match(tokens[0]):
                    tokens = tokens[1:]
                if len(tokens) < 4:
                    continue          # 旧三段条目无作者位 · legacy 3-part head has no author slot
                author = tokens[3]
                entries.append((ln, author, classify_author(author)))
    except OSError as exc:
        return False, {'kinds': ['读失败'], 'samples': [(0, str(exc), '读失败')],
                       'summary': '读失败'}
    kinds = sorted({c for _ln, _a, c in entries})
    if len(kinds) <= 1:
        return True, {'kinds': kinds, 'samples': [],
                      'summary': '%s × %d 条' % (kinds[0] if kinds else '无条目', len(entries))}
    return False, {'kinds': kinds, 'samples': entries[:200],
                   'summary': '%s 混用' % '＋'.join(kinds)}


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


def append_one(path, kind, title, msg, author='未标', to=None,
               msg_id=None, re_ref=None, sig=None, now=None, display_name=None):
    """原子追加一条（**唯一落盘入口**：CLI 与 MCP 共用）。to 为收件人列表或字符串·写入 [致=...] 段·不填即广播。
    Atomically append one entry (**the single landing entry**: shared by the CLI and the MCP). `to` is a recipient list or string · writes a [致=...] segment · broadcasts when omitted.
    格式：[时间] [类] [标题] [作者] [名=…] [id=…] [re=…] [sig=…] [致=汤姆,老宋] 正文
    Format: the tokens above plus the body text.

    display_name：显示名附注 [名=…]；作者位永远保持注册表 id，不被显示名顶替。
    display_name: a display-name annotation [名=…]; the author slot always keeps the registry
    id and is never replaced by a display name.

    msg_id / re_ref / sig：消息总线字段（显式条号、显式回应引用、条目签名）。
    msg_id / re_ref / sig: message-bus fields (explicit entry id, explicit reply reference, entry signature).
    now：由调用方给出时间戳（签名须覆盖落盘时间，避免两次取时钟不一致）。
    now: timestamp supplied by the caller (the signature must cover the written time,
         avoiding a mismatch between two clock reads).

    多写者并发安全：O_APPEND + 单次 write ≤ PIPE_BUF ⇒ POSIX 原子。
    Multi-writer safe: O_APPEND + single write ≤ PIPE_BUF ⇒ POSIX atomic.
    作者 ID 红线：必填·可审可验可追。
    Author ID iron rule: required · auditable, verifiable and traceable.
    收件人寻址（F1·跨 AI 消息平台）：to 字段·逗号分隔多收件人。
    Recipient addressing (F1 · cross-AI messaging platform): `to` field · comma-separated multiple recipients.
    """
    limit = get_pipe_buf(path)
    now = now or time.strftime('%Y-%m-%d %H:%M:%S')  # W-75 修⑥：分钟⇒秒（心跳 alive 判定需秒级）· W-75 fix ⑥: minutes ⇒ seconds (heartbeat alive check needs second resolution)
    head = '[%s] [%s] [%s] [%s] ' % (now, kind, title, author)
    if display_name:
        head += '[名=%s] ' % str(display_name).replace(']', '').replace('\n', ' ').strip()
    if msg_id:
        head += '[id=%s] ' % msg_id
    if re_ref:
        head += '[re=%s] ' % re_ref
    if sig:
        head += '[sig=%s] ' % sig
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


def _read_registry(path):
    """读注册卷 → (id 集合, 名→id 映射)。缺/坏文件返回空集合。
    Read the registry volume → (set of ids, name→id map). Missing/broken returns empty."""
    by_id, by_name = set(), {}
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = REG_BRACKET_RE.findall(line)
                if len(parts) < 3:
                    continue
                if parts[1] == '注册':
                    by_id.add(parts[2])
                    if len(parts) > 3 and parts[3]:
                        by_name[parts[3]] = parts[2]
                elif parts[1] == '吊销':
                    by_id.discard(parts[2])
    except OSError:
        return set(), {}
    # 已吊销的名字不再解析 · revoked names no longer resolve
    for name, aid in list(by_name.items()):
        if aid not in by_id:
            del by_name[name]
    return by_id, by_name


def _registry_for(vol_path):
    """找与卷同目录的注册卷.txt（再退当前目录）。无则 None＝独立模式。
    Find 注册卷.txt next to the volume (then the cwd). None = standalone mode."""
    for cand in (os.path.join(os.path.dirname(os.path.abspath(vol_path)), '注册卷.txt'),
                 os.path.join(os.getcwd(), '注册卷.txt')):
        if os.path.isfile(cand):
            return cand
    return None


def resolve_cli_author(author, vol_path):
    """CLI 作者解析（注册表在则强制 id 源头）。返回 (作者位, 显示名附注或 None)。
    CLI author resolution (id is mandatory when a registry exists). Returns (author slot, display name or None).
    · 已是注册表 id ⇒ 原样，无附注
    · 是已注册显示名 ⇒ 换成 id，显示名作附注
    · 注册表存在但既非 id 也未注册 ⇒ 抛 ValueError（不许显示名顶 id 位）
    · 无注册表 ⇒ 独立模式，原样落盘（兼容单机无注册用法）
    """
    a = (author or '').strip()
    reg = _registry_for(vol_path)
    if reg is None:
        return a, None
    by_id, by_name = _read_registry(reg)
    if a in by_id:
        return a, None
    if a in by_name:
        return by_name[a], a
    raise ValueError('作者位必须是注册表 id（ag-…）：“%s” 既非 id 也未在 %s 注册；'
                     '显示名请用 --name= 附注' % (a, reg))


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ('--check', '-c'):
        path = sys.argv[2] if len(sys.argv) >= 3 else os.curdir
        return check_pipe_buf(path)
    if len(sys.argv) < 3:
        print(__doc__); return 1
    path = sys.argv[1]
    # --name=显示名：显示名只作附注，不占作者位 · display name is annotation only, never the author slot
    name = None
    argv = []
    for a in sys.argv[2:]:
        if a.startswith('--name='):
            name = a.split('=', 1)[1].strip() or None
        else:
            argv.append(a)
    # 支持三种用法：· Three forms are supported:
    #   卷 类 标题 作者 "正文"   # 5 参标准（作者必填）· 5-arg standard (author required)
    #   卷 类 标题 "正文"        # 4 参（作者默认"未标"）· 4-arg (author defaults to "未标")
    #   卷 "正文"                # 2 参旧格式（类=聊，标题=作者，作者=未标）· 2-arg legacy format (kind=聊, title=author, author=未标)
    if len(argv) >= 4:
        kind, title, author, msg = argv[0], argv[1], argv[2], argv[3]
    elif len(argv) == 3:
        kind, title, author, msg = argv[0], argv[1], '未标', argv[2]
    elif len(argv) == 2:
        # 旧格式：第二参为标题，类默认"聊"，作者"未标" · legacy format: second arg is the title, kind defaults to "聊", author "未标"
        kind, title, author, msg = '聊', argv[0], '未标', argv[1]
    else:
        # 仅 path + 类：从 stdin 读正文 · path + kind only: read the body from stdin
        kind, title, author, msg = argv[0], '', '未标', sys.stdin.read()
    if not msg.strip():
        sys.stderr.write('空消息，未写。\n'); return 1
    try:
        author_slot, auto_name = resolve_cli_author(author, path)
    except ValueError as exc:
        sys.stderr.write('%s\n' % exc)
        return 2
    return append_one(path, kind, title, msg, author_slot,
                      display_name=name or auto_name)


if __name__ == '__main__':
    sys.exit(main())
