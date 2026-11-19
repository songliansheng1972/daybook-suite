#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""daybook MCP stdio signing proxy (4.0.7)
=========================================
随包组件：客户端仍按标准 MCP 说话；本代理只在写调用 daybook_append 上补
agent_id、ts、signature，其余 JSON-RPC 原样透传。

版本：0.2.0（4.0.7 随包）
协议：mcp-stdio-signer/1

安全边界
- 密钥从 <root>/.daybook_keys/<agent_id>.key 读取，权限必须恰好 600；
  不写入日志/审计/命令行，审计只记 sha256(key)[:8] 指纹前缀。
- 代理强制使用自己的 agent_id；客户端不能借代理冒充别的 agent。
- 密钥不可用时只拒写，只读请求继续透传，不拖垮只读。

崩溃策略
- 单次签名/写失败只回该请求的 JSON-RPC error，不退出；只读请求继续透传。
- 后端进程异常退出时，代理退出；不会静默伪造成功。
"""
import argparse
import fcntl
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time

VERSION = '0.2.0'
PROTOCOL = 'mcp-stdio-signer/1'
# 4.0.7：璇玑只留一个写工具；其余调度写已移出 MCP 面。
WRITE_SIGN = ('daybook_append',)
ZERO = '0' * 64


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def sha(s):
    if isinstance(s, str):
        s = s.encode('utf-8')
    return hashlib.sha256(s).hexdigest()


def payload_for(tool, args, ts):
    if tool == 'daybook_append':
        return 'append|v2|volume=%s|tag=%s|subtag=%s|to=%s|ts=%d|content=%s' % (
            args.get('volume', ''), args.get('tag', ''),
            args.get('subtag') or '_',
            args.get('to', '') or '', int(ts), args.get('content', ''))
    raise ValueError('not a signing tool: %s' % tool)


def read_conf_volumes(root):
    vols, sec = {}, None
    try:
        with open(os.path.join(root, 'daybook.conf'), encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    sec = line[1:-1]
                    continue
                if sec == 'volumes' and '=' in line and not line.startswith(('#', ';')):
                    k, v = line.split('=', 1)
                    vols[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return vols


def vol_path(root, vol):
    p = read_conf_volumes(root).get(vol)
    if not p:
        return None
    return p if os.path.isabs(p) else os.path.join(root, p)


def count_lines(path):
    try:
        with open(path, 'rb') as f:
            return f.read().count(b'\n')
    except FileNotFoundError:
        return 0


class Audit:
    def __init__(self, base):
        self.dir = os.path.join(base, 'audit')
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self.path = os.path.join(self.dir, 'sign_audit.jsonl')
        self.head = os.path.join(self.dir, 'audit.head')
        self.lock = os.path.join(self.dir, 'sign_audit.lock')
        for p in (self.path, self.head, self.lock):
            if not os.path.exists(p):
                fd = os.open(p, os.O_CREAT | os.O_WRONLY, 0o600)
                os.close(fd)
            os.chmod(p, 0o600)

    def write(self, rec):
        with open(self.lock, 'a+') as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            prev = ZERO
            try:
                with open(self.path, encoding='utf-8') as f:
                    lines = f.read().splitlines()
                if lines:
                    prev = json.loads(lines[-1]).get('self', ZERO)
            except FileNotFoundError:
                pass
            rec = dict(rec)
            rec['prev'] = prev
            rec['self'] = sha(canon(rec))
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (canon(rec) + '\n').encode('utf-8'))
                os.fsync(fd)
            finally:
                os.close(fd)
            n = count_lines(self.path)
            tmp = self.head + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'lines': n, 'last': rec['self'],
                           'updated': time.strftime('%Y-%m-%d %H:%M:%S')},
                          f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.head)
            fcntl.flock(lf, fcntl.LOCK_UN)
            return rec


class Proxy:
    def __init__(self, root, agent, label, server, audit_base):
        self.root = os.path.abspath(root)
        self.agent = agent
        self.label = label
        self.server = server
        self.audit = Audit(audit_base)
        self.key_path = os.path.join(self.root, '.daybook_keys', agent + '.key')
        self.key = None
        self.key_error = None
        try:
            self.key = self._load_key()
        except (OSError, SystemExit) as e:
            # 密钥不可用时不退出：只读请求继续透传，写请求逐条报错。
            self.key_error = str(e)
        self.key_fp = sha(self.key)[:8] if self.key else ''
        self.pending = {}
        self.plock = threading.Lock()
        self.wlock = threading.Lock()
        self.backend = self._spawn()

    def _load_key(self):
        st = os.stat(self.key_path)
        if (st.st_mode & 0o777) != 0o600:
            raise SystemExit('密钥权限不是 600：%s' % self.key_path)
        with open(self.key_path, encoding='utf-8') as f:
            key = f.read().strip()
        if not key:
            raise SystemExit('密钥为空：%s' % self.key_path)
        return key

    def _spawn(self):
        env = os.environ.copy()
        env.pop('MCP_READ_ONLY', None)
        env['DAYBOOK_ROOT'] = self.root
        env['DAYBOOK_AGENT_ID'] = self.agent
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        return subprocess.Popen([sys.executable, self.server], cwd=self.root,
                                env=env, text=True, bufsize=1,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=None)

    def sign(self, msg):
        """Return (modified_msg, pending_meta) or (msg, None)."""
        if msg.get('method') != 'tools/call':
            return msg, None
        name = (msg.get('params') or {}).get('name')
        if name not in WRITE_SIGN:
            return msg, None
        if not self.key:
            raise RuntimeError('签名不可用（%s），写调用被拒；只读调用不受影响'
                               % (self.key_error or '密钥缺失'))
        args = dict(((msg.get('params') or {}).get('arguments') or {}))
        original = dict(args)
        ts = int(time.time())
        args['ts'] = ts
        args['agent_id'] = self.agent
        # 产品侧红线：author 必须等于 agent_id；代理强制署自己的身份。
        args['author'] = self.agent
        payload = payload_for(name, args, ts)
        args['signature'] = hmac.new(self.key.encode(), payload.encode(),
                                     hashlib.sha256).hexdigest()
        msg = dict(msg)
        msg['params'] = dict(msg.get('params') or {})
        msg['params']['arguments'] = args

        volume = args.get('volume', '')
        vp = vol_path(self.root, volume) if volume else None
        before_v = os.path.getsize(vp) if vp and os.path.exists(vp) else 0
        sidecar = os.path.join(self.root, 'MCP签名边车.jsonl')
        before_s = os.path.getsize(sidecar) if os.path.exists(sidecar) else 0
        meta = {
            'tool': name, 'args': original, 'payload': payload,
            'payload_sha256': sha(payload), 'key_fp': self.key_fp,
            'volume': volume, 'volume_path': vp, 'before_v': before_v,
            'before_s': before_s, 'started': time.time(),
        }
        return msg, meta

    def anchor(self, meta):
        """Find the product sidecar line and, for append, the ledger line."""
        out = {}
        sidecar = os.path.join(self.root, 'MCP签名边车.jsonl')
        try:
            with open(sidecar, 'rb') as f:
                f.seek(meta['before_s'])
                tail = f.read().decode('utf-8', 'replace').splitlines()
            base = count_lines(sidecar) - len(tail)
            for i, line in enumerate(tail, 1):
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if (rec.get('tool') == meta['tool'] and
                        rec.get('agent_id') == self.agent and
                        sha(rec.get('payload', '')) == meta['payload_sha256']):
                    out['sidecar_line'] = base + i
                    out['sidecar_sha256'] = sha(line)
        except FileNotFoundError:
            pass
        vp = meta.get('volume_path')
        if meta['tool'] == 'daybook_append' and vp and os.path.exists(vp):
            try:
                with open(vp, 'rb') as f:
                    f.seek(meta['before_v'])
                    tail = f.read().decode('utf-8', 'replace').splitlines()
                base = count_lines(vp) - len(tail)
                content = meta['args'].get('content', '')
                for i in range(len(tail) - 1, -1, -1):
                    if tail[i].endswith(content):
                        out['ledger_line'] = base + i + 1
                        out['ledger_sha256'] = sha(tail[i])
                        break
            except FileNotFoundError:
                pass
        return out

    def audit_one(self, rid, meta, resp):
        ok = not ('error' in resp) and not (resp.get('result') or {}).get('isError')
        rec = {
            'at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'agent_id': self.agent, 'label': self.label,
            'tool': meta['tool'], 'request_id': rid,
            'args_sha256': sha(canon(meta['args'])),
            'payload_sha256': meta['payload_sha256'],
            'key_fp': meta['key_fp'],
            'result': 'ok' if ok else 'error',
            'elapsed_ms': int((time.time() - meta['started']) * 1000),
        }
        if ok:
            rec.update(self.anchor(meta))
        else:
            try:
                rec['error'] = (resp.get('result', {}).get('content', [{}])[0]
                                .get('text', '') or resp.get('error', {}).get('message', ''))[:200]
            except Exception:
                rec['error'] = 'error'
        self.audit.write(rec)

    def client_loop(self):
        for line in sys.stdin:
            try:
                msg = json.loads(line)
                out, meta = self.sign(msg)
                if meta is not None:
                    with self.plock:
                        self.pending[msg.get('id')] = meta
                with self.wlock:
                    self.backend.stdin.write(canon(out) + '\n')
                    self.backend.stdin.flush()
            except Exception as e:
                try:
                    rid = json.loads(line).get('id')
                except Exception:
                    rid = None
                if rid is not None:
                    with self.wlock:
                        sys.stdout.write(canon({'jsonrpc': '2.0', 'id': rid,
                                                'error': {'code': -32603,
                                                          'message': 'signer: %s' % e}}) + '\n')
                        sys.stdout.flush()

    def backend_loop(self):
        for line in self.backend.stdout:
            try:
                resp = json.loads(line)
                rid = resp.get('id')
                with self.plock:
                    meta = self.pending.pop(rid, None)
                if meta is not None:
                    # 先落审计再回客户端：客户端拿到成功前，审计已持久化。
                    self.audit_one(rid, meta, resp)
            except Exception as e:
                sys.stderr.write('signer audit: %s\n' % e)
            with self.wlock:
                sys.stdout.write(line if line.endswith('\n') else line + '\n')
                sys.stdout.flush()
        self.backend.wait()

    def run(self):
        t = threading.Thread(target=self.backend_loop, daemon=False)
        t.start()
        try:
            self.client_loop()
        finally:
            try:
                self.backend.stdin.close()
            except Exception:
                pass
            t.join(timeout=5)
            try:
                self.backend.terminate()
            except Exception:
                pass


def _default_server():
    """默认服务端：随包布局 <BASE>/runtime/daybook-suite/daybook-mcp/mcp_server.py，
    或开发树 <BASE>/daybook-mcp/mcp_server.py。
    Default server: installed layout or the development/release tree."""
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.dirname(here)
    for cand in (os.path.join(base, 'runtime', 'daybook-suite', 'daybook-mcp', 'mcp_server.py'),
                 os.path.join(base, 'daybook-mcp', 'mcp_server.py'),
                 os.path.join(base, 'mcp_server.py')):
        if os.path.exists(cand):
            return cand
    return os.path.join(base, 'daybook-mcp', 'mcp_server.py')


def main():
    ap = argparse.ArgumentParser(description='daybook MCP stdio signing proxy')
    ap.add_argument('--root', required=True, help='账本根（DAYBOOK_ROOT）')
    ap.add_argument('--agent', required=True, help='本代理绑定的 agent_id')
    ap.add_argument('--label', default='', help='审计标签（客户端名）')
    ap.add_argument('--server', default=None, help='mcp_server.py 路径（默认随包探测）')
    ap.add_argument('--audit-base', default=None, help='审计目录的上级（默认 signer 的上级）')
    args = ap.parse_args()
    audit_base = args.audit_base or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    server = args.server or _default_server()
    if not os.path.exists(server):
        sys.stderr.write('signer: 找不到 mcp_server.py：%s\n' % server)
        return 2
    Proxy(args.root, args.agent, args.label, server, audit_base).run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
