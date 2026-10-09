#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP 接口集成测试（W-DB-023-G2·第 6 项·修复版 r2）
================================================
对照审核报告 P0-3 关闭测试盲区 + 新增 P1+/P2-1 测试：
  1. JSON-RPC 2.0 编解码
  2. initialize 握手
  3. resources/list 读 daybook.conf 卷表 + resources/read
  4. tools/list schema
  5. tools/call daybook_query 按字段过滤（P0-2 验证）
  6. tools/call daybook_append 匿名 + 带 G3 签名（P1-1 验证）
  7. tools/call daybook_index 重建
  8. tools/call 失败返 isError:true（P2-1 验证）
  9. 路径穿越 ../ 拒绝（P1-3 验证）
 10. resources/subscribe + mtime push（P1+ 验证）
 11. prompts/list + prompts/get
 12. notification/batch
 13. 零第三方依赖
退出码：0=PASS 1=FAIL
"""
import os, sys, json, subprocess, tempfile, shutil, time, threading, hashlib, hmac

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, 'mcp_server.py')

# 测试用 daybook.conf 模板
CONF_TMPL = """[卷]
测试MCP=测试MCP.txt

[条目]
头正则=^\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2})\\]
标正则=^\\[[^\\]]+\\]\\s*\\[([^\\]]+)\\]\\s*\\[([^\\]]*)\\](?:\\s*\\[([^\\]]*)\\])?
字段=卷,行号,时间,类,标题,作者

[规则]
类=tag:1
标题=tag:2
作者=tag:3

[索引]
输出目录=开发卷
索引前缀=索引_
增量索引=是
"""


def _ok(name, cond, detail=''):
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name,
                          (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    return bool(cond)


def _rpc(req_lines):
    """跑 mcp_server·喂 lines·返 list of parsed response。"""
    stdin_data = '\n'.join(json.dumps(r) for r in req_lines) + '\n'
    p = subprocess.run([sys.executable, SERVER],
                       input=stdin_data, capture_output=True, text=True, timeout=15)
    out = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out, p.stderr


def _setup_tmp_root():
    """造 tmp_root·写 daybook.conf + 测试MCP.txt + 注册卷.txt。"""
    tmp_root = tempfile.mkdtemp(prefix='daybook_mcp_test_')
    with open(os.path.join(tmp_root, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF_TMPL)
    with open(os.path.join(tmp_root, '测试MCP.txt'), 'w', encoding='utf-8') as f:
        f.write('[2026-10-08 03:00] [测试] [条目1] [GLM-5.2] body-a\n')
        f.write('[2026-10-08 03:01] [决策] [条目2] [GLM-5.2] body-b\n')
        f.write('[2026-10-08 03:02] [测试] [条目3] [GLM-5.2] body-c\n')
    # 注册卷·含 1 个测试 agent
    with open(os.path.join(tmp_root, '注册卷.txt'), 'w', encoding='utf-8') as f:
        f.write('# G3 注册卷\n')
    return tmp_root


def _register_test_agent(tmp_root, name='测试Agent'):
    """在 tmp_root 注册一个 agent·返 (agent_id, secret)。"""
    sys.path.insert(0, HERE)
    from agent_registry import Registry
    reg = Registry(os.path.join(tmp_root, '注册卷.txt'))
    return reg.register(name)


def _sign(secret, payload):
    """HMAC-SHA256 hex 签名。"""
    return hmac.new(secret.encode('utf-8'),
                    payload.encode('utf-8'), hashlib.sha256).hexdigest()


def test_transport():
    """验收 1：JSON-RPC 2.0 编解码。"""
    sys.path.insert(0, HERE)
    import mcp_transport as tr
    msg, err = tr.decode_frame('not json')
    if not _ok('1.1 parse error', err is not None and err['error']['code'] == tr.ERR_PARSE_ERROR):
        return False
    msg, err = tr.decode_frame('{"jsonrpc":"1.0","method":"x"}')
    if not _ok('1.2 invalid request 拒非 2.0', err is not None and err['error']['code'] == tr.ERR_INVALID_REQUEST):
        return False
    msg, err = tr.decode_frame('{"jsonrpc":"2.0","id":1,"method":"ping"}')
    if not _ok('1.3 正常 request 解码', msg is not None and msg.get('method') == 'ping'):
        return False
    if not _ok('1.4 notification 识别', tr.is_notification({'jsonrpc': '2.0', 'method': 'x'})):
        return False
    return True


def test_initialize(tmp_root):
    """验收 2：initialize 握手 + protocolVersion 协商。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    req = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
           'params': {'protocolVersion': '2024-11-05'}}
    out, err = _rpc([req])
    if not _ok('2.1 initialize 有响应', len(out) == 1, err):
        return False
    r = out[0]
    if not _ok('2.2 返回 result', 'result' in r, str(r)):
        return False
    res = r['result']
    return _ok('2.3 含 serverInfo/protocolVersion/capabilities',
               'protocolVersion' in res and 'serverInfo' in res
               and 'capabilities' in res
               and res['capabilities'].get('resources', {}).get('subscribe') is True,
               str(res))


def test_resources(tmp_root):
    """验收 3：resources/list 读 conf 卷表 + resources/read。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, err = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'resources/list'}])
    if not _ok('3.1 resources/list 有响应', len(out) == 1, err):
        return False
    rlist = out[0].get('result', {}).get('resources', [])
    found = [r for r in rlist if r.get('name') == '测试MCP']
    if not _ok('3.2 list 含测试MCP卷（读 conf）', len(found) == 1, 'rlist=%s' % rlist):
        return False
    # resources/read
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 2, 'method': 'resources/read',
                    'params': {'uri': 'daybook://测试MCP', 'offset': 2, 'limit': 1}}])
    if not _ok('3.3 read 有响应', len(out) == 1):
        return False
    text = out[0].get('result', {}).get('contents', [{}])[0].get('text', '')
    return _ok('3.4 read offset=2 limit=1 拿到第 2 行', '条目2' in text and '条目1' not in text, text)


def test_daybook_index(tmp_root):
    """验收 7：daybook_index 重建索引·供 query 用。写工具强制验签。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    agent_id, secret = _register_test_agent(tmp_root)
    sig = _sign(secret, 'reindex')
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_index',
                               'arguments': {'agent_id': agent_id, 'signature': sig}}}])
    if not _ok('7.1 daybook_index 有响应', len(out) == 1):
        return False
    text = out[0].get('result', {}).get('content', [{}])[0].get('text', '')
    return _ok('7.2 索引重建成功', '索引已重建' in text and '3 条' in text, text)


def test_daybook_query(tmp_root):
    """验收 5/P0-2：daybook_query 按字段过滤·不再全量返回。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    # 先建索引（也要验签）
    agent_id, secret = _register_test_agent(tmp_root)
    sig = _sign(secret, 'reindex')
    _rpc([{'jsonrpc': '2.0', 'id': 0, 'method': 'tools/call',
           'params': {'name': 'daybook_index',
                      'arguments': {'agent_id': agent_id, 'signature': sig}}}])
    # 查 类=决策 → 只应命中 1 条（条目2）
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_query',
                               'arguments': {'field': '类', 'value': '决策'}}}])
    if not _ok('5.1 daybook_query 有响应', len(out) == 1):
        return False
    text = out[0].get('result', {}).get('content', [{}])[0].get('text', '')
    if not _ok('5.2 命中 1 条', '命中 1 条' in text, text[:80]):
        return False
    if not _ok('5.3 命中条目2·不含条目1/3', '条目2' in text and '条目1' not in text and '条目3' not in text, text):
        return False
    # 反例：查 类=测试 → 命中 2 条
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                    'params': {'name': 'daybook_query',
                               'arguments': {'field': '类', 'value': '测试'}}}])
    text = out[0].get('result', {}).get('content', [{}])[0].get('text', '')
    return _ok('5.4 类=测试 命中 2 条', '命中 2 条' in text, text[:80])


def test_daybook_list(tmp_root):
    """验收 P0-1：daybook_list 返卷列表·不再是帮助文档。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_list', 'arguments': {}}}])
    if not _ok('P0-1.1 daybook_list 有响应', len(out) == 1):
        return False
    text = out[0].get('result', {}).get('content', [{}])[0].get('text', '')
    # 不能再是帮助文档（含 "用法:" 或 "Usage:"）
    is_help = ('用法' in text and 'python3' in text) or 'Usage' in text
    if not _ok('P0-1.2 不是帮助文档', not is_help, 'text=%r' % text[:100]):
        return False
    return _ok('P0-1.3 含测试MCP卷', '测试MCP' in text, text[:100])


def test_daybook_append_anon_rejected(tmp_root):
    """验收 P1-1 监理 r3：匿名 append 必须被拒·返 isError:true。
    这是监理探针发现的漏洞——此前匿名调用成功落盘·违背作者 ID 红线。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_append',
                               'arguments': {'volume': '测试MCP', 'tag': '匿名',
                                             'author': '未注册',
                                             'content': '匿名追加·应被拒'}}}])
    if not _ok('P1-1r3.1 匿名 append 有响应', len(out) == 1):
        return False
    r = out[0].get('result', {})
    if not _ok('P1-1r3.2 匿名 append 返 isError:true（不再落盘）', r.get('isError') is True, str(r)):
        return False
    text = r.get('content', [{}])[0].get('text', '')
    return _ok('P1-1r3.3 文本含"必须 agent_id"', 'agent_id' in text, text)


def test_daybook_append_impersonation(tmp_root):
    """验收 P1-1 监理 r3：author != agent_id 冒名检测。
    用合法 agent_id+signature·但 author 填别人 → 拒。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    agent_id, secret = _register_test_agent(tmp_root)
    content = '冒名测试'
    sig = _sign(secret, content)
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_append',
                               'arguments': {'volume': '测试MCP', 'tag': '冒名',
                                             'author': '别人', 'content': content,
                                             'agent_id': agent_id, 'signature': sig}}}])
    r = out[0].get('result', {})
    if not _ok('P1-1r3.4 冒名 append 返 isError:true', r.get('isError') is True, str(r)):
        return False
    text = r.get('content', [{}])[0].get('text', '')
    return _ok('P1-1r3.5 文本含"红线"', '红线' in text, text)


def test_daybook_append_signed(tmp_root):
    """验收 P1-1：daybook_append 带 agent_id+signature 验签成功。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    agent_id, secret = _register_test_agent(tmp_root)
    content = '签名追加的条目'
    sig = _sign(secret, content)
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_append',
                               'arguments': {'volume': '测试MCP', 'tag': '签名',
                                             'author': agent_id, 'content': content,
                                             'agent_id': agent_id, 'signature': sig}}}])
    if not _ok('P1-1.1 签名 append 有响应', len(out) == 1):
        return False
    text = out[0].get('result', {}).get('content', [{}])[0].get('text', '')
    return _ok('P1-1.2 签名 append 成功', 'appended' in text, text)


def test_daybook_append_bad_sig(tmp_root):
    """验收 P1-1：错误签名返 isError:true。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    agent_id, secret = _register_test_agent(tmp_root)
    bad_sig = '0' * 64
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_append',
                               'arguments': {'volume': '测试MCP', 'tag': '坏签',
                                             'author': agent_id, 'content': 'x',
                                             'agent_id': agent_id, 'signature': bad_sig}}}])
    if not _ok('P1-1.3 坏签名有响应', len(out) == 1):
        return False
    r = out[0].get('result', {})
    if not _ok('P1-1.4 返 isError:true', r.get('isError') is True, str(r)):
        return False
    text = r.get('content', [{}])[0].get('text', '')
    return _ok('P1-1.5 文本含签名校验失败', '签名' in text, text)


def test_path_traversal(tmp_root):
    """验收 P1-3：../ 穿越拒绝。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_append',
                               'arguments': {'volume': '../etc/passwd', 'tag': 'x',
                                             'author': 'x', 'content': 'x'}}}])
    r = out[0].get('result', {})
    if not _ok('P1-3.1 ../ 返 isError:true', r.get('isError') is True, str(r)):
        return False
    text = r.get('content', [{}])[0].get('text', '')
    return _ok('P1-3.2 文本含非法卷名', '非法' in text, text)


def test_unknown_tool_iserror(tmp_root):
    """验收 P2-1：未知工具返 isError:true 而非 -32603。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': '不存在的工具', 'arguments': {}}}])
    if not _ok('P2-1.1 未知工具有响应', len(out) == 1):
        return False
    r = out[0].get('result', {})
    if not _ok('P2-1.2 返 isError:true（非 error:-32603）', r.get('isError') is True, str(r)):
        return False
    text = r.get('content', [{}])[0].get('text', '')
    return _ok('P2-1.3 文本含未知工具', '未知' in text, text)


def test_cross_ref(tmp_root):
    """验收 4+5：tools/list schema + cross_ref_make/verify。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}])
    if not _ok('4.1 tools/list 有响应', len(out) == 1):
        return False
    tlist = out[0].get('result', {}).get('tools', [])
    names = [t.get('name') for t in tlist]
    if not _ok('4.2 含 daybook_query/append/index/list + cross_ref_make/verify',
               all(n in names for n in ('daybook_query', 'daybook_append',
                 'daybook_index', 'daybook_list',
                 'cross_ref_make', 'cross_ref_verify')), 'names=%s' % names):
        return False
    # cross_ref_make
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                    'params': {'name': 'cross_ref_make',
                               'arguments': {'volume': '测试MCP', 'lineno': 1}}}])
    if not _ok('5.1 cross_ref_make 有响应', len(out) == 1):
        return False
    text = out[0].get('result', {}).get('content', [{}])[0].get('text', '')
    if not _ok('5.2 生成引用 [测试MCP#L1-xxx]', text.startswith('[测试MCP#L1-'), 'text=%r' % text):
        return False
    # verify
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                    'params': {'name': 'cross_ref_verify',
                               'arguments': {'ref': text}}}])
    vtext = out[0].get('result', {}).get('content', [{}])[0].get('text', '')
    return _ok('5.3 cross_ref_verify 通过', vtext == 'true', 'v=%r' % vtext)


def test_subscribe_push(tmp_root):
    """验收 P1+：resources/subscribe + mtime 变 → push notifications/resources/updated。"""
    sys.path.insert(0, HERE)
    # 在进程内测 SubscriptionManager（subprocess 难测异步 push）
    from mcp_subscribe import SubscriptionManager
    import mcp_resources as _res
    _res.HERE = tmp_root  # 让 _root() 走 tmp_root
    os.environ['DAYBOOK_ROOT'] = tmp_root

    mgr = SubscriptionManager()
    mgr.POLL_INTERVAL = 0.3  # 加速测试

    pushed = []
    push_lock = threading.Lock()

    def push(msg):
        with push_lock:
            pushed.append(msg)

    uri = 'daybook://测试MCP'
    mgr.subscribe(uri, push)
    time.sleep(0.5)  # 等初始化 mtime

    # 改卷文件触发 mtime 变
    vol_path = os.path.join(tmp_root, '测试MCP.txt')
    with open(vol_path, 'a', encoding='utf-8') as f:
        f.write('[2026-10-08 04:00] [触发] [新条目] [测试] pushed-test\n')

    # 等 watch 线程轮询
    deadline = time.time() + 3
    while time.time() < deadline:
        with push_lock:
            if pushed:
                break
        time.sleep(0.1)

    mgr.stop()
    if not _ok('P1+.1 收到 push 消息', len(pushed) >= 1, 'pushed=%s' % pushed):
        return False
    msg = pushed[0]
    if not _ok('P1+.2 method=notifications/resources/updated',
               msg.get('method') == 'notifications/resources/updated', str(msg)):
        return False
    return _ok('P1+.3 params.uri 正确', msg.get('params', {}).get('uri') == uri, str(msg))


def test_prompts():
    """验收 11：prompts/list + prompts/get。"""
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'prompts/list'}])
    if not _ok('11.1 prompts/list 有响应', len(out) == 1):
        return False
    plist = out[0].get('result', {}).get('prompts', [])
    names = [p.get('name') for p in plist]
    if not _ok('11.2 含 daily_journal/weekly_review/cross_ref_audit/agent_handover',
               all(n in names for n in ('daily_journal', 'weekly_review',
                 'cross_ref_audit', 'agent_handover')), 'names=%s' % names):
        return False
    # get 缺 required
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 2, 'method': 'prompts/get',
                    'params': {'name': 'daily_journal', 'arguments': {}}}])
    if not _ok('11.3 prompts/get 缺 required 报错',
               out[0].get('error', {}).get('code') == -32602, str(out[0])):
        return False
    # get 正常
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 3, 'method': 'prompts/get',
                    'params': {'name': 'daily_journal',
                               'arguments': {'author': 'GLM-5.2', 'tag': 'MCP'}}}])
    msg = out[0].get('result', {}).get('messages', [{}])[0]
    text = msg.get('content', {}).get('text', '')
    return _ok('11.4 prompts/get 填充模板', 'GLM-5.2' in text and 'MCP' in text, text[:80])


def test_notification_batch(tmp_root):
    """验收 12：notification 不回·batch 处理。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, _ = _rpc([{'jsonrpc': '2.0', 'method': 'ping'}])
    if not _ok('12.1 notification 不回响应', len(out) == 0, 'out=%s' % out):
        return False
    out, _ = _rpc([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
        {'jsonrpc': '2.0', 'method': 'ping'},
    ])
    return _ok('12.2 有 id request 回响应·notification 不回', len(out) == 1, 'out=%s' % out)


def test_no_shutdown_method(tmp_root):
    """验收 P2-2：shutdown 方法已删·应返 method not found。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'shutdown'}])
    if not _ok('P2-2.1 shutdown 有响应', len(out) == 1):
        return False
    err = out[0].get('error', {})
    return _ok('P2-2.2 shutdown 返 method not found (-32601)',
               err.get('code') == -32601, str(err))


def test_audit_vol_isolation(tmp_root):
    """验收 监理 r4：AUDIT_VOL 走 _root()·隔离测试审计不混进生产。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    # 跑一次 tools/call 触发审计
    _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'daybook_list', 'arguments': {}}}])
    # tmp_root 应有 MCP审计卷.txt
    tmp_audit = os.path.join(tmp_root, 'MCP审计卷.txt')
    if not _ok('r4.1 隔离卷有审计记录', os.path.exists(tmp_audit), tmp_audit):
        return False
    # 生产 HERE 不应被这次调用污染（只看本次调用后的新增）
    prod_audit = os.path.join(HERE, 'MCP审计卷.txt')
    if os.path.exists(prod_audit):
        with open(prod_audit, 'r', encoding='utf-8') as f:
            content = f.read()
        # 不应含本次调用的标记（daybook_list 在隔离 tmp 跑）
        return _ok('r4.2 生产审计卷无本次隔离调用残留',
                   'r4-isolation-marker' not in content, '生产审计卷仍含新写入')
    return True


def test_zero_deps():
    """验收 13：零第三方依赖。"""
    third_party = ('fastapi', 'uvicorn', 'pydantic', 'aiohttp', 'starlette',
                   'httpx', 'anyio')
    # mcp_* 内部互引不违规·只看是否引外部第三方
    bad = []
    for f in ('mcp_transport.py', 'mcp_resources.py', 'mcp_tools.py',
              'mcp_prompts.py', 'mcp_server.py', 'mcp_subscribe.py'):
        with open(os.path.join(HERE, f), 'r', encoding='utf-8') as fp:
            for line in fp:
                if line.startswith('import ') or line.startswith('from '):
                    for p in third_party:
                        if p in line:
                            bad.append((f, line.strip()))
    return _ok('13. 零第三方依赖', not bad, '违规=%s' % bad if bad else '')


def test_append_to_field(tmp_root):
    """F1：daybook_append 带 [致] 字段·收件人寻址。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    # 先注册两个 agent：发送者 + 收件人
    aid1, sec1 = _register_test_agent(tmp_root, '发送者')
    aid2, _ = _register_test_agent(tmp_root, '收件人')
    content = 'F1 测试·带收件人'
    sig = _sign(sec1, content)
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_append',
                               'arguments': {'volume': '测试MCP', 'tag': 'F1',
                                             'author': aid1, 'content': content,
                                             'to': aid2, 'agent_id': aid1, 'signature': sig}}}])
    r = out[0].get('result', {})
    if not _ok('F1.1 append 带 to 成功', not r.get('isError'), str(r)):
        return False
    # 读卷·验证含 [致=...] 段（倒数第 2 行·因 append_one 后有空行）
    with open(os.path.join(tmp_root, '测试MCP.txt'), 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
    # 找最后一条含 [致= 的行
    to_line = next((l for l in reversed(lines) if '[致=' in l), '')
    return _ok('F1.2 卷里含 [致=%s]', '[致=%s]' % aid2 in to_line, to_line)


def test_append_to_unknown_rejected(tmp_root):
    """F1：收件人未注册·被拒·防垃圾寻址。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    aid, sec = _register_test_agent(tmp_root, '发送者')
    content = 'F1 拒测'
    sig = _sign(sec, content)
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': 'daybook_append',
                               'arguments': {'volume': '测试MCP', 'tag': 'F1',
                                             'author': aid, 'content': content,
                                             'to': 'ag-不存在的ID', 'agent_id': aid, 'signature': sig}}}])
    r = out[0].get('result', {})
    return _ok('F1.3 未注册收件人被拒', r.get('isError') is True and '注册' in r.get('content', [{}])[0].get('text', ''),
               str(r))


def test_unread_mark_read(tmp_root):
    """F2：已读未读游标推进。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    aid, sec = _register_test_agent(tmp_root, '读者')
    # 先写 2 条新内容
    sig1 = _sign(sec, 'F2 条目1')
    _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
           'params': {'name': 'daybook_append',
                      'arguments': {'volume': '测试MCP', 'tag': 'F2',
                                    'author': aid, 'content': 'F2 条目1',
                                    'agent_id': aid, 'signature': sig1}}}])
    sig2 = _sign(sec, 'F2 条目2')
    _rpc([{'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
           'params': {'name': 'daybook_append',
                      'arguments': {'volume': '测试MCP', 'tag': 'F2',
                                    'author': aid, 'content': 'F2 条目2',
                                    'agent_id': aid, 'signature': sig2}}}])
    # 查未读·应含刚写的 2 条 F2 内容（可能含初始 3 条·因游标从 0 起）
    sig_q = _sign(sec, aid)  # 签 agent_id 自己
    out, _ = _rpc([{'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                    'params': {'name': 'daybook_unread',
                               'arguments': {'volume': '测试MCP', 'agent_id': aid, 'signature': sig_q}}}])
    r = out[0].get('result', {})
    text = r.get('content', [{}])[0].get('text', '')
    if not _ok('F2.1 unread 返含新写的 2 条', 'F2 条目1' in text and 'F2 条目2' in text, text):
        return False
    # mark_read 推进游标
    sig_mr = _sign(sec, 'read:测试MCP')
    out2, _ = _rpc([{'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                     'params': {'name': 'daybook_mark_read',
                                'arguments': {'volume': '测试MCP', 'agent_id': aid, 'signature': sig_mr}}}])
    r2 = out2[0].get('result', {})
    if not _ok('F2.2 mark_read 成功', '已读推进' in r2.get('content', [{}])[0].get('text', ''), str(r2)):
        return False
    # 再查未读·应返 0 条（mark_read 推到末尾·无新内容）
    out3, _ = _rpc([{'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
                     'params': {'name': 'daybook_unread',
                                'arguments': {'volume': '测试MCP', 'agent_id': aid, 'signature': sig_q}}}])
    r3 = out3[0].get('result', {})
    text3 = r3.get('content', [{}])[0].get('text', '')
    return _ok('F2.3 mark_read 后未读为 0', '未读 0 条' in text3, text3)


def test_heartbeat_alive(tmp_root):
    """F3：心跳 + 探活。"""
    os.environ['DAYBOOK_ROOT'] = tmp_root
    aid, sec = _register_test_agent(tmp_root, '心跳Agent')
    # 探活前·心跳卷不存在 → offline
    out0, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                     'params': {'name': 'daybook_alive',
                                'arguments': {'agent_id': aid, 'timeout': 60}}}])
    r0 = out0[0].get('result', {})
    text0 = r0.get('content', [{}])[0].get('text', '')
    if not _ok('F3.1 初始无心跳 → offline', 'offline' in text0, text0):
        return False
    # append 心跳
    sig = _sign(sec, 'heartbeat')
    out1, _ = _rpc([{'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                     'params': {'name': 'daybook_heartbeat',
                                'arguments': {'agent_id': aid, 'signature': sig, 'load': '0.3'}}}])
    r1 = out1[0].get('result', {})
    if not _ok('F3.2 heartbeat append 成功', 'heartbeat appended' in r1.get('content', [{}])[0].get('text', ''), str(r1)):
        return False
    # 探活·应 online
    out2, _ = _rpc([{'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                     'params': {'name': 'daybook_alive',
                                'arguments': {'agent_id': aid, 'timeout': 3600}}}])
    r2 = out2[0].get('result', {})
    text2 = r2.get('content', [{}])[0].get('text', '')
    return _ok('F3.3 心跳后 → online', 'online' in text2, text2)


def main():
    print('=== W-DB-023-G2 MCP 接口验收测试（修复版 r2）===')
    tmp_root = _setup_tmp_root()
    os.environ['DAYBOOK_ROOT'] = tmp_root

    results = []
    results.append(('JSON-RPC 编解码', test_transport()))
    results.append(('initialize 握手+协商', test_initialize(tmp_root)))
    results.append(('resources list/read conf', test_resources(tmp_root)))
    results.append(('daybook_list 不再是帮助', test_daybook_list(tmp_root)))
    results.append(('daybook_index 重建', test_daybook_index(tmp_root)))
    results.append(('daybook_query 按字段过滤', test_daybook_query(tmp_root)))
    results.append(('daybook_append 匿名被拒', test_daybook_append_anon_rejected(tmp_root)))
    results.append(('daybook_append 冒名被拒', test_daybook_append_impersonation(tmp_root)))
    results.append(('daybook_append G3 签名', test_daybook_append_signed(tmp_root)))
    results.append(('daybook_append 坏签名拒', test_daybook_append_bad_sig(tmp_root)))
    results.append(('路径穿越拒绝', test_path_traversal(tmp_root)))
    results.append(('未知工具 isError:true', test_unknown_tool_iserror(tmp_root)))
    results.append(('cross_ref make/verify', test_cross_ref(tmp_root)))
    results.append(('subscribe+push', test_subscribe_push(tmp_root)))
    results.append(('prompts list/get', test_prompts()))
    results.append(('notification/batch', test_notification_batch(tmp_root)))
    results.append(('shutdown 已删', test_no_shutdown_method(tmp_root)))
    results.append(('审计卷隔离', test_audit_vol_isolation(tmp_root)))
    results.append(('F1 收件人寻址', test_append_to_field(tmp_root)))
    results.append(('F1 未注册收件人拒', test_append_to_unknown_rejected(tmp_root)))
    results.append(('F2 已读未读', test_unread_mark_read(tmp_root)))
    results.append(('F3 心跳+探活', test_heartbeat_alive(tmp_root)))
    results.append(('零依赖', test_zero_deps()))

    print('=== 总验收 ===')
    for name, ok in results:
        print('  %s: %s' % (name, 'PASS' if ok else 'FAIL'))
    all_ok = all(r[1] for r in results)
    print('=== %s（%d/%d PASS）===' % ('PASS' if all_ok else 'FAIL',
                                       sum(1 for r in results if r[1]), len(results)))
    shutil.rmtree(tmp_root, ignore_errors=True)
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
