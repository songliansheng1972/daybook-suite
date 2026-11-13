#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""DAYBOOK · 起居注体例发行版·索引器与触发器
Daybook — the daybook-format distribution: indexer and trigger.

零依赖：只用 Python 标准库。
Zero dependencies: Python standard library only.

用法 / Usage:
  python3 daybook.py index        生成/刷新索引 · build/refresh the index
  python3 daybook.py multiindex   生成四库式多级目录（部/类/属·跨卷总目）·派生件
                                  build the four-branch multilevel catalogue (derived)
  python3 daybook.py watch [秒]   监视各卷，变动即自动重算索引 + 自动续建多级目录 + 自动备份
                                  watch volumes; on change re-index + rebuild catalogue + backup
  python3 daybook.py backup       手动备份：把所有卷复制到 backup/YYYY-MM-DD_HHMMSS/
                                  manual backup into backup/YYYY-MM-DD_HHMMSS/
  python3 daybook.py query key=value ...  按字段精确查询条目原文（E-11 工具）
                                  exact field query over the index
     字段（field names）：volume/line/time/category/title/author。
     旧中文名（卷/行号/时间/类/标题/作者）仍可用作兼容别名。
     Chinese legacy names still work as compatibility aliases.
     值为子串匹配，留空表示不过滤。Values are substring matches; empty = no filter.
     例 / e.g.: python3 daybook.py query category=实验 time=2026-10
                python3 daybook.py query title=daybook
  python3 daybook.py mcp          启动 MCP 服务器（JSON-RPC 2.0 over stdio）
                                  start the MCP server
      暴露 daybook 卷为 resources · 暴露 query/append/cross_ref 为 tools · 4 个 prompt 模板
      零依赖，不联网，与 index/watch 同一二进制。
  python3 daybook.py orchestrate <子命令>  智能体编排中心「司南」（第三产品线）
                                  the agent orchestration hub (product line 3)
      别名 / alias: 编排 · 司南
      把身份/任务/锁/心跳/路由焊成一个闭环：
      join/who/open/claim/submit/review/pull/board/alarm/selftest
      零依赖，卷为唯一底座，与 index/mcp 同一二进制。
客户可改 daybook.conf 定字段与卷。
Customers may edit daybook.conf to define fields and volumes.
"""
import io, os, re, sys, time, hashlib, json, shutil

ENC_REPORT = []
VIOLATIONS = []      # 本轮 build 的 append-only 违例（卷, 说明）；CLI index 据此非零退出
RULE_WARN = []       # 字段规则告警（tag:N 无法解析等），每轮去重后上报·不再静默
CURSOR_FMT = 2       # 游标代次：1=size+mtime+头尾探针（旧·可伪造⇒判过期）；2=全卷 sha256
INDEX_FMT = 2        # 索引代次：写进 .head_stamp.json 与卷首清单，旧代一律视为过期
HASH_CHUNK = 1 << 20
HERE = os.path.dirname(os.path.abspath(__file__))

_RULE_WARN_SEEN = set()


def _rule_warn(msg):
    """规则告警去重登记（同一配置只报一次）。De-duplicated rule warning (once per build)."""
    if msg in _RULE_WARN_SEEN:
        return
    _RULE_WARN_SEEN.add(msg)
    RULE_WARN.append(msg)


def _hash_vol(path, prefix_limit=None):
    """单遍流式 sha256：返回 (全卷哈希, 前 prefix_limit 字节哈希或 None)。
    One-pass streaming SHA-256: returns (whole-file hex, prefix[0:prefix_limit] hex or None).
    ★ 全卷哈希是「未变」与「等长改写」的唯一判据；mtime/size 只作快筛线索，不作判据。
    ★ 不整卷入内存，14 MB 账卷的读取＋哈希约十几毫秒。"""
    h_full = hashlib.sha256()
    h_pref = hashlib.sha256() if prefix_limit is not None else None
    n = 0
    with open(path, 'rb') as f:
        while True:
            b = f.read(HASH_CHUNK)
            if not b:
                break
            h_full.update(b)
            if h_pref is not None and n < prefix_limit:
                take = min(len(b), prefix_limit - n)
                if take > 0:
                    h_pref.update(b[:take])
            n += len(b)
    return h_full.hexdigest(), (h_pref.hexdigest() if h_pref is not None else None)


def _cursor_current(cur):
    """游标是否为本代（含全卷哈希）。旧代游标一律不参与「未变」判定。
    Whether the cursor is current-generation (carries a whole-file hash)."""
    return bool(cur) and cur.get('fmt') == CURSOR_FMT \
        and isinstance(cur.get('size'), int) and cur.get('content_hash')

# ── 条目头默认口径（唯一真源）─────────────────────────────────
# ── Default entry-head pattern (single source of truth). ──
# ★ v3.2.2：默认口径放宽为「秒可选」。原先只认到分钟，而本套件的写入器
#   （daybook_append.py / 心跳 / 锁 / 消息 / MCP）都写「时:分:秒」，任务卷
#   （task_volume.py）写「时:分」——两种精度都是合法写法，只认一种必吞另一半。
#   ⇒ 任何「只认一种精度」的默认值都是错的，故缺省同时容纳两种。
# ★ v3.2.2: the default widens to "seconds optional". The suite's writers emit
#   "HH:MM:SS" (append/heartbeat/lock/message/MCP) while the task volume emits
#   "HH:MM" — both are legal forms here, so any single-precision default drops
#   half the entries. This one accepts both.
DEFAULT_HEAD_REGEX = r'^(?:\[#\d+\][ ]*)?\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)\]'


# ── 别名归一（英文为准·中文兼容）─────────────────────────────
# ── Alias normalisation (English canonical · Chinese legacy). ──
# ★ 唯一入口：load_conf()。下游一律只见英文名。
# ★ Single entry point: load_conf(). Everything downstream sees English only.
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
    """键名归一（含规则键与字段名）。Canonical key/field name."""
    return KEY_ALIAS.get(name, name)


def canon_field(name):
    """字段名归一（含内置三字段）。Canonical field name."""
    return FIELD_ALIAS.get(name, name)


# ── 编码自动检测与转码（零依赖·不静默·须报出所用编码）──
# ── Encoding sniffing and transcoding (zero-dep, never silent). ──
def sniff(raw):
    """返回 (文本, 编码名, 依据)。Returns (text, encoding, reason).
    薄委托：检测逻辑唯一在 safeio.sniff_bytes（#463 合一·勿在此重实现）。
    Thin delegate: the only detector lives in safeio.sniff_bytes (#463).
    不许静默：依据必须可写出来。Never silent: the reason must be printable."""
    from safeio import sniff_bytes
    return sniff_bytes(raw)

def read_text(path):
    """读卷并返回 (文本, 编码, 检测依据)。Read a volume → (text, encoding, reason)."""
    with open(path, 'rb') as f:
        raw = f.read()
    return sniff(raw)



def load_conf(path=None):
    """Load the DAYBOOK configuration into section and key dictionaries.
    载入配置为「节 → 键」两参字典；此处即中→英别名归一的唯一入口。
    Canonicalisation of Chinese legacy names happens here and nowhere else."""
    path = path or os.path.join(HERE, 'daybook.conf')
    conf = {'volumes': {}, 'entries': {}, 'index': {}, 'trigger': {}}
    sec = None
    for line in io.open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'): continue
        m = re.match(r'^\[(.+)\]$', line.strip())
        if m: sec = canon_sec(m.group(1)); conf.setdefault(sec, {}); continue
        if sec and '=' in line:
            k, v = line.split('=', 1)
            k = canon_key(k.strip())
            if k == 'fields':
                # 字段表里每个名字也归一。Field list members are canonicalised too.
                v = ','.join(canon_field(x) for x in v.split(','))
            conf.setdefault(sec, {})[k] = v.strip()
    return conf


# ── 字段抽取（客户可自定字段：字段名 = 规则）──
# ── Field extraction (customer-defined: field name = rule). ──
BUILTIN = ('volume', 'line', 'time')

def fill(row, fields, rules, line, tag, lines=None, head_re=None, is_extra=False):
    """按 fields 顺序产出整行。规则形 / Emit one row in `fields` order; rule forms:
       tag:N  ⇒ 取条目标签正则的第 N 组 / Nth capture group of the tag regex
       len    ⇒ 该条正文字数 / character count of the entry body
       contains:xxx ⇒ 正文含 xxx 则 1 否则 0 / 1 if body contains xxx, else 0
       count:xxx    ⇒ 出现次数 / occurrence count
       head   ⇒ 标题文字 / heading text
       depth  ⇒ 标题层数 / Markdown heading depth
       无规则 ⇒ 空串（客户可只加表头占位）
       No rule ⇒ empty string (header-only placeholder columns are allowed).
    """
    text = lines if lines is not None else (line or '')
    out = []
    for idx, name in enumerate(fields):
        if idx < len(row) and name in BUILTIN:
            out.append(row[idx]); continue
        r = rules.get(name, '')
        val = ''
        if r.startswith('tag:'):
            try:
                g = int(r.split(':', 1)[1])
                if g < 1:
                    raise ValueError
            except ValueError:
                # ★ 规则写坏（tag:abc / tag:0）⇒ 空列不许静默，登记告警进清单
                # ★ A broken rule must not silently become an empty column
                _rule_warn('tag 规则无法解析：%r（应为 tag:N，N≥1）' % r)
                g = None
            if g is not None:
                try:
                    if tag:
                        t = tag.match(line or '')
                        if t and g <= len(t.groups()) and t.group(g) is not None:
                            val = t.group(g)
                        elif t and g > len(t.groups()):
                            _rule_warn('tag:%d 超出标签正则分组数 %d（该列恒空）'
                                       % (g, len(t.groups())))
                    # ★ 附头（MD 标题）不匹配标正则 ⇒ 退回用标题文字
                    # ★ Extra heads (MD titles) miss the tag regex ⇒ fall back to the title text
                    if not val and is_extra and head_re:
                        hm = head_re.match(line or '')
                        if hm and g == 1: val = '标题'
                        elif hm: val = (line or '')[len(hm.group(0)):].strip()
                except (IndexError, AttributeError):
                    _rule_warn('tag:%d 取值失败（正则分组越界）' % g)
                    val = ''
        elif r == 'len':
            val = str(len(re.sub(r'\s', '', text)))
        elif r.startswith('contains:'):
            val = '1' if r.split(':', 1)[1] in text else '0'
        elif r == 'head':
            if is_extra and head_re:
                mm = head_re.match(line or '')
                val = (line or '')[len(mm.group(0)):].strip() if mm else ''
            elif head_re:
                mm = head_re.match(line or '')
                val = mm.group(1) if mm and mm.groups() else ''
        elif r == 'depth':
            if is_extra and line:
                val = str(len(line) - len(line.lstrip('#')))
        elif r.startswith('count:'):
            val = str(text.count(r.split(':', 1)[1]))
        out.append(val.replace('\t', ' '))
    return out

def _cursor_path(outdir, vol):
    """游标路径（新英文名）。Cursor path (new English name)."""
    return os.path.join(outdir, '.cursor_%s.json' % vol)

def _legacy_cursor_path(outdir, vol):
    """旧中文名游标（只读兼容）。Legacy Chinese-named cursor (read-only fallback)."""
    return os.path.join(outdir, '.游标_%s.json' % vol)


def _criterion_stamp(conf):
    """口径指纹：head_regex／extra_head_regex／tag_regex／fields 四项捆成一个 sha256。
    Criterion fingerprint: SHA-256 over the head/extra-head/tag regexes and the field list.
    ★ 只指纹不 Merkle：判据与时间、次序无关，四项全量即唯一。
    ★ 口径一变，索引口径就漂移。此闸把「改正则必须重建」从文档纪律变成机器判据。
    ★ A criterion change drifts the index; this gate turns "rebuild after editing
      the regex" from prose into an executable check."""
    e = conf.get('entries', {})
    key = '\x1f'.join([e.get('head_regex', ''), e.get('extra_head_regex', ''),
                       e.get('tag_regex', ''), e.get('fields', '')])
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def _criterion_gate(conf, outdir, vols, prefix, report):
    """口径漂移闸：索引旁 .head_stamp.json 记着上次建索引用的口径。
    Drift gate: the stamp records the criterion used by the previous build.
      一致   ⇒ 放行（增量照旧）/ same ⇒ proceed incrementally
      不一致 ⇒ 删该卷 TSV／TXT／游标，全量重扫 / changed ⇒ drop them and rescan
                （增量游标已越过旧行、不回补；留着就是静默丢条目）
      无戳   ⇒ 存量索引口径未溯源：放行并补戳，不冤枉升级用户
                (no stamp ⇒ legacy index: proceed and stamp, never punish an upgrade)
    返回 True 表示本轮触发了漂移重建。Returns True when a drift rebuild happened."""
    sp = os.path.join(outdir, '.head_stamp.json')
    now_stamp = _criterion_stamp(conf)
    old = {}
    if os.path.isfile(sp):
        try:
            old = json.load(io.open(sp, encoding='utf-8'))
        except Exception:
            old = {}
    prev = old.get('口径')
    prev_fmt = old.get('index_fmt')
    if prev is not None and prev_fmt != INDEX_FMT:
        # ★ 索引代次过期：旧判据（size+mtime 即可判「未变」）不可信，暂存的索引一律重建。
        # ★ Stale index generation: the old "unchanged" criterion is forgeable; rebuild all.
        for vol in vols:
            for name in (os.path.join(outdir, '%s%s.tsv' % (prefix, vol)),
                         os.path.join(outdir, '%s%s.txt' % (prefix, vol)),
                         os.path.join(outdir, '%s%s卷.tsv' % (prefix, vol)),
                         _cursor_path(outdir, vol), _legacy_cursor_path(outdir, vol)):
                try:
                    os.remove(name)
                except OSError:
                    pass
        report.append(('格式闸', '★ 索引格式过期（第 %s 代 → 第 %d 代）：旧索引不可静默沿用，已清索引与游标·全量重扫'
                       % (prev_fmt if prev_fmt is not None else '无标记', INDEX_FMT)))
        return True
    if prev is None:
        report.append(('口径闸', '存量索引无口径戳·本轮补戳（口径未溯源）·legacy index, stamp added'))
        return False
    if prev == now_stamp:
        return False
    for vol in vols:
        for name in (os.path.join(outdir, '%s%s.tsv' % (prefix, vol)),
                     os.path.join(outdir, '%s%s.txt' % (prefix, vol)),
                     os.path.join(outdir, '%s%s卷.tsv' % (prefix, vol)),
                     _cursor_path(outdir, vol), _legacy_cursor_path(outdir, vol)):
            try:
                os.remove(name)
            except OSError:
                pass
    report.append(('口径闸', '★ 口径已改（%s → %s）：增量不回补，已清索引与游标·全量重扫'
                   % (prev[:8], now_stamp[:8])))
    return True


def _cursor_obj(size, mtime, resume_byte, n, last_lineno, enc, content_hash):
    """游标对象（第 2 代）：全卷 sha256 为唯一「未变」判据，size/mtime 仅供快筛与记述。
    Cursor object (generation 2): the whole-file SHA-256 is the only "unchanged" criterion;
    size/mtime serve as hints and provenance only."""
    return {'fmt': CURSOR_FMT, 'hash': 'sha256', 'content_hash': content_hash,
            'size': size, 'mtime': mtime, 'resume_byte': resume_byte, 'n': n,
            'last_lineno': last_lineno, 'enc': enc}


def _write_cursor(path, obj):
    """写游标 json（与 index 同临界区）。Write the cursor json (same critical section as the index)."""
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False))


def build(conf, root='.'):
    """扫描各卷，生成索引。append-only ⇒ 增量：未变跳过、只追加读尾部、旧部分被改报违例。
    Scan volumes and build indexes. Append-only ⇒ incremental: skip unchanged,
    tail-read on pure append, flag violations when the old part was rewritten."""
    ENC_REPORT.clear()  # ★ 每轮 build 清空编码报告，防 watch 多轮累积
                        # ★ Clear the encoding report each build so watch does not accumulate
    VIOLATIONS.clear()
    RULE_WARN.clear()
    _RULE_WARN_SEEN.clear()
    vols = conf.get('volumes', {})
    head = re.compile(conf['entries'].get('head_regex', DEFAULT_HEAD_REGEX))
    # ★ 作者 ID 红线（老宋定）：新格式 [时间][类][标题][作者] 4 段优先；
    # 旧格式 [时间][类][标题] 3 段兼容（作者列留空）。
    # ★ Author-ID rule (Song): the 4-part [time][category][title][author] form wins;
    #   the older 3-part form stays compatible (author column left empty).
    tag  = re.compile(conf['entries'].get('tag_regex', r'^\[[^\]]+\]\s*\[([^\]]+)\]\s*\[([^\]]*)\](?:\s*\[([^\]]*)\])?'))
    fields = [x.strip() for x in conf['entries'].get('fields', 'volume,line,time,category,title').split(',')]
    rules = {k: v for k, v in conf.get('rules', {}).items()}
    heads = [head]
    for extra in conf['entries'].get('extra_head_regex', '').split('||'):
        if extra.strip(): heads.append(re.compile(extra.strip()))
    outdir = os.path.join(root, conf['index'].get('out_dir', ''))
    prefix = conf['index'].get('index_prefix', 'index_')
    if not os.path.isdir(outdir): os.makedirs(outdir)
    incremental = conf['trigger'].get('incremental', '是') in ('是', '1', 'true', 'True', 'yes')
    per, total, report = {}, 0, []
    # W-75 修②：索引写入全临界区（TSV/游标/清单·目录级锁）
    # W-75 fix 2: the whole index write is one critical section (TSV/cursor/manifest, dir lock)
    from safeio import locked as _safe_locked
    with _safe_locked(os.path.join(outdir, '.index.lock')):

        # ── 口径漂移闸：口径变了就清索引重扫，不许静默丢条目 ──
        # ── Criterion drift gate: a changed criterion forces a full rescan ──
        _criterion_gate(conf, outdir, vols, prefix, report)

        for vol, path in vols.items():
            p = path if os.path.isabs(path) else os.path.join(root, path)
            idf = os.path.join(outdir, '%s%s.tsv' % (prefix, vol))
            idf_legacy = os.path.join(outdir, '%s%s卷.tsv' % (prefix, vol))
            cp = _cursor_path(outdir, vol)
            cp_legacy = _legacy_cursor_path(outdir, vol)
            if not os.path.exists(p): per[vol] = 0; continue
            size, mt = os.path.getsize(p), os.path.getmtime(p)

            cur = None
            # 读游标：新名优先，旧名回退（兼容改名前的账本）
            # Read cursor: new name first, legacy name as fallback (pre-rename books)
            cpath = cp if os.path.exists(cp) else (cp_legacy if os.path.exists(cp_legacy) else None)
            if incremental and cpath and os.path.exists(idf):
                try: cur = json.load(io.open(cpath, encoding='utf-8'))
                except Exception: cur = None

            rows, mode, n_old = [], 'full', 0
            content_hash = None

            def _violate(msg):
                report.append((vol, msg))
                VIOLATIONS.append((vol, msg))

            # ── 游标代次闸：旧代游标（无全卷哈希）不参与任何「未变」判定 ──
            # ── Cursor-generation gate: an old cursor (no whole-file hash) can never claim "unchanged" ──
            if cur is not None and not _cursor_current(cur):
                report.append((vol, '★ 旧游标格式（第 %s 代）·视为过期·全量重扫'
                               % (cur.get('fmt') if cur.get('fmt') is not None else '无标记')))
                cur = None

            # ── 情形一：字节数与游标相同 ⇒ 必验全卷哈希（mtime 可被 os.utime 恢复，不作判据）──
            # ── Case 1: same size as the cursor ⇒ verify the whole-file hash (mtime is forgeable) ──
            if cur and os.path.exists(idf) and cur.get('size') == size:
                content_hash, _ = _hash_vol(p)
                if content_hash == cur.get('content_hash'):
                    per[vol] = cur.get('n', 0); total += per[vol]
                    if mt != cur.get('mtime'):
                        report.append((vol, '未变·跳过（全卷哈希一致·mtime 已变化，仅记入游标）'))
                        _write_cursor(cp, _cursor_obj(size, mt, size, cur.get('n', 0),
                                                      cur.get('last_lineno', 0),
                                                      cur.get('enc', '?'), content_hash))
                    else:
                        report.append((vol, '未变·跳过（全卷哈希一致）'))
                    ENC_REPORT.append((vol, cur.get('enc', '?'), '游标缓存·全卷哈希复核'))
                    # ★ 老宋定：未变跳过时也要确保索引 TXT 存在（首次升级到带 TXT 版时补齐）
                    # ★ Song: even when skipping, make sure the TXT index exists (first upgrade)
                    itxt = os.path.join(outdir, '%s%s.txt' % (prefix, vol))
                    if not os.path.exists(itxt) and os.path.exists(idf):
                        with io.open(idf, encoding='utf-8') as src:
                            with io.open(itxt, 'w', encoding='utf-8') as dst:
                                dst.write('# index_%s (human-readable; machine-readable TSV alongside)\n' % vol)
                                dst.write('# 索引 %s（人类可读·机器可读 TSV 同目录）\n' % vol)
                                dst.write('# Generated by daybook.py index · rebuildable from the volumes at any time\n')
                                dst.write('# 由 daybook.py index 自动生成·可随时从原文重算\n')
                                dst.write('# The index is a catalogue, not the record. The record is the volumes.\n')
                                dst.write('# 索引是目录不是真相·真相在各卷原文\n\n')
                                lines = src.read().split('\n')
                                for line in lines[1:]:  # 跳过表头 / skip the header
                                    if not line.strip(): continue
                                    cols = line.split('\t')
                                    dst.write('[%s] line=%s category=%s title=%s author=%s\n' % (
                                        cols[2] if len(cols) > 2 else '',
                                        cols[1] if len(cols) > 1 else '',
                                        cols[3] if len(cols) > 3 else '',
                                        cols[4] if len(cols) > 4 else '',
                                        cols[5] if len(cols) > 5 else ''))
                    continue
                _violate('★ 等长改写（字节数未变·全卷哈希不符）·append-only 违例·全重扫')

            # ── 情形二：只追加 ⇒ 已知前缀验哈希 ＋ 读尾部 ＋ 追加写索引 ──
            # ── Case 2: pure append ⇒ verify the known prefix hash + tail-read + append to the index ──
            elif cur and size > cur.get('size'):
                content_hash, pref_hash = _hash_vol(p, prefix_limit=cur['size'])
                n_old_b = cur.get('resume_byte')
                if pref_hash != cur.get('content_hash'):
                    content_hash = None
                    _violate('★ 旧部分被改（前缀全卷哈希不符）·append-only 违例·全重扫')
                elif not isinstance(n_old_b, int) or not 0 <= n_old_b <= size:
                    content_hash = None
                    _violate('★ 游标 resume_byte 越界（%r）·append-only 违例·全重扫' % (n_old_b,))
                else:
                    with open(p, 'rb') as f:
                        f.seek(n_old_b); tail = f.read()
                    n_idx = _count_index_rows(idf)
                    if n_idx != cur.get('n', -1):
                        content_hash = None
                        _violate('★ 索引行数与游标不符（索引 %d 行 / 游标 %r）·append-only 违例·全重扫'
                                 % (n_idx, cur.get('n')))
                    else:
                        enc = cur.get('enc')
                        if not enc:
                            txt, enc, _ = sniff(tail)  # 旧游标无 enc，当场 sniff / legacy cursor has no enc
                        else:
                            try:
                                txt = tail.decode(enc, 'replace')
                            except (LookupError, UnicodeDecodeError):
                                txt, enc, _ = sniff(tail)
                        base_ln = cur.get('last_lineno', 0)                # ★ 从游标读旧最后一行行号 / resume line number
                        rows, final_ln = _parse(txt, heads, fields, rules, tag, vol, base_ln)
                        mode = 'append'; n_old = n_idx
                        report.append((vol, '只追加·验已知前缀哈希·读尾部 %d 字节·索引 append %d 行'
                                       % (len(tail), len(rows))))
                        ENC_REPORT.append((vol, enc, '尾部续读·按游标编码'))

            elif cur and size < cur.get('size'):
                _violate('★ 卷变短（%d → %d 字节）·append-only 违例·全重扫' % (cur['size'], size))

            # ── 情形三：全量 ── / ── Case 3: full rescan ──
            if mode == 'full':
                raw = open(p, 'rb').read()
                content_hash = hashlib.sha256(raw).hexdigest()
                txt, enc, why = sniff(raw)
                rows, final_ln = _parse(txt, heads, fields, rules, tag, vol, 0)
                if not any(r[0] == vol for r in report):
                    report.append((vol, '全扫·%d 行' % len(rows)))
                ENC_REPORT.append((vol, enc, why))

            # ── 写索引 ── / ── Write the index ──
            if mode == 'append':
                with io.open(idf, 'a', encoding='utf-8') as f:
                    for r in rows: f.write('\t'.join(x.replace('\t', ' ') for x in r) + '\n')
                # ★ 索引 TXT 同步追加（老宋定：TSV+TXT 同目录·人读＋机读）
                # ★ Append the TXT index in step (Song: TSV + TXT side by side)
                itxt = os.path.join(outdir, '%s%s.txt' % (prefix, vol))
                with io.open(itxt, 'a', encoding='utf-8') as f:
                    for r in rows:
                        f.write('[%s] line=%s category=%s title=%s author=%s\n' % (
                            r[2] if len(r) > 2 else '', r[1] if len(r) > 1 else '',
                            r[3] if len(r) > 3 else '', r[4] if len(r) > 4 else '',
                            r[5] if len(r) > 5 else ''))
                n_total = n_old + len(rows)
            else:
                with io.open(idf, 'w', encoding='utf-8') as f:
                    f.write('\t'.join(fields) + '\n')
                    for r in rows: f.write('\t'.join(x.replace('\t', ' ') for x in r) + '\n')
                # ★ 索引 TXT 同步生成（全扫重建） / ★ TXT rebuilt too (full rescan)
                itxt = os.path.join(outdir, '%s%s.txt' % (prefix, vol))
                with io.open(itxt, 'w', encoding='utf-8') as f:
                    f.write('# index_%s (human-readable; machine-readable TSV alongside)\n' % vol)
                    f.write('# 索引 %s（人类可读·机器可读 TSV 同目录）\n' % vol)
                    f.write('# Generated by daybook.py index · rebuildable from the volumes at any time\n')
                    f.write('# 由 daybook.py index 自动生成·可随时从原文重算\n')
                    f.write('# The index is a catalogue, not the record. The record is the volumes.\n')
                    f.write('# 索引是目录不是真相·真相在各卷原文\n\n')
                    for r in rows:
                        f.write('[%s] line=%s category=%s title=%s author=%s\n' % (
                            r[2] if len(r) > 2 else '', r[1] if len(r) > 1 else '',
                            r[3] if len(r) > 3 else '', r[4] if len(r) > 4 else '',
                            r[5] if len(r) > 5 else ''))
                n_total = len(rows)
            per[vol] = n_total; total += n_total
            _write_cursor(cp, _cursor_obj(size, mt, size, n_total, final_ln, enc, content_hash))

        with io.open(os.path.join(outdir, conf['index'].get('manifest', 'volumes.md')), 'w', encoding='utf-8') as f:
            f.write('# 卷首清单 / Volume manifest\n')
            f.write('# 索引格式 / index format: %d · 游标格式 / cursor format: %d（全卷 sha256）\n\n'
                    % (INDEX_FMT, CURSOR_FMT))
            f.write('| volume | entries | index file |\n|---|---|---|\n')
            for v, n in per.items(): f.write('| %s | %d | %s%s.tsv |\n' % (v, n, prefix, v))
            f.write('| **合计 / total** | **%d** | |\n\n' % total)
            f.write('索引是目录，不是真相。真相在各卷原文。索引可随时从原文重算。\n')
            f.write('The index is a catalogue, not the record. The record is the volumes; the index is rebuildable.\n\n')
            f.write('## 本次增量报告 / This run\n\n| volume | action |\n|---|---|\n')
            for v, w in report: f.write('| %s | %s |\n' % (v, w))
            for w in RULE_WARN: f.write('| 规则 / rules | ★ %s |\n' % w)
            f.write('\n## 编码检测（不静默）/ Encoding detected (never silent)\n\n| volume | encoding | reason |\n|---|---|---|\n')
            for v, e, w in ENC_REPORT: f.write('| %s | %s | %s |\n' % (v, e, w))
        # 口径戳：本轮判据落盘，供下轮比对（与 TSV／游标同临界区）
        with io.open(os.path.join(outdir, '.head_stamp.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps({'口径': _criterion_stamp(conf),
                                'index_fmt': INDEX_FMT,
                                'cursor_fmt': CURSOR_FMT,
                                'head_regex': conf.get('entries', {}).get('head_regex', ''),
                                '时戳': time.strftime('%Y-%m-%d %H:%M:%S')}, ensure_ascii=False))
        return per, total, report


def _count_index_rows(idf):
    """数索引数据行（不含表头）。Count index data rows (header excluded)."""
    with io.open(idf, encoding='utf-8') as f:
        return sum(1 for l in f if l.strip()) - 1


def _parse(txt, heads, fields, rules, tag, vol, base_ln):
    """单遍扫描：切块 ＋ 记行号。heads[0] 为主头，其余为附头。
    Single pass: split into blocks and track line numbers; heads[0] is the main head.
    返回 (rows, final_ln)：final_ln = 扫描结束时的行号，供下次 append 模式做 base_ln。
    ★ final_ln = base_ln + 实际行数（含末尾空行，按 \\n 数算），不用 ln-1（避免 split 末尾空字符串让行号偏离）。
    ★ final_ln = base_ln + real line count (by \\n), not ln-1, so a trailing empty
      split element cannot shift the line numbers."""
    if not txt:
        return [], base_ln
    actual_lines = txt.count('\n') + (0 if txt.endswith('\n') else 1)
    final_ln = base_ln + actual_lines
    out, cur, ln, start, which = [], None, base_ln + 1, 0, None
    for line in txt.split('\n'):
        hit = None
        for k, h in enumerate(heads):
            if h and h.match(line): hit = k; break
        if hit is not None:
            if cur is not None:
                out.append(_mk(cur, start, which, heads, head_re0=heads[0], fields=fields, rules=rules, tag=tag, vol=vol))
            cur, start, which = line, ln, hit
        elif cur is not None:
            cur += '\n' + line
        ln += 1
    if cur is not None:
        out.append(_mk(cur, start, which, heads, head_re0=heads[0], fields=fields, rules=rules, tag=tag, vol=vol))
    return out, final_ln


def _mk(blk, start, which, heads, head_re0, fields, rules, tag, vol):
    """单块 → 一行。One block → one index row."""
    mm = head_re0.match(blk)
    tm = mm.group(1) if mm else ''
    return fill([vol, str(start), tm], fields, rules, blk, tag,
                head_re=heads[which] if which is not None else head_re0,
                is_extra=(which not in (0, None)))

def backup(conf, root='.'):
    """把所有卷复制到 backup/YYYY-MM-DD_HHMMSS/。append-only 纪律适用于备份：旧的不删不改。
    Copy every volume into backup/YYYY-MM-DD_HHMMSS/. Append-only applies to backups too:
    old copies are never deleted or modified.
    ★ 老宋定：索引目录（TSV+TXT+清单）也一起备份——索引可重算，但备份能救命。
    ★ Song: back up the index directory as well (TSV+TXT+manifest)."""
    vols = conf.get('volumes', {})
    bdir = os.path.join(root, 'backup', time.strftime('%Y-%m-%d_%H%M%S'))
    os.makedirs(bdir, exist_ok=True)
    n = 0
    for vol, path in vols.items():
        p = path if os.path.isabs(path) else os.path.join(root, path)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(bdir, os.path.basename(p)))
            n += 1
    # ★ 备份索引目录（TSV+TXT+清单+游标） / ★ Back up the index directory too
    idx_dir = conf.get('index', {}).get('out_dir', '')
    idx_full = idx_dir if os.path.isabs(idx_dir) else os.path.join(root, idx_dir)
    if os.path.isdir(idx_full):
        bidx = os.path.join(bdir, os.path.basename(idx_full))
        os.makedirs(bidx, exist_ok=True)
        for name in os.listdir(idx_full):
            src = os.path.join(idx_full, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(bidx, name))
    return bdir, n

def hash_volumes(paths):
    """卷内容指纹（含 mtime/size 作变更线索）。watch 的变动判定不得只看元数据：
    等长改写＋os.utime 恢复会让纯元数据指纹完全看不出变化。
    Volume content fingerprint (mtime/size kept as change hints). watch must not rely on
    metadata alone: an equal-length rewrite plus os.utime restoration is invisible to it.
    ★ 代价：每次轮询顺序读一遍各卷（14 MB ≈ 十几毫秒）；这是抓得住篡改的最小代价。"""
    h = hashlib.sha256()
    for p in paths:
        if not os.path.exists(p): continue
        h.update(str(os.path.getmtime(p)).encode()); h.update(str(os.path.getsize(p)).encode())
        try:
            full, _ = _hash_vol(p)
        except OSError:
            continue  # 卷正在被替换/删除：本轮不当变动，下轮再看
        h.update(full.encode())
    return h.hexdigest()[:12]

def query(conf, root, args):
    """按字段精确查询条目原文。E-11 daybook 上下文工具。
    Exact field query over the index — the E-11 daybook context tool.
    索引层：TSV 过滤（字段子串匹配，SQL 式而非向量召回）。
    Index layer: TSV filtering (substring match, SQL-like, not vector recall).
    返回层：按卷+行号定位原文，从该行读到下一条目头前。
    Return layer: locate the source by volume+line and read to the next entry head.
    ★ 优化：同卷只 readlines 一次，所有命中复用 lines（避免 O(n*m) I/O 灾难）。
    ★ Optimised: read each volume once and reuse the lines for all hits.
    ★ 支持 --limit N 限制输出原文条数（默认 50），防 10 万命中爆 stdout。
    ★ Supports --limit N (default 50) to keep huge result sets off stdout.
    ★ 支持 --count 只输出命中数，不读原文。 / ★ --count prints only the hit count.
    ★ 支持 --sample N 采样召回 N 条（均匀抽样），用于触发上下文召回 1000 条喂 AI。
    ★ --sample N takes an even sample of N entries.
    ★ 支持 --context N 返回命中条目 + 前后各 N 条邻居（共 2N+1 条/命中），模拟"周边记忆"。
    ★ --context N returns the hit plus N neighbours either side (2N+1 per hit).
    """
    filters = {}
    limit = 50
    count_only = False
    sample_n = 0
    context_n = 0
    for a in args:
        if a == '--count':
            count_only = True; continue
        if a.startswith('--limit='):
            try: limit = int(a.split('=', 1)[1])
            except: pass
            continue
        if a.startswith('--sample='):
            try: sample_n = int(a.split('=', 1)[1])
            except: pass
            continue
        if a.startswith('--context='):
            try: context_n = int(a.split('=', 1)[1])
            except: pass
            continue
        if '=' in a:
            k, v = a.split('=', 1)
            # 字段名归一：中文别名照收。Canonicalise the field name; Chinese aliases accepted.
            filters[canon_field(k.strip())] = v.strip()
    head_re = re.compile(conf['entries'].get('head_regex', DEFAULT_HEAD_REGEX))
    outdir = os.path.join(root, conf['index'].get('out_dir', ''))
    prefix = conf['index'].get('index_prefix', 'index_')
    fields = [x.strip() for x in conf['entries'].get('fields', 'volume,line,time,category,title').split(',')]
    vols = conf.get('volumes', {})

    def _iter_rows():
        """逐条产出命中行（生成器·不在内存里攒全集）。
        Yield matching rows one at a time (generator; never accumulates the full hit set)."""
        for vol in vols:
            idf = os.path.join(outdir, '%s%s.tsv' % (prefix, vol))
            if not os.path.exists(idf):
                idf = os.path.join(outdir, '%s%s卷.tsv' % (prefix, vol))   # 旧名回退 / legacy fallback
            if not os.path.exists(idf): continue
            with io.open(idf, encoding='utf-8') as f:
                header = f.readline().rstrip('\n').split('\t')
                # 表头可能来自旧中文版 ⇒ 归一后比对。Header may be legacy Chinese ⇒ normalise.
                header_c = [canon_field(h) for h in header]
                # ★ 每卷按自己的 header 重算 filter_idx（修③：原"仅一次"致第一卷缺字段则后续全跳过）
                # ★ Recompute filter_idx per volume (fix 3): a missing column in volume 1 no longer
                #   silently skips every later volume.
                filter_idx = []  # [(field_idx, needle)]
                for k, v in filters.items():
                    if k in header_c: filter_idx.append((header_c.index(k), v))
                # 缺字段则本卷跳过 / skip this volume if a field is missing
                if len(filter_idx) != len(filters):
                    continue
                for line in f:
                    # 快速 split + 长度校验 / fast split + length check
                    cells = line.rstrip('\n').split('\t')
                    if len(cells) < len(header): continue
                    # 直接按下标比对，不做 dict / compare by index, no dict
                    ok = True
                    for fi, needle in filter_idx:
                        if needle not in cells[fi]:
                            ok = False; break
                    if ok:
                        row = dict(zip(header_c, cells))
                        row['_vol_path'] = vols.get(vol, '')
                        yield row

    out = []
    # ★ --count：只数不攒；--limit：边扫边截；--sample：两遍（先数后抽），内存均有上限。
    # ★ --count counts without storing; --limit truncates while scanning; --sample counts
    #   first and samples in a second pass. All three bounded in memory.
    if count_only:
        n = sum(1 for _ in _iter_rows())
        out.append('命中 %d 条' % n)  # 契约行·保持原样 / contract line, keep as-is
        return '\n'.join(out)

    if sample_n > 0:
        total_hits = sum(1 for _ in _iter_rows())
        matched = []
        if total_hits > sample_n:
            step = total_hits / sample_n
            want = set(int(i * step) for i in range(sample_n))
            matched = [r for i, r in enumerate(_iter_rows()) if i in want]
        else:
            matched = list(_iter_rows())
        out.append('命中 %d 条' % total_hits)  # 契约行 / contract line
        if total_hits > sample_n:
            out.append('采样 %d/%d（步长 %.2f）' % (sample_n, total_hits, step))
    else:
        total_hits = 0
        matched = []
        for r in _iter_rows():
            total_hits += 1
            if len(matched) < limit:
                matched.append(r)
        out.append('命中 %d 条' % total_hits)  # 契约行 / contract line
    # 按卷分组读 lines 一次，所有命中复用
    # Read each volume once; every hit reuses the lines
    vol_lines_cache = {}
    for r in matched:
        out.append('---')
        out.append('[%s] [%s] [%s] [volume=%s line=%s]' % (
            r.get('time', ''), r.get('category', ''), r.get('title', ''),
            r.get('volume', ''), r.get('line', '')))
        vol = r.get('volume', '')
        ln_s = r.get('line', '0')
        try: ln = int(ln_s)
        except ValueError: ln = 0
        vp = r.get('_vol_path', '')
        if vp:
            vp = vp if os.path.isabs(vp) else os.path.join(root, vp)
            if vp not in vol_lines_cache:
                if os.path.exists(vp):
                    with open(vp, 'rb') as _f:
                        _raw = _f.read()
                    _text, _enc, _why = sniff(_raw)
                    vol_lines_cache[vp] = _text.splitlines(keepends=True)
                else:
                    vol_lines_cache[vp] = []
            lines = vol_lines_cache[vp]
            if 0 < ln <= len(lines):
                # --context N：扩展前后邻居 / expand to neighbours
                if context_n > 0:
                    start = max(1, ln - context_n * 2)  # 邻居行数×2 因每条 2 行 / 2 lines per entry
                    end = ln
                    while end < len(lines) and (end - ln) < context_n * 2:
                        if head_re.match(lines[end].rstrip('\n')) and end > ln: break
                        end += 1
                    out.append(''.join(lines[start-1:end]).rstrip())
                else:
                    end = ln
                    while end < len(lines):
                        if head_re.match(lines[end].rstrip('\n')): break
                        end += 1
                    out.append(''.join(lines[ln-1:end]).rstrip())
    if total_hits > len(matched):
        out.append('---')
        out.append('（已显示 %d 条，共 %d 命中，用 --limit N / --sample N 调）' % (len(matched), total_hits))
    return '\n'.join(out)


def main():
    """Dispatch the selected command using the adjacent DAYBOOK configuration.
    按所选子命令分派；配置取同目录 daybook.conf。"""
    conf = load_conf()
    # 根目录：conf[index][root] 控制。空=HERE；..=dirname(HERE)；绝对路径=原样
    # Root: conf[index][root]. Empty = HERE; '..' = parent; absolute = as-is.
    root_cfg = conf.get('index', {}).get('root', '').strip()
    if not root_cfg:
        root = HERE
    elif root_cfg == '..':
        root = os.path.dirname(HERE)
    elif os.path.isabs(root_cfg):
        root = root_cfg
    else:
        root = os.path.join(HERE, root_cfg)
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'index'
    vols = [v if os.path.isabs(v) else os.path.join(root, v) for v in conf.get('volumes', {}).values()]
    if cmd == 'index':
        per, total, rep = build(conf, root)
        for v, w in rep: print('  %s: %s' % (v, w), flush=True)
        for w in RULE_WARN: sys.stderr.write('  ★ 规则告警：%s\n' % w)
        print('索引已生成：' + '｜'.join('%s %d' % (k, v) for k, v in per.items()) + '｜合计 %d 条' % total, flush=True)
        if VIOLATIONS:
            sys.stderr.write('★ append-only 违例 %d 处（索引已按违例全量重扫，但账本本身已被改写）：\n'
                             % len(VIOLATIONS))
            for v, w in VIOLATIONS:
                sys.stderr.write('  %s: %s\n' % (v, w))
            sys.exit(3)
    elif cmd in ('multiindex', '多级索引'):
        # 四库式多级目录（部/类/属·跨卷总目）·派生件·零依赖·与 index 同源同入口
        # Four-branch multilevel catalogue (derived data; same entry point as index)
        import daybook_multidx
        sys.exit(daybook_multidx.main(sys.argv[2:]))
    elif cmd == 'backup':
        bdir, n = backup(conf, root)
        print('备份完成：%s（%d 卷）' % (bdir, n), flush=True)
    elif cmd == 'query':
        print(query(conf, root, sys.argv[2:]), flush=True)
    elif cmd == 'watch':
        gap = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        last = None
        print('监视 %d 卷，每 %d 秒查一次变动。Ctrl-C 退出。' % (len(vols), gap), flush=True)
        while True:
            cur = hash_volumes(vols)
            if cur != last:
                try:
                    per, total, _rep = build(conf, root)
                    # [多级] 变动续建：索引后自动重算四库式多级目录（失败不挡索引与备份）
                    # [multilevel] on change: rebuild the catalogue too (failure is non-blocking)
                    m_note = ''
                    if conf.get('multilevel', {}).get('multilevel_enabled', '是') in ('是', '1', 'true', 'True', 'yes'):
                        try:
                            import daybook_multidx
                            _mp, _mt = daybook_multidx.build(conf, root)
                            m_note = ' + 多级目录 %d 条' % _mt
                        except Exception as me:
                            m_note = '（多级目录失败：%s）' % me
                    bdir, n = backup(conf, root)
                    print('[%s] 变动 %s ⇒ 索引重算，合计 %d 条%s + 备份 %d 卷 ⇒ %s' % (
                        time.strftime('%H:%M:%S'), cur, total, m_note, n, os.path.basename(bdir)), flush=True)
                    for v, w in VIOLATIONS:
                        print('  ★ 违例 %s: %s' % (v, w), flush=True)
                    for w in RULE_WARN:
                        print('  ★ 规则告警：%s' % w, flush=True)
                except Exception as e:
                    print('[%s] 变动 %s ⇒ 重算失败（卷可能正在被写入）：%s' % (
                        time.strftime('%H:%M:%S'), cur, e), flush=True)
                # [钩子] 变动令：索引/备份后执行（确定性自动化·人可读可改·失败不挡游标）
                # [hooks] on_change command: runs after index/backup (never blocks the cursor)
                hook = conf.get('hooks', {}).get('on_change', '').strip()
                if hook:
                    import shlex as _shlex, subprocess as _sp
                    try:
                        _sp.run(_shlex.split(hook), timeout=120)
                    except Exception as he:
                        print('  变动令失败：%s' % he, flush=True)
                last = cur
            time.sleep(gap)
    elif cmd == 'mcp':
        # 启动 MCP 服务器（JSON-RPC 2.0 over stdio）·零依赖·与 index/watch 同一二进制
        # Start the MCP server (JSON-RPC 2.0 over stdio); same binary as index/watch
        # 暴露 resources（卷）/ tools（query/append/cross_ref）/ prompts（4 模板）
        try:
            import mcp_server
        except ImportError:
            sys.stderr.write('未安装 daybook-mcp：统一入口 `daybook mcp` 需该包提供 mcp_server。\n'
                             '请先 pip install daybook-mcp。\n')
            sys.exit(2)
        mcp_server.serve()
    elif cmd in ('orchestrate', '编排', '司南'):
        # 智能体编排中心「司南」（第三产品线）·零依赖·与 index/mcp 同一二进制
        # The agent orchestration hub (product line 3); zero-dep, same binary
        # 身份/任务/锁/心跳/路由 焊成一个闭环；卷为唯一底座
        try:
            import orchestrator
        except ImportError:
            sys.stderr.write('未安装 daybook-orch：统一入口 `daybook orchestrate` 需该包提供 orchestrator。\n'
                             '请先 pip install daybook-orch。\n')
            sys.exit(2)
        sys.exit(orchestrator.main(sys.argv[2:]))
    else:
        print(__doc__)

if __name__ == '__main__':
    main()
