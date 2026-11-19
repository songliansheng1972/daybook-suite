#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""MCP Tools（W-DB-023-G2·第 3 项·修复版 r2）
MCP Tools (W-DB-023-G2 · item 3 · fixed version r2)
================================================
对照审核报告 P0/P1/P2 修复：
Fixes for P0/P1/P2 from the review report:
- P0-1 daybook_list 不再 subprocess 调用不存在的 `daybook.py list`·直接读 conf[卷]
- P0-1 daybook_list no longer subprocess-calls the nonexistent `daybook.py list` · reads conf[volumes] directly
- P0-2 daybook_query 不再传 `pattern`·按 daybook.py 真实 key=value 语法构造 args
- P0-2 daybook_query no longer passes `pattern` · builds args using daybook.py's real key=value syntax
- P1-1 写工具（append/index）接受可选 agent_id+signature·调 G3 agent_registry 验签
- P1-1 write tools (append/index) accept optional agent_id+signature · call G3 agent_registry to verify the signature
- P1-2 tools/call 全记入卷（审计卷.txt append-only）
- P1-2 all tools/call are recorded to a volume (审计卷.txt, append-only)
- P1-3 DAYBOOK_ROOT 隔离彻底·直接 import 不 subprocess·volume 路径校验防 ../
- P1-3 DAYBOOK_ROOT isolation is thorough · direct import, no subprocess · volume path validation guards against ../
- P1-4 daybook_index 描述纠正为"重建全部卷索引"·不再误导单卷
- P1-4 the daybook_index description is corrected to "rebuild the index of all volumes" · no longer misleading about a single volume
- P2-1 tools/call 失败返 result{isError:true, content:[{type:text,text:errMsg}]}
- P2-1 a failed tools/call returns result{isError:true, content:[{type:text,text:errMsg}]}
        而非 -32603 internal error·让模型看见错误
        instead of -32603 internal error · so the model can see the error
- 零依赖：仅 Python 3 标准库
- Zero dependencies: Python 3 standard library only
"""
import os, sys, time, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import daybook as _db
import daybook_append as _dba
import mcp_resources as _mr
import mcp_transport as _tr
from conf_norm import canon_field
from agent_registry import Registry as _AgentRegistry

AUDIT_VOL_NAME = 'MCP审计卷.txt'
SIG_SIDECAR = 'MCP签名边车.jsonl'   # 签名边车（append-only JSONL）/ signature sidecar (append-only JSONL)
# 4.0.7：璇玑只留存储面；调度写（mark_read/heartbeat/index）已移出，只剩唯一写入口 append。
# 4.0.7: Xuanji keeps only the storage face; scheduling writes (mark_read/heartbeat/index)
# have moved out, leaving append as the single write entry.
WRITE_TOOLS = ('daybook_append',)


def _audit_vol():
    """审计卷路径·走 _root()·监理 r4 修复：隔离测试审计不再混进生产。
    Audit-volume path · goes through _root() · supervisor r4 fix: isolated-test auditing no longer leaks into production."""
    return os.path.join(_root(), AUDIT_VOL_NAME)


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _root():
    """账本根：统一走 mcp_resources._root()（conf [index] root > DAYBOOK_ROOT 覆盖）。
    Ledger root: always via mcp_resources._root() (conf [index] root > DAYBOOK_ROOT override)."""
    return _mr._root()


def _wal(path, data, mode, who='mcp_tools'):
    """账本写：已在临界区内用 held 取回本线程已持的 LockedRoot，否则取锁。
    Ledger write: inside a critical section fetch this thread's held LockedRoot, else lock.
    写链仍然只有 `LockedRoot.write` 一条；这里只决定「是否要取锁」。
    The write chain is still the single `LockedRoot.write`; this only decides whether to lock."""
    from safeio import exclusive_held, held, locked
    rt = _root()
    if exclusive_held(rt):
        lr = held(rt, who)
        lr.write(lr.root.rel_of(path, who), data, mode=mode)
        return
    with locked(rt) as lr:
        lr.write(lr.root.rel_of(path, who), data, mode=mode)


def _audit(method, agent_id, detail, ok=True):
    """MCP 调用记入审计卷·append-only·白箱可审计（P1-2）。
    detail 含参数摘要与结果摘要·不含全量原文（防爆）。
    只读模式改走 stderr·零写盘。
    Record the MCP call into the audit volume · append-only · white-box auditable (P1-2).
    detail holds a summary of the arguments and result · not the full raw text (to avoid blow-up).
    In read-only mode it goes to stderr instead · zero disk writes."""
    rec = '[%s] [MCP] [tools/%s] [agent=%s] [%s] %s\n' % (
        _now(), method, agent_id or '匿名',
        'OK' if ok else 'FAIL', detail)[:400]
    if _tr.is_read_only():
        try:
            sys.stderr.write(rec)
            sys.stderr.flush()
        except OSError:
            pass
        return
    try:
        from safeio import WriteMode
        _wal(_audit_vol(), rec, WriteMode.APPEND_CREATE, 'mcp_tools._audit')
    except OSError:
        pass  # 审计失败不阻塞主流程
              # an audit failure does not block the main flow


def _record_signature(tool, agent_id, signature, payload, **fields):
    """签名落账（边车·append-only·JSONL）·支持事后验签。
    Record the signature into an append-only JSONL sidecar · supports post-hoc verification.
    只读模式不写（写工具本已被拒·此处再兜一层）。
    No write in read-only mode (write tools are already rejected · this is a second guard)."""
    if _tr.is_read_only():
        return
    rec = {'at': _now(), 'tool': tool, 'agent_id': agent_id,
           'signature': signature, 'payload': payload}
    rec.update(fields)
    from safeio import WriteMode
    _wal(os.path.join(_root(), SIG_SIDECAR),
         json.dumps(rec, ensure_ascii=False, sort_keys=True) + '\n',
         WriteMode.APPEND_CREATE, 'mcp_tools._record_signature')


def _append_payload(volume, tag, subtag, to, ts, content):
    """append 签名载荷（v2）：至少绑 volume/tag/subtag/to/ts·再绑正文。
    Append signature payload (v2): binds at least volume/tag/subtag/to/ts · plus the body."""
    return 'append|v2|volume=%s|tag=%s|subtag=%s|to=%s|ts=%d|content=%s' % (
        volume, tag, subtag or '', to or '', int(ts), content)


def _safe_vol(name):
    """volume 名防穿越（P1-3）。允许 [A-Za-z0-9_-] 与中文·拒绝 ../ 与绝对路径。
    Volume-name traversal guard (P1-3). Allows [A-Za-z0-9_-] and Chinese · rejects ../ and absolute paths."""
    if not name or '..' in name or '/' in name or '\\' in name or os.path.isabs(name):
        raise ValueError('非法卷名：%r' % name)
    return name


def _load_conf():
    """读 daybook.conf（统一走 mcp_resources：conf 目录，非根目录）。
    Read daybook.conf (via mcp_resources: the conf directory, not the root)."""
    return _mr._load_conf()


def _verify_agent(agent_id, signature, payload, force=True):
    """G3 身份校验（P1-1·监理 r3 修复）。
    - force=True（写工具）：必须 agent_id+signature·缺任一即抛·不允许匿名
    - force=False（查询·预留）：允许匿名
    验签失败抛 ValueError。
    G3 identity verification (P1-1 · supervisor r3 fix).
    - force=True (write tools): agent_id+signature required · raise if either is missing · anonymous not allowed
    - force=False (query · reserved): anonymous allowed
    Raises ValueError on signature failure."""
    if not agent_id:
        if force:
            raise ValueError('写工具必须 agent_id（作者 ID 红线·不允许匿名写）')
        return None
    if not signature:
        raise ValueError('agent_id 已提供但缺 signature')
    reg = _AgentRegistry(os.path.join(_root(), '注册卷.txt'))
    if not reg.verify(agent_id, payload, signature):
        raise ValueError('签名校验失败·agent=%s' % agent_id)
    return agent_id


def _agent_reg():
    """取 G3 注册表实例·root 隔离。
    Get a G3 registry instance · isolated by root."""
    return _AgentRegistry(os.path.join(_root(), '注册卷.txt'))


# ── v3.1 多级目录下钻（四库式：部=卷／类·作者／属=条目）──────
# ── v3.1 multi-level directory drilling (four-library style: 部=volume / 类·author / 属=entry) ──
def _multidx_dir():
    """多级目录目录：与 daybook_multidx.py 同源（conf 的 index.out_dir + multilevel.out_dir）。
    Catalogue directory: same source as daybook_multidx.py (conf index.out_dir + multilevel.out_dir)."""
    return _mr._multidx_dir(_root())


def _read_multidx_tsv():
    """读 <根>/multilevel/*_catalog.tsv → [dict(volume,level2,line,time,category,author,title)]。
    目录未生成返 []（调用方给友好提示）。
    新旧名皆认：`<卷>_catalog.tsv`（新）/`<卷>_目录.tsv`（旧·兼容）；表头亦归一（旧中文表头照读）。
    Read <root>/multilevel/*_catalog.tsv → [dict(volume,level2,line,time,category,author,title)].
    Returns [] if the directory has not been generated (the caller gives a friendly hint).
    Both names accepted: `<vol>_catalog.tsv` (new) / `<vol>_目录.tsv` (legacy); headers are normalized too."""
    d = _multidx_dir()
    rows = []
    if not os.path.isdir(d):
        return rows
    for fn in sorted(os.listdir(d)):
        if not (fn.endswith('_catalog.tsv') or fn.endswith('_目录.tsv')):
            continue
        p = os.path.join(d, fn)
        try:
            with open(p, encoding='utf-8') as f:
                lines = [l.rstrip('\n') for l in f if l.strip()]
        except OSError:
            continue
        if not lines:
            continue
        hdr = [_db.canon_field(h) for h in lines[0].split('\t')]  # 旧中文表头照读 / legacy Chinese header still read
        for l in lines[1:]:
            cells = l.split('\t')
            if len(cells) < len(hdr):
                cells = cells + [''] * (len(hdr) - len(cells))
            rows.append(dict(zip(hdr, cells)))
    return rows


class _VolumeIndex:
    """单次 MCP 调用内的整卷索引（行号 → 偏移），跨调用不复用。
    Per-MCP-call whole-volume index (line no → offset); never reused across calls.
    整卷只读一次；键 = (path, mtime_ns, size)，任一项变化即重读。
    The volume is read once; key = (path, mtime_ns, size) — any change forces a re-read.
    cross_ref 生成互见引用与 _entry_full 取全文共用这一份。
    Shared by cross_ref reference building and _entry_full full-text extraction."""

    def __init__(self):
        self._vols = {}
        self._blocks = {}       # (path, start, end) → 条目块文本 / entry block text
        self._texts = {}        # (path, start, end) → 含末尾换行的条目文本 / entry text incl. trailing newline
        self._sha = {}          # (path, start, end) → SHA-256 前 8 位 / first 8 hex of SHA-256
        self.reads = 0          # 实际整卷读取次数（验收指标）/ actual whole-volume reads (acceptance metric)

    def _load(self, path):
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
        item = self._vols.get(path)
        if item is not None and item['key'] == key:
            return item
        with open(path, 'rb') as f:
            raw = f.read()
        from safeio import sniff_bytes
        text, enc, _why = sniff_bytes(raw)
        self.reads += 1
        lines = text.split('\n')
        char_offsets = []
        p = 0
        for ln in lines:
            char_offsets.append(p)
            p += len(ln) + 1
        if enc == 'utf-16':
            # UTF-16 的 '\n' 不是单字节 ⇒ 偏移表建在解码文本上（仍只读一次）
            # UTF-16's '\n' is not a single byte ⇒ offsets are built on the decoded text (still one read)
            item = {'key': key, 'raw': None, 'text': text, 'enc': enc,
                    'lines': lines, 'offsets': char_offsets, 'char_offsets': char_offsets,
                    'heads': {}, 'bytes': False}
        else:
            offsets = [0]
            pos = 0
            while True:
                j = raw.find(b'\n', pos)
                if j < 0:
                    break
                offsets.append(j + 1)
                pos = j + 1
            item = {'key': key, 'raw': raw, 'text': text, 'enc': enc,
                    'lines': lines, 'offsets': offsets, 'char_offsets': char_offsets,
                    'heads': {}, 'bytes': True}
        self._vols[path] = item
        return item

    def _heads(self, item, head_re):
        """行首命中表：一次 C 级 finditer 扫全卷，返行号列表；非 '^' 模式返 None（回退逐行）。
        Line-start match table: one C-level finditer pass over the volume → line numbers; None for non-'^' patterns (fall back to per-line)."""
        key = head_re.pattern
        if key in item['heads']:
            return item['heads'][key]
        heads = None
        if head_re.pattern.startswith('^'):
            import re as _re, bisect as _bisect
            try:
                rx = _re.compile(head_re.pattern, head_re.flags | _re.M)
                coffs = item['char_offsets']
                heads = [_bisect.bisect_right(coffs, m.start()) for m in rx.finditer(item['text'])]
            except _re.error:
                heads = None
        item['heads'][key] = heads
        return heads

    def _span(self, path, lineno, head_re, walk_back):
        """行号 → (item, 起始偏移, 结束偏移, 末行号)。口径与 cross_ref._entry_at / _entry_full 各自一致。
        Line no → (item, start offset, end offset, last line). Semantics follow cross_ref._entry_at / _entry_full respectively.
        行首表可用时按二分定位（O(log n)）；否则回退逐行扫描（保语义一致）。
        Uses the line-start table with binary search (O(log n)) when available; otherwise falls back to per-line scanning (same semantics)."""
        it = self._load(path)
        lines = it['lines']
        if lineno < 1 or lineno > len(lines):
            return None
        heads = self._heads(it, head_re)
        if heads is not None:
            import bisect as _bisect
            start = lineno
            if walk_back and not head_re.match(lines[start - 1]):
                k = _bisect.bisect_right(heads, lineno) - 1
                if k < 0:
                    return None
                start = heads[k]
            j = _bisect.bisect_right(heads, start)
            # end 为 0-based 排他下标（与逐行扫描的 end 同口径）
            # end is a 0-based exclusive index (same as the per-line scan)
            end = (heads[j] - 1) if j < len(heads) else len(lines)
        else:
            start = lineno
            if walk_back and not head_re.match(lines[start - 1]):
                while start > 1 and not head_re.match(lines[start - 1]):
                    start -= 1
                if not head_re.match(lines[start - 1]):
                    return None
            end = start
            while end < len(lines):
                if end > start and head_re.match(lines[end]):
                    break
                end += 1
        offs = it['offsets']
        b0 = offs[start - 1]
        b1 = offs[end] if end < len(offs) else (len(it['raw']) if it['bytes'] else len(it['text']))
        # 末条 = 其后无条目头，块到文末；调用方须显式标注
        # is_last = no following head, block runs to EOF; callers must mark it explicitly
        return it, b0, b1, end, start, end >= len(lines)

    def entry_block(self, path, lineno, head_re):
        """条目原文·不含末尾换行（与 cross_ref._entry_at 同口径）；无条目返 None。
        Entry text without the trailing newline (same rule as cross_ref._entry_at); None when absent.
        同一次调用内按 (path, 起行, 止行) 复用，避免重复解码。
        Reused per (path, start line, end line) within the call to avoid repeated decoding."""
        sp = self._span(path, lineno, head_re, walk_back=True)
        if sp is None:
            return None
        it, b0, b1, end, start, _last = sp
        key = (path, start, end)
        cached = self._blocks.get(key)
        if cached is not None:
            return cached
        # 只在块由下一条目头截断时去掉末尾换行；到文末时与 split('\n')+join 口径一致（保留）。
        # Strip the trailing newline only when a following head terminates the block; at EOF keep it (same as split('\n')+join).
        tail_nl = end < len(it['lines'])
        if it['bytes']:
            block = it['raw'][b0:b1]
            if tail_nl and block.endswith(b'\n'):
                block = block[:-1]
            block = block.decode(it['enc'], 'replace')
        else:
            block = it['text'][b0:b1]
            if tail_nl and block.endswith('\n'):
                block = block[:-1]
        self._blocks[key] = block
        return block

    def entry_sha8(self, path, lineno, head_re):
        """条目块 SHA-256 前 8 位（与 cross_ref._entry_hash 同口径）；无条目返 None。
        First 8 hex of the entry block's SHA-256 (same rule as cross_ref._entry_hash); None when absent.
        同一次调用内按 (path, 起行, 止行) 复用（长块不重复哈希）。
        Reused per (path, start line, end line) within the call (long blocks are not re-hashed)."""
        sp = self._span(path, lineno, head_re, walk_back=True)
        if sp is None:
            return None
        _it, _b0, _b1, end, start, _last = sp
        key = (path, start, end)
        h = self._sha.get(key)
        if h is None:
            import hashlib
            block = self.entry_block(path, lineno, head_re)
            h = hashlib.sha256(block.encode('utf-8')).hexdigest()[:8]
            self._sha[key] = h
        return h

    def entry_text(self, path, lineno, head_re):
        """条目原文·含末尾换行（与旧 _entry_full 同口径）；无条目返 ''。
        Entry text including the trailing newline (same rule as the old _entry_full); '' when absent.
        同一次调用内按 (path, 起行, 止行) 复用。
        Reused per (path, start line, end line) within the call."""
        text, _last = self.entry_text_span(path, lineno, head_re)
        return text

    def entry_text_span(self, path, lineno, head_re):
        """条目原文 + 是否末条（其后无条目头，块到文末）。
        Entry text + is_last (no following head; the block runs to EOF).
        返回 (文本, 是否末条)；无条目返 ('', False)。"""
        sp = self._span(path, lineno, head_re, walk_back=False)
        if sp is None:
            return '', False
        it, b0, b1, end, start, is_last = sp
        key = (path, start, end)
        cached = self._texts.get(key)
        if cached is not None:
            return cached, is_last
        if it['bytes']:
            text = it['raw'][b0:b1].decode(it['enc'], 'replace')
        else:
            text = it['text'][b0:b1]
        self._texts[key] = text
        return text, is_last


def _entry_full(vol, lineno, index=None):
    """按卷+行号取条目原文（含续行·读到下一个条目头前）。返回 (文本, 是否末条)。
    Fetch an entry's raw text by volume+line number (including continuation lines · read until the next entry header).
    Returns (text, is_last)；末条=其后无条目头，块到文末，调用方须显式标注。
    is_last means no following head and the block runs to EOF; callers must mark it explicitly.
    index 提供时复用单次调用内的整卷索引（不再整卷读）。
    When index is given, reuse the per-call whole-volume index (no further whole-volume reads)."""
    import re as _re
    conf = _load_conf()
    rel = conf.get('volumes', {}).get(vol)
    if not rel:
        return '', False
    path = rel if os.path.isabs(rel) else os.path.join(_root(), rel)
    # 缺省口径与 daybook.py 同源（v3.2.2：原缺省 ^\[ 与索引器分钟级不一致 ⇒ 判两个答案）
    # Default shares daybook.DEFAULT_HEAD_REGEX (v3.2.2: the old ^\[ default disagreed
    # with the indexer's minute-level one, i.e. two answers for one question).
    head_re = (conf.get('entries', {}).get('head_regex') or _db.DEFAULT_HEAD_REGEX).strip()
    try:
        pat = _re.compile(head_re)
    except _re.error:
        pat = _re.compile(r'\[')
    if index is not None:
        return index.entry_text_span(path, int(lineno), pat)
    from safeio import read_vol
    txt, _enc, _why = read_vol(path)
    lines = txt.splitlines(keepends=True)
    i = int(lineno) - 1
    if not (0 <= i < len(lines)):
        return '', False
    out = [lines[i]]
    is_last = True
    for l in lines[i + 1:]:
        if pat.match(l):
            is_last = False
            break
        out.append(l)
    return ''.join(out), is_last


def _entry_ref(vol, lineno, index=None):
    """生成互见引用 [卷#L行-SHA8]（v3.1）。
    复用 cross_ref 的哈希算法（保 verify_ref 兼容）·但卷路径按 daybook.conf 卷表解析
    （cross_ref 默认按 <root>/<卷>.txt 找·与 conf 卷名不一致时须校正）。
    失败抛异常·不静默返回空串。
    index 提供时整卷只读一次（单次调用内复用），不再逐条整卷读。
    Generate a cross-reference [volume#Lline-SHA8] (v3.1).
    Reuses cross_ref's hashing algorithm (keeps verify_ref compatible) · but the volume path is resolved via the daybook.conf volume table
    (cross_ref defaults to <root>/<volume>.txt · must be corrected when it disagrees with the conf volume name).
    Raises on failure · never silently returns an empty string.
    When index is given the volume is read once (reused within the call), not once per entry."""
    from cross_ref import CrossRef
    conf = _load_conf()

    def _vp(v, _conf=conf, _root=_root()):
        rel = _conf.get('volumes', {}).get(v)
        if not rel:
            raise KeyError('卷 %s 不在 conf 卷表' % v)
        return rel if os.path.isabs(rel) else os.path.join(_root, rel)

    cr = CrossRef(root=_root())
    cr._vol_path = _vp          # 按 conf 校正卷定位（哈希算法仍用 cross_ref 原实现）
                                # correct the volume location per conf (the hashing algorithm still uses cross_ref's original implementation)
    return cr.make_ref(vol, int(lineno), index=index)


def _multi_query(args):
    """四库式层级下钻。level=部→各卷概览；类→二级分组计数；属(默认)→条目提要行(可全文)。
    附互见引用（cross_ref）·LLM 不必拉全卷。
    Four-library-style hierarchical drilling. level=部→per-volume overview; 类→level-2 group counts; 属(default)→entry summary lines (optionally full text).
    Attaches cross-references (cross_ref) · so the LLM need not pull whole volumes."""
    vol = (args.get('volume') or '').strip()
    cls = (args.get('cls') or '').strip()
    author = (args.get('author') or '').strip()
    timepfx = (args.get('time') or '').strip()
    l2 = (args.get('l2') or '').strip()
    level = (args.get('level') or 'entry').strip()
    # 旧中文层级名兼容；其中「类」属字段别名，统一走 conf_norm.canon_field。
    # Legacy Chinese level names; 「类」is a field alias, so normalise it via conf_norm.
    level = {'部': 'volume', '属': 'entry'}.get(level, canon_field(level))
    try:
        limit = int(args.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    full = bool(args.get('full'))

    rows = _read_multidx_tsv()
    if not rows:
        return ('多级目录为空或未生成（查找目录：%s）。请先在账本侧执行 `python3 daybook.py multiindex`'
                '（按 conf 的 index.out_dir + multilevel.out_dir 生成 <卷>_catalog.tsv）后再下钻。'
                '（旧名 <根>/多级/<卷>_目录.tsv 仍可读）' % _multidx_dir())
    if vol:
        rows = [r for r in rows if r.get('volume') == vol]
    if cls:
        rows = [r for r in rows if cls in (r.get('category') or '')]
    if author:
        rows = [r for r in rows if author in (r.get('author') or '')]
    if timepfx:
        rows = [r for r in rows if (r.get('time') or '').startswith(timepfx)]
    if l2:
        rows = [r for r in rows if l2 in (r.get('level2') or '')]

    scope = 'volume=%s' % (vol or '全部') 
    if cls:
        scope += ' 类~%s' % cls
    if author:
        scope += ' 作者~%s' % author
    if timepfx:
        scope += ' 时间~%s' % timepfx
    if l2:
        scope += ' 二级~%s' % l2

    if level == 'volume':
        per = {}
        for r in rows:
            k = r.get('volume', '')
            g = per.setdefault(k, {'n': 0, 'g': set()})
            g['n'] += 1
            g['g'].add(r.get('level2', ''))
        out = ['【部级概览】%s ｜ 卷 %d 个 ｜ 命中条目 %d 条' % (scope, len(per), len(rows))]
        for k in sorted(per):
            out.append('  %s卷：%d 条 ／ %d 个二级组' % (k, per[k]['n'], len(per[k]['g'])))
        return '\n'.join(out)

    if level == 'category':
        g = {}
        for r in rows:
            k = r.get('level2', '') if vol else '%s·%s' % (r.get('volume', ''), r.get('level2', ''))
            g[k] = g.get(k, 0) + 1
        out = ['【类级分组】%s ｜ %d 组 ｜ 命中 %d 条' % (scope, len(g), len(rows))]
        for k in sorted(g):
            out.append('  %s：%d 条' % (k, g[k]))
        return '\n'.join(out)

    # level 属（默认）：条目提要行
    # level 属 (default): entry summary lines
    def _ln(r):
        try:
            return int(r.get('line') or 0)
        except ValueError:
            return 0
    rows = sorted(rows, key=lambda r: (r.get('time', ''), _ln(r)))
    shown = rows[:limit] if limit else rows
    out = ['【属级条目】%s ｜ 命中 %d 条 ｜ 显示 %d 条%s'
           % (scope, len(rows), len(shown), '（含全文）' if full else '')]
    # 单次调用内的整卷索引：互见引用与全文共用，整卷只读一次（跨调用不复用）
    # Per-call whole-volume index: shared by references and full text; one read per call (never across calls)
    index = _VolumeIndex()
    for r in shown:
        v = r.get('volume', '')
        ln = r.get('line', '0')
        line = '- %s#L%s · [%s] [%s] %s' % (
            v, ln, r.get('time', ''), r.get('category', ''), r.get('title', ''))
        if r.get('author'):
            line += ' · %s' % r['author']
        ref = None
        try:
            ref = _entry_ref(v, ln, index)      # 互见层：附可校验的定位引用
                                                # cross-reference layer: attach a verifiable location reference
        except Exception as e:
            # 失败不静默：stderr 留痕 + 输出显式错误标记
            # Never silent: leave a trace on stderr + emit an explicit error marker
            try:
                sys.stderr.write('WARN 互见引用失败 %s#L%s: %s: %s\n'
                                 % (v, ln, type(e).__name__, e))
                sys.stderr.flush()
            except OSError:
                pass
        if ref:
            line += '  ↪%s' % ref
        else:
            line += '  ↪[互见失败]'
        out.append(line)
        if full:
            t, is_last = _entry_full(v, ln, index)
            if t:
                out.append('    ' + t.rstrip('\n').replace('\n', '\n    '))
                if is_last:
                    # 末条显式标注：其后无条目头，块到文末，不静默延伸
                    # Explicit last-entry marker: no following head, block runs to EOF — never extend silently
                    out.append('    （末条·至文末：其后无条目头）')
    if os.environ.get('DAYBOOK_MCP_TRACE_READS') == '1':
        # 验收购读：一次 multi_query 的整卷读取次数（仅 trace，不改语义）
        # Acceptance trace: whole-volume reads in this multi_query (trace only, semantics unchanged)
        try:
            sys.stderr.write('[daybook-mcp] multi_query volume reads=%d\n' % index.reads)
            sys.stderr.flush()
        except OSError:
            pass
    return '\n'.join(out)


# ── 工具 schema（JSON Schema 风格） ──
# ── Tool schema (JSON Schema style) ──
TOOLS = [
    {
        'name': 'daybook_query',
        'description': '查账本。两种模式：① 字段查询（field/value/extra_filters/count）；'
                       '② 四库式下钻（level/volume/cls/author/time/l2/full·省略 level 默认 entry）。'
                       '下钻读多级目录，条目附互见引用 ↪[卷#L行-SHA8]。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'mode': {'type': 'string', 'enum': ['field', 'drill'],
                         'description': '省略时：有 field 走字段查询，否则走下钻'},
                'field': {'type': 'string', 'description': '字段名（卷/行号/时间/类/标题/作者）'},
                'value': {'type': 'string', 'description': '期望子串·空字符串表示不过滤该字段'},
                'extra_filters': {
                    'type': 'object',
                    'description': '可选·多字段同时过滤·key=字段名 value=期望子串',
                },
                'count': {'type': 'boolean', 'description': '字段查询：只返回命中数·默认 false'},
                'volume': {'type': 'string', 'description': '下钻：卷名（省略＝跨全部在册卷）'},
                'cls': {'type': 'string', 'description': '下钻：类字段过滤（子串·如 报/核/工）'},
                'author': {'type': 'string', 'description': '下钻：作者过滤（子串）'},
                'time': {'type': 'string', 'description': '下钻：时间前缀过滤·如 2026-10 或 2026-10-15'},
                'l2': {'type': 'string', 'description': '下钻：二级键值过滤（二级＝类或作者·按 conf[multilevel] level2_field）'},
                'level': {'type': 'string', 'enum': ['volume', 'category', 'entry'],
                          'description': '下钻层级·默认 entry（属）'},
                'limit': {'type': 'integer', 'description': '最多返回条数·默认 50'},
                'full': {'type': 'boolean', 'description': '下钻属级命中回全文（默认 false·只回提要行）'},
            },
            'required': [],
        },
    },
    {
        'name': 'daybook_list',
        'description': '列 daybook.conf 卷表登记的所有卷·含路径/行数/字节数',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'daybook_append',
        'description': '向卷追加一条日志·append-only·原子写·作者 ID 红线强制：author 必须等于已注册的 agent_id·并附 signature 验签。签名三件（agent_id/signature/ts）经本机签名代理自动填入，客户端无需填写或计算；不经代理直连时须自行提供，算法见 README。to 字段为收件人 ID 列表（逗号分隔）·不填即广播',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'volume': {'type': 'string', 'description': '卷名（不带.txt·按 daybook.conf 卷表）'},
                'tag': {'type': 'string', 'description': '主标签（标签段 1）'},
                'subtag': {'type': 'string', 'description': '子标签（标签段 2·可空）'},
                'author': {'type': 'string', 'description': '作者 ID·必须等于已注册的 agent_id'},
                'content': {'type': 'string', 'description': '正文'},
                'to': {'type': 'string', 'description': '收件人 ID·逗号分隔多收件人·不填即广播（F1 收件人寻址）'},
                'agent_id': {'type': 'string', 'description': '由本机签名代理自动填入；不经代理直连时须自行提供（注册 agent_id）'},
                'signature': {'type': 'string',
                              'description': '由本机签名代理自动填入，客户端无需计算；不经代理直连时须自行提供（算法见 README）'},
                'ts': {'type': 'integer', 'description': '由本机签名代理自动填入；不经代理直连时须自行提供（Unix 秒，服务端校验 ±60s）'},
            },
            'required': ['volume', 'tag', 'author', 'content'],
        },
    },
    {
        'name': 'cross_ref_verify',
        'description': '校验跨卷引用·返回 true/false',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'ref': {'type': 'string', 'description': '[卷名#L行-SHA8]'},
            },
            'required': ['ref'],
        },
    },
]


def list_tools():
    """工具清单·只读模式隐藏唯一写工具 append。
    Tool list · the single write tool (append) is hidden in read-only mode."""
    if _tr.is_read_only():
        return [t for t in TOOLS if t.get('name') not in WRITE_TOOLS]
    return TOOLS


def _tool_error(message):
    """P2-1·tools/call 失败返 result{isError:true, content:[...]} 而非 -32603。
    P2-1 · a failed tools/call returns result{isError:true, content:[...]} instead of -32603."""
    return {'isError': True, 'content': [{'type': 'text', 'text': message}]}


def _tool_ok(text):
    return {'content': [{'type': 'text', 'text': text}]}


def call_tool(name, args, agent_id=None, signature=None):
    """执行工具·返回 result dict（成功 content·失败 isError:true）。
    agent_id/signature 可选·写工具必须验签（P1-1）。
    优先用显式 kwargs（来自 _meta）·缺则从 args 兜底（方便 LLM 客户端直填）。
    Execute a tool · returns a result dict (content on success · isError:true on failure).
    agent_id/signature are optional · write tools must verify the signature (P1-1).
    Prefers explicit kwargs (from _meta) · falls back to args when absent (convenient for LLM clients filling them directly)."""
    args = args or {}
    if not agent_id:
        agent_id = args.get('agent_id')
    if not signature:
        signature = args.get('signature')

    # 只读模式：唯一写工具 append 一律拒·不落盘
    # Read-only mode: the single write tool (append) is rejected · nothing is written
    if _tr.is_read_only() and name in WRITE_TOOLS:
        _audit(name, agent_id, '只读模式拒绝写工具', ok=False)
        return _tool_error('只读模式（MCP_READ_ONLY=1）：写工具 %s 已禁用' % name)

    try:
        if name == 'daybook_query':
            mode = (args.get('mode') or '').strip()
            if not mode:
                mode = 'field' if args.get('field') else 'drill'
            if mode == 'drill':
                # 4.0.7：multi_query 并入 query（不再是独立工具）
                # 4.0.7: multi_query is merged into query (no longer a separate tool)
                out = _multi_query(args)
                _audit('query', agent_id,
                       'drill vol=%s level=%s → %s' % (
                           args.get('volume', ''), args.get('level', 'entry'),
                           out.split('\n')[0][:80]))
                return _tool_ok(out)
            field = args.get('field', '')
            value = args.get('value', '')
            extras = args.get('extra_filters') or {}
            count_only = bool(args.get('count'))
            limit = int(args.get('limit', 50))
            # 构造 daybook.py query 认的 args 列表：key=value
            # build the args list that daybook.py query accepts: key=value
            cli_args = []
            if field:
                cli_args.append('%s=%s' % (field, value))
            for k, v in extras.items():
                cli_args.append('%s=%s' % (k, v))
            if count_only:
                cli_args.append('--count')
            if limit:
                cli_args.append('--limit=%d' % limit)
            conf = _load_conf()
            out = _db.query(conf, _root(), cli_args)
            _audit('query', agent_id, 'field=%s value=%r → %d chars' % (field, value[:40], len(out)))
            return _tool_ok(out)

        if name == 'daybook_append':
            # W-75 修④：先验签后取卷名（防未授权请求泄露卷名信息）
            # W-75 fix ④: verify the signature before fetching the volume name (prevents an unauthorized request from leaking volume-name info)
            # v2：签名载荷绑 volume/tag/subtag/to/ts + 正文·防跨卷重放
            # v2: the signature payload binds volume/tag/subtag/to/ts + body · prevents cross-volume replay
            vol_raw = args.get('volume', '')
            tag = args.get('tag', '')
            subtag = args.get('subtag', '') or '_'
            author = args.get('author', '')
            content = args.get('content', '')
            to = args.get('to')  # F1 收件人寻址·可空
                                 # F1 recipient addressing · may be empty
            ts = int(args.get('ts', 0))
            if not agent_id or not signature:
                # required 已松绑：经代理只传三字段即可；直连未签名时给一句能读懂的指路。
                # required is relaxed: three fields suffice via the proxy; direct unsigned calls
                # get a readable pointer instead of a bare verification error.
                raise ValueError('未签名调用：经本机签名代理时由代理补签名；'
                                 '不经代理直连请提供 agent_id/signature/ts，算法见 README')
            payload = _append_payload(vol_raw, tag, subtag, to, ts, content)
            _verify_agent(agent_id, signature, payload, force=True)
            # 时间窗在验签之后校验：先让匿名/坏签拿到准确错误，再挡重放
            # The time window is checked after verification: anonymous/bad signatures get the precise error first, then replays are blocked
            if abs(time.time() - ts) > 60:
                raise ValueError('append 时间戳越窗（当前 %.0f·收到 %d·允许 ±60s）' % (time.time(), ts))
            vol = _safe_vol(vol_raw)
            # 作者 ID 红线：author 必须等于 agent_id·防冒名
            # Author-ID red line: author must equal agent_id · guards against impersonation
            if author != agent_id:
                raise ValueError('作者 ID 红线：author=%r 必须等于 agent_id=%r（防冒名）' % (author, agent_id))
            # F1 收件人寻址校验：to 里的每个 ID 必须是已注册 agent·防垃圾寻址
            # F1 recipient-addressing check: every ID in `to` must be a registered agent · guards against junk addressing
            if to:
                reg = _agent_reg()
                to_ids = [t.strip() for t in to.split(',') if t.strip()]
                for tid in to_ids:
                    if not reg.lookup(tid):
                        raise ValueError('收件人 %r 未在 G3 注册卷注册（防垃圾寻址）' % tid)
            # 解析卷路径·按 daybook.conf 卷表
            # resolve the volume path · via the daybook.conf volume table
            conf = _load_conf()
            vol_path = conf.get('volumes', {}).get(vol)
            if not vol_path:
                raise ValueError('卷 %r 不在 daybook.conf 卷表' % vol)
            full_path = vol_path if os.path.isabs(vol_path) else os.path.join(_root(), vol_path)
            # 作者口径：作者位写显示名，注册表 id 只作 [id=ag-…] 附注
            # Author convention: the author slot holds the display name; the registry id is an [id=ag-…] annotation
            _agent = _agent_reg().lookup(agent_id)
            author_slot = (_agent.name if _agent and _agent.name else agent_id)
            # 签名先落边车·写失败则不动卷（保证事后可验签）
            # Record the signature to the sidecar first · if that fails the volume is untouched (post-hoc verifiability guaranteed)
            _record_signature('daybook_append', agent_id, signature, payload,
                              volume=vol, tag=tag, subtag=subtag, to=to or '', ts=ts)
            # 调 daybook_append.append_one 原子写·传 to
            # call daybook_append.append_one for an atomic write · passing `to`
            rc = _dba.append_one(full_path, tag, subtag, content, author=author_slot,
                                 to=to, author_id=agent_id, root=_root())
            if rc != 0:
                raise RuntimeError('append_one rc=%d' % rc)
            _audit('append', agent_id, 'vol=%s tag=%s to=%s → %s' % (vol, tag, to or '广播', full_path))
            return _tool_ok('appended to %s' % vol)

        if name == 'daybook_list':
            conf = _load_conf()
            vols = conf.get('volumes', {})
            lines = ['daybook.conf 卷表（%d 卷）：' % len(vols)]
            for vname, vpath in vols.items():
                full = vpath if os.path.isabs(vpath) else os.path.join(_root(), vpath)
                if os.path.exists(full):
                    st = os.stat(full)
                    # W-75 修⑤：硬编码 utf-8 ⇒ 走 sniff（gb18030 等卷不乱码）
                    # W-75 fix ⑤: hard-coded utf-8 ⇒ go through sniff (gb18030 and other volumes are not garbled)
                    _raw = open(full, 'rb').read()
                    from safeio import sniff_bytes
                    _txt, _enc, _why = sniff_bytes(_raw)
                    ln = sum(1 for _ in _txt.split('\n'))
                    lines.append('  %s → %s (%d 字节, %d 行)' % (vname, vpath, st.st_size, ln))
                else:
                    lines.append('  %s → %s （文件不存在）' % (vname, vpath))
            out = '\n'.join(lines)
            _audit('list', agent_id, '→ %d 卷' % len(vols))
            return _tool_ok(out)

        if name == 'cross_ref_verify':
            from cross_ref import CrossRef
            cr = CrossRef(root=_root())
            ok = cr.verify_ref(args['ref'])
            _audit('cross_ref_verify', agent_id, 'ref=%s → %s' % (args['ref'][:60], ok))
            return _tool_ok('true' if ok else 'false')

        # 未知工具
        # unknown tool
        _audit(name, agent_id, '未知工具', ok=False)
        return _tool_error('未知工具：%s' % name)

    except ValueError as e:
        # 参数错/验签失败/卷不存在·返 isError:true 让模型看见（P2-1）
        # bad args / signature failure / missing volume · return isError:true so the model can see it (P2-1)
        _audit(name, agent_id, 'FAIL: %s' % str(e)[:200], ok=False)
        return _tool_error('参数错：%s' % e)
    except Exception as e:
        _audit(name, agent_id, 'FAIL: %s: %s' % (type(e).__name__, str(e)[:200]), ok=False)
        return _tool_error('执行失败：%s: %s' % (type(e).__name__, e))
