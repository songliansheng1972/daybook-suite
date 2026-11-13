#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook-orch 四条缺陷回归测试
Regression tests for the four daybook-orch defects
================================================
只测四条：
1. pull 不许按位置判已回（只认 [re=<条号>]，旧条目判 unknown）
2. 身份接上 HMAC-SHA256（落盘带 [sig=]，读取验签；unsigned/invalid 明确告警）
3. 卷路径 conf 驱动 + 单一根（--root 一处生效，消息卷跟着走）
4. read_vol 共享锁读（长条目并发读写不撕裂）

用法：
    python3 orch_fixes_test.py            # 全部
    python3 orch_fixes_test.py --only 1   # 只跑第 N 条（变异回归用）
退出码：0=全绿；1=有红。
"""
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


TESTS = {1: test_pull_reply, 2: test_identity_signature,
         3: test_root_resolution, 4: test_read_locking}


def main(argv):
    only = None
    if '--only' in argv:
        i = argv.index('--only')
        only = int(argv[i + 1])
    print('=== daybook-orch 四条缺陷回归 ===')
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
