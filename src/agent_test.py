#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 协作底座集成测试（W-DB-023-G3·第 7 项）
================================================
覆盖工单验收标准 7 项：
  1. 3 个 Agent 可同时注册·各自独立身份
  2. 任务卷可流转：待办→进行中→完成→待审→已审
  3. 跨卷引用可解析+校验 SHA-256
  4. Agent A 写卷后·Agent B 收到 notify
  5. 文件锁可防多 Agent 同时改一任务
  6. Agent 心跳 > 3 周期不跳 → 标 dead
  7. 零第三方依赖
退出码：0=PASS 1=FAIL
"""
import os, sys, time, tempfile, shutil, subprocess, threading

HERE = os.path.dirname(os.path.abspath(__file__))


def _ok(name, cond, detail=''):
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', name, (' · ' + detail) if detail else ''))
    sys.stdout.flush()
    return bool(cond)


def test_agent_registry(tmp):
    """验收 1：3 个 Agent 同时注册·各自独立身份；验收 7：零依赖。"""
    from agent_registry import Registry
    sys.path.insert(0, HERE)
    # import 已成功=零依赖成立
    reg = Registry(os.path.join(tmp, '注册卷.txt'))
    agents = [reg.register(n) for n in ('汤姆', '史泰龙', '皮特')]
    ids = [a[0] for a in agents]
    # 各自独立身份：agent_id 全不同
    if not _ok('1.1 3 Agent 各自独立身份', len(set(ids)) == 3, 'ids=%s' % ids):
        return False
    # 验签
    aid, _ = agents[0]
    sig = reg.sign(aid, 'payload-测试')
    if not _ok('1.2 签名生成+验证', reg.verify(aid, 'payload-测试', sig)):
        return False
    # 错签名被拒
    if not _ok('1.3 错签名被拒', not reg.verify(aid, 'payload-测试', sig + 'x')):
        return False
    # 吊销后验签失败
    reg.revoke(aid)
    if not _ok('1.4 吊销后验签失败', not reg.verify(aid, 'payload-测试', sig)):
        return False
    return True


def test_task_volume(tmp):
    """验收 2：任务流转 待办→进行中→完成→待审→已审。"""
    from task_volume import TaskVolume
    tv = TaskVolume(os.path.join(tmp, '任务卷.txt'))
    tid = tv.create('ag-tom', '实现 MCP resources/list')
    if not _ok('2.1 创建任务', tid.startswith('T')):
        return False
    # 正向迁移
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
    # 终态不可再迁
    try:
        tv.transition(tid, '进行中', 'ag-tom', '返工')
        return _ok('2.3 终态拒迁', False, '终态不该能迁')
    except PermissionError:
        if not _ok('2.3 终态拒迁', True):
            return False
    # 非法迁移
    tid2 = tv.create('ag-pit', '另一任务')
    try:
        tv.transition(tid2, '完成', 'ag-pit', '跳过')  # 待办→完成 非法
        return _ok('2.4 非法迁移被拒', False, '不该允许跳过进行中')
    except PermissionError:
        return _ok('2.4 非法迁移被拒', True)


def test_cross_ref(tmp):
    """验收 3：跨卷引用解析+SHA-256 校验。"""
    from cross_ref import CrossRef
    # 造一个测试卷
    vol_path = os.path.join(tmp, '测试卷.txt')
    with open(vol_path, 'w', encoding='utf-8') as f:
        f.write('[2026-10-08 03:00] [测试] [条目A] body-a\n')
        f.write('\n')
        f.write('[2026-10-08 03:01] [测试] [条目B] body-b\n')
    cr = CrossRef(root=tmp)
    ref = cr.make_ref('测试卷', 1)
    if not _ok('3.1 生成引用 [卷#L行-sha8]', ref.startswith('[测试卷#L1-') and ref.endswith(']')):
        return False
    # 解析回来
    p = cr.parse(ref)
    if not _ok('3.2 解析引用', p and p[0] == '测试卷' and p[1] == 1):
        return False
    # 校验 hash 通过
    if not _ok('3.3 校验 hash 通过', cr.verify('测试卷', 1, p[2])):
        return False
    # 篡改条目→校验失败
    with open(vol_path, 'r', encoding='utf-8') as f:
        content = f.read()
    with open(vol_path, 'w', encoding='utf-8') as f:
        f.write(content.replace('body-a', 'TAMPERED'))
    if not _ok('3.4 篡改后 hash 不匹配', not cr.verify('测试卷', 1, p[2])):
        return False
    return True


def test_agent_message(tmp):
    """验收 4：Agent A 写卷后 Agent B 收到 notify。"""
    sys.path.insert(0, HERE)
    import agent_message as am
    # 改 inbox 路径到 tmp
    am.INBOX_VOL = os.path.join(tmp, '消息卷.txt')
    am.SOCK_DIR = tmp
    # 启 B 的服务端
    srv = am.AgentServer('B')
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    # A 发 notify
    ok, reply = am.send('A', 'B', 'notify', '写完协作卷条目 12')
    srv.shutdown()
    srv.server_close()
    if not _ok('4.1 notify 送达', ok, reply or ''):
        return False
    # inbox 卷有记录
    if not os.path.exists(am.INBOX_VOL):
        return _ok('4.2 消息卷有记录', False, '文件不存在')
    with open(am.INBOX_VOL, 'r', encoding='utf-8') as f:
        content = f.read()
    return _ok('4.2 消息卷有记录', 'notify' in content and 'B' in content, content)


def test_agent_lock(tmp):
    """验收 5：文件锁防多 Agent 同时改一任务。"""
    from agent_lock import AgentLock
    lk = AgentLock(lock_dir=os.path.join(tmp, '.locks'),
                   lease_vol=os.path.join(tmp, '租约卷.txt'))
    lid1 = lk.acquire('task:T001', 'ag-tom', ttl=60)
    if not _ok('5.1 Agent A 获取锁', bool(lid1)):
        return False
    # Agent B 拿不到
    lid2 = lk.acquire('task:T001', 'ag-pit', ttl=60)
    if not _ok('5.2 Agent B 同资源拿不到锁', lid2 is None):
        return False
    # A 释放
    lk.release(lid1)
    # B 现在能拿到
    lid3 = lk.acquire('task:T001', 'ag-pit', ttl=60)
    if not _ok('5.3 A 释放后 B 能拿到', bool(lid3)):
        return False
    lk.release(lid3)
    return True


def test_agent_heartbeat(tmp):
    """验收 6：心跳 > 3 周期不跳 → 标 dead。"""
    from agent_heartbeat import Heartbeat
    # 用 1 秒周期·3 周期后死
    hb = Heartbeat(path=os.path.join(tmp, '心跳卷.txt'), period=1, dead_after=3)
    hb.beat('ag-tom')
    if not _ok('6.1 心跳写入后 alive', hb.is_alive('ag-tom')):
        return False
    # 等 4 秒·超过 3 周期
    time.sleep(4)
    if not _ok('6.2 > 3 周期不跳 → dead', not hb.is_alive('ag-tom')):
        return False
    if not _ok('6.3 dead_agents 列出', 'ag-tom' in hb.dead_agents()):
        return False
    # 恢复
    hb.recover('ag-tom')
    return _ok('6.4 恢复后 alive', hb.is_alive('ag-tom'))


def test_zero_deps():
    """验收 7：零第三方依赖。"""
    # 所有模块 import 都成功（test 启动即证明）
    # 再扫一遍源码·确认没有 import 第三方包
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
