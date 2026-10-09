#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Resources（W-DB-023-G2·第 2 项·修复版 r2）
================================================
对照审核报告 P2-3 修复：
- list 不再扫描 *.txt·改读 daybook.conf [卷] 表·与系统其余部分语义一致
- read 同步：卷名按 conf 解析·未在 conf 的卷返 None
- _vol_path 加 ../ 穿越防护（P1-3）
- read 写审计留痕（P1-2）
- 零依赖：仅 Python 3 标准库
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

AUDIT_VOL_NAME = 'MCP审计卷.txt'


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


def list_resources(root=None, pattern=None):
    """列 daybook.conf [卷] 表登记的所有卷。
    pattern 参数忽略（保留兼容）·按 conf 顺序返回。"""
    vols = _load_volumes()
    out = []
    for name, rel in vols.items():
        base = root or _root()
        path = rel if os.path.isabs(rel) else os.path.join(base, rel)
        meta = _vol_meta(name, path)
        if meta:
            out.append(meta)
    return out


def read_resource(uri, offset=None, limit=None, root=None, agent_id=None):
    """读卷·支持行范围。
    - uri: daybook://卷名
    - offset: 起始行（1-based·省略=1）
    - limit: 最多读多少行（省略=全卷）
    返回 {uri, mimeType, text} 或 None（卷不存在）"""
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
