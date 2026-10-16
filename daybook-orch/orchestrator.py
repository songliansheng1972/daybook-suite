#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""orchestrator.py —— daybook 智能体编排中心「司南」（零依赖·斯坦森 2026-10-08）
orchestrator.py —— daybook agent orchestration hub "Sinan" (zero dependencies · Statham · 2026-10-08)
================================================================
名号：司南。语出《韩非子·有度》"先王立司南以端朝夕"——以器定方向，不测天时、不观星象。
Name: Sinan. From Han Feizi · Youdu: "the ancient kings set up the south-pointer to fix morning and evening" — direction is set by an instrument, not by reading the sky or watching the stars.
      取义：方向由器定，不因问者而异。同一条，任何时刻、任何人来问，都得同一个下一手。
      Meaning: the direction is fixed by the instrument, not by who asks. For the same entry, at any time, whoever asks, you get the same next hand.
daybook 有两条产品线：① 账本本体（纯文本 append-only）；② MCP 接口。
daybook has two product lines: ① the ledger proper (plain-text append-only); ② the MCP interface.
本件是第三条、也是把前两条**焊成一个可跑闭环**的那件：**智能体编排中心**。
This file is the third, and the one that **welds the first two into a runnable closed loop**: the **agent orchestration hub**.

不造调度器，只把 daybook 底座上已有的六件原语接上**一个入口**：
No scheduler is built; this merely wires the six existing primitives of the daybook base to **one entry point**:
    身份   agent_registry    HMAC-SHA256·不可伪造
    identity  agent_registry    HMAC-SHA256 · unforgeable
    任务   task_volume       待办→进行中→完成→待审→已审（终态拒迁）
    task      task_volume       todo → in-progress → done → pending-review → reviewed (terminal states reject transitions)
    锁     agent_lock        fcntl.flock + TTL 租约（认领并发互斥）
    lock      agent_lock        fcntl.flock + TTL lease (mutual exclusion on claim)
    在场   agent_heartbeat   心跳卷·缺 ≥ dead_after 周期判 dead
    presence  agent_heartbeat   heartbeat volume · missing ≥ dead_after periods marks dead
    消息   agent_message     Unix socket + 致= 寻址（可接）
    message   agent_message     Unix socket + "致=" addressing (connectable)
    引用   cross_ref         [卷#L行-SHA8] 防篡改（可校）
    reference cross_ref         [volume#Lline-SHA8] tamper-proof (verifiable)
    路由   本件               类 → 角色 → 人（**确定性查表·不推理**）
    routing  this file         class → role → person (**deterministic table lookup · no reasoning**)

一个闭环：
A closed loop:
    入伙(join) → 开单(open) → 认领(claim·加锁互斥) → 交活(submit·落报条[致=复审])
    join → open → claim (lock-mutual-exclusion) → submit (writes a report entry [致=review])
    → 取件(pull·查表定下一手) → 裁决(review·通过/驳回) → 结单(已审)
    → pull (table lookup decides the next hand) → review (pass/reject) → close (reviewed)
全程只 append 到 daybook 卷；真相在卷里，派生件（收件箱/看板）可删可重建。
The whole flow only appends to daybook volumes; the truth is in the volumes, and derived views (inbox/board) can be deleted and rebuilt.

三条戒律（与路由层同）：
Three commandments (same as the routing layer):
    1. 只读**条头字段**（类/致/作者）与**关键词子串命中**，**绝不读正文语义做推理**（子串匹配是结构性校验，非语义理解）；
    1. Read only the **entry-header fields** (class/致= /author) and **keyword substring hits**, and **never read body semantics to reason** (substring matching is a structural check, not semantic understanding);
    2. **绝不写影子状态**——一切落到 append-only 卷；
    2. **Never write shadow state** — everything lands in append-only volumes;
    3. 路由表/角色表**人可读可改**，不藏在码里。
    3. The routing/role tables are **human-readable and human-editable**, not hidden in code.

用法：
Usage:
    python3 orchestrator.py join 汤姆
    python3 orchestrator.py who
    python3 orchestrator.py open "实现 X" --by 汤姆
    python3 orchestrator.py claim T001 ag-xxxx
    python3 orchestrator.py submit T001 ag-xxxx --to 皮特 --note "已提交"
    python3 orchestrator.py pull 皮特
    python3 orchestrator.py review T001 ag-yyyy 通过
    python3 orchestrator.py board
    python3 orchestrator.py alarm
    python3 orchestrator.py digest [--vol 卷] [--cls 类] [--push 收件人]   # v3.1 读多级目录·分发摘要
    python3 orchestrator.py selftest
退出码：0 正常；1 alarm 有硬警；2 参数/文件错。
Exit codes: 0 normal; 1 alarm has a hard warning; 2 argument/file error.
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

# ── 角色名别名（英文为准·中文兼容）/ role aliases (English canonical, Chinese legacy) ──
ROLE_ALIAS = {'施工': 'build', '复审': 'review', '返工': 'rework', '终审': 'final', '广播': 'broadcast'}


def canon_role(name):
    """角色名归一。Canonical role name."""
    return ROLE_ALIAS.get(name, name)


def canon_rolespec(v):
    """角色表达式归一：'@非作者:施工' → '@non-author:build'。
    Canonical role spec: legacy '@非作者:<role>' → '@non-author:<role>'."""
    v = (v or '').strip()
    for pre in ('@非作者', '@non-author'):
        if v.startswith(pre):
            rest = v[len(pre):]
            if rest[:1] in (':', '：'):
                return '@non-author:' + canon_role(rest[1:].strip())
            return '@non-author'
    return v


# ── 字段名别名（英文为准·中文兼容）/ field aliases (English canonical, Chinese legacy) ──
#   旧版 daybook_multidx 产出的目录表头为中文，升级后须照读 ⇒ 读表头时一律归一。
#   Legacy multidx wrote a Chinese header; after the rename we must still read it,
#   so every header cell is normalized on read.
FIELD_ALIAS = {'卷': 'volume', '二级': 'level2', '行号': 'line', '时间': 'time',
               '类': 'category', '作者': 'author', '标题': 'title'}


def canon_field(name):
    """字段名归一。Canonical field name."""
    return FIELD_ALIAS.get(name, name)

HEAD = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)\]\s*(\[.*)$')
BRK = re.compile(r'\[([^\]]*)\]')
SPLIT_TO = re.compile(r'[,，/]')


def make_entry_ref(root, vol, lineno):
    """生成互见引用 [卷#L行-SHA8]（v3.1）。复用 cross_ref 哈希算法·卷路径按 conf 卷表解析。失败返 ''。
    Generate a cross-reference [volume#Lline-SHA8] (v3.1). Reuses the cross_ref hashing algorithm · the volume path is resolved via the conf volume table. Returns '' on failure."""
    try:
        from cross_ref import CrossRef
    except Exception:
        return ''
    vols = _load_volumes(root)

    def _vp(v, _vols=vols, _root=root):
        rel = _vols.get(v)
        if not rel:
            raise KeyError('volume %s not in conf volume table' % v)
        return rel if os.path.isabs(rel) else os.path.join(_root, rel)

    try:
        cr = CrossRef(root=root)
        cr._vol_path = _vp
        return cr.make_ref(vol, int(lineno))
    except Exception:
        return ''


# ── 路由：类[：关键词] → 角色；角色 → 人 ──────────────────────────────
# Routing: class[:keyword] → role; role → person
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
            rules.append((k.strip(), kw.strip(), canon_role(role)))
        else:
            rules.append((left, None, canon_role(role)))
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
        roles[canon_role(k.strip())] = canon_rolespec(v)
    return roles


# ── v3.1 四库式多级目录：分发接上目录（读派生件·缺则原文兜底）──────────
# v3.1 four-library-style multi-level directory: distribution hooked to the directory (reads derived artifacts · falls back to raw text if absent)
def _load_volumes(root):
    """读 <root>/daybook.conf [卷] 表 → {卷名: 相对/绝对路径}。缺则 {}。
    Read the <root>/daybook.conf [volumes] table → {volume name: relative/absolute path}. {} if absent."""
    path = os.path.join(root, 'daybook.conf')
    vols, sec = {}, None
    if not os.path.exists(path):
        return vols
    for line in io.open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = re.match(r'^\[(.+)\]$', line.strip())
        if m:
            sec = m.group(1)
            continue
        if sec in ('volumes', '卷') and '=' in line:
            k, v = line.split('=', 1)
            vols[k.strip()] = v.strip()
    return vols


def read_multidx_rows(root):
    """读 <root>/multilevel/*_catalog.tsv（daybook_multidx 之产出；旧名 *_目录.tsv 亦认）。
    返回 (rows, 来源)。来源 ∈ {'catalog','volume-fallback'}。
    Read <root>/multilevel/*_catalog.tsv (the output of daybook_multidx; legacy *_目录.tsv also accepted).
    Returns (rows, source). source ∈ {'catalog','volume-fallback'}."""
    d = os.path.join(root, 'multilevel')
    rows = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not (fn.endswith('_catalog.tsv') or fn.endswith('_目录.tsv')):
                continue
            try:
                lines = [l.rstrip('\n') for l in io.open(os.path.join(d, fn), encoding='utf-8')
                         if l.strip()]
            except OSError:
                continue
            if not lines:
                continue
            hdr = [canon_field(h) for h in lines[0].split('\t')]  # 旧中文表头照读 / legacy Chinese header still read
            for l in lines[1:]:
                cells = l.split('\t')
                if len(cells) < len(hdr):
                    cells = cells + [''] * (len(hdr) - len(cells))
                rows.append(dict(zip(hdr, cells)))
    if rows:
        return rows, 'catalog'
    # 兜底：直读在册卷原文·自建 部(卷)/类(kind)/属(条目)（orch 单包自持可跑）
    # Fallback: read the registered volumes' raw text directly and build 部(volume)/类(kind)/属(entry) ourselves (so the orch package runs standalone)
    for name, rel in _load_volumes(root).items():
        path = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        _, entries = _scan_vol_rows(path)
        for e in entries:
            rows.append({'volume': name, 'level2': e['kind'], 'line': str(e['lineno']),
                         'time': e['time'], 'category': e['kind'],
                         'author': e['author'], 'title': e['title']})
    return rows, 'volume-fallback'


def _scan_vol_rows(path):
    """轻量扫卷：逐行找条目头·记录行号与条头字段。返回 (text, entries)。
    Lightweight volume scan: find entry headers line by line · record line numbers and header fields. Returns (text, entries)."""
    from safeio import read_vol
    text, _enc, _why = read_vol(path)
    entries, cur = [], None
    for i, line in enumerate(text.splitlines(), 1):
        m = HEAD.match(line.rstrip('\n'))
        if m:
            if cur is not None:
                entries.append(cur)
            hm = re.match(r'^((?:\s*\[[^\]]*\])+)', m.group(2))
            segs = BRK.findall(hm.group(1)) if hm else []
            kind = segs[0] if len(segs) > 0 else ''
            title = segs[1] if len(segs) > 1 else ''
            author = ''
            for s in segs[2:]:
                if s.startswith('致='):
                    continue
                if not author:
                    author = s
            cur = {'lineno': i, 'time': m.group(1), 'kind': kind,
                   'title': title, 'author': author}
    if cur is not None:
        entries.append(cur)
    return text, entries


def route(kind, title, body, author, to, rules, roles):
    """算一条的下一手。返回 (人, 依据)。确定性：定于查表，不定于推理。

    所读输入：条头字段（类/致/作者）＋ 标题/正文的**关键词子串命中**（结构性比对，
    非语义理解）——合戒律①之精神，非「只读条头」之字面。#279 措辞订正。
    Compute the next hand for an entry. Returns (person, basis). Deterministic: decided by table lookup, not by reasoning.
    Inputs read: entry-header fields (class/致= /author) + **keyword substring hits** in the title/body (a structural comparison,
    not semantic understanding) — matching the spirit of commandment ①, not the letter of "read only the header". #279 wording fix."""
    if to:
        return to, '条头[致=]'
    hay = (title or '') + '\n' + (body or '')
    best = None
    for (k, kw, role) in rules:
        if k != kind:
            continue
        if kw is None:
            best = (role, 'category=%s' % kind)
        elif kw in hay:
            best = (role, 'category=%s 命中「%s」' % (kind, kw))
    if best is None:
        return None, '无规则→广播'
    role, why = best
    val = roles.get(role, '')
    if val.startswith('@non-author'):
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
    """解析 daybook 原生卷（[时间][类][标题][作者][致=]?）。
    Parse a native daybook volume ([time][class][title][author][致=]?)."""
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
            # Capture the consecutive [xxx] segments at the start of the line (only whitespace allowed between them) · do not capture [...] in the body
            _hm = re.match(r'^((?:\s*\[[^\]]*\])+)', m.group(2))
            _segs = BRK.findall(_hm.group(1)) if _hm else []
            kind = _segs[0] if len(_segs) > 0 else ''
            title = _segs[1] if len(_segs) > 1 else ''
            # 作者可选·致= 段可在第 3 或第 4 位
            # Author is optional · the 致= segment may be in the 3rd or 4th position
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
    """编排中心：六件原语 + 路由，统一入口。
    Orchestration hub: the six primitives + routing, under a single entry point."""

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
    # —— Internal ——
    def _log(self, kind, title, msg, author, to=None):
        to_ids = self._resolve_to(to) if to else None
        _dba.append_one(self.ledger, kind, title, msg or title, author=author, to=to_ids)

    def _resolve_to(self, to):
        """把 to 里的 token（名字或 id）解析为已注册 agent_id；解析不出的原样保留。
        Resolve each token (name or id) in `to` to a registered agent_id; keep unresolvable tokens as-is."""
        by_name = {a.name: a.agent_id for a in self.reg.list()}
        out = []
        for t in SPLIT_TO.split(to):
            t = t.strip()
            if not t:
                continue
            out.append(by_name.get(t, t))
        return ','.join(out)

    def _to_names(self, to):
        """agent_id → name（若可解析），便于人读。
        agent_id → name (if resolvable), for human readability."""
        by_id = {a.agent_id: a.name for a in self.reg.list()}
        return ','.join(by_id.get(t.strip(), t.strip()) for t in SPLIT_TO.split(to) if t.strip())

    def _name_of(self, aid):
        """agent_id → name。路由的角色池用人名，去「非作者」时须用名字比。
        agent_id → name. Routing's role pool uses person names, so excluding the "non-author" must compare by name."""
        a = self.reg.lookup(aid) if aid else None
        return a.name if a else (aid or '')

    def _aid_of(self, token):
        """名字或 id → id（未注册的原样保留）。作者 ID 红线：卷内记 id。
        Name or id → id (kept as-is if unregistered). Author-ID red line: the volume records ids."""
        if not token:
            return token
        by_name = {a.name: a.agent_id for a in self.reg.list()}
        return by_name.get(token, token)

    # —— 身份/在场 ——
    # —— Identity / presence ——
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
    # —— Tasks ——
    def open(self, title, by):
        by_id = self._aid_of(by)
        tid = self.tv.create(by_id, title)
        self._log('工', title, '开单 %s' % tid, by_id)
        return tid

    def claim(self, tid, aid):
        """认领：加锁 → 校验当前态 → 迁移进行中 → 解锁。锁使「读-判-写」原子。
        Claim: lock → verify current state → transition to in-progress → unlock. The lock makes read-check-write atomic."""
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
        """交活：进行中 → 完成 → 待审，落一条报条（可带 [致=]）。
        Submit: in-progress → done → pending-review, writing one report entry (may carry [致=])."""
        self.tv.transition(tid, '完成', aid, note or '交活')
        self.tv.transition(tid, '待审', aid, note or '待审')
        self._log('报', '交活 %s' % tid, note or '交活', aid, to=to)
        person, why = self.route_for('报', '交活 %s' % tid, note, self._name_of(aid), to)
        return person, why

    def review(self, tid, aid, verdict, note=''):
        """裁决：通过→已审；驳回→进行中（返工）。
        Review: pass → reviewed; reject → in-progress (rework)."""
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
    # —— Pull (derived view · deletable and rebuildable) ——
    def pull(self, who):
        """按路由表算下一手，列出落脚于 who 且 who 尚未落条回应的条。
        Compute the next hand via the routing table, listing entries that land on `who` and that `who` has not yet responded to."""
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

    # —— 分发接上目录（v3.1·派生视图·可删可重建） ——
    # —— Distribution hooked to the directory (v3.1 · derived view · deletable and rebuildable) ——
    def digest(self, vol=None, cls=None, limit=20):
        """变动摘要：读多级目录（部→类→属）·给出「新条已挂进层级·带提要」的分发摘要。
        返回 (lines, rows, src)。src ∈ {'catalog','volume-fallback'}。
        Change digest: read the multi-level directory (部→类→属) · produce a distribution digest of "new entries already attached to the hierarchy, with summaries".
        Returns (lines, rows, src). src ∈ {'catalog','volume-fallback'}."""
        rows, src = read_multidx_rows(self.root)
        if vol:
            rows = [r for r in rows if r.get('volume') == vol]
        if cls:
            rows = [r for r in rows if cls in (r.get('category') or '')]

        def _ln(r):
            try:
                return int(r.get('line') or 0)
            except ValueError:
                return 0
        rows = sorted(rows, key=lambda r: (r.get('time', ''), _ln(r)))
        shown = rows[-limit:] if limit and len(rows) > limit else rows  # 取最近（尾部）
                                                                         # take the most recent (tail)

        head = '变动摘要（%s·%d 条%s）' % (
            src, len(rows), '' if not vol else '·volume=%s' % vol)
        lines = [head]
        for r in shown:
            ref = make_entry_ref(self.root, r.get('volume', ''), r.get('line', '0'))  # 互见层来源
                                                                                      # source of the cross-reference layer
            lines.append('  部.%s ▸ 类.%s ▸ 属.%s  [%s#L%s]%s' % (
                r.get('volume', ''), r.get('level2', '') or r.get('category', ''),
                r.get('title', ''), r.get('volume', ''), r.get('line', '0'),
                ('  ↪%s' % ref) if ref else ''))
        return lines, rows, src

    def push_digest(self, to, vol=None, cls=None, limit=20):
        """把 digest 摘要经 agent_message 推送（不在线则仅落编排卷·不阻断）。
        Push the digest summary via agent_message (if offline, it just lands in the orchestration volume · non-blocking)."""
        lines, _rows, src = self.digest(vol=vol, cls=cls, limit=limit)
        summary = '\n'.join(lines)
        self._log('推', '变动摘要', summary, self._aid_of('司南'))
        for t in [x for x in SPLIT_TO.split(to or '') if x.strip()]:
            try:
                import agent_message as _am
                ok, info = _am.send('司南', t, 'notify', summary)
            except Exception as e:
                ok, info = False, '%s: %s' % (type(e).__name__, e)
            print('  推送 → %s：%s %s' % (t, 'OK' if ok else 'FAIL', info if not ok else ''))
        return summary, src

    # —— 体检 ——
    # —— Health check ——
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
        # Owners that appear in the task volume but not in the registry (ghosts)
        reg_ids = {a.agent_id for a in self.reg.list()}
        for tid, st, ag, ct, _hist in self.tv.list():
            if ag and ag not in reg_ids:
                issues.append('幽灵负责人：%s 的 %s 未在注册卷' % (tid, ag))
        return issues


# ── CLI ──────────────────────────────────────────────────────────────
# ── CLI (command-line interface) ─────────────────────────────────────
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
    p = sub.add_parser('digest')            # v3.1：读多级目录·分发摘要
                                            # v3.1: read the multi-level directory · distribution digest
    p.add_argument('--vol', default='')
    p.add_argument('--cls', default='')
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--push', default='', help='推送给收件人（逗号分隔·走 agent_message·不在线不阻断）')
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
    elif args.cmd == 'digest':
        if args.push:
            _summary, src = hub.push_digest(args.push, args.vol or None,
                                            args.cls or None, args.limit)
            print('摘要来源：%s（已推 %s）' % (src, args.push))
        else:
            lines, _rows, src = hub.digest(args.vol or None, args.cls or None, args.limit)
            print('来源：%s' % src)
            for l in lines:
                print(l)
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
    """端到端验收：临时根目录跑通 入伙→开单→认领→交活→取件→裁决 全链。
    End-to-end acceptance: run the whole chain join → open → claim → submit → pull → review in a temporary root directory."""
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
                                      # rules come from the two default confs (orchestration_routing.conf / orchestration_roles.conf)

        aid, _ = hub.join('汤姆')
        bid, _ = hub.join('皮特')
        chk(len(hub.who()) == 2, '入伙 2 人')

        tid = hub.open('实现 MCP resources/list', aid)
        st = hub.tv.get(tid)[-1][1]
        chk(st == '待办', '开单 → 待办')

        okc, _msg = hub.claim(tid, aid)
        chk(okc and hub.tv.get(tid)[-1][1] == '进行中', '认领 → 进行中')

        # 并发争用：再认领同单应失败（锁 + 状态校验）
        # Concurrency contention: claiming the same task again should fail (lock + state check)
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
        # Reject and rework
        tid2 = hub.open('第二单', aid)
        hub.claim(tid2, aid)
        hub.submit(tid2, aid, '初版')
        hub.review(tid2, bid, '驳回', '不行')
        chk(hub.tv.get(tid2)[-1][1] == '进行中', '驳回 → 返工（进行中）')

        # v3.1：分发接上目录——造多级目录 tsv → digest 应出「部▸类▸属」摘要
        # v3.1: distribution hooked to the directory — build a multi-level directory tsv → digest should emit a 部▸类▸属 summary
        mdir = os.path.join(root, 'multilevel')
        if not os.path.isdir(mdir):
            os.makedirs(mdir)
        # ① 新英文名/新英文表头（canonical）/ canonical English name + English header
        with io.open(os.path.join(mdir, '协作_catalog.tsv'), 'w', encoding='utf-8') as f:
            f.write('volume\tlevel2\tline\ttime\tcategory\tauthor\ttitle\n')
            f.write('协作\t报\t12\t2026-10-15 09:00\t报\t汤姆\t交活 T001\n')
            f.write('协作\t核\t20\t2026-10-15 10:00\t核\t皮特\t核 T001\n')
        dl, drows, dsrc = hub.digest(vol='协作')
        chk(dsrc == 'catalog' and len(drows) == 2 and any('部.协作' in x for x in dl),
            'digest：读多级目录（英文名/表头）→ 部▸类▸属 摘要（来源=%s）' % dsrc)
        _dl2, drows2, _s2 = hub.digest(cls='核')
        chk(len(drows2) == 1, 'digest：按类过滤命中 1 条')
        # ② 旧中文名/旧中文表头（compat 别名）/ legacy Chinese name + header (compat alias)
        os.remove(os.path.join(mdir, '协作_catalog.tsv'))
        with io.open(os.path.join(mdir, '协作_目录.tsv'), 'w', encoding='utf-8') as f:
            f.write('卷\t二级\t行号\t时间\t类\t作者\t标题\n')
            f.write('协作\t报\t12\t2026-10-15 09:00\t报\t汤姆\t交活 T001\n')
            f.write('协作\t核\t20\t2026-10-15 10:00\t核\t皮特\t核 T001\n')
        dl3, drows3, dsrc3 = hub.digest(vol='协作')
        chk(dsrc3 == 'catalog' and len(drows3) == 2 and any('部.协作' in x for x in dl3),
            'digest：读多级目录（旧中文名/表头兼容）→ 摘要（来源=%s）' % dsrc3)

        issues = hub.alarm()
        print('  体检：' + '；'.join(issues))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print('== 编排中心自检：%s ==' % ('全绿' if ok else '有红'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
