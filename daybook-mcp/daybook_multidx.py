#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook_multidx.py —— DAYBOOK 四库式多级索引生成器
DAYBOOK four-branch multilevel catalogue generator.
（L1 部·卷 → L2 类/作者 → L3 属·条目；另出跨卷总目）
(Level 1 volume → level 2 category/author → level 3 entry, plus a cross-volume digest.)

定位（承 volume_format_spec.md §五「索引是目录不是真相」）：
Positioning (per volume_format_spec.md §5, "the index is a catalogue, not the record"):
  · **只读索引**，不读卷、不碰账；产出**派生件**（可删可重建）。
    **Read-only**: it reads indexes only, never volumes, never the record;
    the output is **derived data** (deletable and rebuildable).
  · 改卷 → 重跑 `daybook.py index` → 再重跑本件即重生（单一入口·禁各自扫卷）。
    Change a volume → rerun `daybook.py index` → rerun this file to regenerate.
  · **零依赖**（仅标准库）·**确定性**（同索引源·任何时刻算·得同一产出）。
    **Zero dependencies**; **deterministic** (same index source ⇒ same output).

输入：各卷**平铺索引 TSV**（`<索引前缀><卷>.tsv`·`daybook.py index` 之产物；本件不解析正账）
Input: the flat index TSV per volume (`<index_prefix><volume>.tsv`, produced by
`daybook.py index`). This file never parses the source volumes.
产出（默认落 `<out_dir>/multilevel/`）/ Output (default `<out_dir>/multilevel/`):
  `<卷>_catalog.md`  人读：部(卷)→类(二级)→属(条目) 三级树
                     human-readable three-level tree
  `<卷>_catalog.tsv` 机读：volume·level2·line·time·category·author·title
  `catalog.md`       跨卷总目（四库式·按类(子)／按年月(史)／按作者(集) 三序）
                     cross-volume digest (three views)

用法 / Usage：
  python3 daybook_multidx.py                 # 读同目录 daybook.conf
  python3 daybook_multidx.py --now "2026-10-15 15:00"   # 钉死时间戳（双跑校对）
  python3 daybook_multidx.py --volume 协作               # 只出该卷目录（跳总目录）
  python3 daybook_multidx.py --order 子                  # 总目录只出「按类」一序
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

# ── 别名归一（与 daybook 侧同表·本件自持以保自包含）──
# ── Alias normalisation (same table as daybook.py, held locally to stay self-contained). ──
SEC_ALIAS = {
    '卷': 'volumes', '条目': 'entries', '规则': 'rules', '索引': 'index',
    '触发': 'trigger', '多级': 'multilevel', '钩子': 'hooks',
}
KEY_ALIAS = {
    '头正则': 'head_regex', '附头正则': 'extra_head_regex', '标正则': 'tag_regex',
    '字段': 'fields', '根': 'root', '输出目录': 'out_dir', '索引前缀': 'index_prefix',
    '清单名': 'manifest', '自动索引': 'auto_index', '增量索引': 'incremental',
    '多级索引': 'multilevel_enabled', '二级键': 'level2_field', '变动令': 'on_change',
    '类': 'category', '标题': 'title', '作者': 'author',
}
FIELD_ALIAS = {
    '卷': 'volume', '行号': 'line', '时间': 'time',
    '类': 'category', '标题': 'title', '作者': 'author',
}


def canon_sec(name):
    """节名归一。Canonical section name."""
    return SEC_ALIAS.get(name, name)


def canon_key(name):
    """键名归一。Canonical key name."""
    return KEY_ALIAS.get(name, name)


def canon_field(name):
    """字段名归一。Canonical field name."""
    return FIELD_ALIAS.get(name, name)


# ── 配置读取（语义与 daybook.load_conf 一致·本件自持以保自包含）──
# ── Config reader (same semantics as daybook.load_conf; local for self-containment). ──
def load_conf(path):
    conf, sec = {}, None
    for line in io.open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = re.match(r'^\[(.+)\]$', line.strip())
        if m:
            sec = canon_sec(m.group(1))
            conf.setdefault(sec, {})
            continue
        if sec and '=' in line:
            k, v = line.split('=', 1)
            k = canon_key(k.strip())
            if k == 'fields':
                v = ','.join(canon_field(x) for x in v.split(','))
            conf[sec][k] = v.strip()
    return conf


def resolve_root(conf, here):
    """根目录：conf[index][root] 控制。空=here；..=上一级；绝对=原样。（与 daybook.py 同口径）
    Root resolution: conf[index][root]. Empty = here; '..' = parent; absolute = as-is."""
    rc = (conf.get('index', {}).get('root', '') or '').strip()
    if not rc:
        return here
    if rc == '..':
        return os.path.dirname(here)
    if os.path.isabs(rc):
        return rc
    return os.path.join(here, rc)


# ── 工具 ──────────────────────────────────────────────────────
# ── Helpers ───────────────────────────────────────────────────
def _t(s):
    """去首尾空白（None 安全）。Strip; None-safe."""
    return (s or '').strip()


def _int(s):
    """宽松转 int，失败返 0。Lenient int; 0 on failure."""
    try:
        return int(str(s).strip())
    except Exception:
        return 0


def _ym(t):
    """取 YYYY-MM 前缀。Take the YYYY-MM prefix."""
    return _t(t)[:7]


def _f(row, name):
    """按标准字段名取行值（表头若为旧中文名亦兼容）。Field lookup by canonical name."""
    return row.get(name, row.get(FIELD_ALIAS.get(name, name), ''))


def _sort_key(vr, with_vol):
    """条目排序键：时间 → （跨卷时先卷名）→ 行号。稳定·与 PYTHONHASHSEED 无关。
    Sort key: time → (volume when cross-volume) → line. Stable, hash-seed independent."""
    v, r = vr
    if with_vol:
        return (_t(_f(r, 'time')), v, _int(_f(r, 'line')))
    return (_t(_f(r, 'time')), _int(_f(r, 'line')))


def _item_line(vol, row):
    """条目提要行：卷#L行号 · [时间] [类] 标题 · 作者
    Entry digest line: volume#L<line> · [time] [category] title · author"""
    ln = _t(_f(row, 'line')) or '0'
    t = _t(_f(row, 'time'))
    k = _t(_f(row, 'category'))
    ti = _t(_f(row, 'title'))
    au = _t(_f(row, 'author'))
    s = '- %s#L%s · [%s] [%s] %s' % (vol, ln, t, k, ti)
    if au:
        s += ' · %s' % au
    return s


def read_tsv(path):
    """读平铺索引 TSV → (header, rows)。缺列补空；行短于表头则忽略该行。
    表头名一律归一为英文（旧中文表头的索引照读）。
    Read a flat index TSV → (header, rows). Short rows are padded; shorter-than-header
    rows are dropped. Header names are canonicalised, so legacy Chinese headers still work."""
    if not os.path.exists(path):
        return [], []
    with io.open(path, encoding='utf-8') as f:
        lines = [l.rstrip('\n') for l in f]
    lines = [l for l in lines if l.strip()]
    if not lines:
        return [], []
    header = [canon_field(h) for h in lines[0].split('\t')]
    rows = []
    for l in lines[1:]:
        cells = l.split('\t')
        if len(cells) < len(header):
            cells = cells + [''] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return header, rows


# ── 构建 ──────────────────────────────────────────────────────
# ── Build ─────────────────────────────────────────────────────
def build_vol_md(vol, rows, now, l2name):
    """单卷三级树 Markdown。One volume, three-level Markdown tree."""
    groups = OrderedDict()
    for r in rows:
        g = _t(_f(r, l2name)) or '（未标）'
        groups.setdefault(g, []).append((vol, r))
    out = ['# %s卷 · 多级目录（四库式）' % vol, '',
           '> 派生件：由 `daybook_multidx.py` 自《index_%s.tsv》生成（%s）。' % (vol, now),
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
    """单卷机读 TSV（表头英文）。One volume, machine-readable TSV (English header)."""
    buf = ['volume\tlevel2\tline\ttime\tcategory\tauthor\ttitle']
    for v, r in sorted(((vol, r) for r in rows), key=lambda vr: _sort_key(vr, False)):
        buf.append('\t'.join([
            vol, _t(_f(r, l2name)), _t(_f(r, 'line')), _t(_f(r, 'time')),
            _t(_f(r, 'category')), _t(_f(r, 'author')),
            _t(_f(r, 'title')).replace('\t', ' ')]))
    return '\n'.join(buf) + '\n'


def build_total_md(vol_rows, now, orders=('子', '史', '集')):
    """跨卷总目 Markdown（三序）。Cross-volume digest Markdown (three views)."""
    total = sum(len(rs) for rs in vol_rows.values())
    has_author = any(any(_t(_f(r, 'author')) for r in rs) for rs in vol_rows.values())
    out = ['# DAYBOOK 总目录（四库式·跨卷）', '',
           '> 派生件：由 `daybook_multidx.py` 自各卷平铺索引生成（%s）。只读·可删可重建·确定性。' % now,
           '> 索引是目录不是真相；真相在各卷原文。', '',
           '卷表：' + ' ／ '.join('%s(%d)' % (v, len(rs)) for v, rs in vol_rows.items())
           + ' ／ 合计 **%d** 条' % total, '']

    # 子·按类 / view: by category
    if '子' in orders:
        out += ['## 子·按类（跨卷合并）', '']
        cls = OrderedDict()
        for v, rs in vol_rows.items():
            for r in rs:
                cls.setdefault(_t(_f(r, 'category')) or '（未标）', []).append((v, r))
        for c in sorted(cls):
            items = sorted(cls[c], key=lambda vr: _sort_key(vr, True))
            out.append('### %s（%d 条）' % (c, len(items)))
            out.append('')
            for v, r in items:
                out.append(_item_line(v, r))
            out.append('')

    # 史·按年月 / view: by month
    if '史' in orders:
        out += ['## 史·按年月', '']
        ym = OrderedDict()
        for v, rs in vol_rows.items():
            for r in rs:
                ym.setdefault(_ym(_f(r, 'time')) or '（无时）', []).append((v, r))
        for y in sorted(ym):
            items = sorted(ym[y], key=lambda vr: _sort_key(vr, True))
            out.append('### %s（%d 条）' % (y, len(items)))
            out.append('')
            for v, r in items:
                out.append(_item_line(v, r))
            out.append('')

    # 集·按作者（无作者列则略）/ view: by author (skipped when no author column)
    if '集' in orders and has_author:
        out += ['## 集·按作者（跨卷）', '']
        au = OrderedDict()
        for v, rs in vol_rows.items():
            for r in rs:
                au.setdefault(_t(_f(r, 'author')) or '（无作者）', []).append((v, r))
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
    Read each volume's flat TSV → write the three artifacts. With only_vol, write
    just that volume's catalogue (digest skipped).
    返回 (per_vol_counts, total)。Returns (per_vol_counts, total)."""
    now = now or datetime.now().strftime('%Y-%m-%d %H:%M')
    vols = conf.get('volumes', {})
    outdir = (conf.get('index', {}).get('out_dir', '') or '').strip()
    prefix = conf.get('index', {}).get('index_prefix', 'index_')
    mdest = (conf.get('multilevel', {}).get('out_dir', '') or '').strip()
    l2name = (conf.get('multilevel', {}).get('level2_field', 'category') or 'category').strip() or 'category'
    if l2name in FIELD_ALIAS:              # 旧中文「二级键」值亦归一 / canonicalise legacy value
        l2name = FIELD_ALIAS[l2name]

    base = os.path.join(root, outdir) if outdir else root
    mdir = os.path.join(base, mdest) if mdest else os.path.join(base, 'multilevel')
    if not os.path.isdir(mdir):
        os.makedirs(mdir)

    vol_rows = OrderedDict()
    per = OrderedDict()
    for vol in vols:
        if only_vol and vol != only_vol:
            continue
        idf = os.path.join(base, '%s%s.tsv' % (prefix, vol))
        if not os.path.exists(idf):
            idf = os.path.join(base, '%s%s卷.tsv' % (prefix, vol))   # 旧名回退 / legacy fallback
        _header, rows = read_tsv(idf)
        vol_rows[vol] = rows
        per[vol] = len(rows)
        with io.open(os.path.join(mdir, '%s_catalog.md' % vol), 'w', encoding='utf-8') as f:
            f.write(build_vol_md(vol, rows, now, l2name))
        with io.open(os.path.join(mdir, '%s_catalog.tsv' % vol), 'w', encoding='utf-8') as f:
            f.write(build_vol_tsv(vol, rows, l2name))
    if not only_vol:
        with io.open(os.path.join(mdir, 'catalog.md'), 'w', encoding='utf-8') as f:
            f.write(build_total_md(vol_rows, now, orders))
    return per, sum(per.values())


def main(argv=None):
    """命令行入口。Command-line entry point."""
    ap = argparse.ArgumentParser(description='DAYBOOK 四库式多级索引生成器 / multilevel catalogue generator')
    ap.add_argument('--conf', default=None, help='配置文件（默认同目录 daybook.conf）/ config file')
    ap.add_argument('--now', default=None, help='钉死生成时间戳（双跑校对用）/ pin the timestamp')
    ap.add_argument('--volume', '--卷', dest='only_vol', default=None,
                    help='只生成该卷目录（不写总目录）——大账本按需裁剪 / single volume only')
    ap.add_argument('--order', '--序', dest='order_view', default='全部',
                    help='总目录视图：子/史/集 任意组合｜全部（默认·大账本可只用一序省体积）/ digest views')
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    orders = ('子', '史', '集') if a.order_view == '全部' else tuple(x for x in ('子', '史', '集') if x in a.order_view)
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
