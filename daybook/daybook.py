#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DAYBOOK · 起居注体例发行版·索引器与触发器
零依赖：只用 Python 标准库。
用法：
  python3 daybook.py index        生成/刷新索引
  python3 daybook.py watch [秒]   监视各卷，变动即自动重算索引 + 自动备份
  python3 daybook.py backup       手动备份：把所有卷复制到 备份/YYYY-MM-DD_HHMMSS/
  python3 daybook.py query key=value ...  按字段精确查询条目原文（E-11 工具）
     字段：卷/行号/时间/类/标题。值为子串匹配，留空表示不过滤。
     例：python3 daybook.py query 类=实验 时间=2026-10
         python3 daybook.py query 标题=daybook
  python3 daybook.py mcp          启动 MCP 服务器（JSON-RPC 2.0 over stdio）
      暴露 daybook 卷为 resources · 暴露 query/append/cross_ref 为 tools · 4 个 prompt 模板
      零依赖，不联网，与 index/watch 同一二进制。
  python3 daybook.py 编排 <子命令>  智能体编排中心「司南」（第三产品线）·别名 司南
      把身份/任务/锁/心跳/路由焊成一个闭环：join/who/open/claim/submit/review/pull/board/alarm/selftest
      零依赖，卷为唯一底座，与 index/mcp 同一二进制。
客户可改 daybook.conf 定字段与卷。
"""
import io, os, re, sys, time, hashlib, json, shutil

ENC_REPORT = []
HERE = os.path.dirname(os.path.abspath(__file__))

# ── 编码自动检测与转码（零依赖·不静默·须报出所用编码）──
def sniff(raw):
    """返回 (文本, 编码名, 依据)。
    薄委托：检测逻辑唯一在 safeio.sniff_bytes（#463 合一·勿在此重实现）。
    不许静默：依据必须可写出来。"""
    from safeio import sniff_bytes
    return sniff_bytes(raw)

def read_text(path):
    """Read a volume and return its decoded text, encoding, and detection reason."""
    with open(path, 'rb') as f:
        raw = f.read()
    return sniff(raw)



def load_conf(path=None):
    """Load the DAYBOOK configuration into section and key dictionaries."""
    path = path or os.path.join(HERE, 'daybook.conf')
    conf = {'卷': {}, '条目': {}, '索引': {}, '触发': {}}
    sec = None
    for line in io.open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'): continue
        m = re.match(r'^\[(.+)\]$', line.strip())
        if m: sec = m.group(1); continue
        if sec and '=' in line:
            k, v = line.split('=', 1)
            conf.setdefault(sec, {})[k.strip()] = v.strip()
    return conf


# ── 字段抽取（客户可自定字段：字段名 = 规则）──
BUILTIN = ('卷', '行号', '时间')

def fill(row, fields, rules, line, tag, lines=None, head_re=None, is_extra=False):
    """按 fields 顺序产出整行。规则形：
       tag:N  ⇒ 取条目标签正则的第 N 组
       len    ⇒ 该条正文字数
       contains:xxx ⇒ 正文含 xxx 则 1 否则 0
       无规则 ⇒ 空串（客户可只加表头占位）
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
                if tag:
                    t = tag.match(line or '')
                    if t and g <= len(t.groups()) and t.group(g) is not None:
                        val = t.group(g)
                # ★ 附头（MD 标题）不匹配标正则 ⇒ 退回用标题文字
                if not val and is_extra and head_re:
                    hm = head_re.match(line or '')
                    if hm and g == 1: val = '标题'
                    elif hm: val = (line or '')[len(hm.group(0)):].strip()
            except Exception: val = ''
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
    return os.path.join(outdir, '.游标_%s.json' % vol)

def build(conf, root='.'):
    """扫描各卷，生成索引。append-only ⇒ 增量：未变跳过、只追加读尾部、旧部分被改报违例。"""
    ENC_REPORT.clear()  # ★ 每轮 build 清空编码报告，防 watch 多轮累积
    vols = conf.get('卷', {})
    head = re.compile(conf['条目'].get('头正则', r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]'))
    # ★ 作者 ID 红线（老宋定）：新格式 [时间][类][标题][作者] 4 段优先；
    # 旧格式 [时间][类][标题] 3 段兼容（作者列留空）。
    tag  = re.compile(conf['条目'].get('标正则', r'^\[[^\]]+\]\s*\[([^\]]+)\]\s*\[([^\]]*)\](?:\s*\[([^\]]*)\])?'))
    fields = [x.strip() for x in conf['条目'].get('字段', '卷,行号,时间,类,标题').split(',')]
    rules = {k: v for k, v in conf.get('规则', {}).items()}
    heads = [head]
    for extra in conf['条目'].get('附头正则', '').split('||'):
        if extra.strip(): heads.append(re.compile(extra.strip()))
    outdir = os.path.join(root, conf['索引'].get('输出目录', ''))
    prefix = conf['索引'].get('索引前缀', '索引_')
    if not os.path.isdir(outdir): os.makedirs(outdir)
    incremental = conf['触发'].get('增量索引', '是') in ('是', '1', 'true', 'True')
    per, total, report = {}, 0, []
    # W-75 修②：索引写入全临界区（TSV/游标/清单·目录级锁）
    from safeio import locked as _safe_locked
    with _safe_locked(os.path.join(outdir, '.索引锁')):

        for vol, path in vols.items():
            p = path if os.path.isabs(path) else os.path.join(root, path)
            idf = os.path.join(outdir, '%s%s卷.tsv' % (prefix, vol))
            cp = _cursor_path(outdir, vol)
            if not os.path.exists(p): per[vol] = 0; continue
            size, mt = os.path.getsize(p), os.path.getmtime(p)

            cur = None
            if incremental and os.path.exists(cp) and os.path.exists(idf):
                try: cur = json.load(io.open(cp, encoding='utf-8'))
                except Exception: cur = None

            rows, mode, n_old = [], 'full', 0

            # ── 情形一：文件未变 ⇒ 跳过 ──
            if cur and cur.get('size') == size and cur.get('mtime') == mt:
                per[vol] = cur.get('n', 0); total += per[vol]
                report.append((vol, '未变·跳过'))
                ENC_REPORT.append((vol, cur.get('enc', '?'), '游标缓存'))
                # ★ 老宋定：未变跳过时也要确保索引 TXT 存在（首次升级到带 TXT 版时补齐）
                itxt = os.path.join(outdir, '%s%s卷.txt' % (prefix, vol))
                if not os.path.exists(itxt) and os.path.exists(idf):
                    with io.open(idf, encoding='utf-8') as src:
                        with io.open(itxt, 'w', encoding='utf-8') as dst:
                            dst.write('# 索引_%s卷（人类可读·机器可读 TSV 同目录）\n' % vol)
                            dst.write('# 由 daybook.py index 自动生成·可随时从原文重算\n')
                            dst.write('# 索引是目录不是真相·真相在各卷原文\n\n')
                            lines = src.read().split('\n')
                            for line in lines[1:]:  # 跳过表头
                                if not line.strip(): continue
                                cols = line.split('\t')
                                dst.write('[%s] 行=%s 类=%s 标题=%s 作者=%s\n' % (
                                    cols[2] if len(cols) > 2 else '',
                                    cols[1] if len(cols) > 1 else '',
                                    cols[3] if len(cols) > 3 else '',
                                    cols[4] if len(cols) > 4 else '',
                                    cols[5] if len(cols) > 5 else ''))
                continue

            # ── 情形二：只追加 ⇒ 读尾部 ＋ 追加写索引 ──
            if (cur and cur.get('resume_byte') is not None
                    and size > cur['size']):
                n_old_b = cur['resume_byte']
                with open(p, 'rb') as f:
                    f.seek(n_old_b); tail = f.read()
                    f.seek(0); head4 = f.read(min(4096, n_old_b))          # ★ 以旧大小为界
                    q = max(0, n_old_b - 4096)
                    f.seek(q); pre4 = f.read(n_old_b - q)                 # ★ 同样以旧大小为界
                probe = hashlib.sha256(head4 + pre4).hexdigest()[:16]
                n_idx = _count_index_rows(idf)
                if probe == cur.get('probe_hash') and n_idx == cur.get('n', -1):
                    enc = cur.get('enc')
                    if not enc:
                        txt, enc, _ = sniff(tail)  # 旧游标无 enc，当场 sniff
                    else:
                        try:
                            txt = tail.decode(enc, 'replace')
                        except (LookupError, UnicodeDecodeError):
                            txt, enc, _ = sniff(tail)
                    base_ln = cur.get('last_lineno', 0)                # ★ 从游标读旧最后一行行号
                    rows, final_ln = _parse(txt, heads, fields, rules, tag, vol, base_ln)
                    mode = 'append'; n_old = n_idx
                    report.append((vol, '只追加·读尾部 %d 字节·索引 append %d 行'
                                   % (len(tail), len(rows))))
                    ENC_REPORT.append((vol, enc, '尾部续读·按游标编码'))
                else:
                    report.append((vol, '★ 旧部分被改或索引不符·append-only 违例·全重扫'))

            # ── 情形二·补：字节数未变而 mtime 变 ⇒ 原地改过 ⇒ 违例 ──
            if mode == 'full' and cur and size == cur.get('size') and mt != cur.get('mtime'):
                report.append((vol, '★ 原地改过（字节数未变·mtime 变）·append-only 违例·全重扫'))

            # ── 情形三：全量 ──
            if mode == 'full':
                raw = open(p, 'rb').read()
                txt, enc, why = sniff(raw)
                rows, final_ln = _parse(txt, heads, fields, rules, tag, vol, 0)
                if not any(r[0] == vol for r in report):
                    report.append((vol, '全扫·%d 行' % len(rows)))
                ENC_REPORT.append((vol, enc, why))

            # ── 写索引 ──
            if mode == 'append':
                with io.open(idf, 'a', encoding='utf-8') as f:
                    for r in rows: f.write('\t'.join(x.replace('\t', ' ') for x in r) + '\n')
                # ★ 索引 TXT 同步追加（老宋定：TSV+TXT 同目录，人类可读 + 机器可读）
                itxt = os.path.join(outdir, '%s%s卷.txt' % (prefix, vol))
                with io.open(itxt, 'a', encoding='utf-8') as f:
                    for r in rows:
                        f.write('[%s] 行=%s 类=%s 标题=%s 作者=%s\n' % (
                            r[2] if len(r) > 2 else '', r[1] if len(r) > 1 else '',
                            r[3] if len(r) > 3 else '', r[4] if len(r) > 4 else '',
                            r[5] if len(r) > 5 else ''))
                n_total = n_old + len(rows)
            else:
                with io.open(idf, 'w', encoding='utf-8') as f:
                    f.write('\t'.join(fields) + '\n')
                    for r in rows: f.write('\t'.join(x.replace('\t', ' ') for x in r) + '\n')
                # ★ 索引 TXT 同步生成（全扫重建）
                itxt = os.path.join(outdir, '%s%s卷.txt' % (prefix, vol))
                with io.open(itxt, 'w', encoding='utf-8') as f:
                    f.write('# 索引_%s卷（人类可读·机器可读 TSV 同目录）\n' % vol)
                    f.write('# 由 daybook.py index 自动生成·可随时从原文重算\n')
                    f.write('# 索引是目录不是真相·真相在各卷原文\n\n')
                    for r in rows:
                        f.write('[%s] 行=%s 类=%s 标题=%s 作者=%s\n' % (
                            r[2] if len(r) > 2 else '', r[1] if len(r) > 1 else '',
                            r[3] if len(r) > 3 else '', r[4] if len(r) > 4 else '',
                            r[5] if len(r) > 5 else ''))
                n_total = len(rows)
            per[vol] = n_total; total += n_total
            with open(p, 'rb') as f:
                f.seek(0); h4 = f.read(min(4096, size))
                q2 = max(0, size - 4096)
                f.seek(q2); p4 = f.read(size - q2)
            with io.open(cp, 'w', encoding='utf-8') as f:
                f.write(json.dumps({
                    'size': size, 'mtime': mt, 'resume_byte': size, 'n': n_total,
                    'last_lineno': final_ln,                                    # ★ 游标存最后行号供下次 append
                    'enc': enc,                                                  # ★ 游标存编码供增量解码
                    'probe_hash': hashlib.sha256(h4 + p4).hexdigest()[:16]}, ensure_ascii=False))

        with io.open(os.path.join(outdir, conf['索引'].get('清单名', 'volumes.md')), 'w', encoding='utf-8') as f:
            f.write('# 卷首清单\n\n| 卷 | 条数 | 索引文件 |\n|---|---|---|\n')
            for v, n in per.items(): f.write('| %s卷 | %d | %s%s卷.tsv |\n' % (v, n, prefix, v))
            f.write('| **合计** | **%d** | |\n\n' % total)
            f.write('索引是目录，不是真相。真相在各卷原文。索引可随时从原文重算。\n\n')
            f.write('## 本次增量报告\n\n| 卷 | 处理 |\n|---|---|\n')
            for v, w in report: f.write('| %s | %s |\n' % (v, w))
            f.write('\n## 编码检测（不静默）\n\n| 卷 | 编码 | 依据 |\n|---|---|---|\n')
            for v, e, w in ENC_REPORT: f.write('| %s | %s | %s |\n' % (v, e, w))
        return per, total, report


def _count_index_rows(idf):
    with io.open(idf, encoding='utf-8') as f:
        return sum(1 for l in f if l.strip()) - 1


def _parse(txt, heads, fields, rules, tag, vol, base_ln):
    """单遍扫描：切块 ＋ 记行号。heads[0] 为主头，其余为附头。
    返回 (rows, final_ln)：final_ln = 扫描结束时的行号，供下次 append 模式做 base_ln。
    ★ final_ln = base_ln + 实际行数（含末尾空行，按 \\n 数算），不用 ln-1（避免 split 末尾空字符串让行号偏离）。"""
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
    mm = head_re0.match(blk)
    tm = mm.group(1) if mm else ''
    return fill([vol, str(start), tm], fields, rules, blk, tag,
                head_re=heads[which] if which is not None else head_re0,
                is_extra=(which not in (0, None)))

def backup(conf, root='.'):
    """把所有卷复制到 备份/YYYY-MM-DD_HHMMSS/。append-only 纪律适用于备份：旧的不删不改。
    ★ 老宋定：索引目录（TSV+TXT+清单）也一起备份——索引可重算，但备份能救命。"""
    vols = conf.get('卷', {})
    bdir = os.path.join(root, '备份', time.strftime('%Y-%m-%d_%H%M%S'))
    os.makedirs(bdir, exist_ok=True)
    n = 0
    for vol, path in vols.items():
        p = path if os.path.isabs(path) else os.path.join(root, path)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(bdir, os.path.basename(p)))
            n += 1
    # ★ 备份索引目录（TSV+TXT+清单+游标）
    idx_dir = conf.get('索引', {}).get('输出目录', '')
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
    """Hash volume metadata (mtime and size) only; this does not read contents."""
    h = hashlib.sha256()
    for p in paths:
        if os.path.exists(p): h.update(str(os.path.getmtime(p)).encode()); h.update(str(os.path.getsize(p)).encode())
    return h.hexdigest()[:12]

def query(conf, root, args):
    """按字段精确查询条目原文。E-11 daybook 上下文工具。
    索引层：TSV 过滤（字段子串匹配，SQL 式而非向量召回）。
    返回层：按卷+行号定位原文，从该行读到下一条目头前。
    ★ 优化：同卷只 readlines 一次，所有命中复用 lines（避免 O(n*m) I/O 灾难）。
    ★ 支持 --limit N 限制输出原文条数（默认 50），防 10 万命中爆 stdout。
    ★ 支持 --count 只输出命中数，不读原文。
    ★ 支持 --sample N 采样召回 N 条（均匀抽样），用于触发上下文召回 1000 条喂 AI。
    ★ 支持 --context N 返回命中条目 + 前后各 N 条邻居（共 2N+1 条/命中），模拟"周边记忆"。
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
            filters[k.strip()] = v.strip()
    head_re = re.compile(conf['条目'].get('头正则', r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]'))
    outdir = os.path.join(root, conf['索引'].get('输出目录', ''))
    prefix = conf['索引'].get('索引前缀', '索引_')
    fields = [x.strip() for x in conf['条目'].get('字段', '卷,行号,时间,类,标题').split(',')]
    vols = conf.get('卷', {})
    matched = []
    # 预编译过滤器：字段索引 + 期望子串
    # filters: {字段名: 期望子串} → 字段在 header 中的下标 + 子串
    for vol in vols:
        idf = os.path.join(outdir, '%s%s卷.tsv' % (prefix, vol))
        if not os.path.exists(idf): continue
        with io.open(idf, encoding='utf-8') as f:
            header = f.readline().rstrip('\n').split('\t')
            # ★ 每卷按自己的 header 重算 filter_idx（修③：原"仅一次"致第一卷缺字段则后续全跳过）
            filter_idx = []  # [(field_idx, needle)]
            for k, v in filters.items():
                if k in header: filter_idx.append((header.index(k), v))
            # 缺字段则本卷跳过
            if len(filter_idx) != len(filters):
                continue
            for line in f:
                # 快速 split + 长度校验
                cells = line.rstrip('\n').split('\t')
                if len(cells) < len(header): continue
                # 直接按下标比对，不做 dict
                ok = True
                for fi, needle in filter_idx:
                    if needle not in cells[fi]:
                        ok = False; break
                if ok:
                    row = dict(zip(header, cells))
                    row['_vol_path'] = vols.get(vol, '')
                    matched.append(row)
    out = []
    out.append('命中 %d 条' % len(matched))
    if count_only:
        return '\n'.join(out)
    # --sample N：均匀抽样 N 条
    if sample_n > 0 and len(matched) > sample_n:
        step = len(matched) / sample_n
        sampled = [matched[int(i * step)] for i in range(sample_n)]
        out.append('采样 %d/%d（步长 %.2f）' % (sample_n, len(matched), step))
        matched = sampled
    # 按卷分组读 lines 一次，所有命中复用
    vol_lines_cache = {}
    shown = 0
    target = sample_n if sample_n else limit
    for r in matched:
        if shown >= target:
            out.append('---')
            out.append('（已显示 %d 条，共 %d 命中，用 --limit N / --sample N 调）' % (target, len(matched)))
            break
        out.append('---')
        out.append('[%s] [%s] [%s] [卷=%s 行=%s]' % (
            r.get('时间', ''), r.get('类', ''), r.get('标题', ''),
            r.get('卷', ''), r.get('行号', '')))
        vol = r.get('卷', '')
        ln_s = r.get('行号', '0')
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
                # --context N：扩展前后邻居
                if context_n > 0:
                    start = max(1, ln - context_n * 2)  # 邻居行数×2 因每条 2 行
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
        shown += 1
    return '\n'.join(out)


def main():
    """Dispatch the selected command using the adjacent DAYBOOK configuration."""
    conf = load_conf()
    # 根目录：conf[索引][根] 控制。空=HERE；..=dirname(HERE)；绝对路径=原样
    root_cfg = conf.get('索引', {}).get('根', '').strip()
    if not root_cfg:
        root = HERE
    elif root_cfg == '..':
        root = os.path.dirname(HERE)
    elif os.path.isabs(root_cfg):
        root = root_cfg
    else:
        root = os.path.join(HERE, root_cfg)
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'index'
    vols = [v if os.path.isabs(v) else os.path.join(root, v) for v in conf.get('卷', {}).values()]
    if cmd == 'index':
        per, total, rep = build(conf, root)
        for v, w in rep: print('  %s: %s' % (v, w), flush=True)
        print('索引已生成：' + '｜'.join('%s %d' % (k, v) for k, v in per.items()) + '｜合计 %d 条' % total, flush=True)
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
                    bdir, n = backup(conf, root)
                    print('[%s] 变动 %s ⇒ 索引重算，合计 %d 条 + 备份 %d 卷 ⇒ %s' % (
                        time.strftime('%H:%M:%S'), cur, total, n, os.path.basename(bdir)), flush=True)
                except Exception as e:
                    print('[%s] 变动 %s ⇒ 重算失败（卷可能正在被写入）：%s' % (
                        time.strftime('%H:%M:%S'), cur, e), flush=True)
                # [钩子] 变动令：索引/备份后执行（确定性自动化·人可读可改·失败不挡游标）
                hook = conf.get('钩子', {}).get('变动令', '').strip()
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
        # 暴露 resources（卷）/ tools（query/append/cross_ref）/ prompts（4 模板）
        import mcp_server
        mcp_server.serve()
    elif cmd in ('编排', '司南'):
        # 智能体编排中心「司南」（第三产品线）·零依赖·与 index/mcp 同一二进制
        # 身份/任务/锁/心跳/路由 焊成一个闭环；卷为唯一底座
        import orchestrator
        sys.exit(orchestrator.main(sys.argv[2:]))
    else:
        print(__doc__)

if __name__ == '__main__':
    main()
