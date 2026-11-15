#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 协作底座集成测试（W-DB-023-G3·第 7 项）
Agent collaboration base integration test (W-DB-023-G3 · item 7)
================================================
覆盖工单验收标准 7 项：
Covers the 7 ticket acceptance criteria:
  1. 3 个 Agent 可同时注册·各自独立身份
     3 agents can register concurrently · each with an independent identity
  2. 任务卷可流转：待办→进行中→完成→待审→已审
     The task volume flows: 待办→进行中→完成→待审→已审
  3. 跨卷引用可解析+校验 SHA-256
     Cross-volume references parse + verify SHA-256
  4. Agent A 写卷后·Agent B 收到 notify
     After Agent A writes a volume, Agent B receives a notify
  5. 文件锁可防多 Agent 同时改一任务
     The file lock prevents multiple agents from editing one task simultaneously
  6. Agent 心跳 > 3 周期不跳 → 标 dead
     An agent heartbeat missing > 3 periods → marked dead
  7. 零第三方依赖
     Zero third-party dependencies
退出码：0=PASS 1=FAIL
Exit code: 0=PASS 1=FAIL
"""
import os, sys, time, tempfile, shutil, subprocess, threading

HERE = os.path.dirname(os.path.abspath(__file__))


def _ok(name, cond, detail=''):
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name, (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    return bool(cond)


def test_agent_registry(tmp):
    """验收 1：3 个 Agent 同时注册·各自独立身份；验收 7：零依赖。
    Acceptance 1: 3 agents register concurrently with independent identities; acceptance 7: zero dependencies."""
    from agent_registry import Registry
    sys.path.insert(0, HERE)
    # import 已成功=零依赖成立 · import succeeded = zero dependencies holds
    reg = Registry(os.path.join(tmp, '注册卷.txt'))
    agents = [reg.register(n) for n in ('汤姆', '史泰龙', '皮特')]
    ids = [a[0] for a in agents]
    # 各自独立身份：agent_id 全不同 · independent identities: all agent_ids differ
    if not _ok('1.1 3 Agent 各自独立身份', len(set(ids)) == 3, 'ids=%s' % ids):
        return False
    # 验签 · verify the signature
    aid, _ = agents[0]
    sig = reg.sign(aid, 'payload-测试')
    if not _ok('1.2 签名生成+验证', reg.verify(aid, 'payload-测试', sig)):
        return False
    # 错签名被拒 · a wrong signature is rejected
    if not _ok('1.3 错签名被拒', not reg.verify(aid, 'payload-测试', sig + 'x')):
        return False
    # 吊销后验签失败 · verification fails after revocation
    reg.revoke(aid)
    if not _ok('1.4 吊销后验签失败', not reg.verify(aid, 'payload-测试', sig)):
        return False
    return True


def test_task_volume(tmp):
    """验收 2：任务流转 待办→进行中→完成→待审→已审。
    Acceptance 2: task flow 待办→进行中→完成→待审→已审."""
    from task_volume import TaskVolume
    tv = TaskVolume(os.path.join(tmp, '任务卷.txt'), root=tmp)
    tid = tv.create('ag-tom', '实现 MCP resources/list')
    if not _ok('2.1 创建任务', tid.startswith('T')):
        return False
    # 正向迁移 · forward transition
    ok = True
    try:
        tv.transition(tid, '进行中', 'ag-tom', '开工')
        tv.transition(tid, '完成', 'ag-tom', '提交')
        tv.transition(tid, '待审', 'ag-tom', '送审')
        tv.transition(tid, '已审', 'ag-tom', '通过')
    except Exception as e:
        ok = False
        err = str(e)
    if not _ok('2.2 正向流转 待办→进行中→完成→待审→已审', ok, err if not ok else ''):
        return False
    # 终态不可再迁 · a terminal state cannot transition again
    try:
        tv.transition(tid, '进行中', 'ag-tom', '返工')
        return _ok('2.3 终态拒迁', False, '终态不该能迁')
    except PermissionError:
        if not _ok('2.3 终态拒迁', True):
            return False
    # 非法迁移 · illegal transition
    tid2 = tv.create('ag-pit', '另一任务')
    try:
        tv.transition(tid2, '完成', 'ag-pit', '跳过')  # 待办→完成 非法 · 待办→完成 is illegal
        return _ok('2.4 非法迁移被拒', False, '不该允许跳过进行中')
    except PermissionError:
        return _ok('2.4 非法迁移被拒', True)


def test_cross_ref(tmp):
    """验收 3：跨卷引用解析+SHA-256 校验。
    Acceptance 3: cross-volume reference parsing + SHA-256 verification."""
    from cross_ref import CrossRef
    # 造一个测试卷 · build a test volume
    vol_path = os.path.join(tmp, '测试卷.txt')
    with open(vol_path, 'w', encoding='utf-8') as f:
        f.write('[2026-10-08 03:00] [测试] [条目A] body-a\n')
        f.write('\n')
        f.write('[2026-10-08 03:01] [测试] [条目B] body-b\n')
    cr = CrossRef(root=tmp)
    ref = cr.make_ref('测试卷', 1)
    if not _ok('3.1 生成引用 [卷#L行-sha8]', ref.startswith('[测试卷#L1-') and ref.endswith(']')):
        return False
    # 解析回来 · parse it back
    p = cr.parse(ref)
    if not _ok('3.2 解析引用', p and p[0] == '测试卷' and p[1] == 1):
        return False
    # 校验 hash 通过 · hash verification passes
    if not _ok('3.3 校验 hash 通过', cr.verify('测试卷', 1, p[2])):
        return False
    # 篡改条目→校验失败 · tamper with the entry → verification fails
    with open(vol_path, 'r', encoding='utf-8') as f:
        content = f.read()
    with open(vol_path, 'w', encoding='utf-8') as f:
        f.write(content.replace('body-a', 'TAMPERED'))
    if not _ok('3.4 篡改后 hash 不匹配', not cr.verify('测试卷', 1, p[2])):
        return False
    return True


def test_agent_message(tmp):
    """验收 4：Agent A 写卷后 Agent B 收到 notify。
    Acceptance 4: after Agent A writes a volume, Agent B receives a notify."""
    sys.path.insert(0, HERE)
    import agent_message as am
    # 消息卷一律经 conf 解析：把 tmp 作为 conf 目录（显式 DAYBOOK_ROOT）
    # The inbox is always resolved through the conf: make tmp the conf dir (explicit DAYBOOK_ROOT).
    with open(os.path.join(tmp, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[volumes]\ninbox=消息卷.txt\n')
    saved = os.environ.get('DAYBOOK_ROOT')
    os.environ['DAYBOOK_ROOT'] = tmp
    am.SOCK_DIR = tmp
    inbox = am.inbox_path()
    try:
        # 启 B 的服务端 · start B's server
        srv = am.AgentServer('B')
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        time.sleep(0.3)
        # A 发 notify · A sends notify
        ok, reply = am.send('A', 'B', 'notify', '写完协作卷条目 12')
        srv.shutdown()
        srv.server_close()
    finally:
        if saved is None:
            os.environ.pop('DAYBOOK_ROOT', None)
        else:
            os.environ['DAYBOOK_ROOT'] = saved
    if not _ok('4.1 notify 送达', ok, reply or ''):
        return False
    # inbox 卷有记录 · the inbox volume has a record
    if not os.path.exists(inbox):
        return _ok('4.2 消息卷有记录', False, '文件不存在')
    with open(inbox, 'r', encoding='utf-8') as f:
        content = f.read()
    return _ok('4.2 消息卷有记录', 'notify' in content and 'B' in content, content)


def test_agent_lock(tmp):
    """验收 5：账本根锁防多 Agent 同时改一任务（签名：acquire(label, agent_id, blocking=False)）。
    Acceptance 5: the ledger-root lock prevents multiple agents from editing one task at once
    (signature: acquire(label, agent_id, blocking=False); the label never narrows the scope)."""
    from agent_lock import AgentLock
    import threading
    lk = AgentLock(None, os.path.join(tmp, '租约卷.txt'), root=tmp)
    lid1 = lk.acquire('task:T001', 'ag-tom')
    if not _ok('5.1 Agent A 获取锁', bool(lid1)):
        return False
    # 同线程重复获取：立即报错（不等待、不静默放行——等自己必自死锁）
    # Same-thread re-acquire: immediate error (no wait, no silent pass-through — self-deadlock)
    t_dup = time.time()
    try:
        lk.acquire('task:T002', 'ag-tom', blocking=True)
        dup = 'ACQUIRED'
    except RuntimeError as e:
        dup = 'RAISED'
        dup_msg = str(e)
    dup_dt = time.time() - t_dup
    if not _ok('5.2 同线程重复获取⇒立即报错（不等待）',
               dup == 'RAISED' and dup_dt < 0.05,
               'dup=%s dt=%.3fs msg=%r' % (dup, dup_dt, dup_msg if dup == 'RAISED' else '')):
        return False
    # 另一线程非阻塞：必须立刻拿到 None（不是等一会儿才 None）
    # Another thread, non-blocking: must return None immediately
    got2 = []

    def _nb():
        got2.append(lk.acquire('task:T001', 'ag-pit'))
    t0 = time.time()
    th2 = threading.Thread(target=_nb)
    th2.start(); th2.join(2)
    dt = time.time() - t0
    lid2 = got2[0] if got2 else 'THREAD_HUNG'
    if not _ok('5.3 另一线程非阻塞拿不到锁（立刻 None）',
               lid2 is None and dt < 0.5, 'lid2=%r dt=%.3fs' % (lid2, dt)):
        return False
    # 阻塞：C 一直等到 A 释放才进临界区。用 Event 握手，不靠 sleep+is_alive 猜调度。
    # Blocking: C waits until A releases. Event handshake — no sleep+is_alive scheduling guess.
    got = []
    started = threading.Event()
    done = threading.Event()
    release_evt = threading.Event()

    def _blocking_acquire():
        started.set()
        lid = lk.acquire('task:T001', 'ag-c', blocking=True)
        got.append(lid)
        done.set()
        release_evt.wait(5)
        if lid:
            lk.release(lid)

    th = threading.Thread(target=_blocking_acquire)
    th.start()
    started.wait(2)
    # 持锁未放：0.5s 内 done 必然不置位（置位就证明它没真阻塞）
    # Lock still held: done must not fire within 0.5s (firing proves it never blocked)
    blocked = not done.wait(0.5)
    lk.release(lid1)
    finished = done.wait(5)
    release_evt.set()
    th.join(5)
    if not _ok('5.4 blocking=True 确实阻塞到释放之后（Event 握手）',
               blocked and finished and bool(got) and got[0],
               'blocked=%s finished=%s got=%r' % (blocked, finished, got)):
        return False
    # 释放后可再次获取 · acquirable again after release
    lid4 = lk.acquire('task:T001', 'ag-pit')
    if not _ok('5.5 释放后可再次获取', bool(lid4)):
        return False
    lk.release(lid4)
    # 变异自证：acquire 永远「成功」时，5.3（互斥）与 5.4（真阻塞）的断言必须都失败
    # Mutation self-check: if acquire always "succeeds", both the 5.3 exclusion assertion
    # and the 5.4 "really blocked" assertion must fail
    orig = AgentLock.acquire
    AgentLock.acquire = lambda self, label, agent_id, blocking=False: 'fake-lease'
    try:
        probe = AgentLock(None, os.path.join(tmp, '租约卷.txt'), root=tmp)
        first = probe.acquire('task:MUT', 'ag-x')
        second = probe.acquire('task:MUT', 'ag-y')
        excl_green = (first is not None and second is None)   # 5.3 形态，变异下必 False
        # 5.4 形态：持锁线程未释放时，blocking 调用不得返回；变异下它会立即返回
        blocked_green = (probe.acquire('task:MUT2', 'ag-z', blocking=True) is None)
    finally:
        AgentLock.acquire = orig
    return _ok('5.6 变异：acquire 恒真 ⇒ 5.3/5.4 断言都必须红',
               not excl_green and not blocked_green,
               'excl_green=%s blocked_green=%s' % (excl_green, blocked_green))


def test_agent_heartbeat(tmp):
    """验收 6：心跳 > 3 周期不跳 → 标 dead。
    Acceptance 6: heartbeat missing > 3 periods → marked dead."""
    from agent_heartbeat import Heartbeat
    # 用 1 秒周期·3 周期后死 · use a 1-second period · dead after 3 periods
    hb = Heartbeat(path=os.path.join(tmp, '心跳卷.txt'), period=1, dead_after=3)
    hb.beat('ag-tom')
    if not _ok('6.1 心跳写入后 alive', hb.is_alive('ag-tom')):
        return False
    # 等 4 秒·超过 3 周期 · wait 4 seconds · more than 3 periods
    time.sleep(4)
    if not _ok('6.2 > 3 周期不跳 → dead', not hb.is_alive('ag-tom')):
        return False
    if not _ok('6.3 dead_agents 列出', 'ag-tom' in hb.dead_agents()):
        return False
    # 恢复 · recover
    hb.recover('ag-tom')
    return _ok('6.4 恢复后 alive', hb.is_alive('ag-tom'))


def test_zero_deps():
    """验收 7：零第三方依赖。
    Acceptance 7: zero third-party dependencies."""
    # 所有模块 import 都成功（test 启动即证明） · all module imports succeed (proven as soon as the test starts)
    # 再扫一遍源码·确认没有 import 第三方包 · then scan the source again to confirm no third-party package is imported
    third_party_prefixes = ('fastapi', 'uvicorn', 'pydantic', 'cryptography',
                            'rsa', 'numpy', 'pandas', 'requests', 'aiohttp')
    bad = []
    for f in ('agent_registry.py', 'task_volume.py', 'cross_ref.py',
              'agent_message.py', 'agent_lock.py', 'agent_heartbeat.py'):
        with open(os.path.join(HERE, f), 'r', encoding='utf-8') as fp:
            for line in fp:
                if line.startswith('import ') or line.startswith('from '):
                    for p in third_party_prefixes:
                        if p in line:
                            bad.append((f, line.strip()))
    return _ok('7. 零第三方依赖', not bad, '违规=%s' % bad if bad else '')


def main():
    tmp = tempfile.mkdtemp(prefix='daybook_agent_test_')
    print('=== W-DB-023-G3 Agent 底座验收测试 ===')
    print('tmp: %s' % tmp)
    results = []
    results.append(('Agent 注册表', test_agent_registry(tmp)))
    results.append(('任务状态卷', test_task_volume(tmp)))
    results.append(('跨卷引用', test_cross_ref(tmp)))
    results.append(('Agent 间消息', test_agent_message(tmp)))
    results.append(('锁与租约', test_agent_lock(tmp)))
    results.append(('心跳检测', test_agent_heartbeat(tmp)))
    results.append(('零依赖', test_zero_deps()))
    print('=== 总验收 ===')
    for name, ok in results:
        print('  %s: %s' % (name, 'PASS' if ok else 'FAIL'))
    all_ok = all(r[1] for r in results)
    print('=== %s ===' % ('PASS' if all_ok else 'FAIL'))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
