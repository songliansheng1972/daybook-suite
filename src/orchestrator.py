#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""orchestrator.py —— daybook 智能体编排中心「司南」（零依赖·斯坦森 2026-10-08）
================================================================
名号：司南。语出《韩非子·有度》"先王立司南以端朝夕"——以器定方向，不测天时、不观星象。
      取义：方向由器定，不因问者而异。同一条，任何时刻、任何人来问，都得同一个下一手。
daybook 有两条产品线：① 账本本体（纯文本 append-only）；② MCP 接口。
本件是第三条、也是把前两条**焊成一个可跑闭环**的那件：**智能体编排中心**。

不造调度器，只把 daybook 底座上已有的六件原语接上**一个入口**：
    身份   agent_registry    HMAC-SHA256·不可伪造
    任务   task_volume       待办→进行中→完成→待审→已审（终态拒迁）
    锁     agent_lock        fcntl.flock + TTL 租约（认领并发互斥）
    在场   agent_heartbeat   心跳卷·缺 ≥ dead_after 周期判 dead
    消息   agent_message     Unix socket + 致= 寻址（可接）
    引用   cross_ref         [卷#L行-SHA8] 防篡改（可校）
    路由   本件               类 → 角色 → 人（**确定性查表·不推理**）

一个闭环：
    入伙(join) → 开单(open) → 认领(claim·加锁互斥) → 交活(submit·落报条[致=复审])
    → 取件(pull·查表定下一手) → 裁决(review·通过/驳回) → 结单(已审)
全程只 append 到 daybook 卷；真相在卷里，派生件（收件箱/看板）可删可重建。

三条戒律（与路由层同）：
    1. 只读**条头字段**（类/致/作者）与**关键词子串命中**，**绝不读正文语义做推理**（子串匹配是结构性校验，非语义理解）；
    2. **绝不写影子状态**——一切落到 append-only 卷；
    3. 路由表/角色表**人可读可改**，不藏在码里。

用法：
    python3 orchestrator.py join 汤姆
    python3 orchestrator.py who
    python3 orchestrator.py open "实现 X" --by 汤姆
    python3 orchestrator.py claim T001 ag-xxxx
    python3 orchestrator.py submit T001 ag-xxxx --to 皮特 --note "已提交"
    python3 orchestrator.py pull 皮特
    python3 orchestrator.py review T001 ag-yyyy 通过
    python3 orchestrator.py board
    python3 orchestrator.py alarm
    python3 orchestrator.py selftest
退出码：0 正常；1 alarm 有硬警；2 参数/文件错。
"""
import argparse
import io
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent_registry as _reg
import task_volume as _tv
import agent_heartbeat as _hb
import agent_lock as _lock
import daybook_append as _dba

DEFAULT_RULE = os.path.join(HERE, 'orchestration_routing.conf')
DEFAULT_ROLES = os.path.join(HERE, 'orchestration_roles.conf')

HEAD = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)\]\s*(\[.*)$')
BRK = re.compile(r'\[([^\]]*)\]')
SPLIT_TO = re.compile(r'[,，/]')


# ── 路由：类[：关键词] → 角色；角色 → 人 ──────────────────────────────
def load_rules(path):
    rules = []
    if not os.path.exists(path):
        return rules
    for line in io.open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        left, role = line.split('=', 1)
        left, role = left.strip(), role.strip()
        if ':' in left or '：' in left:
            k, kw = re.split(r'[:：]', left, maxsplit=1)
            rules.append((k.strip(), kw.strip(), role))
        else:
            rules.append((left, None, role))
    return rules


def load_roles(path):
    roles = {}
    if not os.path.exists(path):
        return roles
    for line in io.open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        roles[k.strip()] = v.strip()
    return roles


def route(kind, title, body, author, to, rules, roles):
    """算一条的下一手。返回 (人, 依据)。确定性：定于查表，不定于推理。

    所读输入：条头字段（类/致/作者）＋ 标题/正文的**关键词子串命中**（结构性比对，
    非语义理解）——合戒律①之精神，非「只读条头」之字面。#279 措辞订正。"""
    if to:
        return to, '条头[致=]'
    hay = (title or '') + '\n' + (body or '')
    best = None
    for (k, kw, role) in rules:
        if k != kind:
            continue
        if kw is None:
            best = (role, '类=%s' % kind)
        elif kw in hay:
            best = (role, '类=%s 命中「%s」' % (kind, kw))
    if best is None:
        return None, '无规则→广播'
    role, why = best
    val = roles.get(role, '')
    if val.startswith('@非作者'):
        base = val.split(':', 1)[1] if ':' in val else ''
        pool = [x for x in SPLIT_TO.split(roles.get(base, '')) if x.strip()]
        if not author:
            return None, '待定（作者缺）'
        rest = [x for x in pool if x != author]
        if not rest:
            return None, '待定（无非作者可选）'
        return '/'.join(rest), why + '·非作者(剔 %s)' % author
    names = [x for x in SPLIT_TO.split(val) if x.strip()]
    return ('/'.join(names) if names else None), why


def parse_ledger(path):
    """解析 daybook 原生卷（[时间][类][标题][作者][致=]?）。"""
    entries, cur = [], None
    if not os.path.exists(path):
        return entries
    from safeio import read_vol
    text, _enc, _why = read_vol(path)
    for line in text.splitlines():
        line = line.rstrip('\n')
        m = HEAD.match(line)
        if m:
            if cur is not None:
                entries.append(cur)
            # 抓行首连续的 [xxx] 段（段间只允许空白）·不抓正文里的 [...]
            _hm = re.match(r'^((?:\s*\[[^\]]*\])+)', m.group(2))
            _segs = BRK.findall(_hm.group(1)) if _hm else []
            kind = _segs[0] if len(_segs) > 0 else ''
            title = _segs[1] if len(_segs) > 1 else ''
            # 作者可选·致= 段可在第 3 或第 4 位
            author = ''
            to = ''
            for _s in _segs[2:]:
                if _s.startswith('致='):
                    to = _s[2:]
                elif not author:
                    author = _s
            e = {'time': m.group(1), 'kind': kind, 'title': title,
                 'author': author, 'to': to, 'body': []}
            cur = e
        elif cur is not None:
            cur['body'].append(line)
    if cur is not None:
        entries.append(cur)
    return entries


class Hub:
    """编排中心：六件原语 + 路由，统一入口。"""

    def __init__(self, root=None, rule=None, roles=None):
        self.root = root or HERE
        self.reg = _reg.Registry(os.path.join(self.root, '注册卷.txt'))
        self.tv = _tv.TaskVolume(os.path.join(self.root, '任务卷.txt'))
        self.hb = _hb.Heartbeat(os.path.join(self.root, '心跳卷.txt'))
        self.lock = _lock.AgentLock(os.path.join(self.root, '.locks'),
                                    os.path.join(self.root, '租约卷.txt'))
        self.ledger = os.path.join(self.root, '编排卷.txt')
        self.rules = load_rules(rule or DEFAULT_RULE)
        self.roles = load_roles(roles or DEFAULT_ROLES)

    # —— 内部 ——
    def _log(self, kind, title, msg, author, to=None):
        to_ids = self._resolve_to(to) if to else None
        _dba.append_one(self.ledger, kind, title, msg or title, author=author, to=to_ids)

    def _resolve_to(self, to):
        """把 to 里的 token（名字或 id）解析为已注册 agent_id；解析不出的原样保留。"""
        by_name = {a.name: a.agent_id for a in self.reg.list()}
        out = []
        for t in SPLIT_TO.split(to):
            t = t.strip()
            if not t:
                continue
            out.append(by_name.get(t, t))
        return ','.join(out)

    def _to_names(self, to):
        """agent_id → name（若可解析），便于人读。"""
        by_id = {a.agent_id: a.name for a in self.reg.list()}
        return ','.join(by_id.get(t.strip(), t.strip()) for t in SPLIT_TO.split(to) if t.strip())

    def _name_of(self, aid):
        """agent_id → name。路由的角色池用人名，去「非作者」时须用名字比。"""
        a = self.reg.lookup(aid) if aid else None
        return a.name if a else (aid or '')

    def _aid_of(self, token):
        """名字或 id → id（未注册的原样保留）。作者 ID 红线：卷内记 id。"""
        if not token:
            return token
        by_name = {a.name: a.agent_id for a in self.reg.list()}
        return by_name.get(token, token)

    # —— 身份/在场 ——
    def join(self, name):
        aid, secret = self.reg.register(name)
        self.hb.beat(aid)
        self._log('编', '到场', '%s 加入编排' % name, aid)
        return aid, secret

    def leave(self, aid):
        self.reg.revoke(aid)
        self._log('编', '退场', 'agent 退场', aid)

    def who(self):
        return [(a.agent_id, a.name, self.hb.is_alive(a.agent_id), a.revoked)
                for a in self.reg.list()]

    # —— 任务 ——
    def open(self, title, by):
        by_id = self._aid_of(by)
        tid = self.tv.create(by_id, title)
        self._log('工', title, '开单 %s' % tid, by_id)
        return tid

    def claim(self, tid, aid):
        """认领：加锁 → 校验当前态 → 迁移进行中 → 解锁。锁使「读-判-写」原子。"""
        lease = self.lock.acquire('task:%s' % tid, aid, ttl=60)
        if lease is None:
            return False, '并发争用：锁未获，请重试'
        try:
            hist = self.tv.get(tid)
            if not hist:
                return False, '任务 %s 不存在' % tid
            cur = hist[-1][1]
            if cur != '待办':
                return False, '状态=%s，不可认领' % cur
            self.tv.transition(tid, '进行中', aid, '认领')
            self._log('认领', tid, '认领 %s' % tid, aid)
        finally:
            self.lock.release(lease)
        return True, '认领成功'

    def submit(self, tid, aid, note='', to=None):
        """交活：进行中 → 完成 → 待审，落一条报条（可带 [致=]）。"""
        self.tv.transition(tid, '完成', aid, note or '交活')
        self.tv.transition(tid, '待审', aid, note or '待审')
        self._log('报', '交活 %s' % tid, note or '交活', aid, to=to)
        person, why = self.route_for('报', '交活 %s' % tid, note, self._name_of(aid), to)
        return person, why

    def review(self, tid, aid, verdict, note=''):
        """裁决：通过→已审；驳回→进行中（返工）。"""
        if verdict in ('通过', 'pass', '已审', 'ok'):
            self.tv.transition(tid, '已审', aid, note or '通过')
            self._log('审', '裁决 %s·通过' % tid, note or '通过', aid)
            return '已审'
        self.tv.transition(tid, '进行中', aid, note or '驳回')
        self._log('审', '裁决 %s·驳回' % tid, note or '驳回', aid)
        return '进行中'

    def route_for(self, kind, title, body, author, to):
        return route(kind, title, body, author, to, self.rules, self.roles)

    def board(self):
        return self.tv.list()

    # —— 取件（派生视图·可删可重建） ——
    def pull(self, who):
        """按路由表算下一手，列出落脚于 who 且 who 尚未落条回应的条。"""
        entries = parse_ledger(self.ledger)
        names = {a.name: a.agent_id for a in self.reg.list()}
        who_id = names.get(who, who)
        pend = []
        for i, e in enumerate(entries):
            person, why = route(e['kind'], e['title'], '\n'.join(e['body']),
                                self._name_of(e['author']), e['to'], self.rules, self.roles)
            targets = [t.strip() for t in SPLIT_TO.split(person or '') if t.strip()]
            if who not in targets and who_id not in targets:
                continue
            replied = any(entries[j]['author'] in (who, who_id) for j in range(i + 1, len(entries)))
            if not replied:
                pend.append((e, person, why))
        return pend

    # —— 体检 ——
    def alarm(self):
        issues = []
        dead = self.hb.dead_agents()
        if dead:
            issues.append('失联 agent：%s' % '、'.join(dead))
        for tid, st, ag, ct, _hist in self.tv.list():
            if st in ('进行中', '待审') and ag in dead:
                issues.append('孤儿任务：%s [%s] 由失联 %s 持有' % (tid, st, ag))
            if st == '完成':
                issues.append('滞留：%s 停在[完成]、未推进[待审]' % tid)
        # 任务卷里出现、注册卷里没有的负责人（幽灵）
        reg_ids = {a.agent_id for a in self.reg.list()}
        for tid, st, ag, ct, _hist in self.tv.list():
            if ag and ag not in reg_ids:
                issues.append('幽灵负责人：%s 的 %s 未在注册卷' % (tid, ag))
        return issues


# ── CLI ──────────────────────────────────────────────────────────────
def _print_who(hub):
    rows = hub.who()
    if not rows:
        print('（注册卷空·先 join）')
        return
    print('在场 %d 人：' % len(rows))
    for aid, name, alive, revoked in rows:
        print('  %-16s %-6s %s%s' % (aid, name, '在线' if alive else '离线',
                                     '（已吊销）' if revoked else ''))


def _print_board(hub):
    tasks = hub.board()
    if not tasks:
        print('（任务卷空·先 open）')
        return
    order = ['待办', '进行中', '完成', '待审', '已审', '取消']
    bucket = {s: [] for s in order}
    for tid, st, ag, ct, _h in tasks:
        bucket.setdefault(st, []).append((tid, ag, ct))
    print('看板（%d 单）：' % len(tasks))
    for s in order:
        items = bucket.get(s) or []
        if not items:
            continue
        print('  [%s] %d 单' % (s, len(items)))
        for tid, ag, ct in items:
            print('    %-6s %-16s %s' % (tid, ag, ct))


def _print_pull(hub, who):
    pend = hub.pull(who)
    print('取件 %s：待办 %d 条' % (who, len(pend)))
    for e, person, why in pend:
        to = hub._to_names(e['to']) if e['to'] else (person or '广播')
        print('  [%s] [%s] → %s  %s  ← %s' % (e['time'][11:], e['kind'], to, e['title'], why))


def main(argv=None):
    ap = argparse.ArgumentParser(description='daybook 智能体编排中心')
    ap.add_argument('--root', default=HERE, help='卷根目录（默认本包自身）')
    ap.add_argument('--rule', default=DEFAULT_RULE)
    ap.add_argument('--roles', default=DEFAULT_ROLES)
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('join'); p.add_argument('name')
    p = sub.add_parser('leave'); p.add_argument('agent_id')
    sub.add_parser('who')
    p = sub.add_parser('open'); p.add_argument('title'); p.add_argument('--by', required=True)
    p = sub.add_parser('claim'); p.add_argument('tid'); p.add_argument('agent_id')
    p = sub.add_parser('submit')
    p.add_argument('tid'); p.add_argument('agent_id')
    p.add_argument('--to', default=''); p.add_argument('--note', default='')
    p = sub.add_parser('review')
    p.add_argument('tid'); p.add_argument('agent_id'); p.add_argument('verdict')
    p.add_argument('--note', default='')
    p = sub.add_parser('pull'); p.add_argument('who')
    sub.add_parser('board')
    sub.add_parser('alarm')
    sub.add_parser('selftest')

    args = ap.parse_args(argv)
    if args.cmd == 'selftest':
        return _selftest()
    if not args.cmd:
        ap.print_help()
        return 2

    hub = Hub(root=args.root, rule=args.rule, roles=args.roles)

    if args.cmd == 'join':
        aid, secret = hub.join(args.name)
        print('agent_id: %s' % aid)
        print('secret:   %s' % secret)
        print('（secret 仅此刻可见·请妥善保存）')
    elif args.cmd == 'leave':
        hub.leave(args.agent_id); print('已吊销：%s' % args.agent_id)
    elif args.cmd == 'who':
        _print_who(hub)
    elif args.cmd == 'open':
        print('task_id: %s (待办)' % hub.open(args.title, args.by))
    elif args.cmd == 'claim':
        ok, msg = hub.claim(args.tid, args.agent_id)
        print(('OK  ' if ok else 'FAIL ') + msg)
        return 0 if ok else 1
    elif args.cmd == 'submit':
        person, why = hub.submit(args.tid, args.agent_id, args.note, args.to)
        print('已交活 %s → 待审；下一手=%s（%s）' % (args.tid, person or '广播', why))
    elif args.cmd == 'review':
        st = hub.review(args.tid, args.agent_id, args.verdict, args.note)
        print('裁决 %s：→ %s' % (args.tid, st))
    elif args.cmd == 'pull':
        _print_pull(hub, args.who)
    elif args.cmd == 'board':
        _print_board(hub)
    elif args.cmd == 'alarm':
        issues = hub.alarm()
        print('== 编排体检 ==')
        for it in issues:
            print('  · ' + it)
        hard = any('失联' in it or '孤儿' in it for it in issues)
        print('判：%s' % ('★ 有硬警' if hard else '干净'))
        return 1 if hard else 0
    return 0


def _selftest():
    """端到端验收：临时根目录跑通 入伙→开单→认领→交活→取件→裁决 全链。"""
    import shutil
    import tempfile
    root = tempfile.mkdtemp(prefix='db_orch_')
    ok = True

    def chk(cond, label):
        nonlocal ok
        print('  [%s] %s' % ('PASS' if cond else 'FAIL', label))
        ok = ok and bool(cond)

    try:
        hub = Hub(root=root)          # 规则取默认两份 conf（orchestration_routing.conf / orchestration_roles.conf）

        aid, _ = hub.join('汤姆')
        bid, _ = hub.join('皮特')
        chk(len(hub.who()) == 2, '入伙 2 人')

        tid = hub.open('实现 MCP resources/list', aid)
        st = hub.tv.get(tid)[-1][1]
        chk(st == '待办', '开单 → 待办')

        okc, _msg = hub.claim(tid, aid)
        chk(okc and hub.tv.get(tid)[-1][1] == '进行中', '认领 → 进行中')

        # 并发争用：再认领同单应失败（锁 + 状态校验）
        okc2, _ = hub.claim(tid, bid)
        chk(not okc2, '重复认领被拒')

        person, why = hub.submit(tid, aid, '已实现', to=None)
        chk(hub.tv.get(tid)[-1][1] == '待审', '交活 → 待审')
        chk('皮特' in (person or ''), '报条路由到非作者（剔汤姆·得 %s·%s）' % (person, why))

        pend = hub.pull('皮特')
        chk(len(pend) >= 1, '取件：皮特收到交活单')

        st = hub.review(tid, bid, '通过', '复核通过')
        chk(st == '已审' and hub.tv.get(tid)[-1][1] == '已审', '裁决通过 → 已审')

        # 驳回返工
        tid2 = hub.open('第二单', aid)
        hub.claim(tid2, aid)
        hub.submit(tid2, aid, '初版')
        hub.review(tid2, bid, '驳回', '不行')
        chk(hub.tv.get(tid2)[-1][1] == '进行中', '驳回 → 返工（进行中）')

        issues = hub.alarm()
        print('  体检：' + '；'.join(issues))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print('== 编排中心自检：%s ==' % ('全绿' if ok else '有红'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
