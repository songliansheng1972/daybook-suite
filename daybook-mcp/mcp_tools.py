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
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import daybook as _db
import daybook_append as _dba
from agent_registry import Registry as _AgentRegistry

AUDIT_VOL_NAME = 'MCP审计卷.txt'


def _audit_vol():
    """审计卷路径·走 _root()·监理 r4 修复：隔离测试审计不再混进生产。
    Audit-volume path · goes through _root() · supervisor r4 fix: isolated-test auditing no longer leaks into production."""
    return os.path.join(_root(), AUDIT_VOL_NAME)


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _root():
    return os.environ.get('DAYBOOK_ROOT') or HERE


def _audit(method, agent_id, detail, ok=True):
    """MCP 调用记入审计卷·append-only·白箱可审计（P1-2）。
    detail 含参数摘要与结果摘要·不含全量原文（防爆）。
    Record the MCP call into the audit volume · append-only · white-box auditable (P1-2).
    detail holds a summary of the arguments and result · not the full raw text (to avoid blow-up)."""
    try:
        rec = '[%s] [MCP] [tools/%s] [agent=%s] [%s] %s\n' % (
            _now(), method, agent_id or '匿名',
            'OK' if ok else 'FAIL', detail)[:400]
        from safeio import atomic_append
        atomic_append(_audit_vol(), rec)
    except OSError:
        pass  # 审计失败不阻塞主流程
              # an audit failure does not block the main flow


def _safe_vol(name):
    """volume 名防穿越（P1-3）。允许 [A-Za-z0-9_-] 与中文·拒绝 ../ 与绝对路径。
    Volume-name traversal guard (P1-3). Allows [A-Za-z0-9_-] and Chinese · rejects ../ and absolute paths."""
    if not name or '..' in name or '/' in name or '\\' in name or os.path.isabs(name):
        raise ValueError('非法卷名：%r' % name)
    return name


def _load_conf():
    """读 daybook.conf·root 按 _root()·生产同 HERE·测试可走 DAYBOOK_ROOT。
    Read daybook.conf · root follows _root() · production uses HERE · tests may go via DAYBOOK_ROOT."""
    conf_path = os.path.join(_root(), 'daybook.conf')
    return _db.load_conf(conf_path)


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


def _read_cursor(agent_id, vol):
    """F2 已读未读：读某 agent 对某卷的游标。
    F2 read/unread: read an agent's cursor for a volume."""
    import json
    cp = os.path.join(_root(), '.已读_%s_%s.json' % (agent_id, vol))
    if os.path.exists(cp):
        with open(cp, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'resume_byte': 0}


def _write_cursor(agent_id, vol, resume_byte):
    """F2 已读未读：写游标。
    F2 read/unread: write the cursor."""
    import json
    cp = os.path.join(_root(), '.已读_%s_%s.json' % (agent_id, vol))
    cur = {'resume_byte': resume_byte, 'mtime': time.time()}
    with open(cp, 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False)


# ── v3.1 多级目录下钻（四库式：部=卷／类·作者／属=条目）──────
# ── v3.1 multi-level directory drilling (four-library style: 部=volume / 类·author / 属=entry) ──
def _multidx_dir():
    return os.path.join(_root(), 'multilevel')


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


def _entry_full(vol, lineno):
    """按卷+行号取条目原文（含续行·读到下一个条目头前）。
    Fetch an entry's raw text by volume+line number (including continuation lines · read until the next entry header)."""
    import re as _re
    conf = _load_conf()
    rel = conf.get('volumes', {}).get(vol)
    if not rel:
        return ''
    path = rel if os.path.isabs(rel) else os.path.join(_root(), rel)
    from safeio import read_vol
    txt, _enc, _why = read_vol(path)
    lines = txt.splitlines(keepends=True)
    i = int(lineno) - 1
    if not (0 <= i < len(lines)):
        return ''
    head_re = (conf.get('entries', {}).get('head_regex') or r'^\[').strip()
    try:
        pat = _re.compile(head_re)
    except _re.error:
        pat = _re.compile(r'\[')
    out = [lines[i]]
    for l in lines[i + 1:]:
        if pat.match(l):
            break
        out.append(l)
    return ''.join(out)


def _entry_ref(vol, lineno):
    """生成互见引用 [卷#L行-SHA8]（v3.1）。
    复用 cross_ref 的哈希算法（保 verify_ref 兼容）·但卷路径按 daybook.conf 卷表解析
    （cross_ref 默认按 <root>/<卷>.txt 找·与 conf 卷名不一致时须校正）。失败返 ''。
    Generate a cross-reference [volume#Lline-SHA8] (v3.1).
    Reuses cross_ref's hashing algorithm (keeps verify_ref compatible) · but the volume path is resolved via the daybook.conf volume table
    (cross_ref defaults to <root>/<volume>.txt · must be corrected when it disagrees with the conf volume name). Returns '' on failure."""
    try:
        from cross_ref import CrossRef
    except Exception:
        return ''
    conf = _load_conf()

    def _vp(v, _conf=conf, _root=_root()):
        rel = _conf.get('volumes', {}).get(v)
        if not rel:
            raise KeyError('卷 %s 不在 conf 卷表' % v)
        return rel if os.path.isabs(rel) else os.path.join(_root, rel)

    try:
        cr = CrossRef(root=_root())
        cr._vol_path = _vp          # 按 conf 校正卷定位（哈希算法仍用 cross_ref 原实现）
                                    # correct the volume location per conf (the hashing algorithm still uses cross_ref's original implementation)
        return cr.make_ref(vol, int(lineno))
    except Exception:
        return ''


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
    level = {'部': 'volume', '类': 'category', '属': 'entry'}.get(level, level)   # 旧中文层级名兼容 / legacy level names
    try:
        limit = int(args.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    full = bool(args.get('full'))

    rows = _read_multidx_tsv()
    if not rows:
        return ('多级目录为空或未生成。请先在账本侧执行 `python3 daybook.py multiindex`'
                '（生成 <根>/multilevel/<卷>_catalog.tsv）后再下钻；'
                '或在 MCP 侧调 `daybook_index` 后由 watch/多级续建生成。'
                '（旧名 <根>/多级/<卷>_目录.tsv 仍可读）')
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
    for r in shown:
        v = r.get('volume', '')
        ln = r.get('line', '0')
        line = '- %s#L%s · [%s] [%s] %s' % (
            v, ln, r.get('time', ''), r.get('category', ''), r.get('title', ''))
        if r.get('author'):
            line += ' · %s' % r['author']
        ref = _entry_ref(v, ln)      # 互见层：附可校验的定位引用
                                     # cross-reference layer: attach a verifiable location reference
        if ref:
            line += '  ↪%s' % ref
        out.append(line)
        if full:
            t = _entry_full(v, ln)
            if t:
                out.append('    ' + t.rstrip('\n').replace('\n', '\n    '))
    return '\n'.join(out)


# ── 工具 schema（JSON Schema 风格） ──
# ── Tool schema (JSON Schema style) ──
TOOLS = [
    {
        'name': 'daybook_query',
        'description': '按字段精确查询 daybook 卷条目·返回匹配条目原文。字段：卷/行号/时间/类/标题/作者·值为子串匹配',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'field': {'type': 'string', 'description': '字段名（卷/行号/时间/类/标题/作者）'},
                'value': {'type': 'string', 'description': '期望子串·空字符串表示不过滤该字段'},
                'extra_filters': {
                    'type': 'object',
                    'description': '可选·多字段同时过滤·key=字段名 value=期望子串',
                },
                'count': {'type': 'boolean', 'description': '只返回命中数·默认 false'},
                'limit': {'type': 'integer', 'description': '最多返回多少条·默认 50'},
            },
            'required': ['field', 'value'],
        },
    },
    {
        'name': 'daybook_append',
        'description': '向卷追加一条日志·append-only·原子写·作者 ID 红线强制：author 必须等于已注册的 agent_id·并附 signature 验签。to 字段为收件人 ID 列表（逗号分隔）·不填即广播',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'volume': {'type': 'string', 'description': '卷名（不带.txt·按 daybook.conf 卷表）'},
                'tag': {'type': 'string', 'description': '主标签（标签段 1）'},
                'subtag': {'type': 'string', 'description': '子标签（标签段 2·可空）'},
                'author': {'type': 'string', 'description': '作者 ID·必须等于已注册的 agent_id'},
                'content': {'type': 'string', 'description': '正文'},
                'to': {'type': 'string', 'description': '收件人 ID·逗号分隔多收件人·不填即广播（F1 收件人寻址）'},
                'agent_id': {'type': 'string', 'description': '必填·G3 注册的 agent_id'},
                'signature': {'type': 'string', 'description': '必填·对 content 的 HMAC-SHA256 hex 签名'},
            },
            'required': ['volume', 'tag', 'author', 'content', 'agent_id', 'signature'],
        },
    },
    {
        'name': 'daybook_unread',
        'description': '查某 agent 对某卷的未读条目·返回 resume_byte 之后的新增条目原文。读完调 daybook_mark_read 推进游标（F2 已读未读）',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'volume': {'type': 'string', 'description': '卷名'},
                'agent_id': {'type': 'string', 'description': '读者 agent_id'},
                'signature': {'type': 'string', 'description': '必填·对 "unread:<agent_id>:<ts>" 的签名（防重放）'},
                'ts': {'type': 'integer', 'description': '必填·Unix 时间戳·防重放（服务端校验 ±60s 窗口）'},
            },
            'required': ['volume', 'agent_id', 'signature', 'ts'],
        },
    },
    {
        'name': 'daybook_mark_read',
        'description': '把某 agent 对某卷的已读游标推进到当前卷末尾（F2 已读未读·配合 daybook_unread）',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'volume': {'type': 'string', 'description': '卷名'},
                'agent_id': {'type': 'string', 'description': '读者 agent_id'},
                'signature': {'type': 'string', 'description': '必填·对 "read:<volume>" 的签名'},
            },
            'required': ['volume', 'agent_id', 'signature'],
        },
    },
    {
        'name': 'daybook_heartbeat',
        'description': 'Agent 心跳注册·append 一条 [心跳] 条目到 心跳卷.txt·配合 daybook_alive 查在线状态（F3 在线感知）',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'agent_id': {'type': 'string', 'description': '必填·G3 agent_id'},
                'signature': {'type': 'string', 'description': '必填·对 "heartbeat:<ts>" 的签名'},
                'ts': {'type': 'integer', 'description': '必填·Unix 时间戳·防重放（服务端校验 ±60s 窗口）'},
                'load': {'type': 'string', 'description': '可选·负载描述·如 0.3'},
            },
            'required': ['agent_id', 'signature', 'ts'],
        },
    },
    {
        'name': 'daybook_alive',
        'description': '查某 agent 是否在线（心跳卷最后一条在 timeout 秒内即在线·默认 120 秒）·不验签·纯查询',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'agent_id': {'type': 'string', 'description': '查的 agent_id'},
                'timeout': {'type': 'integer', 'description': '心跳超时秒数·默认 120'},
            },
            'required': ['agent_id'],
        },
    },
    {
        'name': 'daybook_index',
        'description': '重建全部卷索引（注：daybook.py build 不支持单卷·此工具会重建所有卷）·必须附 agent_id+signature 验签',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'agent_id': {'type': 'string', 'description': '必填·G3 agent_id'},
                'signature': {'type': 'string', 'description': '必填·对 "reindex:<ts>" 的签名（防重放）'},
                'ts': {'type': 'integer', 'description': '必填·Unix 时间戳·防重放（服务端校验 ±60s 窗口）'},
            },
            'required': ['agent_id', 'signature', 'ts'],
        },
    },
    {
        'name': 'daybook_list',
        'description': '列 daybook.conf 卷表登记的所有卷·含路径/行数/字节数',
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'cross_ref_make',
        'description': '生成跨卷引用 [卷名#L行-SHA8]',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'volume': {'type': 'string'},
                'lineno': {'type': 'integer'},
            },
            'required': ['volume', 'lineno'],
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
    {
        'name': 'daybook_multi_query',
        'description': '按四库式层级「按需下钻」查询（v3.1）·读多级目录（部=卷／类／作者／时／二级）·'
                       'level=部→各卷概览｜类→二级分组计数｜属（默认）→条目提要行（可 full 回全文）·'
                       '每条附互见引用 ↪[卷#L行-SHA8]。LLM 不必拉全卷 ⇒ 长上下文＝按需下钻。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'volume': {'type': 'string', 'description': '卷名（省略＝跨全部在册卷）'},
                'cls': {'type': 'string', 'description': '类字段过滤（子串·如 报/核/工）'},
                'author': {'type': 'string', 'description': '作者过滤（子串）'},
                'time': {'type': 'string', 'description': '时间前缀过滤·如 2026-10 或 2026-10-15'},
                'l2': {'type': 'string', 'description': '二级键值过滤（二级＝类或作者·按 conf[multilevel] level2_field）'},
                'level': {'type': 'string', 'enum': ['volume', 'category', 'entry'], 'description': '下钻层级·默认 属'},
                'limit': {'type': 'integer', 'description': '最多返回条数（属级）·默认 50'},
                'full': {'type': 'boolean', 'description': '属级命中回全文（默认 false·只回提要行·省上下文）'},
            },
            'required': [],
        },
    },
]


def list_tools():
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

    try:
        if name == 'daybook_query':
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
            # W-75 修④：先验签后取卷名
            # W-75 fix ④: verify the signature before fetching the volume name（防未授权请求泄露卷名信息）
            # W-75 fix ④: verify the signature before fetching the volume name (prevents an unauthorized request from leaking volume-name info)
            _verify_agent(agent_id, signature, args.get('content', ''), force=True)
            vol = _safe_vol(args['volume'])
            tag = args['tag']
            subtag = args.get('subtag', '') or '_'
            author = args['author']
            content = args['content']
            to = args.get('to')  # F1 收件人寻址·可空
                                 # F1 recipient addressing · may be empty
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
            # 调 daybook_append.append_one 原子写·传 to
            # call daybook_append.append_one for an atomic write · passing `to`
            rc = _dba.append_one(full_path, tag, subtag, content, author=author, to=to)
            if rc != 0:
                raise RuntimeError('append_one rc=%d' % rc)
            _audit('append', agent_id, 'vol=%s tag=%s to=%s → %s' % (vol, tag, to or '广播', full_path))
            return _tool_ok('appended to %s' % vol)

        if name == 'daybook_unread':
            # F2 已读未读：查 agent 对卷的未读条目
            # F2 read/unread: query an agent's unread entries for a volume
            # W-75 修④：先验签后取卷名
            # W-75 fix ④: verify the signature before fetching the volume name
            ts = int(args.get('ts', 0))
            if abs(time.time() - ts) > 60:
                raise ValueError('unread 时间戳越窗（当前 %.0f·收到 %d·允许 ±60s）' % (time.time(), ts))
            payload = 'unread:%s:%d' % (agent_id, ts)
            _verify_agent(agent_id, signature, payload, force=True)  # 防任意查他人未读
                                                                     # guards against querying others' unread at will
            vol = _safe_vol(args['volume'])
            conf = _load_conf()
            vol_path = conf.get('volumes', {}).get(vol)
            if not vol_path:
                raise ValueError('卷 %r 不在 daybook.conf 卷表' % vol)
            full_path = vol_path if os.path.isabs(vol_path) else os.path.join(_root(), vol_path)
            cursor = _read_cursor(agent_id, vol)
            resume_byte = cursor.get('resume_byte', 0)
            with open(full_path, 'rb') as f:
                f.seek(resume_byte)
                new_bytes = f.read()
            # W-75 修⑤：硬编码 utf-8 ⇒ 走 sniff（gb18030 等卷不乱码）
            # W-75 fix ⑤: hard-coded utf-8 ⇒ go through sniff (gb18030 and other volumes are not garbled)
            from safeio import sniff_bytes
            new_text, _enc, _why = sniff_bytes(new_bytes)
            n_new = new_text.count('\n\n') + (1 if new_text and not new_text.endswith('\n\n') else 0)
            _audit('unread', agent_id, 'vol=%s resume_byte=%d → %d new bytes' % (vol, resume_byte, len(new_bytes)))
            return _tool_ok('未读 %d 条（%d 字节）·resume_byte=%d\n\n%s' % (n_new, len(new_bytes), resume_byte, new_text))

        if name == 'daybook_mark_read':
            # F2 已读未读：推进游标到卷末尾
            # F2 read/unread: advance the cursor to the end of the volume
            # W-75 修④：先验签后取卷名
            # W-75 fix ④: verify the signature before fetching the volume name
            payload = 'read:' + args.get('volume', '')
            _verify_agent(agent_id, signature, payload, force=True)
            vol = _safe_vol(args['volume'])
            conf = _load_conf()
            vol_path = conf.get('volumes', {}).get(vol)
            if not vol_path:
                raise ValueError('卷 %r 不在 daybook.conf 卷表' % vol)
            full_path = vol_path if os.path.isabs(vol_path) else os.path.join(_root(), vol_path)
            size = os.path.getsize(full_path)
            _write_cursor(agent_id, vol, size)
            _audit('mark_read', agent_id, 'vol=%s → resume_byte=%d' % (vol, size))
            return _tool_ok('已读推进到 %s 末尾（resume_byte=%d）' % (vol, size))

        if name == 'daybook_heartbeat':
            # F3 在线感知：append 一条 [心跳] 条目到 心跳卷.txt
            # F3 presence sensing: append one [心跳] entry to 心跳卷.txt
            ts = int(args.get('ts', 0))
            if abs(time.time() - ts) > 60:
                raise ValueError('心跳时间戳越窗（当前 %.0f·收到 %d·允许 ±60s）' % (time.time(), ts))
            payload = 'heartbeat:%d' % ts
            _verify_agent(agent_id, signature, payload, force=True)
            load = args.get('load', '')
            hb_vol = os.path.join(_root(), '心跳卷.txt')
            msg = 'alive' + ('｜负载=%s' % load if load else '')
            rc = _dba.append_one(hb_vol, '心跳', agent_id, msg, author=agent_id)
            if rc != 0:
                raise RuntimeError('heartbeat append_one rc=%d' % rc)
            _audit('heartbeat', agent_id, 'load=%s' % load)
            return _tool_ok('heartbeat appended for %s' % agent_id)

        if name == 'daybook_alive':
            # F3 在线感知：查心跳卷最后一条时间·在 timeout 秒内即在线
            # F3 presence sensing: check the last timestamp in the heartbeat volume · online if within `timeout` seconds
            aid = args['agent_id']
            timeout = int(args.get('timeout', 120))
            hb_vol = os.path.join(_root(), '心跳卷.txt')
            if not os.path.exists(hb_vol):
                _audit('alive', agent_id, 'agent=%s → 心跳卷不存在' % aid)
                return _tool_ok('offline（心跳卷不存在）')
            # 扫心跳卷·找该 agent 最后一条 [心跳]
            # scan the heartbeat volume · find this agent's last [心跳] entry
            last_ts = None
            import re as _re
            _aid_pat = _re.compile(r'^\[[^\]]+\] \[心跳\] \[%s\] ' % _re.escape(aid))
            import mcp_resources as _mr
            _hb_text, _enc, _why = _mr.read_vol(hb_vol)
            for line in _hb_text.split('\n'):
                if _aid_pat.match(line):
                        # W-75 修⑥：解析行首时间·秒级（心跳已改秒级格式）
                        # W-75 fix ⑥: parse the leading timestamp · second-level (heartbeats have moved to a second-level format)
                        if line.startswith('['):
                            end = line.find(']')
                            if end > 0:
                                ts_str = line[1:end]
                                try:
                                    last_ts = time.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                                except ValueError:
                                    try:  # 兼容旧分钟级条目
                                          # compatible with old minute-level entries
                                        last_ts = time.strptime(ts_str, '%Y-%m-%d %H:%M')
                                    except ValueError:
                                        pass
            if last_ts is None:
                _audit('alive', agent_id, 'agent=%s → 无心跳记录' % aid)
                return _tool_ok('offline（无心跳记录）')
            now_ts = time.time()
            hb_epoch = time.mktime(last_ts)
            age = int(now_ts - hb_epoch)
            status = 'online' if age <= timeout else 'offline（超时 %d 秒）' % age
            _audit('alive', agent_id, 'agent=%s age=%d → %s' % (aid, age, status))
            return _tool_ok('%s·%s' % (aid, status))

        if name == 'daybook_index':
            # P1-1 写工具验签：agent_id+signature 验 "reindex:<ts>"
            # P1-1 write-tool signature verification: verify "reindex:<ts>" with agent_id+signature
            ts = int(args.get('ts', 0))
            if abs(time.time() - ts) > 60:
                raise ValueError('index 时间戳越窗（当前 %.0f·收到 %d·允许 ±60s）' % (time.time(), ts))
            _verify_agent(agent_id, signature, 'reindex:%d' % ts)
            conf = _load_conf()
            per, total, _rep = _db.build(conf, _root())
            summary = '索引已重建：' + '｜'.join('%s %d' % (k, v) for k, v in per.items()) + '｜合计 %d 条' % total
            _audit('index', agent_id, '→ %d 条' % total)
            return _tool_ok(summary)

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

        if name == 'cross_ref_make':
            from cross_ref import CrossRef
            cr = CrossRef(root=_root())
            vol = _safe_vol(args['volume'])
            ref = cr.make_ref(vol, int(args['lineno']))
            _audit('cross_ref_make', agent_id, '→ %s' % ref)
            return _tool_ok(ref)

        if name == 'cross_ref_verify':
            from cross_ref import CrossRef
            cr = CrossRef(root=_root())
            ok = cr.verify_ref(args['ref'])
            _audit('cross_ref_verify', agent_id, 'ref=%s → %s' % (args['ref'][:60], ok))
            return _tool_ok('true' if ok else 'false')

        if name == 'daybook_multi_query':
            # v3.1 四库式层级下钻（只读·不需要验签）
            # v3.1 four-library-style hierarchical drilling (read-only · no signature verification needed)
            out = _multi_query(args)
            _audit('multi_query', agent_id,
                   'vol=%s level=%s → %s' % (args.get('volume', ''), args.get('level', 'entry'),
                                             out.split('\n')[0][:80]))
            return _tool_ok(out)

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
