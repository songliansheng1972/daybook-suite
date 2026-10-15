#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""MCP Resources（W-DB-023-G2·第 2 项·修复版 r2）
================================================
对照审核报告 P2-3 修复：
- list 不再扫描 *.txt·改读 daybook.conf [卷] 表·与系统其余部分语义一致
- read 同步：卷名按 conf 解析·未在 conf 的卷返 None
- _vol_path 加 ../ 穿越防护（P1-3）
- read 写审计留痕（P1-2）
- 零依赖：仅 Python 3 标准库

v3.1（四库式多级目录·长上下文）：
- 新增**目录资源** `daybook://目录/<卷>`、`daybook://目录/总目` —— 读 <根>/多级/*.md
  （由 `daybook.py multiindex` 生成的派生件·只读·可删可重建）
- 目录资源**存在才列**（未跑 multiindex 时静默不列·不报错）
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

AUDIT_VOL_NAME = 'MCP审计卷.txt'

# ── v3.1 多级目录资源（四库式：部=卷／类·作者／属=条目）──
MULTIDX_SUBDIR = '多级'
DIR_URI_PREFIX = 'daybook://目录/'
DIR_ALIASES = ('总目', '总目录')


def _audit_vol():
    """审计卷路径·走 _root()·监理 r4 修复。"""
    return os.path.join(_root(), AUDIT_VOL_NAME)


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _root():
    return os.environ.get('DAYBOOK_ROOT') or HERE


def _audit(method, agent_id, detail):
    try:
        rec = '[%s] [MCP] [resources/%s] [agent=%s] %s\n' % (
            _now(), method, agent_id or '匿名', detail)[:400]
        from safeio import atomic_append
        atomic_append(_audit_vol(), rec)
    except OSError:
        pass


def _load_volumes():
    """读 daybook.conf [卷] 表·返回有序 dict {卷名: 相对路径}。
    失败返空 dict（不阻塞 list）。
    conf 路径走 _root()·生产同 HERE·测试可走 DAYBOOK_ROOT。"""
    try:
        import daybook as _db
        conf_path = os.path.join(_root(), 'daybook.conf')
        conf = _db.load_conf(conf_path)
        return conf.get('卷', {})
    except Exception:
        return {}


def _safe_vol(name):
    """卷名防穿越（P1-3）。"""
    if not name or '..' in name or '/' in name or '\\' in name or os.path.isabs(name):
        return None
    return name


def _vol_path(name, root=None):
    """卷名 → 文件路径。按 conf 解析·找不到返 None。
    root 默认 _root()。"""
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
    返回 (text, enc, why)。"""
    from safeio import read_vol as _rv
    return _rv(path)


def _vol_meta(name, path):
    """读卷元数据：行数/字节数/mtime。"""
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
    """多级目录所在目录：<根>/多级/（daybook_multidx 之产出）。"""
    return os.path.join(root or _root(), MULTIDX_SUBDIR)


def _safe_dir_name(name):
    """目录资源名防穿越：拒绝空/../斜杠/绝对路径。返回原名或 None。"""
    if not name or '..' in name or '/' in name or '\\' in name or os.path.isabs(name):
        return None
    return name


def _dir_md_name(name):
    """目录资源名 → 文件名。总目 → 总目录.md；其余 → <名>_目录.md。"""
    return '总目录.md' if name in DIR_ALIASES or name == '' else '%s_目录.md' % name


def _dir_meta(name, path):
    """多级目录元数据（text/markdown）。文件不存在返 None。"""
    try:
        from safeio import sniff_bytes
        st = os.stat(path)
        with open(path, 'rb') as f:
            raw = f.read()
        txt, _enc, _why = sniff_bytes(raw)
        line_count = txt.count('\n') + (0 if txt.endswith('\n') else 1)
        return {
            'uri': DIR_URI_PREFIX + (name or '总目'),
            'name': '目录/%s' % (name or '总目'),
            'mimeType': 'text/markdown',
            'size': st.st_size,
            'lines': line_count,
            'mtime': int(st.st_mtime),
        }
    except OSError:
        return None


def list_resources(root=None, pattern=None):
    """列 daybook.conf [卷] 表登记的所有卷；并附 v3.1 多级目录资源（存在才列）。
    pattern 参数忽略（保留兼容）·按 conf 顺序返回。"""
    vols = _load_volumes()
    out = []
    base = root or _root()
    for name, rel in vols.items():
        path = rel if os.path.isabs(rel) else os.path.join(base, rel)
        meta = _vol_meta(name, path)
        if meta:
            out.append(meta)
    # ── v3.1：多级目录（四库式）·派生资源·存在才列 ──
    mdir = _multidx_dir(base)
    if os.path.isdir(mdir):
        m = _dir_meta('总目', os.path.join(mdir, '总目录.md'))
        if m:
            out.append(m)
        for name in vols:
            m = _dir_meta(name, os.path.join(mdir, '%s_目录.md' % name))
            if m:
                out.append(m)
    return out


def _read_dir_resource(uri, offset, limit, root, agent_id):
    """读目录资源 `daybook://目录/<名>`（名=卷名 或 总目）。返回 {uri,mimeType,text} 或 None。"""
    name = uri[len(DIR_URI_PREFIX):]
    if _safe_dir_name(name) is None:
        _audit('read', agent_id, '非法目录名 %r' % name)
        return None
    path = os.path.join(_multidx_dir(root or _root()), _dir_md_name(name))
    if not os.path.exists(path):
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
    - uri: daybook://卷名 ｜ daybook://目录/<卷名 或 总目>（v3.1）
    - offset: 起始行（1-based·省略=1）
    - limit: 最多读多少行（省略=全卷）
    返回 {uri, mimeType, text} 或 None（卷/目录不存在）"""
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
    """按名字找卷·返回 uri 或 None。"""
    path = _vol_path(name, root or _root())
    if path and os.path.exists(path):
        return 'daybook://%s' % name
    return None


def resource_path(name, root=None):
    """供 subscribe 模块用·返绝对路径或 None。"""
    return _vol_path(name, root or _root())
