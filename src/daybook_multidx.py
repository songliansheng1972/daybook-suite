#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook_multidx.py —— DAYBOOK 四库式多级索引生成器
（L1 部·卷 → L2 类/作者 → L3 属·条目；另出跨卷总目）

定位（承 volume_format_spec.md §五「索引是目录不是真相」）：
  · **只读索引**，不读卷、不碰账；产出**派生件**（可删可重建）。
  · 改卷 → 重跑 `daybook.py index` → 再重跑本件即重生（单一入口·禁各自扫卷）。
  · **零依赖**（仅标准库）·**确定性**（同索引源·任何时刻算·得同一产出）。

输入：各卷**平铺索引 TSV**（`<索引前缀><卷>卷.tsv`·`daybook.py index` 之产物；本件不解析正账）
产出（默认落 `<输出目录>/多级/`）：
  `<卷>_目录.md`    人读：部(卷)→类(二级)→属(条目) 三级树
  `<卷>_目录.tsv`   机读：卷·二级·行号·时间·类·作者·标题
  `总目录.md`       跨卷总目（四库式·按类(子)／按年月(史)／按作者(集) 三序）

用法：
  python3 daybook_multidx.py                 # 读同目录 daybook.conf
  python3 daybook_multidx.py --now "2026-10-15 15:00"   # 钉死时间戳（双跑校对）
  python3 daybook_multidx.py --卷 协作        # 只出该卷目录（大账本按需裁剪·跳总目录）
  python3 daybook_multidx.py --序 子          # 总目录只出「按类」一序（省体积）
  python3 daybook.py multiindex              # 同一入口（daybook 侧子命令）
"""
import argparse
import io
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


# ── 配置读取（语义与 daybook.load_conf 一致·本件自持以保自包含）──
def load_conf(path):
    conf, sec = {}, None
    for line in io.open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = re.match(r'^\[(.+)\]$', line.strip())
        if m:
            sec = m.group(1)
            conf.setdefault(sec, {})
            continue
        if sec and '=' in line:
            k, v = line.split('=', 1)
            conf[sec][k.strip()] = v.strip()
    return conf


def resolve_root(conf, here):
    """根目录：conf[索引][根] 控制。空=here；..=上一级；绝对=原样。（与 daybook.py 同口径）"""
    rc = (conf.get('索引', {}).get('根', '') or '').strip()
    if not rc:
        return here
    if rc == '..':
        return os.path.dirname(here)
    if os.path.isabs(rc):
        return rc
    return os.path.join(here, rc)


# ── 工具 ──────────────────────────────────────────────────────
def _t(s):
    return (s or '').strip()


def _int(s):
    try:
        return int(str(s).strip())
    except Exception:
        return 0


def _ym(t):
    return _t(t)[:7]


def _sort_key(vr, with_vol):
    """条目排序键：时间 → （跨卷时先卷名）→ 行号。稳定·与 PYTHONHASHSEED 无关。"""
    v, r = vr
    if with_vol:
        return (_t(r.get('时间')), v, _int(r.get('行号')))
    return (_t(r.get('时间')), _int(r.get('行号')))


def _item_line(vol, row):
    """条目提要行：卷#L行号 · [时间] [类] 标题 · 作者"""
    ln = _t(row.get('行号')) or '0'
    t = _t(row.get('时间'))
    k = _t(row.get('类'))
    ti = _t(row.get('标题'))
    au = _t(row.get('作者'))
    s = '- %s#L%s · [%s] [%s] %s' % (vol, ln, t, k, ti)
    if au:
        s += ' · %s' % au
    return s


def read_tsv(path):
    """读平铺索引 TSV → (header, rows)。缺列补空；行短于表头则忽略该行。"""
    if not os.path.exists(path):
        return [], []
    with io.open(path, encoding='utf-8') as f:
        lines = [l.rstrip('\n') for l in f]
    lines = [l for l in lines if l.strip()]
    if not lines:
        return [], []
    header = lines[0].split('\t')
    rows = []
    for l in lines[1:]:
        cells = l.split('\t')
        if len(cells) < len(header):
            cells = cells + [''] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return header, rows


# ── 构建 ──────────────────────────────────────────────────────
def build_vol_md(vol, rows, now, l2name):
    groups = OrderedDict()
    for r in rows:
        g = _t(r.get(l2name)) or '（未标）'
        groups.setdefault(g, []).append((vol, r))
    out = ['# %s卷 · 多级目录（四库式）' % vol, '',
           '> 派生件：由 `daybook_multidx.py` 自《索引_%s卷.tsv》生成（%s）。' % (vol, now),
           '> 只读索引·不碰账·可删可重建·确定性。引用用 `%s#L行号`（行号＝卷内行号）。' % vol,
           '> 索引是目录不是真相；真相在本卷原文，改卷→重跑 `daybook.py index`→再重跑本件即重生。',
           '', '总条数：%d　｜　部：%s卷　｜　L2＝%s（%d 个二级组）'
           % (len(rows), vol, l2name, len(groups)), '']
    for g in sorted(groups):
        items = sorted(groups[g], key=lambda vr: _sort_key(vr, False))
        out.append('### %s（%d 条）' % (g, len(items)))
        out.append('')
        for v, r in items:
            out.append(_item_line(v, r))
        out.append('')
    if not rows:
        out.append('（本卷暂无条目）')
        out.append('')
    out.append('---')
    out.append('部次：%s（%d 条／%d 组）' % (vol, len(rows), len(groups)))
    return '\n'.join(out) + '\n'


def build_vol_tsv(vol, rows, l2name):
    buf = ['卷\t二级\t行号\t时间\t类\t作者\t标题']
    for v, r in sorted(((vol, r) for r in rows), key=lambda vr: _sort_key(vr, False)):
        buf.append('\t'.join([
            vol, _t(r.get(l2name)), _t(r.get('行号')), _t(r.get('时间')),
            _t(r.get('类')), _t(r.get('作者')),
            _t(r.get('标题')).replace('\t', ' ')]))
    return '\n'.join(buf) + '\n'


def build_total_md(vol_rows, now, orders=('子', '史', '集')):
    total = sum(len(rs) for rs in vol_rows.values())
    has_author = any(any(_t(r.get('作者')) for r in rs) for rs in vol_rows.values())
    out = ['# DAYBOOK 总目录（四库式·跨卷）', '',
           '> 派生件：由 `daybook_multidx.py` 自各卷平铺索引生成（%s）。只读·可删可重建·确定性。' % now,
           '> 索引是目录不是真相；真相在各卷原文。', '',
           '卷表：' + ' ／ '.join('%s(%d)' % (v, len(rs)) for v, rs in vol_rows.items())
           + ' ／ 合计 **%d** 条' % total, '']

    # 子·按类
    if '子' in orders:
        out += ['## 子·按类（跨卷合并）', '']
        cls = OrderedDict()
        for v, rs in vol_rows.items():
            for r in rs:
                cls.setdefault(_t(r.get('类')) or '（未标）', []).append((v, r))
        for c in sorted(cls):
            items = sorted(cls[c], key=lambda vr: _sort_key(vr, True))
            out.append('### %s（%d 条）' % (c, len(items)))
            out.append('')
            for v, r in items:
                out.append(_item_line(v, r))
            out.append('')

    # 史·按年月
    if '史' in orders:
        out += ['## 史·按年月', '']
        ym = OrderedDict()
        for v, rs in vol_rows.items():
            for r in rs:
                ym.setdefault(_ym(r.get('时间')) or '（无时）', []).append((v, r))
        for y in sorted(ym):
            items = sorted(ym[y], key=lambda vr: _sort_key(vr, True))
            out.append('### %s（%d 条）' % (y, len(items)))
            out.append('')
            for v, r in items:
                out.append(_item_line(v, r))
            out.append('')

    # 集·按作者（无作者列则略）
    if '集' in orders and has_author:
        out += ['## 集·按作者（跨卷）', '']
        au = OrderedDict()
        for v, rs in vol_rows.items():
            for r in rs:
                au.setdefault(_t(r.get('作者')) or '（无作者）', []).append((v, r))
        for a in sorted(au):
            items = sorted(au[a], key=lambda vr: _sort_key(vr, True))
            out.append('### %s（%d 条）' % (a, len(items)))
            out.append('')
            for v, r in items:
                out.append(_item_line(v, r))
            out.append('')

    out += ['---',
            '部次：' + ' ／ '.join('%s(%d)' % (v, len(rs)) for v, rs in vol_rows.items())
            + ' ／ 合计(%d)　｜　视图：%s' % (total, ''.join(orders))]
    return '\n'.join(out) + '\n'


def build(conf, root, now=None, only_vol=None, orders=('子', '史', '集')):
    """读各卷平铺 TSV → 写三件。only_vol 指定时只出该卷目录（跳总目录）。
    返回 (per_vol_counts, total)。"""
    now = now or datetime.now().strftime('%Y-%m-%d %H:%M')
    vols = conf.get('卷', {})
    outdir = (conf.get('索引', {}).get('输出目录', '') or '').strip()
    prefix = conf.get('索引', {}).get('索引前缀', '索引_')
    mdest = (conf.get('多级', {}).get('输出目录', '') or '').strip()
    l2name = (conf.get('多级', {}).get('二级键', '类') or '类').strip() or '类'

    base = os.path.join(root, outdir) if outdir else root
    mdir = os.path.join(base, mdest) if mdest else os.path.join(base, '多级')
    if not os.path.isdir(mdir):
        os.makedirs(mdir)

    vol_rows = OrderedDict()
    per = OrderedDict()
    for vol in vols:
        if only_vol and vol != only_vol:
            continue
        idf = os.path.join(base, '%s%s卷.tsv' % (prefix, vol))
        _header, rows = read_tsv(idf)
        vol_rows[vol] = rows
        per[vol] = len(rows)
        with io.open(os.path.join(mdir, '%s_目录.md' % vol), 'w', encoding='utf-8') as f:
            f.write(build_vol_md(vol, rows, now, l2name))
        with io.open(os.path.join(mdir, '%s_目录.tsv' % vol), 'w', encoding='utf-8') as f:
            f.write(build_vol_tsv(vol, rows, l2name))
    if not only_vol:
        with io.open(os.path.join(mdir, '总目录.md'), 'w', encoding='utf-8') as f:
            f.write(build_total_md(vol_rows, now, orders))
    return per, sum(per.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description='DAYBOOK 四库式多级索引生成器')
    ap.add_argument('--conf', default=None, help='配置文件（默认同目录 daybook.conf）')
    ap.add_argument('--now', default=None, help='钉死生成时间戳（双跑校对用）')
    ap.add_argument('--卷', dest='only_vol', default=None,
                    help='只生成该卷目录（不写总目录）——大账本按需裁剪')
    ap.add_argument('--序', default='全部',
                    help='总目录视图：子/史/集 任意组合｜全部（默认·大账本可只用一序省体积）')
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    orders = ('子', '史', '集') if a.序 == '全部' else tuple(x for x in ('子', '史', '集') if x in a.序)
    if not orders:
        orders = ('子',)
    conf = load_conf(a.conf or os.path.join(HERE, 'daybook.conf'))
    root = resolve_root(conf, HERE)
    per, total = build(conf, root, now=a.now, only_vol=a.only_vol, orders=orders)
    print('多级目录已生成：' + '｜'.join('%s %d' % (k, v) for k, v in per.items())
          + '｜合计 %d 条' % total
          + ('｜仅卷 %s（跳总目录）' % a.only_vol if a.only_vol else '｜视图 %s' % ''.join(orders)),
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
