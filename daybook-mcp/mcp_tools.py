#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Tools（W-DB-023-G2·第 3 项·修复版 r2）
================================================
对照审核报告 P0/P1/P2 修复：
- P0-1 daybook_list 不再 subprocess 调用不存在的 `daybook.py list`·直接读 conf[卷]
- P0-2 daybook_query 不再传 `pattern`·按 daybook.py 真实 key=value 语法构造 args
- P1-1 写工具（append/index）接受可选 agent_id+signature·调 G3 agent_registry 验签
- P1-2 tools/call 全记入卷（审计卷.txt append-only）
- P1-3 DAYBOOK_ROOT 隔离彻底·直接 import 不 subprocess·volume 路径校验防 ../
- P1-4 daybook_index 描述纠正为"重建全部卷索引"·不再误导单卷
- P2-1 tools/call 失败返 result{isError:true, content:[{type:text,text:errMsg}]}
        而非 -32603 internal error·让模型看见错误
- 零依赖：仅 Python 3 标准库
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import daybook as _db
import daybook_append as _dba
from agent_registry import Registry as _AgentRegistry

AUDIT_VOL_NAME = 'MCP审计卷.txt'


def _audit_vol():
    """审计卷路径·走 _root()·监理 r4 修复：隔离测试审计不再混进生产。"""
    return os.path.join(_root(), AUDIT_VOL_NAME)


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _root():
    return os.environ.get('DAYBOOK_ROOT') or HERE


def _audit(method, agent_id, detail, ok=True):
    """MCP 调用记入审计卷·append-only·白箱可审计（P1-2）。
    detail 含参数摘要与结果摘要·不含全量原文（防爆）。"""
    try:
        rec = '[%s] [MCP] [tools/%s] [agent=%s] [%s] %s\n' % (
            _now(), method, agent_id or '匿名',
            'OK' if ok else 'FAIL', detail)[:400]
        from safeio import atomic_append
        atomic_append(_audit_vol(), rec)
    except OSError:
        pass  # 审计失败不阻塞主流程


def _safe_vol(name):
    """volume 名防穿越（P1-3）。允许 [A-Za-z0-9_-] 与中文·拒绝 ../ 与绝对路径。"""
    if not name or '..' in name or '/' in name or '\\' in name or os.path.isabs(name):
        raise ValueError('非法卷名：%r' % name)
    return name


def _load_conf():
    """读 daybook.conf·root 按 _root()·生产同 HERE·测试可走 DAYBOOK_ROOT。"""
    conf_path = os.path.join(_root(), 'daybook.conf')
    return _db.load_conf(conf_path)


def _verify_agent(agent_id, signature, payload, force=True):
    """G3 身份校验（P1-1·监理 r3 修复）。
    - force=True（写工具）：必须 agent_id+signature·缺任一即抛·不允许匿名
    - force=False（查询·预留）：允许匿名
    验签失败抛 ValueError。"""
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
    """取 G3 注册表实例·root 隔离。"""
    return _AgentRegistry(os.path.join(_root(), '注册卷.txt'))


def _read_cursor(agent_id, vol):
    """F2 已读未读：读某 agent 对某卷的游标。"""
    import json
    cp = os.path.join(_root(), '.已读_%s_%s.json' % (agent_id, vol))
    if os.path.exists(cp):
        with open(cp, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'resume_byte': 0}


def _write_cursor(agent_id, vol, resume_byte):
    """F2 已读未读：写游标。"""
    import json
    cp = os.path.join(_root(), '.已读_%s_%s.json' % (agent_id, vol))
    cur = {'resume_byte': resume_byte, 'mtime': time.time()}
    with open(cp, 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False)


# ── 工具 schema（JSON Schema 风格） ──
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
]


def list_tools():
    return TOOLS


def _tool_error(message):
    """P2-1·tools/call 失败返 result{isError:true, content:[...]} 而非 -32603。"""
    return {'isError': True, 'content': [{'type': 'text', 'text': message}]}


def _tool_ok(text):
    return {'content': [{'type': 'text', 'text': text}]}


def call_tool(name, args, agent_id=None, signature=None):
    """执行工具·返回 result dict（成功 content·失败 isError:true）。
    agent_id/signature 可选·写工具必须验签（P1-1）。
    优先用显式 kwargs（来自 _meta）·缺则从 args 兜底（方便 LLM 客户端直填）。"""
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
            _verify_agent(agent_id, signature, args.get('content', ''), force=True)
            vol = _safe_vol(args['volume'])
            tag = args['tag']
            subtag = args.get('subtag', '') or '_'
            author = args['author']
            content = args['content']
            to = args.get('to')  # F1 收件人寻址·可空
            # 作者 ID 红线：author 必须等于 agent_id·防冒名
            if author != agent_id:
                raise ValueError('作者 ID 红线：author=%r 必须等于 agent_id=%r（防冒名）' % (author, agent_id))
            # F1 收件人寻址校验：to 里的每个 ID 必须是已注册 agent·防垃圾寻址
            if to:
                reg = _agent_reg()
                to_ids = [t.strip() for t in to.split(',') if t.strip()]
                for tid in to_ids:
                    if not reg.lookup(tid):
                        raise ValueError('收件人 %r 未在 G3 注册卷注册（防垃圾寻址）' % tid)
            # 解析卷路径·按 daybook.conf 卷表
            conf = _load_conf()
            vol_path = conf.get('卷', {}).get(vol)
            if not vol_path:
                raise ValueError('卷 %r 不在 daybook.conf 卷表' % vol)
            full_path = vol_path if os.path.isabs(vol_path) else os.path.join(_root(), vol_path)
            # 调 daybook_append.append_one 原子写·传 to
            rc = _dba.append_one(full_path, tag, subtag, content, author=author, to=to)
            if rc != 0:
                raise RuntimeError('append_one rc=%d' % rc)
            _audit('append', agent_id, 'vol=%s tag=%s to=%s → %s' % (vol, tag, to or '广播', full_path))
            return _tool_ok('appended to %s' % vol)

        if name == 'daybook_unread':
            # F2 已读未读：查 agent 对卷的未读条目
            # W-75 修④：先验签后取卷名
            ts = int(args.get('ts', 0))
            if abs(time.time() - ts) > 60:
                raise ValueError('unread 时间戳越窗（当前 %.0f·收到 %d·允许 ±60s）' % (time.time(), ts))
            payload = 'unread:%s:%d' % (agent_id, ts)
            _verify_agent(agent_id, signature, payload, force=True)  # 防任意查他人未读
            vol = _safe_vol(args['volume'])
            conf = _load_conf()
            vol_path = conf.get('卷', {}).get(vol)
            if not vol_path:
                raise ValueError('卷 %r 不在 daybook.conf 卷表' % vol)
            full_path = vol_path if os.path.isabs(vol_path) else os.path.join(_root(), vol_path)
            cursor = _read_cursor(agent_id, vol)
            resume_byte = cursor.get('resume_byte', 0)
            with open(full_path, 'rb') as f:
                f.seek(resume_byte)
                new_bytes = f.read()
            # W-75 修⑤：硬编码 utf-8 ⇒ 走 sniff（gb18030 等卷不乱码）
            from safeio import sniff_bytes
            new_text, _enc, _why = sniff_bytes(new_bytes)
            n_new = new_text.count('\n\n') + (1 if new_text and not new_text.endswith('\n\n') else 0)
            _audit('unread', agent_id, 'vol=%s resume_byte=%d → %d new bytes' % (vol, resume_byte, len(new_bytes)))
            return _tool_ok('未读 %d 条（%d 字节）·resume_byte=%d\n\n%s' % (n_new, len(new_bytes), resume_byte, new_text))

        if name == 'daybook_mark_read':
            # F2 已读未读：推进游标到卷末尾
            # W-75 修④：先验签后取卷名
            payload = 'read:' + args.get('volume', '')
            _verify_agent(agent_id, signature, payload, force=True)
            vol = _safe_vol(args['volume'])
            conf = _load_conf()
            vol_path = conf.get('卷', {}).get(vol)
            if not vol_path:
                raise ValueError('卷 %r 不在 daybook.conf 卷表' % vol)
            full_path = vol_path if os.path.isabs(vol_path) else os.path.join(_root(), vol_path)
            size = os.path.getsize(full_path)
            _write_cursor(agent_id, vol, size)
            _audit('mark_read', agent_id, 'vol=%s → resume_byte=%d' % (vol, size))
            return _tool_ok('已读推进到 %s 末尾（resume_byte=%d）' % (vol, size))

        if name == 'daybook_heartbeat':
            # F3 在线感知：append 一条 [心跳] 条目到 心跳卷.txt
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
            aid = args['agent_id']
            timeout = int(args.get('timeout', 120))
            hb_vol = os.path.join(_root(), '心跳卷.txt')
            if not os.path.exists(hb_vol):
                _audit('alive', agent_id, 'agent=%s → 心跳卷不存在' % aid)
                return _tool_ok('offline（心跳卷不存在）')
            # 扫心跳卷·找该 agent 最后一条 [心跳]
            last_ts = None
            import re as _re
            _aid_pat = _re.compile(r'^\[[^\]]+\] \[心跳\] \[%s\] ' % _re.escape(aid))
            import mcp_resources as _mr
            _hb_text, _enc, _why = _mr.read_vol(hb_vol)
            for line in _hb_text.split('\n'):
                if _aid_pat.match(line):
                        # W-75 修⑥：解析行首时间·秒级（心跳已改秒级格式）
                        if line.startswith('['):
                            end = line.find(']')
                            if end > 0:
                                ts_str = line[1:end]
                                try:
                                    last_ts = time.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                                except ValueError:
                                    try:  # 兼容旧分钟级条目
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
            vols = conf.get('卷', {})
            lines = ['daybook.conf 卷表（%d 卷）：' % len(vols)]
            for vname, vpath in vols.items():
                full = vpath if os.path.isabs(vpath) else os.path.join(_root(), vpath)
                if os.path.exists(full):
                    st = os.stat(full)
                    # W-75 修⑤：硬编码 utf-8 ⇒ 走 sniff（gb18030 等卷不乱码）
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

        # 未知工具
        _audit(name, agent_id, '未知工具', ok=False)
        return _tool_error('未知工具：%s' % name)

    except ValueError as e:
        # 参数错/验签失败/卷不存在·返 isError:true 让模型看见（P2-1）
        _audit(name, agent_id, 'FAIL: %s' % str(e)[:200], ok=False)
        return _tool_error('参数错：%s' % e)
    except Exception as e:
        _audit(name, agent_id, 'FAIL: %s: %s' % (type(e).__name__, str(e)[:200]), ok=False)
        return _tool_error('执行失败：%s: %s' % (type(e).__name__, e))
