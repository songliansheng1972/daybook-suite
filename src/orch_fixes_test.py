#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook-orch 缺陷回归测试（批次一 4 条 + 批次二 8 条）
Regression tests for the daybook-orch defects (batch 1: 4 items + batch 2: 8 items)
================================================
批次一（v4.0.3）：
1. pull 不许按位置判已回（只认 [re=<条号>]，旧条目判 unknown）
2. 身份接上 HMAC-SHA256（落盘带 [sig=]，读取验签；unsigned/invalid 明确告警）
3. 卷路径 conf 驱动 + 单一根（--root 一处生效，消息卷跟着走）
4. read_vol 共享锁读（长条目并发读写不撕裂）
批次二：
5. route 确定性查表（致= 优先、关键词、非作者、未知类不猜）
6. digest 兜底不静默（卷表空/读失败/互见失败可见）＋ --limit 语义（0=全部，负数报错）
7. alarm 结构判据（时间戳+阈值、注册表成员）＋ 硬警/异常退出码拆分（1/3）
8. CLI --limit 语义写进帮助文本
9. 跨进程锁（真跨进程：6 进程同刻抢锁恰好 1 个成功）
10. cross_ref.verify 必须给基准（缺基准报错，禁自比自过）
11. sock_path 净化（不生成嵌套路径、拒绝非法/超长名）＋ 死代码清理
12. 单遍性能（digest 每卷一读、dead_agents 整卷只读一次）

用法：
    python3 orch_fixes_test.py            # 全部
    python3 orch_fixes_test.py --only 5   # 只跑第 N 条（变异回归用）
退出码：0=全绿；1=有红。
"""
import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_results = []


def check(label, cond, detail=''):
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', label,
                           (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    _results.append(bool(cond))
    return bool(cond)


def _fresh_root(tag):
    root = tempfile.mkdtemp(prefix='orch_fix_%s_' % tag)
    return root


# ── 1. pull 回复关系 ────────────────────────────────────────────────
def test_pull_reply():
    print('== 1. pull：显式引用 [re=] / 旧条目 unknown ==')
    from orchestrator import Hub
    from daybook_append import append_one

    root = _fresh_root('pull')
    try:
        hub = Hub(root=root)
        aid_t, _ = hub.join('汤姆')
        aid_p, _ = hub.join('皮特')

        # 旧格式批次：两条落在皮特，随后一条皮特的无关消息（旧代码据位置判「已回」）
        append_one(hub.ledger, '报', '交活 T001', '旧正文一', author=aid_t, to=aid_p)
        append_one(hub.ledger, '报', '交活 T002', '旧正文二', author=aid_t, to=aid_p)
        append_one(hub.ledger, '聊', '皮特自言自语', '与回复无关', author=aid_p)
        pend = hub.pull('皮特')
        legacy = [e for e, _p, _w in pend if e['title'] in ('交活 T001', '交活 T002')]
        check('旧批次无 id= → 判 unknown，照样列出（2 条）', len(legacy) == 2,
              '实际 %d 条' % len(legacy))
        check('旧批次全部标 reply=unknown', all(e['reply_state'] == 'unknown' for e in legacy))

        # 新格式：签名报条 + 显式 [re=] 回应 → 不再列出
        eid = hub._log('报', '交活 T003', '新正文三', aid_t, to=aid_p)
        pend_ids = [e.get('id') for e, _p, _w in hub.pull('皮特')]
        check('新报条（未回应）在取件里', eid in pend_ids)
        hub._log('审', '裁决 T003', '收到', aid_p, re_ref=eid)
        pend_ids = [e.get('id') for e, _p, _w in hub.pull('皮特')]
        check('显式 [re=] 回应后不再列出', eid not in pend_ids)

        # 未签名「回应」不算已回
        eid2 = hub._log('报', '交活 T004', '新正文四', aid_t, to=aid_p)
        append_one(hub.ledger, '审', '伪造回应', '未签名', author=aid_p, re_ref=eid2)
        pend_ids = [e.get('id') for e, _p, _w in hub.pull('皮特')]
        check('unsigned 回应不计为已回', eid2 in pend_ids)

        # 篡改签名条目 → invalid，仍列出
        eid3 = hub._log('报', '交活 T005', 'TAMPER-TARGET-9f3a', aid_t, to=aid_p)
        with open(hub.ledger, encoding='utf-8') as f:
            old = f.read()
        with open(hub.ledger, 'w', encoding='utf-8') as f:
            f.write(old.replace('TAMPER-TARGET-9f3a', 'TAMPERED-BODY-9f3a'))
        pend = hub.pull('皮特')
        hit = [e for e, _p, _w in pend if e.get('id') == eid3]
        check('篡改后验签 invalid 且仍列出', bool(hit) and hit[0]['auth'] == 'invalid',
              'auth=%s' % (hit[0]['auth'] if hit else '缺失'))
        print('  读数：旧批次取件 %d 条（旧算法为 0 条）' % len(legacy))
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── 2. 身份签名 ────────────────────────────────────────────────────
def test_identity_signature():
    print('== 2. 身份：HMAC-SHA256 落盘 + 读取验签 ==')
    from orchestrator import Hub, parse_ledger, entry_payload
    from daybook_append import append_one

    root = _fresh_root('sig')
    try:
        hub = Hub(root=root)
        aid_t, _ = hub.join('汤姆')
        aid_p, _ = hub.join('皮特')

        keydir = os.path.join(root, '.daybook_keys')
        kf = os.path.join(keydir, aid_t + '.key')
        check('密钥目录 0700', stat.S_IMODE(os.stat(keydir).st_mode) == 0o700,
              oct(stat.S_IMODE(os.stat(keydir).st_mode)))
        check('密钥文件 0600', stat.S_IMODE(os.stat(kf).st_mode) == 0o600,
              oct(stat.S_IMODE(os.stat(kf).st_mode)))

        eid = hub._log('报', '交活 T101', '正文', aid_t, to=aid_p)
        e = [x for x in parse_ledger(hub.ledger) if x.get('id') == eid][0]
        check('落盘带 [id=]/[sig=]', bool(e['id']) and len(e['sig']) == 64)
        check('正常条目验签 ok', hub.entry_auth(e) == 'ok', hub.entry_auth(e))

        # 旧格式（无 sig）→ unsigned，不得当合法
        append_one(hub.ledger, '聊', '旧条目', '无签名', author=aid_t)
        e_old = parse_ledger(hub.ledger)[-1]
        check('旧条目判 unsigned', hub.entry_auth(e_old) == 'unsigned', hub.entry_auth(e_old))

        # 借用别人的密钥冒充 → invalid
        now = '2026-11-14 00:00:00'
        forged_id = 'mforged000000001'
        payload = entry_payload(now, '聊', '冒充', aid_p, '', forged_id, '', '冒名正文')
        wrong_sig = hub.reg.sign(aid_t, payload)       # 用汤姆的钥签皮特的名
        append_one(hub.ledger, '聊', '冒充', '冒名正文', author=aid_p,
                   msg_id=forged_id, sig=wrong_sig, now=now)
        e_forged = [x for x in parse_ledger(hub.ledger) if x.get('id') == forged_id][0]
        check('借钥冒充判 invalid', hub.entry_auth(e_forged) == 'invalid',
              hub.entry_auth(e_forged))

        # 环境变量只选钥，不改身份：显式身份优先
        os.environ['DAYBOOK_AGENT_ID'] = aid_p
        check('显式身份优先于 DAYBOOK_AGENT_ID', hub._actor(aid_t) == aid_t)
        check('缺省时 DAYBOOK_AGENT_ID 仅提供身份输入', hub._actor('') == aid_p)
        del os.environ['DAYBOOK_AGENT_ID']

        # 篡改正文 → invalid
        with open(hub.ledger, encoding='utf-8') as f:
            body = f.read()
        with open(hub.ledger, 'w', encoding='utf-8') as f:
            f.write(body.replace('交活 T101', '交活 T101·篡改'))
        e2 = [x for x in parse_ledger(hub.ledger) if x.get('id') == eid][0]
        check('篡改条头后验签 invalid', hub.entry_auth(e2) == 'invalid', hub.entry_auth(e2))
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── 3. 根解析 ──────────────────────────────────────────────────────
def test_root_resolution():
    print('== 3. 根解析：conf 驱动 + 单一根 ==')
    import agent_message as am

    roots = []
    paths = {}
    code_inbox = os.path.join(HERE, '消息卷.txt')
    code_before = (os.path.exists(code_inbox),
                   os.path.getsize(code_inbox) if os.path.exists(code_inbox) else -1)
    try:
        for tag in ('A', 'B'):
            root = _fresh_root('root' + tag)
            roots.append(root)
            with open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
                f.write('[volumes]\n')
                f.write('registry=state/reg.txt\n')
                f.write('tasks=state/tasks.txt\n')
                f.write('heartbeat=state/hb.txt\n')
                f.write('leases=state/lease.txt\n')
                f.write('ledger=state/ledger.txt\n')
                f.write('inbox=state/inbox.txt\n')
                f.write('locks=state/locks\n')
                f.write('协作=sample/协作卷.txt\n')
            r = subprocess.run([sys.executable, os.path.join(HERE, 'orchestrator.py'),
                                '--root', root, 'join', '汤姆'],
                               capture_output=True, text=True)
            check('%s 根 join rc=0' % tag, r.returncode == 0,
                  (r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else '')
            am._append_inbox({'from': 'x', 'to': 'y', 'type': 'notify', 'content': tag},
                             direction='收', root=root)
            paths[tag] = {k: os.path.join(root, 'state', v)
                          for k, v in (('registry', 'reg.txt'), ('tasks', 'tasks.txt'),
                                       ('heartbeat', 'hb.txt'), ('ledger', 'ledger.txt'),
                                       ('inbox', 'inbox.txt'))}
            check('%s 注册卷落在根下 state/' % tag,
                  os.path.exists(paths[tag]['registry']))
            check('%s 编排卷落在根下 state/' % tag,
                  os.path.exists(paths[tag]['ledger']))
            check('%s 心跳卷落在根下 state/' % tag,
                  os.path.exists(paths[tag]['heartbeat']))
            check('%s 消息卷落在根下 state/' % tag,
                  os.path.exists(paths[tag]['inbox']))
            print('  根 %s：%s' % (tag, root))
            for k in ('registry', 'ledger', 'heartbeat', 'inbox'):
                print('    %-8s %s' % (k, paths[tag][k]))
        # 两个根的落盘位置不同
        check('两个不同根落盘位置不同',
              paths['A']['ledger'] != paths['B']['ledger']
              and os.path.exists(paths['A']['ledger'])
              and os.path.exists(paths['B']['ledger']))
        # 不应再写代码目录的消息卷
        code_after = (os.path.exists(code_inbox),
                      os.path.getsize(code_inbox) if os.path.exists(code_inbox) else -1)
        check('代码目录不再落消息卷', code_after == code_before,
              '%s → %s' % (code_before, code_after))
        return all(_results)
    finally:
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)


# ── 4. read_vol 共享锁 ─────────────────────────────────────────────
def test_read_locking():
    print('== 4. read_vol：并发读写不撕裂 ==')
    from safeio import read_vol, locked

    root = _fresh_root('lock')
    path = os.path.join(root, 'vol.txt')
    try:
        record = '[2026-11-14 00:00:00] [测] [长条] [x] ' + ('A' * 65536) + '\n'
        torn = []
        stop = threading.Event()

        def writer():
            for _ in range(6):
                with locked(path):          # 写侧持独占锁，分两段慢写（模拟长条目落盘窗口）
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                    try:
                        half = len(record.encode('utf-8')) // 2
                        raw = record.encode('utf-8')
                        os.write(fd, raw[:half])
                        time.sleep(0.08)
                        os.write(fd, raw[half:])
                    finally:
                        os.close(fd)
            stop.set()

        def reader():
            while not stop.is_set():
                try:
                    text, _enc, _why = read_vol(path)
                except FileNotFoundError:
                    continue
                if text and not text.endswith('\n'):
                    torn.append(text[-40:])
                if len(torn) > 50:
                    break

        tw = threading.Thread(target=writer)
        tr = threading.Thread(target=reader)
        tw.start(); tr.start()
        tw.join(); tr.join()
        check('共享锁读：撕裂 0 次', len(torn) == 0, 'torn=%d' % len(torn))
        text, _e, _w = read_vol(path)
        check('完整记录 6 条', text.count('[测]') == 6, 'count=%d' % text.count('[测]'))
        print('  读数：撕裂 %d 次（无锁旧行为下应 >0）' % len(torn))
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── 批次二：路由 / digest / alarm / CLI / 跨进程锁 / 引用校验 / 单遍性能 ──
# Batch 2: route / digest / alarm / CLI / cross-process lock / reference verification / single-pass performance

def _make_volume(path, n, hour=10, kind='报', author='汤姆'):
    """造 n 条条目（每条 3 行）·返回条目头行号（1 起）。
    Build n entries (3 lines each) · return the entry-head line numbers (1-based)."""
    lines = []
    for i in range(n):
        lines.append('[2026-11-14 %02d:%02d:00] [%s] [条目%02d] [%s]' % (hour, i, kind, i, author))
        lines.append('正文 %d' % i)
        lines.append('')
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return [1 + i * 3 for i in range(n)]


def test_route():
    print('== 5. route：确定性查表 ==')
    from orchestrator import route, load_rules, load_roles, DEFAULT_RULE, DEFAULT_ROLES
    rules = load_rules(DEFAULT_RULE)
    roles = load_roles(DEFAULT_ROLES)
    p, why = route('报', '交活 T001', '已实现', '汤姆', '', rules, roles)
    check('报 → 非作者池（汤姆被剔）', p == '皮特/史泰龙', '%s · %s' % (p, why))
    p2, why2 = route('报', '交活 T001', '已实现', '汤姆', '', rules, roles)
    check('同一条两次结果一致（确定性）', (p, why) == (p2, why2))
    _p, why = route('报', '交活 T001', '复核驳回', '汤姆', '', rules, roles)
    check('关键词命中「驳回」→ rework', '命中「驳回」' in why, why)
    p, why = route('聊', '随便聊聊', '', '汤姆', '', rules, roles)
    check('未知类 → 无规则→广播', p is None and '广播' in why, why)
    p, why = route('聊', '随便聊聊', '', '汤姆', '老宋', rules, roles)
    check('条头[致=] 优先于查表', p == '老宋' and '致=' in why, '%s · %s' % (p, why))
    p, why = route('报', '交活 T001', '', '', '', rules, roles)
    check('作者缺 → 待定（不猜）', p is None and '作者缺' in why, why)
    return all(_results)


def test_digest_visibility_and_limit():
    print('== 6. digest：兜底不静默 / 互见失败可见 / limit 语义 ==')
    from orchestrator import Hub
    root = _fresh_root('dig')
    try:
        with io.open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n协作=协作卷.txt\n语汇=语汇卷.txt\n百科=百科卷.txt\n')
        _make_volume(os.path.join(root, '协作卷.txt'), 8, hour=10)
        _make_volume(os.path.join(root, '语汇卷.txt'), 8, hour=11, kind='核')
        _make_volume(os.path.join(root, '百科卷.txt'), 8, hour=12, kind='典')
        hub = Hub(root=root)
        lines, rows, src = hub.digest(limit=0)
        check('无目录件 → 卷原文兜底', src == 'volume-fallback' and len(rows) == 24,
              '%s · %d 条' % (src, len(rows)))
        check('兜底摘要每条互见引用成功', not any('互见失败' in x for x in lines))
        lines5, _r5, _s5 = hub.digest(limit=5)
        check('limit=5 只出 5 条', sum(1 for x in lines5 if x.startswith('  部.')) == 5)
        try:
            hub.digest(limit=-1)
            check('limit=-1 → ValueError（不再少一条）', False)
        except ValueError:
            check('limit=-1 → ValueError（不再少一条）', True)

        empty = _fresh_root('digempty')
        try:
            hub2 = Hub(root=empty)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                lines2, rows2, src2 = hub2.digest(limit=0)
            check('卷表为空 → src=no-volumes', src2 == 'no-volumes' and rows2 == [], src2)
            check('卷表为空 → 输出显式标注', any('卷表为空' in x for x in lines2))
            check('卷表为空 → stderr 留痕', '卷表为空' in err.getvalue(),
                  err.getvalue().strip()[:60])
        finally:
            shutil.rmtree(empty, ignore_errors=True)

        missing = _fresh_root('digmiss')
        try:
            with io.open(os.path.join(missing, 'daybook.conf'), 'w', encoding='utf-8') as f:
                f.write('[volumes]\n协作=没这卷.txt\n')
            hub3 = Hub(root=missing)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                lines3, _rows3, src3 = hub3.digest(limit=0)
            check('卷不存在 → 显式告警（不静默 0 条）',
                  any('不存在' in x for x in lines3) and '不存在' in err.getvalue(), src3)
        finally:
            shutil.rmtree(missing, ignore_errors=True)

        broken = _fresh_root('digref')
        try:
            with io.open(os.path.join(broken, 'daybook.conf'), 'w', encoding='utf-8') as f:
                f.write('[volumes]\n协作=协作卷.txt\n')
            _make_volume(os.path.join(broken, '协作卷.txt'), 2, hour=10)
            md = os.path.join(broken, 'multilevel')
            os.makedirs(md)
            with io.open(os.path.join(md, '协作_catalog.tsv'), 'w', encoding='utf-8') as f:
                f.write('volume\tlevel2\tline\ttime\tcategory\tauthor\ttitle\n')
                f.write('协作\t报\t999\t2026-11-14 10:00\t报\t汤姆\t空行引用\n')
            hub4 = Hub(root=broken)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                lines4, _rows4, src4 = hub4.digest(limit=0)
            check('互见引用失败 → 输出标注', any('互见失败' in x for x in lines4), src4)
            check('互见引用失败 → stderr 留痕', '互见引用失败' in err.getvalue())
        finally:
            shutil.rmtree(broken, ignore_errors=True)
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_alarm_structure_and_exit_codes():
    print('== 7. alarm：结构判据 + 退出码拆分 ==')
    from orchestrator import Hub
    from safeio import atomic_append
    root = _fresh_root('alarm')
    try:
        hub = Hub(root=root)
        aid_t, _ = hub.join('汤姆')
        hub.join('皮特')
        old = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - 3600))
        atomic_append(hub.vols['heartbeat'], '[%s] [心跳] [ag-dead] alive\n' % old)

        hub.tv.create('ag-ghost', '幽灵单')
        tid_s = hub.tv.create(aid_t, '滞留单')
        hub.tv.transition(tid_s, '进行中', aid_t, '')
        hub.tv.transition(tid_s, '完成', aid_t, '')
        tid_o = hub.tv.create('ag-dead', '孤儿单')
        hub.tv.transition(tid_o, '进行中', 'ag-dead', '')

        issues = hub.alarm()
        by = {i.code: i for i in issues}
        check('失联 agent → 硬警（时间戳+阈值）', 'dead_agents' in by and by['dead_agents'].hard)
        check('幽灵负责人 → 硬警（注册表成员）', 'ghost_owner' in by and by['ghost_owner'].hard)
        check('孤儿任务 → 硬警', 'orphan_task' in by and by['orphan_task'].hard)
        check('滞留 → 软警（不升格硬警）', 'stalled_done' in by and not by['stalled_done'].hard)

        def run_alarm(r):
            return subprocess.run([sys.executable, os.path.join(HERE, 'orchestrator.py'),
                                   '--root', r, 'alarm'], capture_output=True, text=True)

        rr = run_alarm(root)
        check('有硬警 → rc=1', rr.returncode == 1, 'rc=%d' % rr.returncode)
        ghost = _fresh_root('alarmghost')
        try:
            h = Hub(root=ghost)
            h.join('汤姆')
            h.tv.create('ag-ghost', '幽灵单')
            rc = run_alarm(ghost)
            check('仅幽灵负责人 → rc=1（旧字串判据会误判干净）',
                  rc.returncode == 1, 'rc=%d' % rc.returncode)
        finally:
            shutil.rmtree(ghost, ignore_errors=True)
        clean = _fresh_root('alarmclean')
        try:
            Hub(root=clean).join('汤姆')
            rc = run_alarm(clean)
            check('干净 → rc=0', rc.returncode == 0, 'rc=%d' % rc.returncode)
        finally:
            shutil.rmtree(clean, ignore_errors=True)
        broken = _fresh_root('alarmerr')
        try:
            os.makedirs(os.path.join(broken, '任务卷.txt'))  # 任务卷是目录 → 读失败 · task volume is a directory → read failure
            rc = run_alarm(broken)
            check('执行异常 → rc=3（不与硬警共用 1）', rc.returncode == 3, 'rc=%d' % rc.returncode)
        finally:
            shutil.rmtree(broken, ignore_errors=True)
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cli_limit_semantics():
    print('== 8. CLI：--limit 语义 ==')
    root = _fresh_root('clilimit')
    try:
        with io.open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n协作=协作卷.txt\n')
        _make_volume(os.path.join(root, '协作卷.txt'), 6)

        def run(*args):
            return subprocess.run([sys.executable, os.path.join(HERE, 'orchestrator.py'),
                                   '--root', root, 'digest'] + list(args),
                                  capture_output=True, text=True)

        r = run('--limit', '-1')
        check('--limit -1 → rc=2（负数非法）',
              r.returncode == 2 and '--limit' in r.stderr, 'rc=%d' % r.returncode)
        r = run('--limit', '0')
        n0 = sum(1 for x in r.stdout.splitlines() if x.startswith('  部.'))
        check('--limit 0 → 全部 6 条', r.returncode == 0 and n0 == 6,
              'rc=%d n=%d' % (r.returncode, n0))
        r = run('--limit', '2')
        n2 = sum(1 for x in r.stdout.splitlines() if x.startswith('  部.'))
        check('--limit 2 → 最近 2 条', r.returncode == 0 and n2 == 2,
              'rc=%d n=%d' % (r.returncode, n2))
        h = subprocess.run([sys.executable, os.path.join(HERE, 'orchestrator.py'),
                            'digest', '--help'], capture_output=True, text=True)
        check('帮助文本写明 0=全部', '0=全部' in h.stdout)
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


_LOCK_CHILD = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
from agent_lock import AgentLock
lock_dir, lease, marker_dir, idx, n, result = sys.argv[2:8]
lk = AgentLock(lock_dir, lease)
open(os.path.join(marker_dir, 'm%s' % idx), 'w').close()
deadline = time.time() + 10
while len(os.listdir(marker_dir)) < int(n) and time.time() < deadline:
    time.sleep(0.005)
lid = lk.acquire('task:X', 'a%s' % idx)
with open(result, 'a') as f:
    f.write('1\n' if lid else '0\n')
if lid:
    time.sleep(1.0)
    lk.release(lid)
'''


def test_cross_process_lock():
    print('== 9. 跨进程锁：真跨进程互斥 ==')
    root = _fresh_root('xproc')
    try:
        marker_dir = os.path.join(root, 'barrier')
        os.makedirs(marker_dir)
        result = os.path.join(root, 'result.txt')
        n = 6
        procs = [subprocess.Popen([sys.executable, '-c', _LOCK_CHILD, HERE,
                                   os.path.join(root, 'locks'),
                                   os.path.join(root, 'lease.txt'),
                                   marker_dir, str(i), str(n), result])
                 for i in range(n)]
        for p in procs:
            p.wait(timeout=20)
        with io.open(result, encoding='utf-8') as f:
            wins = [x for x in f.read().split() if x == '1']
        check('6 进程同刻抢同一锁 → 恰好 1 个成功', len(wins) == 1, 'wins=%d' % len(wins))
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_verify_requires_baseline():
    print('== 10. cross_ref.verify：缺基准报错 ==')
    from cross_ref import CrossRef
    root = _fresh_root('xref')
    try:
        _make_volume(os.path.join(root, '协作卷.txt'), 2)
        cr = CrossRef(root=root)
        ref = cr.make_ref('协作卷', 1)
        sha = ref.split('-')[-1].rstrip(']')
        check('带正确基准 → PASS', cr.verify('协作卷', 1, sha) is True, ref)
        check('基准不符 → False', cr.verify('协作卷', 1, 'deadbeef') is False)
        try:
            cr.verify('协作卷', 1)
            check('缺基准 → 抛 ValueError（不自比自过）', False)
        except ValueError:
            check('缺基准 → 抛 ValueError（不自比自过）', True)
        try:
            cr.verify('协作卷', 1, 'XYZ')
            check('基准格式非法 → 抛 ValueError', False)
        except ValueError:
            check('基准格式非法 → 抛 ValueError', True)
        r = subprocess.run([sys.executable, os.path.join(HERE, 'cross_ref.py'),
                            'verify', '协作卷', '1'], capture_output=True, text=True)
        check('CLI 缺基准 → rc=2', r.returncode == 2, 'rc=%d' % r.returncode)
        return all(_results)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_sock_and_dead_code():
    print('== 11. sock_path 净化 / 死代码清理 / conf 抬头 ==')
    import agent_message as am
    import safeio
    import agent_registry
    import agent_lock
    p = am.sock_path('a/b')
    check('sock_path 净化：不生成嵌套路径',
          os.path.dirname(p) == am.SOCK_DIR and '/a/' not in p, p)
    check('中文 agent 名照用', am.sock_path('汤姆').endswith('汤姆.sock'))
    for bad in ('', '.', '..', 'x' * 200):
        try:
            am.sock_path(bad)
            check('非法/超长名 %r → 抛 ValueError' % (bad[:8],), False)
        except ValueError:
            check('非法/超长名 %r → 抛 ValueError' % (bad[:8],), True)
    check('Agent.to_authors 已删',
          not hasattr(agent_registry.Agent, 'to_authors')
          and not hasattr(agent_registry.Registry, 'to_authors'))
    check('safeio.read_json/write_json 已删',
          not hasattr(safeio, 'read_json') and not hasattr(safeio, 'write_json'))
    check('AgentLock.renew/force_release/sweep 已删',
          not any(hasattr(agent_lock.AgentLock, n)
                  for n in ('renew', 'force_release', 'sweep')))
    conf = io.open(os.path.join(HERE, 'daybook.conf'), encoding='utf-8').read()
    check('daybook.conf 抬头不再写 daybook-mcp', 'daybook-mcp' not in conf)
    return all(_results)


def test_single_pass_reads():
    print('== 12. 性能：digest 每卷一读 / dead_agents 单遍 ==')
    import safeio
    from orchestrator import Hub
    from safeio import atomic_append
    root = _fresh_root('perf')
    orig = safeio.read_vol
    stats = {'calls': 0, 'bytes': 0}

    def counted(path):
        stats['calls'] += 1
        try:
            stats['bytes'] += os.path.getsize(path)
        except OSError:
            pass
        return orig(path)
    try:
        with io.open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n协作=协作卷.txt\n语汇=语汇卷.txt\n百科=百科卷.txt\n')
        for name, hour in (('协作卷.txt', 10), ('语汇卷.txt', 11), ('百科卷.txt', 12)):
            _make_volume(os.path.join(root, name), 40, hour=hour)
        hub = Hub(root=root)
        safeio.read_vol = counted
        try:
            stats.update(calls=0, bytes=0)
            _l, rows, _s = hub.digest(limit=20)
            check('digest 20 条：卷读次数=3（不是 20）', stats['calls'] == 3,
                  'calls=%d bytes=%d rows=%d' % (stats['calls'], stats['bytes'], len(rows)))
        finally:
            safeio.read_vol = orig
        hb = hub.vols['heartbeat']
        for a in range(200):
            for _b in range(3):
                atomic_append(hb, '[2026-11-14 09:00:00] [心跳] [ag-%03d] alive\n' % a)
        safeio.read_vol = counted
        try:
            stats.update(calls=0, bytes=0)
            hub.hb.dead_agents()
            check('dead_agents 200 agent：整卷只读 1 次', stats['calls'] == 1,
                  'calls=%d bytes=%d' % (stats['calls'], stats['bytes']))
        finally:
            safeio.read_vol = orig
        return all(_results)
    finally:
        safeio.read_vol = orig
        shutil.rmtree(root, ignore_errors=True)


TESTS = {1: test_pull_reply, 2: test_identity_signature,
         3: test_root_resolution, 4: test_read_locking,
         5: test_route, 6: test_digest_visibility_and_limit,
         7: test_alarm_structure_and_exit_codes, 8: test_cli_limit_semantics,
         9: test_cross_process_lock, 10: test_verify_requires_baseline,
         11: test_sock_and_dead_code, 12: test_single_pass_reads}


def main(argv):
    only = None
    if '--only' in argv:
        i = argv.index('--only')
        only = int(argv[i + 1])
    print('=== daybook-orch 缺陷回归（批次一 4 + 批次二 8）===')
    ok = True
    for n in sorted(TESTS):
        if only is not None and n != only:
            continue
        before = len(_results)
        try:
            r = TESTS[n]()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            r = False
        ok = ok and bool(r) and all(_results[before:])
    print('=== %s ===' % ('全绿' if ok else '有红'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
