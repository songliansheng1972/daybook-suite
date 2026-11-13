#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""MCP Resources（W-DB-023-G2·第 2 项·修复版 r2）
MCP resources — audit report P2-3 fixes.
================================================
对照审核报告 P2-3 修复 / Fixes against the P2-3 audit:
- list 不再扫描 *.txt·改读 daybook.conf [volumes] 表·与系统其余部分语义一致
  list no longer scans *.txt; it reads the conf [volumes] table, matching the rest of the system
- read 同步：卷名按 conf 解析·未在 conf 的卷返 None
  read follows the same rule; a volume absent from conf returns None
- _vol_path 加 ../ 穿越防护（P1-3）/ ../ traversal guard
- read 写审计留痕（P1-2）/ reads leave an audit record
- 零依赖：仅 Python 3 标准库 / zero dependencies: Python 3 stdlib only

v3.1（四库式多级目录·长上下文）/ v3.1 four-branch multilevel catalogue:
- 新增**目录资源** `daybook://catalog/<卷>`、`daybook://catalog/<总目>` —— 读 <根>/multilevel/*.md
  New catalogue resources; they read <root>/multilevel/*.md
  （由 `daybook.py multiindex` 生成的派生件·只读·可删可重建）
- 目录资源**存在才列**（未跑 multiindex 时静默不列·不报错）
  Catalogue resources are listed only when present (silent when multiindex has not run)
- 旧中文 URI（`daybook://目录/…`）与旧文件名仍可读（兼容别名）
  Legacy Chinese URIs and file names still read (compatibility aliases)
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mcp_transport as _tr

AUDIT_VOL_NAME = 'MCP审计卷.txt'
CONF_NAME = 'daybook.conf'


class RootError(RuntimeError):
    """账本根/配置不可用。绝不静默回落成空账本。
    Ledger root/config unavailable. Never silently falls back to an empty ledger."""


# 自检告警去重（同一进程只报一次）/ dedupe self-check warnings (once per process)
_WARNED = set()

# ── v3.1 多级目录资源（四库式：部=卷／类·作者／属=条目）──
# ── v3.1 catalogue resources (four-branch: volume / category·author / entry) ──
MULTIDX_SUBDIR = 'multilevel'          # 旧名 '多级' 仍读 / legacy '多级' still readable
DIR_URI_PREFIX = 'daybook://catalog/'  # 旧前缀 'daybook://目录/' 仍读 / legacy prefix still readable
DIR_URI_PREFIX_LEGACY = 'daybook://目录/'
DIR_ALIASES = ('catalog', 'index', '总目', '总目录')


def _audit_vol():
    """审计卷路径·走 _root()·监理 r4 修复。Audit volume path, resolved via _root()."""
    return os.path.join(_root(), AUDIT_VOL_NAME)


def _now():
    """当前时间戳。Current timestamp."""
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _warn(msg, key=None):
    """自检告警走 stderr·同一 key 只报一次。
    Self-check warnings go to stderr · each key is reported once."""
    if key is not None:
        if key in _WARNED:
            return
        _WARNED.add(key)
    try:
        sys.stderr.write('[daybook-mcp] WARN %s\n' % msg)
        sys.stderr.flush()
    except OSError:
        pass


def _conf_dir():
    """conf 所在目录：DAYBOOK_ROOT 显式覆盖，否则本件所在目录。
    Directory holding daybook.conf: explicit DAYBOOK_ROOT override, else this file's dir."""
    return (os.environ.get('DAYBOOK_ROOT') or '').strip() or HERE


def _conf_path():
    """daybook.conf 的绝对路径。Absolute path of daybook.conf."""
    return os.path.join(_conf_dir(), CONF_NAME)


def _resolve_root(conf_dir, conf):
    """conf [index] root → 绝对根目录（与 daybook.py main 同口径）。
    [index] root → absolute root (same rule as daybook.py main).
    空=conf 所在目录；'..'=上一级；绝对=原样；相对=join(conf 目录)。
    Empty = conf dir; '..' = parent; absolute = as-is; relative = join(conf dir).
    目录不存在 → 抛 RootError（不静默返回空账本）。
    A missing directory raises RootError (never a silent empty ledger)."""
    rc = (conf.get('index', {}).get('root', '') or '').strip()
    if not rc:
        root = conf_dir
    elif rc == '..':
        root = os.path.dirname(conf_dir)
    elif os.path.isabs(rc):
        root = rc
    else:
        root = os.path.join(conf_dir, rc)
    root = os.path.normpath(root)
    if not os.path.isdir(root):
        raise RootError(
            '账本根目录不存在或不是目录：%s（conf=%s，index.root=%r）'
            % (root, os.path.join(conf_dir, CONF_NAME), rc))
    return root


def _root():
    """账本根：DAYBOOK_ROOT（显式覆盖）> conf [index] root（空=conf 所在目录）。
    Ledger root: explicit DAYBOOK_ROOT override > conf [index] root (empty = conf dir).
    解析失败抛 RootError —— 读错根必须报错，绝不静默当空账本。
    Raises RootError on failure — a wrong root must fail loudly, never masquerade as an empty ledger."""
    env = (os.environ.get('DAYBOOK_ROOT') or '').strip()
    if env:
        env = os.path.normpath(os.path.abspath(os.path.expanduser(env)))
        if not os.path.isdir(env):
            raise RootError('DAYBOOK_ROOT 指向的目录不存在：%s' % env)
        return env
    return _resolve_root(HERE, _load_conf())


def _audit(method, agent_id, detail):
    """写一行审计留痕（失败静默）。只读模式改走 stderr·零写盘。
    Append one audit line (failures are silent). In read-only mode it goes to stderr · zero disk writes."""
    rec = '[%s] [MCP] [resources/%s] [agent=%s] %s\n' % (
        _now(), method, agent_id or '匿名', detail)[:400]
    if _tr.is_read_only():
        try:
            sys.stderr.write(rec)
            sys.stderr.flush()
        except OSError:
            pass
        return
    try:
        from safeio import atomic_append
        atomic_append(_audit_vol(), rec)
    except OSError:
        pass


def _load_conf():
    """读 <conf 目录>/daybook.conf。缺失/不可读抛 RootError（不静默返空）。
    Read <conf dir>/daybook.conf. Missing/unreadable raises RootError (never silently {})."""
    cp = _conf_path()
    try:
        import daybook as _db
        return _db.load_conf(cp)
    except (OSError, UnicodeDecodeError) as e:
        raise RootError('无法读取配置 %s：%s' % (cp, e))


def _load_volumes():
    """读 daybook.conf [volumes] 表·返回有序 dict {卷名: 相对路径}。
    Read the conf [volumes] table → ordered dict {volume name: relative path}.
    失败抛 RootError（不静默当空卷表）。
    conf 路径走 conf 目录·生产=本件所在目录·测试可走 DAYBOOK_ROOT。"""
    return _load_conf().get('volumes', {})


def _safe_vol(name):
    """卷名防穿越（P1-3）。Volume-name traversal guard."""
    if not name or '..' in name or '/' in name or '\\' in name or os.path.isabs(name):
        return None
    return name


def _vol_path(name, root=None):
    """卷名 → 文件路径。按 conf 解析·找不到返 None。root 默认 _root()。
    Volume name → file path via conf; None when unknown."""
    name = _safe_vol(name)
    if name is None:
        return None
    vols = _load_volumes()
    rel = vols.get(name)
    if not rel:
        return None
    base = root or _root()
    return rel if os.path.isabs(rel) else os.path.join(base, rel)


def read_vol(path):
    """读卷·走 safeio.read_vol（统一口径：MCP/orch 读卷一律经 safeio）。
    Read a volume through safeio.read_vol (single source of truth for decoding).
    返回 (text, enc, why)。"""
    from safeio import read_vol as _rv
    return _rv(path)


def _vol_meta(name, path):
    """读卷元数据：行数/字节数/mtime。Volume metadata: line count / size / mtime."""
    try:
        from safeio import sniff_bytes
        st = os.stat(path)
        with open(path, 'rb') as f:
            raw = f.read()
        txt, _enc, _why = sniff_bytes(raw)
        line_count = txt.count('\n') + (0 if txt.endswith('\n') else 1)
        return {
            'uri': 'daybook://%s' % name,
            'name': name,
            'mimeType': 'text/plain',
            'size': st.st_size,
            'lines': line_count,
            'mtime': int(st.st_mtime),
        }
    except OSError:
        return None


def _multidx_dir(root=None):
    """多级目录所在目录：<根>/<index.out_dir>/<multilevel.out_dir 或 multilevel>。
    Catalogue directory: <root>/<index.out_dir>/<multilevel.out_dir or multilevel>.
    与 daybook_multidx.py 同源（生产 conf index.out_dir=索引 ⇒ <根>/索引/multilevel）。
    Same source as daybook_multidx.py (production conf index.out_dir=索引 ⇒ <root>/索引/multilevel)."""
    base = root or _root()
    conf = _load_conf()
    idx = (conf.get('index', {}).get('out_dir', '') or '').strip()
    ml = (conf.get('multilevel', {}).get('out_dir', '') or '').strip()
    if idx:
        base = os.path.join(base, idx)
    return os.path.join(base, ml) if ml else os.path.join(base, MULTIDX_SUBDIR)


def _safe_dir_name(name):
    """目录资源名防穿越：拒绝空/../斜杠/绝对路径。返回原名或 None。
    Catalogue resource name traversal guard."""
    if not name or '..' in name or '/' in name or '\\' in name or os.path.isabs(name):
        return None
    return name


def _dir_md_name(name):
    """目录资源名 → 文件名。总目 → catalog.md；其余 → <名>_catalog.md。
    Catalogue resource name → file name: digest → catalog.md, else <name>_catalog.md."""
    return 'catalog.md' if name in DIR_ALIASES or name == '' else '%s_catalog.md' % name


def _dir_md_name_legacy(name):
    """旧中文文件名（只读兼容）。Legacy Chinese file name (read-only fallback)."""
    return '总目录.md' if name in DIR_ALIASES or name == '' else '%s_目录.md' % name


def _dir_meta(name, path):
    """多级目录元数据（text/markdown）。文件不存在返 None。
    Catalogue metadata (text/markdown); None when the file is missing."""
    try:
        from safeio import sniff_bytes
        st = os.stat(path)
        with open(path, 'rb') as f:
            raw = f.read()
        txt, _enc, _why = sniff_bytes(raw)
        line_count = txt.count('\n') + (0 if txt.endswith('\n') else 1)
        return {
            'uri': DIR_URI_PREFIX + (name or 'catalog'),
            'name': 'catalog/%s' % (name or 'catalog'),
            'mimeType': 'text/markdown',
            'size': st.st_size,
            'lines': line_count,
            'mtime': int(st.st_mtime),
        }
    except OSError:
        return None


def self_check():
    """启动自检：根可解析、conf 可读、卷非空（空/全不可读 → stderr 告警）。
    Startup self-check: root resolvable, conf readable, volumes non-empty (empty/all-missing → stderr warning).
    返回 (root, 登记卷数)。根无效抛 RootError。
    Returns (root, registered volume count). An invalid root raises RootError."""
    root = _root()
    vols = _load_volumes()
    if not vols:
        _warn('自检：volumes 为空 —— %s 的 [volumes] 未登记任何卷，'
              'resources/list 将返回 0 个资源；请在该 conf 登记卷。' % _conf_path(),
              'empty-volumes')
    else:
        missing = [n for n, rel in vols.items()
                   if not os.path.exists(rel if os.path.isabs(rel) else os.path.join(root, rel))]
        if missing:
            _warn('自检：volumes 登记 %d 卷，其中 %d 卷文件不存在（root=%s）：%s'
                  % (len(vols), len(missing), root, ', '.join(missing)),
                  'missing-volumes:' + ','.join(missing))
    return root, len(vols)


def list_resources(root=None, pattern=None):
    """列 daybook.conf [volumes] 表登记的所有卷；并附 v3.1 多级目录资源（存在才列）。
    List every volume in the conf [volumes] table, plus v3.1 catalogue resources.
    pattern 参数忽略（保留兼容）·按 conf 顺序返回。"""
    vols = _load_volumes()
    out = []
    base = root or _root()
    if not vols:
        _warn('volumes 为空（%s）：resources/list 返回 0 个资源。'
              % _conf_path(), 'empty-volumes')
    for name, rel in vols.items():
        path = rel if os.path.isabs(rel) else os.path.join(base, rel)
        meta = _vol_meta(name, path)
        if meta:
            out.append(meta)
    if vols and not any(m.get('uri', '').startswith('daybook://') for m in out):
        _warn('volumes 登记 %d 卷但文件全部不可读（root=%s）：resources/list 返回 0 个卷。'
              % (len(vols), base), 'all-unreadable')
    # ── v3.1：多级目录（四库式）·派生资源·存在才列 ──
    # ── v3.1: catalogue artifacts — derived, listed only when present ──
    mdir = _multidx_dir(base)
    if os.path.isdir(mdir):
        m = _dir_meta('catalog', os.path.join(mdir, 'catalog.md'))
        if m:
            out.append(m)
        for name in vols:
            m = _dir_meta(name, os.path.join(mdir, '%s_catalog.md' % name))
            if m:
                out.append(m)
    return out


def _resolve_dir_path(mdir, name):
    """新名优先、旧名回退。New file name first, legacy name as fallback."""
    for cand in (_dir_md_name(name), _dir_md_name_legacy(name)):
        p = os.path.join(mdir, cand)
        if os.path.exists(p):
            return p
    return None


def resource_file_path(uri, root=None):
    """uri → 实际文件路径（卷或目录资源）·非法/未知返 None（不判存在）。
    uri → the real file path (volume or catalogue resource) · None when illegal/unknown (existence not checked)."""
    if not isinstance(uri, str):
        return None
    if uri.startswith(DIR_URI_PREFIX_LEGACY):
        uri = uri.replace(DIR_URI_PREFIX_LEGACY, DIR_URI_PREFIX, 1)
    base = root or _root()
    if uri.startswith(DIR_URI_PREFIX):
        name = uri[len(DIR_URI_PREFIX):]
        if _safe_dir_name(name) is None:
            return None
        return _resolve_dir_path(_multidx_dir(base), name)
    if not uri.startswith('daybook://'):
        return None
    name = uri[len('daybook://'):]
    if _safe_vol(name) is None:
        return None
    return _vol_path(name, base)


def resource_exists(uri, root=None):
    """uri 是否存在（卷文件存在 / 目录派生件存在）。
    Whether the uri exists (the volume file exists / the catalogue artifact exists)."""
    p = resource_file_path(uri, root)
    return bool(p) and os.path.exists(p)


def _read_dir_resource(uri, offset, limit, root, agent_id):
    """读目录资源 `daybook://catalog/<名>`（名=卷名 或 catalog）。返回 {uri,mimeType,text} 或 None。
    Read a catalogue resource (name = volume name or 'catalog')."""
    name = uri[len(DIR_URI_PREFIX):]
    if _safe_dir_name(name) is None:
        _audit('read', agent_id, '非法目录名 %r' % name)
        return None
    path = _resolve_dir_path(_multidx_dir(root or _root()), name)
    if path is None:
        _audit('read', agent_id, '目录不存在 %s' % name)
        return None
    offset = max(1, offset or 1)
    from safeio import sniff_bytes
    with open(path, 'rb') as f:
        raw = f.read()
    txt, _enc, _why = sniff_bytes(raw)
    all_lines = txt.splitlines(keepends=True)
    lines = all_lines[offset - 1:]
    if limit is not None:
        lines = lines[:limit]
    _audit('read', agent_id, 'uri=%s offset=%s limit=%s → %d chars' % (
        uri, offset, limit, sum(len(x) for x in lines)))
    return {
        'uri': uri,
        'mimeType': 'text/markdown',
        'text': ''.join(lines),
    }


def read_resource(uri, offset=None, limit=None, root=None, agent_id=None):
    """读卷或目录·支持行范围。
    Read a volume or a catalogue resource, with an optional line range.
    - uri: daybook://<卷名> ｜ daybook://catalog/<卷名 或 catalog>（v3.1）
           旧写法 daybook://目录/… 仍可读（兼容别名）
    - offset: 起始行（1-based·省略=1）/ start line, 1-based
    - limit: 最多读多少行（省略=全卷）/ max lines
    返回 {uri, mimeType, text} 或 None（卷/目录不存在）"""
    if uri.startswith(DIR_URI_PREFIX_LEGACY):
        return _read_dir_resource(uri.replace(DIR_URI_PREFIX_LEGACY, DIR_URI_PREFIX, 1),
                                  offset, limit, root, agent_id)
    if uri.startswith(DIR_URI_PREFIX):
        return _read_dir_resource(uri, offset, limit, root, agent_id)
    if not uri.startswith('daybook://'):
        return None
    name = uri[len('daybook://'):]
    if _safe_vol(name) is None:
        _audit('read', agent_id, '非法卷名 %r' % name)
        return None
    path = _vol_path(name, root or _root())
    if path is None or not os.path.exists(path):
        _audit('read', agent_id, '卷不存在 %s' % name)
        return None
    offset = max(1, offset or 1)
    from safeio import sniff_bytes
    with open(path, 'rb') as f:
        raw = f.read()
    txt, _enc, _why = sniff_bytes(raw)
    all_lines = txt.splitlines(keepends=True)
    lines = all_lines[offset - 1:]
    if limit is not None:
        lines = lines[:limit]
    _audit('read', agent_id, 'uri=%s offset=%s limit=%s → %d chars' % (
        uri, offset, limit, sum(len(x) for x in lines)))
    return {
        'uri': uri,
        'mimeType': 'text/plain',
        'text': ''.join(lines),
    }


def find_resource(name, root=None):
    """按名字找卷·返回 uri 或 None。Find a volume by name → uri or None."""
    path = _vol_path(name, root or _root())
    if path and os.path.exists(path):
        return 'daybook://%s' % name
    return None


def resource_path(name, root=None):
    """供 subscribe 模块用·返绝对路径或 None。Absolute path for the subscribe module."""
    return _vol_path(name, root or _root())
