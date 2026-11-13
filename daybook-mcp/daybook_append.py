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
  python3 daybook_append.py <卷文件> <类> <标题> <作者> "正文"   # 标准条目（作者必填·无默认占位）
                                                              # standard entry (author mandatory, no placeholder default)
  python3 daybook_append.py <卷文件> <类> <标题> <作者>          # 正文从 stdin 读 · body from stdin
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
★ 作者位＝显示名（人读）；注册表 id 降为 [id=ag-…] 附注。作者位出现机器 id 即判红。
★ The author slot holds the display name (human-readable); the registry id is demoted to an
  [id=ag-…] annotation. A machine id in the author slot is red.
★ 未注册的名字允许写入：stderr 警告 + 附注 [未注册]（人记账不该先登记才能记事）。
★ Unregistered names are allowed: a stderr warning plus an [未注册] annotation.
★ 同卷口径机检：check_author_consistency() 只按 head_regex 锚定条目头，抓机器 id 与混用。
★ Per-volume convention check: check_author_consistency() anchors entry heads by head_regex only,
  and flags machine ids / mixed conventions.
"""
import io, os, re, sys, time

FALLBACK_LIMIT = 4096          # POSIX PIPE_BUF 之保守值（探测失败兜底）· conservative POSIX PIPE_BUF value (fallback on probe failure)
PROMPT_TEMPLATE = '★ 本条超 {limit} 字节：POSIX 只保证 ≤ PIPE_BUF 之单次 write 原子。请拆条或改用加锁写入。\n'

# ── 作者口径（作者位＝显示名·id 只作附注）──────────────────────
# ── Author convention (author slot = display name · id is annotation only). ──
AUTHOR_ID_RE = re.compile(r'^ag-[0-9a-f]{16}$')          # 注册表 id 形态 · registry-id shape
AUTHOR_PLACEHOLDERS = frozenset(('', '未标', '_', '（未标）'))  # 未标占位 · unmarked placeholders
ENTRY_NO_RE = re.compile(r'^#\d+$')                      # 可选的 [#N] 条号前缀 · optional [#N] entry number
REG_BRACKET_RE = re.compile(r'\[([^\]]*)\]')
# 条头之后的结构/附注段：作者位到此为止（防「旧三段条目正文里的 [致=…] 被当作者」）
# Structural/annotation tokens after the head: the author slot ends here, so a body-level
# [致=…] in a legacy 3-part entry can never be mistaken for an author.
STRUCT_PREFIXES = ('致=', 'id=', 're=', 'sig=', 'thread=', '名=')
DEFAULT_HEAD_RE = re.compile(r'^(?:\[#\d+\][ ]*)?\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)\]')


def _head_tokens(line):
    """取行首连续的 [..] 段（遇到结构/附注段或正文即停）。返回 token 列表。
    Take the leading [..] tokens (stop at a structural/annotation token or the body)."""
    tokens, rest = [], line
    while rest.startswith('['):
        end = rest.find(']')
        if end < 0:
            break
        tok = rest[1:end]
        if tok.startswith(STRUCT_PREFIXES):
            break
        tokens.append(tok)
        rest = rest[end + 1:].lstrip(' ')
    return tokens


def classify_author(author):
    """作者口径归类：显示名 / 机器id / 未标。
    Classify an author value: display / machine-id / unmarked."""
    a = (author or '').strip()
    if a in AUTHOR_PLACEHOLDERS:
        return '未标'
    if AUTHOR_ID_RE.match(a):
        return '机器id'
    return '显示名'


def check_author_consistency(path, head_regex=None):
    """机检：作者位必须是显示名；出现机器 id、或同卷混两种形态即报红。
    Machine check: the author slot must hold a display name; a machine id, or two
    conventions mixed in one volume, is red.
    返回 (ok, detail)；detail = {kinds, samples, summary}。
    Returns (ok, detail); detail = {kinds, samples, summary}.
    条目头只由 head_regex 锚定——正文里的 [注][甲][乙][老宋] 不会被当成条目。
    Entry heads are anchored by head_regex only, so body lines like [注][甲][乙][老宋]
    are never mistaken for entries.
    旧三段条目无作者位，不参与判定。
    Legacy 3-part heads have no author slot and take no part in the verdict."""
    head_re = re.compile(head_regex) if head_regex else DEFAULT_HEAD_RE
    entries = []
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            for ln, line in enumerate(f, 1):
                line = line.rstrip('\n')
                if not head_re.match(line):
                    continue          # 非条目头（含正文行）· not an entry head (body lines included)
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
    if '机器id' in kinds:
        return False, {'kinds': kinds, 'samples': entries[:200],
                       'summary': '作者位出现机器 id（应为显示名）'}
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
               msg_id=None, re_ref=None, sig=None, now=None, author_id=None,
               unregistered=False):
    """原子追加一条（**唯一落盘入口**：CLI 与 MCP 共用）。to 为收件人列表或字符串·写入 [致=...] 段·不填即广播。
    Atomically append one entry (**the single landing entry**: shared by the CLI and the MCP). `to` is a recipient list or string · writes a [致=...] segment · broadcasts when omitted.
    格式：[时间] [类] [标题] [作者显示名] [id=ag-…] [未注册] [id=<条号>] [re=…] [sig=…] [致=汤姆,老宋] 正文
    Format: the tokens above plus the body text.

    author：作者位写**显示名**（人读）。
    author: the author slot holds the **display name** (human-readable).
    author_id：注册表 id 只作 [id=ag-…] 附注，不占作者位。
    author_id: the registry id is only an [id=ag-…] annotation, never the author slot.
    unregistered：未注册作者仍写入，附注 [未注册]（并已由调用方在 stderr 警告）。
    unregistered: unregistered authors are still written, annotated [未注册]
                  (the caller has already warned on stderr).

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
    if author_id:
        head += '[id=%s] ' % author_id
    if unregistered:
        head += '[未注册] '
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
    """CLI 作者解析：作者位写显示名，注册表 id 只作附注。返回 (作者位, id 附注或 None, 是否未注册)。
    CLI author resolution: the author slot holds the display name; the registry id is annotation
    only. Returns (author slot, id annotation or None, unregistered flag).
    · 已注册显示名 ⇒ 原样作作者位，id 作附注
    · 注册表 id     ⇒ 反查显示名作作者位，id 作附注
    · 未注册的名字   ⇒ 仍写入，打 stderr 警告并标 [未注册]（人记账不该先登记才能记事）
    · 未注册的机器 id⇒ 拒写（无法反查显示名，且作者位不许出现 id）
    · 无注册表      ⇒ 独立模式，名字原样落盘
    """
    a = (author or '').strip()
    if a in AUTHOR_PLACEHOLDERS:
        return a or '未标', None, False
    # 机器 id 一律拒写（独立模式也一样）：作者位只许显示名
    # Machine ids are refused even in standalone mode: the author slot is a display name only
    if AUTHOR_ID_RE.match(a):
        reg = _registry_for(vol_path)
        if reg is not None:
            name = next((n for n, i in _read_registry(reg)[1].items() if i == a), None)
            if name:
                return name, a, False
        raise ValueError('作者位写显示名；不接受机器 id（%s，未注册或无注册表）' % a)
    reg = _registry_for(vol_path)
    if reg is None:
        return a, None, False
    by_id, by_name = _read_registry(reg)
    if a in by_name:
        return a, by_name[a], False
    sys.stderr.write('★ 警告：作者「%s」未在 %s 注册·仍写入并标 [未注册]\n' % (a, reg))
    return a, None, True


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ('--check', '-c'):
        path = sys.argv[2] if len(sys.argv) >= 3 else os.curdir
        return check_pipe_buf(path)
    if len(sys.argv) < 3:
        print(__doc__); return 1
    path = sys.argv[1]
    # --name=显示名：显式指定作者位的显示名（作者位本就写显示名，此参作覆盖）
    # 作者必填、无后门：· The author is mandatory and there is no back door:
    #   卷 类 标题 作者 "正文"
    # 三参/四参旧形态（作者默认「未标」）一律拒写：不给绕过作者口径的入口
    # Legacy 3/4-arg forms (author defaulting to 未标) are refused: no path around the author check
    argv = sys.argv[2:]
    bad = [a for a in argv if a.startswith('--')]
    if bad:
        sys.stderr.write('不支持的选项：%s（作者位只接受显示名，不再有 --name= 后门）\n' % ' '.join(bad))
        return 2
    if len(argv) < 4:
        sys.stderr.write('用法：daybook_append.py <卷文件> <类> <标题> <作者> "正文"\n'
                         '（作者必填；没有默认「未标」，也没有 --name= 覆盖入口）\n')
        return 2
    kind, title, author, msg = argv[0], argv[1], argv[2], argv[3]
    if (author or '').strip() in AUTHOR_PLACEHOLDERS:
        sys.stderr.write('作者必填：不许用空值/「未标」占位绕过作者口径\n')
        return 2
    if not msg.strip():
        sys.stderr.write('空消息，未写。\n'); return 1
    try:
        author_slot, author_id, unregistered = resolve_cli_author(author, path)
    except ValueError as exc:
        sys.stderr.write('%s\n' % exc)
        return 2
    return append_one(path, kind, title, msg, author_slot,
                      author_id=author_id, unregistered=unregistered)


if __name__ == '__main__':
    sys.exit(main())
