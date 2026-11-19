# -*- coding: utf-8 -*-
"""账本实例号：安装期生成，落 `实例.json`；心跳/条目携带 `[实例=<uid@路径tag>]`。

Ledger instance id: generated at install time into `实例.json`; heartbeats and entries carry
`[实例=<uid@path-tag>]`.

用途（4.0.7 只做告警，不硬拒）：克隆后的两份身份若同时指向同一 root，游标会互相吃；
doctor / alive 看到同一 agent_id 有两个活跃实例时给出告警。

Scope (4.0.7 warns, never hard-rejects): two copies of the same identity pointing at one root
can eat each other's cursors; doctor / alive warn when one agent_id shows two active instances.

边界：`uid` 来自安装期生成的文件，克隆会连同 `实例.json` 一起复制；运行时 token 另拼
`BASE 绝对路径` 的短哈希，因此**不同路径上的两份副本** token 不同，告警才会触发。
Boundary: the uid is copied with the ledger; the runtime token appends a short hash of the
BASE absolute path, so two copies at different paths get different tokens and the warning fires.
"""
import functools
import hashlib
import json
import os
import subprocess
import time
import uuid

FILE = '实例.json'
TOKEN_RE = r'\[实例=([^\]]+)\]'


@functools.lru_cache(maxsize=1)
def _machine_id():
    """稳定机器标识：优先环境覆盖，其次 /etc/machine-id、~/.daybook-machine-id、
    IOPlatformUUID，最后网卡节点。锚都在 BASE 之外，且不用主机名——改名会漂。
    import 时不读锚；首次 host_tag() 才触发，同进程内缓存一次。
    Stable machine id: env override, then /etc/machine-id, ~/.daybook-machine-id,
    IOPlatformUUID, then the NIC node. Anchors live outside BASE; never the hostname.
    No anchor read at import time: the first host_tag() call reads it, cached per process."""
    env = os.environ.get('DAYBOOK_HOST_ID')
    if env:
        return env
    mid = ''
    for p in ('/etc/machine-id', '/var/lib/dbus/machine-id',
              os.path.expanduser('~/.daybook-machine-id')):
        try:
            # 只走派发读锚（不经 open）：dispatch 函数不得夹带任何写原语。
            # Anchor read via dispatch only (no open): a dispatch function must carry no writes.
            mid = subprocess.run(['cat', p], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, universal_newlines=True,
                                 timeout=2).stdout.strip()
            if mid:
                break
        except (OSError, subprocess.SubprocessError):
            continue
    if not mid:
        try:
            out = subprocess.run(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 universal_newlines=True, timeout=3).stdout
            for line in out.splitlines():
                if 'IOPlatformUUID' in line:
                    mid = line.split('=', 1)[1].strip().strip('"')
                    break
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    if not mid:
        mid = '%x' % uuid.getnode()
    return mid


def host_tag():
    """机器维度：稳定机器标识的 sha1 前 8 位；首次调用才读锚并缓存。
    Machine dimension: first 8 hex of sha1(machine id); the anchor is read on first call only."""
    mid = os.environ.get('DAYBOOK_HOST_ID') or _machine_id()
    return hashlib.sha1(mid.encode('utf-8')).hexdigest()[:8]


def ensure(base):
    """确保 BASE 有实例号并返回 uid；已有则原样返回（幂等）。
    Ensure the BASE has an instance id and return the uid; keep the existing one (idempotent)."""
    p = os.path.join(base, FILE)
    try:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        if d.get('实例'):
            return d['实例']
    except (OSError, ValueError):
        pass
    rec = {'实例': uuid.uuid4().hex,
           '生成': time.strftime('%Y-%m-%d %H:%M:%S'),
           'BASE': os.path.abspath(base)}
    # 账本桶只许 safeio：实例文件也走唯一写链（原子替换）。
    # Ledger-bucket writes must go through safeio: the instance file uses the single write chain.
    from safeio import locked, WriteMode
    with locked(base) as lr:
        lr.write(lr.root.rel_of(p, 'instance.ensure'),
                 json.dumps(rec, ensure_ascii=False),
                 mode=WriteMode.REPLACE, perm=0o644)
    return rec['实例']


def token(base):
    """运行时实例 token：`uid8@path8@machine8`；无实例文件返回 None。
    机器维度让「同路径还原/迁移到另一台机」也能区分为两个实例。
    Runtime token: `uid[:8]@sha1(path)[:8]@sha1(machine)[:8]`; None when no instance file exists.
    The machine dimension distinguishes a same-path restore/migration on two machines."""
    if base is None:
        return None
    base = getattr(base, 'label', base)
    try:
        with open(os.path.join(base, FILE), encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    uid = str(d.get('实例') or '')
    if not uid:
        return None
    tag = hashlib.sha1(os.path.realpath(os.path.abspath(base)).encode('utf-8')).hexdigest()[:8]
    return '%s@%s@%s' % (uid[:8], tag, host_tag())


def _ts(parts0):
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return time.mktime(time.strptime(parts0, fmt))
        except ValueError:
            continue
    return None


def active(heartbeat_path, timeout=120, now=None):
    """扫心跳卷 → {agent_id: {实例token: 最后时间戳}}，只留 timeout 内的活跃实例。
    Scan the heartbeat volume → {agent_id: {instance token: last ts}}, only active ones
    within `timeout` seconds."""
    now = time.time() if now is None else now
    out = {}
    try:
        text = open(heartbeat_path, encoding='utf-8').read()
    except OSError:
        return out
    import re
    for line in text.splitlines():
        if '[心跳]' not in line or 'alive' not in line:
            continue
        parts = [p.strip(' []') for p in line.split(']') if p.strip()]
        if len(parts) < 3:
            continue
        aid = parts[2]
        if not aid or aid in ('心跳', 'alive'):
            continue
        ts = _ts(parts[0])
        m = re.search(TOKEN_RE, line)
        tok = m.group(1) if m else None
        if ts is None or ts < now - timeout:
            continue
        d = out.setdefault(aid, {})
        if tok not in d or ts > d[tok]:
            d[tok] = ts
    return out
