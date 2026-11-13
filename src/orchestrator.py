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
    身份   agent_registry    密钥文件（0600/0700）+ HMAC-SHA256 落盘验签
    identity  agent_registry   key files (0600/0700) + HMAC-SHA256 on-disk signatures
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

编排卷条目头（v3.2 起）：
Ledger entry header (since v3.2):
    [时间] [类] [标题] [作者] [id=<条号>] [re=<回应条号>] [sig=<HMAC-SHA256>] [致=…] 正文
    · pull 只认 [re=] 判「已回」；旧条目无 id=/sig= ⇒ unknown/unsigned，绝不默认合法。
    · pull only honours [re=] as "replied"; legacy entries without id=/sig= ⇒ unknown/unsigned, never silently legal.
    · 七卷路径全由 <root>/daybook.conf 的 [volumes] 段解析，--root 一处生效。
    · All seven volume paths resolve from the [volumes] section of <root>/daybook.conf; --root takes effect in one place.

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
退出码：0 正常；1 alarm 有硬警；2 参数/文件错；3 alarm 执行异常（读卷/解析失败）。
Exit codes: 0 normal; 1 alarm has a hard warning; 2 argument/file error; 3 alarm execution error (volume read/parse failure).
"""
import argparse
import hashlib
import io
import os
import re
import secrets
import sys
import time
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent_registry as _reg
import task_volume as _tv
import agent_heartbeat as _hb
import agent_lock as _lock
import daybook_append as _dba
import volume_paths as _vp

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

# 条头里不是作者的结构字段（作者字段固定第 4 段；这些前缀只在缺作者时才会被误当作者）
# Structural header fields that are not the author (the author is fixed at segment 4;
# these prefixes could be mistaken for an author only when the author is missing).
ENTRY_FIELD_PREFIX = ('致=', 'id=', 're=', 'sig=', 'thread=')
SIG_SCHEME = 'daybook-orch-entry-v1'

# 体检结论：code=结构判据名；hard=是否硬警；msg=人读说明。
# Health-check finding: code = structural criterion name; hard = whether it is a hard warning; msg = human-readable text.
Alarm = namedtuple('Alarm', 'code hard msg')


def entry_payload(now, kind, title, author, to, eid, re_ref, body):
    """条目签名的规范载荷（验签时从条头+正文同样重建）。
    Canonical payload for an entry signature (rebuilt identically from header + body on verification)."""
    return '\n'.join([SIG_SCHEME, now or '', kind or '', title or '', author or '',
                      to or '', eid or '', re_ref or '', (body or '').rstrip('\n')])


def is_field_seg(seg):
    """该 [xxx] 段是否是结构字段（id=/re=/sig=/致=/thread=），而非作者。
    Whether a [xxx] segment is a structural field (id=/re=/sig=/致=/thread=) rather than an author."""
    return any(seg.startswith(p) for p in ENTRY_FIELD_PREFIX)


def entry_body(e):
    """条目正文：同行正文 + 后续行（与落盘字节一致）。验签用。
    Entry body: inline text + following lines (identical to the bytes on disk). Used for verification."""
    full = e.get('inline') or ''
    lines = e.get('body') or []
    if lines:
        full = full + '\n' + '\n'.join(lines)
    return full.rstrip('\n')


class VolumeIndex:
    """单次 digest 内的整卷索引：每卷只读一次，按行号取条目块并算 SHA8。
    Per-digest whole-volume index: each volume is read once; entry blocks are sliced by line number for SHA8.

    修前 digest 每出一条摘要就整卷重读一次（20 条＝20 次盘读＋20 次 conf 解析）；
    本索引把「整卷读」与「逐条哈希」拆开：盘读 O(卷数)，条目哈希只算被展示的那几条。
    Before: every digest line re-read the whole volume (20 lines = 20 disk reads + 20 conf parses).
    This index separates "read the volume" from "hash one entry": disk reads = O(volumes),
    and only the entries actually shown are hashed.
    行号口径与 cross_ref._entry_at 完全一致：非条目头则向前找最近条目头；块止于下一条目头。
    Line semantics match cross_ref._entry_at exactly: walk back to the nearest head when needed;
    the block ends at the next head.
    """
    def __init__(self):
        self._vols = {}
        self._sha = {}
        self.reads = 0

    def _load(self, path):
        it = self._vols.get(path)
        if it is not None:
            return it
        from safeio import read_vol
        text, enc, why = read_vol(path)
        self.reads += 1
        it = {'text': text, 'lines': text.split('\n'),
              'enc': enc, 'why': why}
        self._vols[path] = it
        return it

    def volume_text(self, path):
        """整卷文本（同一次 digest 内只读一次）。
        Whole-volume text (read once per digest)."""
        return self._load(path)['text']

    def entry_sha8(self, path, lineno, head_re):
        """条目块 SHA-256 前 8 位（与 cross_ref._entry_hash 同口径）。无条目返 None。
        First 8 hex of the entry block's SHA-256 (same rule as cross_ref._entry_hash). None when absent.

        只对「被展示的那几条」做块边界搜索（O(块长)），不预建百万行条目头表。
        Only the shown rows get a block-boundary search (O(block length)); no million-line head table is prebuilt.
        行号口径：非条目头则向前找最近条目头；块止于下一条目头。
        Line semantics: walk back to the nearest head when the line is not one; the block ends at the next head."""
        lineno = int(lineno)
        key = (path, lineno, head_re.pattern)
        if key in self._sha:
            return self._sha[key]
        lines = self._load(path)['lines']
        if lineno < 1 or lineno > len(lines):
            return None
        if not head_re.match(lines[lineno - 1]):
            start = lineno
            while start > 1 and not head_re.match(lines[start - 2]):
                start -= 1
            if not head_re.match(lines[start - 1]):
                return None
        else:
            start = lineno
        end = start
        while end < len(lines) and not head_re.match(lines[end]):
            end += 1
        block = '\n'.join(lines[start - 1:end])
        h = hashlib.sha256(block.encode('utf-8')).hexdigest()[:8]
        self._sha[key] = h
        return h


def make_entry_ref(root, vol, lineno, vols=None, index=None):
    """生成互见引用 [卷#L行-SHA8]（v3.1）。返回 (引用, 错误原因)；成功时错误为 ''。
    Build a cross-reference [volume#Lline-SHA8] (v3.1). Returns (ref, error_reason); error is '' on success.

    修前失败一律 `except Exception: return ''`，与「本来就没有引用」无法区分；
    现在把失败原因显式交给调用方，另写 stderr 留痕。
    Before, every failure was `except Exception: return ''`, indistinguishable from "no reference at all";
    now the reason is returned explicitly and also written to stderr."""
    try:
        from cross_ref import CrossRef
    except Exception as exc:  # 导入失败也要看得见 · import failures must be visible too
        err = 'cross_ref 导入失败：%s: %s' % (type(exc).__name__, exc)
        sys.stderr.write('⚠ 互见引用失败（卷=%s 行=%s）：%s\n' % (vol, lineno, err))
        return '', err
    if vols is None:
        vols = _load_volumes(root)
    rel = vols.get(vol)
    if not rel:
        err = '卷 %s 不在 conf 卷表' % vol
        sys.stderr.write('⚠ 互见引用失败（卷=%s 行=%s）：%s\n' % (vol, lineno, err))
        return '', err
    path = rel if os.path.isabs(rel) else os.path.join(root, rel)

    def _vp(v, _path=path, _vol=vol):
        if v != _vol:
            raise KeyError('volume %s not in conf volume table' % v)
        return _path

    try:
        cr = CrossRef(root=root)
        cr._vol_path = _vp
        return cr.make_ref(vol, int(lineno), index=index), ''
    except Exception as exc:
        err = '%s: %s' % (type(exc).__name__, exc)
        sys.stderr.write('⚠ 互见引用失败（卷=%s 行=%s）：%s\n' % (vol, lineno, err))
        return '', err


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
    """读 <root>/daybook.conf [volumes] 表 → {卷名: 相对/绝对路径}。缺则 {}。
    orch 内部卷的保留键（registry/tasks/…）不算内容卷，此处过滤。
    Read the <root>/daybook.conf [volumes] table → {volume name: relative/absolute path}. {} if absent.
    Reserved orch-internal keys (registry/tasks/…) are not content volumes and are filtered out here."""
    return _vp.content_volumes(root)


def read_multidx_rows(root, index=None):
    """读 <root>/multilevel/*_catalog.tsv（daybook_multidx 之产出；旧名 *_目录.tsv 亦认）。
    返回 (rows, 来源, 错误清单)。来源 ∈ {'catalog','volume-fallback','no-volumes'}。
    Read <root>/multilevel/*_catalog.tsv (the output of daybook_multidx; legacy *_目录.tsv also accepted).
    Returns (rows, source, errors). source ∈ {'catalog','volume-fallback','no-volumes'}.

    修前：读目录失败静默 continue、卷表为空直接返回 0 条，二者都看着像「没有新条」；
    现在把失败与空卷表都记入 errors，由 digest 显式标注。
    Before: directory read failures were silently skipped and an empty volume table returned 0 rows —
    both looked like "nothing new"; now both are recorded in errors and surfaced by digest."""
    d = os.path.join(root, 'multilevel')
    rows, errors = [], []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not (fn.endswith('_catalog.tsv') or fn.endswith('_目录.tsv')):
                continue
            try:
                lines = [l.rstrip('\n') for l in io.open(os.path.join(d, fn), encoding='utf-8')
                         if l.strip()]
            except OSError as exc:
                errors.append('目录件 %s 读取失败：%s' % (fn, exc))
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
        return rows, 'catalog', errors
    # 兜底：直读在册卷原文·自建 部(卷)/类(kind)/属(条目)（orch 单包自持可跑）
    # Fallback: read the registered volumes' raw text directly and build 部(volume)/类(kind)/属(entry) ourselves (so the orch package runs standalone)
    vols = _load_volumes(root)
    if not vols:
        errors.append('卷表为空：%s 的 [volumes] 未登记任何内容卷' % os.path.join(root, 'daybook.conf'))
        return [], 'no-volumes', errors
    for name, rel in vols.items():
        path = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if not os.path.exists(path):
            errors.append('卷 %s 不存在：%s' % (name, path))
            continue
        try:
            _, entries = _scan_vol_rows(path, index=index)
        except OSError as exc:
            errors.append('卷 %s 读取失败：%s' % (name, exc))
            continue
        for e in entries:
            rows.append({'volume': name, 'level2': e['kind'], 'line': str(e['lineno']),
                         'time': e['time'], 'category': e['kind'],
                         'author': e['author'], 'title': e['title']})
    return rows, 'volume-fallback', errors


def _scan_vol_rows(path, index=None):
    """轻量扫卷：逐行找条目头·记录行号与条头字段。返回 (text, entries)。
    Lightweight volume scan: find entry headers line by line · record line numbers and header fields. Returns (text, entries).
    index 提供时复用整卷文本（同一次 digest 内不再重读）。
    When index is given, reuse the whole-volume text (no re-read within the same digest)."""
    if index is not None:
        text = index.volume_text(path)
    else:
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
                if is_field_seg(s):
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
            # 条头之后的同行正文（条头末段后固定一个空格）· the inline body after the header (one space follows the last segment)
            inline = m.group(2)[_hm.end():] if _hm else m.group(2)
            if inline.startswith(' '):
                inline = inline[1:]
            # 作者可选·致=/id=/re=/sig= 段可在其后 / author optional · 致=/id=/re=/sig= may follow
            author = ''
            to = ''
            eid = ''
            re_ref = ''
            sig = ''
            for _s in _segs[2:]:
                if _s.startswith('致='):
                    to = _s[2:]
                elif _s.startswith('id='):
                    eid = _s[3:]
                elif _s.startswith('re='):
                    re_ref = _s[3:]
                elif _s.startswith('sig='):
                    sig = _s[4:]
                elif not author and not is_field_seg(_s):
                    author = _s
            e = {'time': m.group(1), 'kind': kind, 'title': title,
                 'author': author, 'to': to, 'id': eid, 're': re_ref,
                 'sig': sig, 'inline': inline, 'body': []}
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
        # 单一根 + conf 驱动：七卷全由 <root>/daybook.conf 解析，--root 一处生效。
        # Single root + conf-driven: all seven volumes resolve from <root>/daybook.conf, so --root takes effect in one place.
        self.root = _vp.resolve_root(root)
        self.vols = _vp.resolve_volumes(self.root)
        # conf 指向自定义子目录时先建父目录（卷本身仍由各件按需创建）。
        # Create parent directories first when conf points at custom subdirectories
        # (the volume files themselves are still created on demand by each primitive).
        for role, path in self.vols.items():
            if role == 'root':
                continue
            parent = os.path.dirname(path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
        self.reg = _reg.Registry(self.vols['registry'])
        self.tv = _tv.TaskVolume(self.vols['tasks'])
        self.hb = _hb.Heartbeat(self.vols['heartbeat'])
        self.lock = _lock.AgentLock(self.vols['locks'], self.vols['leases'])
        self.ledger = self.vols['ledger']
        self.rules = load_rules(rule or DEFAULT_RULE)
        self.roles = load_roles(roles or DEFAULT_ROLES)

    # —— 内部 ——
    # —— Internal ——
    def entry_auth(self, e):
        """验签：返回 'ok' / 'unsigned' / 'invalid' / 'unknown-key'。
        Verify a signature: returns 'ok' / 'unsigned' / 'invalid' / 'unknown-key'.
        旧条目无 sig 字段 ⇒ unsigned（绝不默认当合法）；签名对不上 ⇒ invalid。
        A legacy entry without a sig field ⇒ unsigned (never silently legal); a mismatched signature ⇒ invalid."""
        if not e.get('sig'):
            return 'unsigned'
        author = e.get('author') or ''
        if not self.reg.lookup(author):
            return 'unknown-key'
        payload = entry_payload(e.get('time'), e.get('kind'), e.get('title'),
                                author, e.get('to'), e.get('id'), e.get('re'),
                                entry_body(e))
        return 'ok' if self.reg.verify(author, payload, e['sig']) else 'invalid'

    def _actor(self, explicit):
        """身份解析：显式参数优先；缺省才由 DAYBOOK_AGENT_ID 选钥（环境变量只选钥，不证明身份）。
        Identity resolution: an explicit argument wins; DAYBOOK_AGENT_ID only selects a key when omitted
        (the environment variable selects a key, it does not prove identity)."""
        return (explicit or '').strip() or os.environ.get('DAYBOOK_AGENT_ID', '').strip()

    def _log(self, kind, title, msg, author, to=None, re_ref=None):
        """落一条带显式条号 + 签名 + 回应引用的编排卷条目。返回条号 id。
        Append one ledger entry with an explicit id + signature + reply reference. Returns the entry id."""
        to_ids = self._resolve_to(to) if to else None
        body = (msg or title or '').rstrip('\n')
        eid = 'm' + secrets.token_hex(8)
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        sig = None
        try:
            sig = self.reg.sign(author, entry_payload(now, kind, title, author,
                                                      to_ids, eid, re_ref, body))
        except (KeyError, PermissionError) as exc:
            sys.stderr.write('⚠ 未签名条目 id=%s author=%s：%s（读取侧将标 unsigned）\n'
                             % (eid, author, exc))
        _dba.append_one(self.ledger, kind, title, body, author=author, to=to_ids,
                        msg_id=eid, re_ref=re_ref, sig=sig, now=now)
        return eid

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
        # 先落条再吊销：吊销后密钥不可再签，退场条会变成 unsigned。
        # Log first, then revoke: after revocation the key cannot sign, and the leave entry would be unsigned.
        aid = self._actor(aid)
        self._log('编', '退场', 'agent 退场', aid)
        self.reg.revoke(aid)

    def who(self):
        return [(a.agent_id, a.name, self.hb.is_alive(a.agent_id), a.revoked)
                for a in self.reg.list()]

    # —— 任务 ——
    # —— Tasks ——
    def open(self, title, by):
        by_id = self._aid_of(self._actor(by))
        tid = self.tv.create(by_id, title)
        self._log('工', title, '开单 %s' % tid, by_id)
        return tid

    def claim(self, tid, aid):
        """认领：加锁 → 校验当前态 → 迁移进行中 → 解锁。锁使「读-判-写」原子。
        Claim: lock → verify current state → transition to in-progress → unlock. The lock makes read-check-write atomic."""
        aid = self._actor(aid)
        lease = self.lock.acquire('task:%s' % tid, aid)
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

    def submit(self, tid, aid, note='', to=None, re_ref=None):
        """交活：进行中 → 完成 → 待审，落一条报条（可带 [致=] / [re=]）。
        Submit: in-progress → done → pending-review, writing one report entry (may carry [致=] / [re=])."""
        aid = self._actor(aid)
        self.tv.transition(tid, '完成', aid, note or '交活')
        self.tv.transition(tid, '待审', aid, note or '待审')
        self._log('报', '交活 %s' % tid, note or '交活', aid, to=to, re_ref=re_ref)
        person, why = self.route_for('报', '交活 %s' % tid, note, self._name_of(aid), to)
        return person, why

    def review(self, tid, aid, verdict, note='', re_ref=None):
        """裁决：通过→已审；驳回→进行中（返工）。可带 [re=] 显式回应某条。
        Review: pass → reviewed; reject → in-progress (rework). May carry [re=] to reply to a specific entry."""
        aid = self._actor(aid)
        if verdict in ('通过', 'pass', '已审', 'ok'):
            self.tv.transition(tid, '已审', aid, note or '通过')
            self._log('审', '裁决 %s·通过' % tid, note or '通过', aid, re_ref=re_ref)
            return '已审'
        self.tv.transition(tid, '进行中', aid, note or '驳回')
        self._log('审', '裁决 %s·驳回' % tid, note or '驳回', aid, re_ref=re_ref)
        return '进行中'

    def route_for(self, kind, title, body, author, to):
        return route(kind, title, body, author, to, self.rules, self.roles)

    def board(self):
        return self.tv.list()

    # —— 取件（派生视图·可删可重建） ——
    # —— Pull (derived view · deletable and rebuildable) ——
    def pull(self, who):
        """按路由表算下一手，列出落脚于 who 且 who 尚未**显式引用回应**的条。
        Compute the next hand via the routing table, listing entries that land on `who`
        and that `who` has not yet explicitly referenced in a reply.

        回复关系只认 `[re=<条号>]`：位置相邻、同作者、时间先后一律不作数。
        Only `[re=<entry-id>]` counts as a reply: adjacency, same author or chronological order never do.
        旧条目没有 `[id=]` → 回应对不上，判 unknown，照样列出（绝不默认当已回）。
        A legacy entry without `[id=]` → its reply cannot be matched, so it is marked unknown and still listed
        (never silently treated as replied).
        回应条自身须验签通过；unsigned/invalid 的「回应」不计，并明确告警。
        A reply must itself verify; unsigned/invalid "replies" are not counted and raise an explicit warning."""
        entries = parse_ledger(self.ledger)
        names = {a.name: a.agent_id for a in self.reg.list()}
        who_id = names.get(who, who)
        auth = [self.entry_auth(e) for e in entries]

        replied = set()
        ignored = []
        for j, e in enumerate(entries):
            if e['author'] not in (who, who_id):
                continue
            refs = [t.strip() for t in SPLIT_TO.split(e.get('re') or '') if t.strip()]
            if not refs:
                continue
            if auth[j] != 'ok':
                ignored.append((e, auth[j]))
                continue
            replied.update(refs)
        for e, st in ignored:
            sys.stderr.write('⚠ %s 的回应 id=%s 验签=%s，不计为已回（引用=%s）\n'
                             % (who, e.get('id') or '（无）', st, e.get('re')))

        pend = []
        for i, e in enumerate(entries):
            person, why = route(e['kind'], e['title'], '\n'.join(e['body']),
                                self._name_of(e['author']), e['to'], self.rules, self.roles)
            targets = [t.strip() for t in SPLIT_TO.split(person or '') if t.strip()]
            if who not in targets and who_id not in targets:
                continue
            e['auth'] = auth[i]
            if not e.get('id'):
                e['reply_state'] = 'unknown'
            elif e['id'] in replied:
                e['reply_state'] = 'replied'
                continue
            else:
                e['reply_state'] = 'pending'
            if e['auth'] != 'ok':
                sys.stderr.write('⚠ 条目 id=%s author=%s 验签=%s，不得视为合法（位置决定处理优先级，不决定真伪）\n'
                                 % (e.get('id') or '（无）', e['author'] or '（缺）', e['auth']))
            pend.append((e, person, why))
        return pend

    # —— 分发接上目录（v3.1·派生视图·可删可重建） ——
    # —— Distribution hooked to the directory (v3.1 · derived view · deletable and rebuildable) ——
    def digest(self, vol=None, cls=None, limit=20):
        """变动摘要：读多级目录（部→类→属）·给出「新条已挂进层级·带提要」的分发摘要。
        返回 (lines, rows, src)。src ∈ {'catalog','volume-fallback','no-volumes'}。
        limit：0=全部；正数=最近 N 条；负数=参数错（ValueError）。
        Change digest: read the multi-level directory (部→类→属) · produce a distribution digest of "new entries already attached to the hierarchy, with summaries".
        Returns (lines, rows, src). src ∈ {'catalog','volume-fallback','no-volumes'}.
        limit: 0 = all; positive = the most recent N; negative = argument error (ValueError)."""
        if limit is None:
            limit = 0
        if limit < 0:
            raise ValueError('limit 必须 ≥ 0（0=全部，正数=最近 N 条）')
        index = VolumeIndex()
        rows, src, errors = read_multidx_rows(self.root, index=index)
        vols = _load_volumes(self.root)
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
        shown = rows if limit == 0 else (rows[-limit:] if len(rows) > limit else rows)  # 取最近（尾部）
                                                                                        # take the most recent (tail)

        head = '变动摘要（%s·%d 条%s）' % (
            src, len(rows), '' if not vol else '·volume=%s' % vol)
        lines = [head]
        if src == 'no-volumes':
            lines.append('  ⚠ 卷表为空：0 条不代表「没有新条」，是没登记卷（见 %s）'
                         % os.path.join(self.root, 'daybook.conf'))
        for e in errors:
            sys.stderr.write('⚠ digest：%s\n' % e)
            lines.append('  ⚠ %s' % e)
        ref_errors = 0
        for r in shown:
            ref, err = make_entry_ref(self.root, r.get('volume', ''), r.get('line', '0'),
                                      vols=vols, index=index)  # 互见层来源
                                                               # source of the cross-reference layer
            if err:
                ref_errors += 1
                ref_txt = '  ↪[互见失败:%s]' % err[:60]
            else:
                ref_txt = ('  ↪%s' % ref) if ref else ''
            lines.append('  部.%s ▸ 类.%s ▸ 属.%s  [%s#L%s]%s' % (
                r.get('volume', ''), r.get('level2', '') or r.get('category', ''),
                r.get('title', ''), r.get('volume', ''), r.get('line', '0'), ref_txt))
        if ref_errors:
            lines.append('  ⚠ %d 条互见引用失败（原因见 stderr；不当作「没有引用」）' % ref_errors)
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
                ok, info = _am.send('司南', t, 'notify', summary, root=self.root)
            except Exception as e:
                ok, info = False, '%s: %s' % (type(e).__name__, e)
            print('  推送 → %s：%s %s' % (t, 'OK' if ok else 'FAIL', info if not ok else ''))
        return summary, src

    # —— 体检 ——
    # —— Health check ——
    def alarm(self):
        """体检：返回 [Alarm(code, hard, msg)]。判据只按结构字段（心跳时间戳+阈值、注册表成员、状态机位置），
        不比对任何自产的中文字串——修前 `'失联' in msg` 这类判据会让幽灵负责人也判「干净」。
        Health check: returns [Alarm(code, hard, msg)]. Criteria use structural fields only
        (heartbeat timestamp + threshold, registry membership, state-machine position), never
        self-produced Chinese substrings — before, `'失联' in msg` let ghost owners pass as "clean"."""
        out = []
        dead = self.hb.dead_agents()
        dead_set = set(dead)
        if dead:
            out.append(Alarm('dead_agents', True, '失联 agent：%s' % '、'.join(dead)))
        tasks = self.tv.list()
        reg_ids = {a.agent_id for a in self.reg.list()}
        for tid, st, ag, ct, _hist in tasks:
            if st in ('进行中', '待审') and ag in dead_set:
                out.append(Alarm('orphan_task', True,
                                 '孤儿任务：%s [%s] 由失联 %s 持有' % (tid, st, ag)))
            if st == '完成':
                out.append(Alarm('stalled_done', False,
                                 '滞留：%s 停在[完成]、未推进[待审]' % tid))
            # 任务卷里出现、注册卷里没有的负责人（幽灵）——硬警，修前只会判「干净」
            # Owners that appear in the task volume but not in the registry (ghosts) — a hard warning; before, they passed as "clean"
            if ag and ag not in reg_ids:
                out.append(Alarm('ghost_owner', True,
                                 '幽灵负责人：%s 的 %s 未在注册卷' % (tid, ag)))
        return out


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
    unknown = sum(1 for e, _p, _w in pend if e.get('reply_state') == 'unknown')
    unauth = sum(1 for e, _p, _w in pend if e.get('auth') != 'ok')
    print('取件 %s：待办 %d 条（unknown %d · 验签非 ok %d）' % (who, len(pend), unknown, unauth))
    for e, person, why in pend:
        to = hub._to_names(e['to']) if e['to'] else (person or '广播')
        print('  [%s] [%s] id=%s auth=%s reply=%s → %s  %s  ← %s' % (
            e['time'][11:], e['kind'], e.get('id') or '（无）', e.get('auth') or '?',
            e.get('reply_state') or '?', to, e['title'], why))


def main(argv=None):
    ap = argparse.ArgumentParser(description='daybook 智能体编排中心')
    ap.add_argument('--root', default=HERE, help='卷根目录（默认本包自身）')
    ap.add_argument('--rule', default=DEFAULT_RULE)
    ap.add_argument('--roles', default=DEFAULT_ROLES)
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('join'); p.add_argument('name')
    p = sub.add_parser('leave'); p.add_argument('agent_id', nargs='?', default='')
    sub.add_parser('who')
    p = sub.add_parser('open'); p.add_argument('title'); p.add_argument('--by', required=True)
    p = sub.add_parser('claim'); p.add_argument('tid')
    p.add_argument('agent_id', nargs='?', default='')
    p = sub.add_parser('submit')
    p.add_argument('tid'); p.add_argument('agent_id', nargs='?', default='')
    p.add_argument('--to', default=''); p.add_argument('--note', default='')
    p.add_argument('--re', default='', help='显式回应条号 id=（消息总线回复关系）')
    p = sub.add_parser('review')
    p.add_argument('tid'); p.add_argument('agent_id', nargs='?', default=''); p.add_argument('verdict')
    p.add_argument('--note', default='')
    p.add_argument('--re', default='', help='显式回应条号 id=（消息总线回复关系）')
    p = sub.add_parser('pull'); p.add_argument('who')
    sub.add_parser('board')
    sub.add_parser('alarm')
    p = sub.add_parser('digest')            # v3.1：读多级目录·分发摘要
                                            # v3.1: read the multi-level directory · distribution digest
    p.add_argument('--vol', default='')
    p.add_argument('--cls', default='')
    p.add_argument('--limit', type=int, default=20,
                   help='只取最近 N 条；0=全部；负数非法（默认 20）')
    p.add_argument('--push', default='', help='推送给收件人（逗号分隔·走 agent_message·不在线不阻断）')
    sub.add_parser('selftest')

    args = ap.parse_args(argv)
    if args.cmd == 'digest' and args.limit < 0:
        ap.error('--limit 必须 ≥ 0（0=全部，正数=最近 N 条）')
    if args.cmd == 'selftest':
        return _selftest()
    if not args.cmd:
        ap.print_help()
        return 2

    try:
        hub = Hub(root=args.root, rule=args.rule, roles=args.roles)
    except Exception as exc:  # 初始化失败也不许与「有硬警」共用 rc=1 · init failures must not share rc=1 with hard warnings
        sys.stderr.write('⚠ 初始化失败：%s: %s\n' % (type(exc).__name__, exc))
        if args.cmd == 'alarm':
            print('== 编排体检 ==')
            print('判：执行异常（rc=3）')
            return 3
        return 2

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
        person, why = hub.submit(args.tid, args.agent_id, args.note, args.to,
                                 re_ref=args.re or None)
        print('已交活 %s → 待审；下一手=%s（%s）' % (args.tid, person or '广播', why))
    elif args.cmd == 'review':
        st = hub.review(args.tid, args.agent_id, args.verdict, args.note,
                        re_ref=args.re or None)
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
        try:
            issues = hub.alarm()
        except Exception as exc:  # 执行异常与「有硬警」必须分开退出码 · execution errors vs hard warnings need distinct exit codes
            sys.stderr.write('⚠ 体检执行失败：%s: %s\n' % (type(exc).__name__, exc))
            print('== 编排体检 ==')
            print('判：执行异常（rc=3）')
            return 3
        print('== 编排体检 ==')
        for it in issues:
            print('  · [%s]%s %s' % (it.code, '★' if it.hard else '·', it.msg))
        hard = any(it.hard for it in issues)
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
        # 造一个自洽根：目录件引用的卷必须在 conf 卷表里，否则互见引用会显式报失败。
        # Build a self-consistent root: volumes referenced by the catalogue must be registered
        # in conf, otherwise cross-references explicitly report failure.
        with io.open(os.path.join(root, 'daybook.conf'), 'w', encoding='utf-8') as f:
            f.write('[volumes]\n协作=协作卷.txt\n')
        vol_lines = []
        for i in range(1, 26):
            if i in (12, 20):
                vol_lines.append('[2026-10-15 09:00] [报] [交活 T%03d] [汤姆]' % i)
            else:
                vol_lines.append('')
        with io.open(os.path.join(root, '协作卷.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(vol_lines) + '\n')

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
        chk(not any('互见失败' in x for x in dl), 'digest：互见引用生成成功（无静默失败）')
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
        print('  体检：' + '；'.join(i.msg for i in issues))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print('== 编排中心自检：%s ==' % ('全绿' if ok else '有红'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
