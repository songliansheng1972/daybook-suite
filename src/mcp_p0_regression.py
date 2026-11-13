#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP P0 最小回归（只读模式 / cross_ref 秒级头 / 生产索引路径 / offset-limit）
MCP P0 minimal regression (read-only mode / second-level cross_ref head / production index path / offset-limit)
================================================
覆盖 / Covers：
  1. initialize
  2. tools/list（只读模式隐藏四个写工具）
  3. daybook_append / daybook_mark_read / daybook_heartbeat / daybook_index 只读被拒
  4. cross_ref 秒级条目头（[YYYY-MM-DD HH:MM:SS]）
  5. 生产索引路径：conf index.out_dir=索引 + multilevel.out_dir 空 ⇒ 索引/multilevel
  6. resources/read 的 offset/limit
  7. resources/subscribe 不存在即报错、存在才订阅
  8. 只读模式零写盘 + 密钥文件 0600 + 注册卷不落明文
  9. 根目录由 conf [index] root 解析（空/非空/无效/DAYBOOK_ROOT 覆盖）
  10. 启动路径零 __pycache__（不依赖外部环境变量）
  11. 空卷自检：启动与 resources/list 都向 stderr 告警
  12. cross_ref 编号前缀：带编号/旧无编号/跳号/编号重复/末条到文末（make 与 verify 双路径）
退出码：0=PASS 1=FAIL
Exit code: 0=PASS 1=FAIL
"""
import os, sys, json, subprocess, tempfile, shutil, time, hashlib, stat

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, 'mcp_server.py')

CONF = """[volumes]
测试=测试.txt

[entries]
head_regex=^(?:\\[#\\d+\\][ ]*)?\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}(?::\\d{2})?)\\]
tag_regex=^(?:\\[#\\d+\\][ ]*)?\\[\\d{4}[^\\]]*\\][ ]*\\[([^\\]]+)\\][ ]*\\[([^\\]]*)\\](?:[ ]*\\[([^\\]]*)\\])?
fields=volume,line,time,category,title,author

[rules]
category=tag:1
title=tag:2
author=tag:3

[index]
out_dir=索引
index_prefix=index_

[multilevel]
out_dir=
level2_field=category
"""

VOL = (
    '[2026-11-13 10:00:05] [测试] [秒级条目] [皮特] body-second\n'
    '[2026-11-13 10:01] [测试] [分钟级条目] [皮特] body-minute\n'
)

# 编号卷：带 [编号] 前缀 / 无编号旧条目 / 跳号 / 编号重复 / 末条到文末（无结尾换行）
# Numbered volume: [#N] prefix / legacy unnumbered / skipped number / duplicate number / last entry at EOF (no trailing newline)
NUM_VOL = (
    '[#83429] [2026-11-13 21:20] [编号] [跳号前] [皮特] body-1\n'
    '[#83431] [2026-11-13 21:21] [编号] [跳号后] [皮特] body-2\n'
    '[2026-11-13 21:22] [编号] [无编号旧条目] [皮特] body-3\n'
    '[#83431] [2026-11-13 21:23] [编号] [编号重复] [皮特] body-4\n'
    '[#83435] [2026-11-13 21:24] [编号] [末条] [皮特] body-5'
)


def _ok(name, cond, detail=''):
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name,
                          (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    return bool(cond)


def _rpc(req_lines, read_only=True, tmp_root=None):
    """跑 mcp_server·喂 lines·返 (responses, stderr, 是否零写盘)。
    Run mcp_server · feed lines · return (responses, stderr, zero_write)."""
    env = dict(os.environ)
    env['DAYBOOK_ROOT'] = tmp_root
    if read_only:
        env['MCP_READ_ONLY'] = '1'
    else:
        env.pop('MCP_READ_ONLY', None)
    before = _snapshot(tmp_root)
    stdin_data = '\n'.join(json.dumps(r) for r in req_lines) + '\n'
    p = subprocess.run([sys.executable, SERVER], input=stdin_data,
                       capture_output=True, text=True, timeout=20, env=env)
    after = _snapshot(tmp_root)
    out = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out, p.stderr, before == after


def _snapshot(root):
    """树快照：相对路径 → (大小, mtime_ns, sha256)。
    Tree snapshot: relative path → (size, mtime_ns, sha256)."""
    snap = {}
    for dp, dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            try:
                st = os.stat(p)
                h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
                snap[rel] = (st.st_size, st.st_mtime_ns, h)
            except OSError:
                snap[rel] = ('ERR', 0, '')
    return snap


def _setup():
    root = tempfile.mkdtemp(prefix='daybook_p0_')
    with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write(CONF)
    with open(os.path.join(root, '测试.txt'), 'w', encoding='utf-8') as f:
        f.write(VOL)
    # 生产形态：索引/index_测试.tsv + 索引/multilevel/测试_catalog.tsv
    idx = os.path.join(root, '索引')
    os.makedirs(os.path.join(idx, 'multilevel'))
    with open(os.path.join(idx, 'index_测试.tsv'), 'w', encoding='utf-8') as f:
        f.write('volume\tline\ttime\tcategory\ttitle\tauthor\n')
        f.write('测试\t1\t2026-11-13 10:00:05\t测试\t秒级条目\t皮特\n')
        f.write('测试\t2\t2026-11-13 10:01\t测试\t分钟级条目\t皮特\n')
    with open(os.path.join(idx, 'multilevel', '测试_catalog.tsv'), 'w', encoding='utf-8') as f:
        f.write('volume\tlevel2\tline\ttime\tcategory\tauthor\ttitle\n')
        f.write('测试\t测试\t1\t2026-11-13 10:00:05\t测试\t皮特\t秒级条目\n')
    return root


def test_initialize(t):
    out, err, zero = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                            'params': {'protocolVersion': '2024-11-05'}}],
                          tmp_root=t)
    if not _ok('1.1 initialize 有响应', len(out) == 1, err):
        return False
    res = out[0].get('result', {})
    return _ok('1.2 含 serverInfo/protocolVersion',
               'serverInfo' in res and 'protocolVersion' in res, str(res))


def test_tools_list_hides_write(t):
    out, err, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}], tmp_root=t)
    if not _ok('2.1 tools/list 有响应', len(out) == 1, err):
        return False
    names = [x.get('name') for x in out[0].get('result', {}).get('tools', [])]
    writes = ('daybook_append', 'daybook_mark_read', 'daybook_heartbeat', 'daybook_index')
    if not _ok('2.2 四个写工具已隐藏', not any(n in names for n in writes), 'names=%s' % names):
        return False
    return _ok('2.3 读工具仍在', 'daybook_query' in names and 'daybook_list' in names, 'names=%s' % names)


def test_write_tools_rejected(t):
    calls = [
        ('daybook_append', {'volume': '测试', 'tag': 'x', 'author': 'a', 'content': 'x',
                            'agent_id': 'a', 'signature': '0' * 64, 'ts': int(time.time())}),
        ('daybook_mark_read', {'volume': '测试', 'agent_id': 'a', 'signature': '0' * 64}),
        ('daybook_heartbeat', {'agent_id': 'a', 'signature': '0' * 64, 'ts': int(time.time())}),
        ('daybook_index', {'agent_id': 'a', 'signature': '0' * 64, 'ts': int(time.time())}),
    ]
    reqs = [{'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
             'params': {'name': n, 'arguments': a}} for i, (n, a) in enumerate(calls)]
    out, err, zero = _rpc(reqs, tmp_root=t)
    if not _ok('3.1 四个写工具都有响应', len(out) == len(calls), err):
        return False
    ok = True
    for name, resp in zip([c[0] for c in calls], out):
        r = resp.get('result', {})
        text = r.get('content', [{}])[0].get('text', '')
        ok = _ok('3.2 %s 被拒（isError+只读）' % name,
                 r.get('isError') is True and '只读模式' in text, text) and ok
    return ok


def test_cross_ref_seconds(t):
    out, err, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                         'params': {'name': 'cross_ref_make',
                                    'arguments': {'volume': '测试', 'lineno': 1}}}], tmp_root=t)
    if not _ok('4.1 cross_ref_make 有响应', len(out) == 1, err):
        return False
    r = out[0].get('result', {})
    text = r.get('content', [{}])[0].get('text', '')
    if not _ok('4.2 秒级条目头可生成引用', not r.get('isError')
               and text.startswith('[测试#L1-'), text):
        return False
    out2, _, _ = _rpc([{'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                        'params': {'name': 'cross_ref_verify',
                                   'arguments': {'ref': text}}}], tmp_root=t)
    v = out2[0].get('result', {}).get('content', [{}])[0].get('text', '')
    return _ok('4.3 引用可验', v == 'true', 'v=%r' % v)


def test_cross_ref_numbered():
    """13. 编号前缀：带编号/旧无编号/跳号/编号重复/末条到文末，make 与 verify 双路径。
    Numbered prefixes: numbered / legacy unnumbered / skipped number / duplicate number / last entry at EOF,
    covering both make and verify."""
    t = tempfile.mkdtemp(prefix='daybook_num_')
    try:
        conf = CONF.replace('测试=测试.txt', '编号=编号.txt')
        with open(os.path.join(t, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write(conf)
        with open(os.path.join(t, '编号.txt'), 'w', encoding='utf-8') as f:
            f.write(NUM_VOL)
        idx = os.path.join(t, '索引', 'multilevel')
        os.makedirs(idx)
        with open(os.path.join(idx, '编号_catalog.tsv'), 'w', encoding='utf-8') as f:
            f.write('volume\tlevel2\tline\ttime\tcategory\tauthor\ttitle\n')
            for ln, (tag, title) in enumerate(
                    [('归', '跳号前'), ('归', '跳号后'), ('归', '无编号旧条目'),
                     ('归', '编号重复'), ('归', '末条')], 1):
                f.write('编号\t归\t%d\t2026-11-13 21:2%d\t编号\t皮特\t%s\n' % (ln, ln, title))

        # 13.1-13.3 经 MCP：带编号、旧无编号都能生成并验签
        reqs = [{'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                 'params': {'name': 'cross_ref_make',
                            'arguments': {'volume': '编号', 'lineno': i}}}
                for i in (1, 3, 5)]
        out, err, _ = _rpc(reqs, tmp_root=t)
        if not _ok('13.1 三条 make 都有响应', len(out) == 3, err):
            return False
        texts = [o.get('result', {}).get('content', [{}])[0].get('text', '') for o in out]
        ok = _ok('13.2 带编号条目可生成引用', texts[0].startswith('[编号#L1-'), texts[0])
        ok = _ok('13.3 旧无编号条目可生成引用', texts[1].startswith('[编号#L3-'), texts[1]) and ok
        ok = _ok('13.4 末条可生成引用', texts[2].startswith('[编号#L5-'), texts[2]) and ok
        vreqs = [{'jsonrpc': '2.0', 'id': 10 + i, 'method': 'tools/call',
                  'params': {'name': 'cross_ref_verify', 'arguments': {'ref': x}}}
                 for i, x in enumerate(texts)]
        vout, verr, _ = _rpc(vreqs, tmp_root=t)
        vtexts = [o.get('result', {}).get('content', [{}])[0].get('text', '') for o in vout]
        ok = _ok('13.5 三条引用 verify 全 True', vtexts == ['true'] * 3, '%s %s' % (vtexts, verr)) and ok

        # 13.6 块边界：到下一个条目头为止（不并入后条）
        sys.path.insert(0, HERE)
        from cross_ref import CrossRef
        cr = CrossRef(root=t)
        r1 = cr.resolve('编号', 1)
        ok = _ok('13.6 块只到下一条目头', bool(r1) and 'body-2' not in r1[0]
                 and r1[0].strip().endswith('body-1') and r1[3] is False,
                 repr(r1[0]) if r1 else 'None') and ok

        # 13.7 跳号与重复编号：行号定位，各自验签；哈希互不串
        r2 = cr.resolve('编号', 2)
        r4 = cr.resolve('编号', 4)
        h2 = cr._entry_hash(open(os.path.join(t, '编号.txt'), encoding='utf-8').read(), 2)
        h4 = cr._entry_hash(open(os.path.join(t, '编号.txt'), encoding='utf-8').read(), 4)
        ok = _ok('13.7 跳号条目不误并前条', bool(r2) and 'body-1' not in r2[0] and 'body-3' not in r2[0],
                 repr(r2[0]) if r2 else 'None') and ok
        ok = _ok('13.8 重复编号各自独立（哈希不同且都验签）',
                 h2 != h4 and cr.verify('编号', 2, h2) and cr.verify('编号', 4, h4),
                 '%s / %s' % (h2, h4)) and ok

        # 13.9 末条：块到文末且显式标记 is_last
        r5 = cr.resolve('编号', 5)
        ok = _ok('13.9 末条块到文末且 is_last=True',
                 bool(r5) and r5[3] is True and r5[0].strip().endswith('body-5'),
                 repr(r5[0]) if r5 else 'None') and ok

        # 13.10 multi_query 全文：末条显式标注，编号条目不再互见失败
        mout, merr, _ = _rpc([{'jsonrpc': '2.0', 'id': 20, 'method': 'tools/call',
                               'params': {'name': 'daybook_multi_query',
                                          'arguments': {'volume': '编号', 'level': 'entry',
                                                        'full': True}}}], tmp_root=t)
        mt = mout[0].get('result', {}).get('content', [{}])[0].get('text', '')
        ok = _ok('13.10 multi_query 编号条目无互见失败',
                 '↪[编号#L1-' in mt and '[互见失败]' not in mt, mt[:200]) and ok
        ok = _ok('13.11 multi_query 末条显式标注', '（末条·至文末' in mt, mt[-200:]) and ok
        sha_mq = mt.split('[编号#L1-', 1)[1][:8] if '[编号#L1-' in mt else ''
        ok = _ok('13.12 make 与 multi_query 引用口径一致（同一 SHA8）',
                 bool(sha_mq) and texts[0] == '[编号#L1-%s]' % sha_mq,
                 'make=%s mq=%s' % (texts[0], sha_mq)) and ok
        return ok
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_production_index_path(t):
    out, err, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                         'params': {'name': 'daybook_multi_query',
                                    'arguments': {'volume': '测试', 'level': 'entry'}}}], tmp_root=t)
    if not _ok('5.1 multi_query 有响应', len(out) == 1, err):
        return False
    r = out[0].get('result', {})
    text = r.get('content', [{}])[0].get('text', '')
    if not _ok('5.2 读到 索引/multilevel 的条目', not r.get('isError') and '秒级条目' in text, text):
        return False
    return _ok('5.3 附秒级互见引用', '↪[测试#L1-' in text, text)


def test_read_offset_limit(t):
    out, err, _ = _rpc([{'jsonrpc': '2.0', 'id': 1, 'method': 'resources/read',
                         'params': {'uri': 'daybook://测试', 'offset': 2, 'limit': 1}}], tmp_root=t)
    if not _ok('6.1 resources/read 有响应', len(out) == 1, err):
        return False
    text = out[0].get('result', {}).get('contents', [{}])[0].get('text', '')
    return _ok('6.2 offset=2 limit=1 只取第 2 行',
               '分钟级条目' in text and '秒级条目' not in text, text)


def test_subscribe_validation(t):
    out, err, _ = _rpc([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'resources/subscribe',
         'params': {'uri': 'daybook://不存在的卷'}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'resources/subscribe',
         'params': {'uri': 'daybook://测试'}},
    ], tmp_root=t)
    if not _ok('7.1 subscribe 有响应', len(out) == 2, err):
        return False
    e1 = out[0].get('error', {})
    if not _ok('7.2 不存在的 URI 报错（-32602）', e1.get('code') == -32602, str(out[0])):
        return False
    r2 = out[1].get('result', {})
    return _ok('7.3 存在的 URI 才订阅成功', r2.get('subscribed') is True, str(out[1]))


def test_zero_write(t):
    reqs = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'resources/read',
         'params': {'uri': 'daybook://测试'}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
         'params': {'name': 'daybook_list', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
         'params': {'name': 'daybook_query',
                    'arguments': {'field': 'category', 'value': '测试'}}},
    ]
    out, err, zero = _rpc(reqs, tmp_root=t)
    if not _ok('8.1 只读批次全部有响应', len(out) == len(reqs), err):
        return False
    if not _ok('8.2 只读模式零写盘（树快照全同）', zero,
               '审计应走 stderr：%s' % err[:120]):
        return False
    return _ok('8.3 未生成 MCP审计卷.txt',
               not os.path.exists(os.path.join(t, 'MCP审计卷.txt')))


def test_secret_file_mode(t):
    sys.path.insert(0, HERE)
    from agent_registry import Registry, KEY_DIR_NAME
    reg_path = os.path.join(t, '注册卷_密钥测试.txt')
    reg = Registry(reg_path)
    aid, secret = reg.register('密钥测试')
    keyfile = os.path.join(t, KEY_DIR_NAME, aid + '.key')
    if not _ok('9.1 独立密钥文件存在', os.path.exists(keyfile), keyfile):
        return False
    mode = stat.S_IMODE(os.stat(keyfile).st_mode)
    if not _ok('9.2 密钥文件 0600', mode == 0o600, oct(mode)):
        return False
    dmode = stat.S_IMODE(os.stat(os.path.join(t, KEY_DIR_NAME)).st_mode)
    if not _ok('9.3 密钥目录 0700', dmode == 0o700, oct(dmode)):
        return False
    with open(reg_path, 'r', encoding='utf-8') as f:
        body = f.read()
    if not _ok('9.4 注册卷不含明文密钥', secret not in body and '密钥文件=' in body, body[:120]):
        return False
    # 重载后验签仍可用 / signature still verifies after reload
    reg2 = Registry(reg_path)
    sig = reg2.sign(aid, 'payload-x')
    return _ok('9.5 重载后验签可用', reg2.verify(aid, 'payload-x', sig))


def test_root_from_conf():
    """10. 根解析：conf 空/非空/无效 + DAYBOOK_ROOT 只作显式覆盖。
    Root resolution: conf empty/non-empty/invalid + DAYBOOK_ROOT as an explicit override only."""
    sys.path.insert(0, HERE)
    import mcp_resources as mr
    saved_env = os.environ.pop('DAYBOOK_ROOT', None)
    saved_here = mr.HERE
    ok = True
    dirs = []

    def mk(root_line):
        d = tempfile.mkdtemp(prefix='daybook_root_')
        dirs.append(d)
        with open(os.path.join(d, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n2026=2026.txt\n\n[index]\nroot=%s\n' % root_line)
        with open(os.path.join(d, '2026.txt'), 'w', encoding='utf-8') as f:
            f.write('[2026-01-01 00:00:00] [测试] [根解析] [皮特] x\n')
        return d

    try:
        d = mk('')
        mr.HERE = d
        ok = _ok('10.1 conf root 为空 ⇒ conf 所在目录', mr._root() == d, mr._root()) and ok

        d2 = mk('ledger')
        os.makedirs(os.path.join(d2, 'ledger'))
        mr.HERE = d2
        ok = _ok('10.2 conf root=ledger ⇒ conf 目录/ledger',
                 mr._root() == os.path.join(d2, 'ledger'), mr._root()) and ok

        d3 = mk('./nope')
        mr.HERE = d3
        try:
            mr._root()
            ok = _ok('10.3 无效 conf root 报 RootError', False, '未报错') and ok
        except mr.RootError as e:
            ok = _ok('10.3 无效 conf root 报 RootError', True, str(e)[:60]) and ok

        d4 = mk('')
        mr.HERE = d4
        no_env = mr._root()
        os.environ['DAYBOOK_ROOT'] = d4
        with_env = mr._root()
        os.environ.pop('DAYBOOK_ROOT', None)
        ok = _ok('10.4 无 env 与 DAYBOOK_ROOT 指向同一账本',
                 no_env == with_env == d4, '%s | %s' % (no_env, with_env)) and ok

        os.environ['DAYBOOK_ROOT'] = '/no/such/dir_xyz'
        try:
            mr._root()
            ok = _ok('10.5 无效 DAYBOOK_ROOT 报 RootError', False, '未报错') and ok
        except mr.RootError:
            ok = _ok('10.5 无效 DAYBOOK_ROOT 报 RootError', True) and ok
    finally:
        os.environ.pop('DAYBOOK_ROOT', None)
        if saved_env is not None:
            os.environ['DAYBOOK_ROOT'] = saved_env
        mr.HERE = saved_here
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)
    return ok


def _copy_server(tmproot):
    """把 src 下的 .py 拷到 tmproot·返回 mcp_server.py 路径。
    Copy the .py files from src into tmproot · return the mcp_server.py path."""
    for f in os.listdir(HERE):
        if f.endswith('.py'):
            shutil.copy2(os.path.join(HERE, f), os.path.join(tmproot, f))
    return os.path.join(tmproot, 'mcp_server.py')


def test_zero_bytecode():
    """11. 启动路径零 __pycache__：不带 PYTHONDONTWRITEBYTECODE 启动也不生成。
    Startup path emits no __pycache__ even when PYTHONDONTWRITEBYTECODE is absent."""
    t = tempfile.mkdtemp(prefix='daybook_pyc_')
    try:
        server = _copy_server(t)
        with open(os.path.join(t, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n2026=2026.txt\n\n[index]\nroot=\n')
        with open(os.path.join(t, '2026.txt'), 'w', encoding='utf-8') as f:
            f.write('[2026-01-01 00:00:00] [测试] [零字节码] [皮特] x\n')
        env = dict(os.environ)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        env['DAYBOOK_ROOT'] = t
        env['MCP_READ_ONLY'] = '1'
        req = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
        p = subprocess.run([sys.executable, server], input=req + '\n',
                           capture_output=True, text=True, timeout=20, env=env)
        caches = [dp for dp, _, _ in os.walk(t) if os.path.basename(dp) == '__pycache__']
        return _ok('11 启动路径不生成 __pycache__', not caches and '"result"' in p.stdout,
                   'caches=%s' % caches)
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_empty_volumes_warns():
    """12. 空卷自检：启动与 resources/list 都向 stderr 告警，不静默。
    Empty-volume self-check: both startup and resources/list warn on stderr, never silently."""
    t = tempfile.mkdtemp(prefix='daybook_empty_')
    try:
        server = _copy_server(t)
        with open(os.path.join(t, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n\n[index]\nroot=\n')
        env = dict(os.environ)
        env['DAYBOOK_ROOT'] = t
        env['MCP_READ_ONLY'] = '1'
        req = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'resources/list'})
        p = subprocess.run([sys.executable, server], input=req + '\n',
                           capture_output=True, text=True, timeout=20, env=env)
        empty = json.loads(p.stdout.splitlines()[0]).get('result', {}).get('resources') == []
        return _ok('12 空卷有 stderr 告警且列表为 0', 'volumes 为空' in p.stderr and empty,
                   p.stderr.strip().splitlines()[0] if p.stderr.strip() else 'no stderr')
    finally:
        shutil.rmtree(t, ignore_errors=True)


def main():
    print('=== MCP P0 最小回归 ===')
    t = _setup()
    try:
        results = [
            ('initialize', test_initialize(t)),
            ('tools/list 隐藏写工具', test_tools_list_hides_write(t)),
            ('四个写工具只读被拒', test_write_tools_rejected(t)),
            ('cross_ref 秒级头', test_cross_ref_seconds(t)),
            ('cross_ref 编号前缀与末条', test_cross_ref_numbered()),
            ('生产 索引/multilevel 路径', test_production_index_path(t)),
            ('resources/read offset/limit', test_read_offset_limit(t)),
            ('subscribe 存在性校验', test_subscribe_validation(t)),
            ('只读零写盘', test_zero_write(t)),
            ('密钥 0600 + 不落明文', test_secret_file_mode(t)),
            ('根目录由 conf 解析', test_root_from_conf()),
            ('启动路径零 __pycache__', test_zero_bytecode()),
            ('空卷自检告警', test_empty_volumes_warns()),
        ]
    finally:
        shutil.rmtree(t, ignore_errors=True)
    print('=== 总验收 ===')
    for name, ok in results:
        print('  %s: %s' % (name, 'PASS' if ok else 'FAIL'))
    all_ok = all(r[1] for r in results)
    print('=== %s（%d/%d PASS）===' % ('PASS' if all_ok else 'FAIL',
                                       sum(1 for r in results if r[1]), len(results)))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
