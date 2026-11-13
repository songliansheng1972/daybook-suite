#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""Agent 间消息协议（W-DB-023-G3·第 4 项）
Inter-agent messaging protocol (W-DB-023-G3 · item 4)
================================================
- 本地 Unix socket（POSIX：Linux/macOS）
  Local Unix socket (POSIX: Linux/macOS)
- 消息格式：[from] [to] [type] [content]
  Message format: [from] [to] [type] [content]
  - type：notify/request/response/broadcast
    type: notify/request/response/broadcast
- Agent A 写完卷 → notify Agent B
  After Agent A finishes writing a volume → notify Agent B
- 零依赖：仅用 Python 3 标准库（socketserver/socket/json/threading）
  Zero dependencies: only the Python 3 standard library (socketserver/socket/json/threading)

设计：
Design:
  - 每个 Agent 一个 socket 路径 /tmp/daybook_agent_<name>.sock
    One socket path per agent: /tmp/daybook_agent_<name>.sock
  - 消息以 '\n' 结尾·JSON 编码·单次 recv ≤ 65536
    Messages end with '\n' · JSON-encoded · a single recv ≤ 65536
  - 服务端单线程接收·所有消息写入同一 inbox 卷（`to` 只作字段记录，不按收件人分卷）
    The server receives single-threaded · all messages go to one inbox volume (`to` is recorded as a field only; no per-recipient volumes)
  - inbox 卷 append-only：[时间] [收] [from] [to] [type] content
    The inbox volume is append-only: [时间] [收] [from] [to] [type] content

用法：
Usage:
  # 服务端常驻 · server kept running
  python3 agent_message.py serve 汤姆
  # 客户端发消息 · client sends a message
  python3 agent_message.py send 汤姆 史泰龙 notify "MCP resources/list 已实现"
"""
import os, sys, time, json, socket, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import volume_paths as _vp

SOCK_DIR = '/tmp'
# 默认 inbox（无 --root 时的旧行为）· default inbox (legacy behavior without --root)
INBOX_VOL = os.path.join(HERE, '消息卷.txt')

MSG_TYPES = ('notify', 'request', 'response', 'broadcast')


def inbox_path(root=None):
    """消息卷路径：给了 root 就经 conf 解析（与编排卷同一个根），否则用旧默认。
    Inbox volume path: with a root, resolve through conf (same root as the ledger); otherwise the legacy default."""
    return INBOX_VOL if root is None else _vp.resolve_volumes(root)['inbox']


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _safe_agent_token(agent_name):
    """agent 名 → socket 文件名 token：去路径分隔符与控制字符，保留 Unicode（中文名照用）。
    拒绝空、'.'、'..'（防止路径穿越与落到父目录）。
    Agent name → socket filename token: strip path separators and control chars, keep Unicode
    (Chinese names still work). Reject empty, '.', '..' (prevents traversal and parent-dir escapes)."""
    s = str(agent_name or '').replace('\x00', '').strip()
    for sep in ('/', '\\', os.sep, os.altsep):
        if sep:
            s = s.replace(sep, '_')
    if s in ('', '.', '..'):
        raise ValueError('非法 agent 名（不能为空、. 或 ..）：%r' % (agent_name,))
    return s


def sock_path(agent_name):
    """agent 名的 socket 路径。名字先净化，且不得超过 sockaddr_un 的路径上限。
    Socket path for an agent name. The name is sanitized first and the path must fit sockaddr_un."""
    path = os.path.join(SOCK_DIR, 'daybook_agent_%s.sock' % _safe_agent_token(agent_name))
    # Linux/macOS 的 sockaddr_un.sun_path 通常 104/108 字节（含结尾 NUL）；超出即无法 bind/connect。
    # Linux/macOS sockaddr_un.sun_path is typically 104/108 bytes including the trailing NUL; longer cannot bind/connect.
    if len(os.fsencode(path)) >= 104:
        raise ValueError('socket 路径过长（%d 字节 ≥104）：%s' % (len(os.fsencode(path)), path))
    return path


def encode(msg):
    """msg=dict{from,to,type,content}。返回 bytes（JSON + '\n'）。
    msg=dict{from,to,type,content}. Returns bytes (JSON + '\n')."""
    if not msg.get('type') in MSG_TYPES:
        raise ValueError('非法消息类型：%s' % msg.get('type'))
    return (json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8')


def decode_stream(buf):
    """从已收 buffer（bytes）里切出完整消息·返回 (list_of_msgs, remaining_buf)。
    Slice complete messages out of the received buffer (bytes) · returns (list_of_msgs, remaining_buf).
    按 b'\n' 切行后逐行 decode·避免多字节字符跨 recv 边界导致 UnicodeDecodeError。
    Split on b'\n' then decode line by line · avoids UnicodeDecodeError from multibyte chars crossing a recv boundary."""
    msgs = []
    while b'\n' in buf:
        line, buf = buf.split(b'\n', 1)
        if line.strip():
            try:
                msgs.append(json.loads(line.decode('utf-8')))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
    return msgs, buf


def _append_inbox(msg, direction='收', root=None):
    """消息进 inbox 卷·append-only·白箱可审计。
    Write the message into the inbox volume · append-only · white-box auditable."""
    from safeio import atomic_append
    path = inbox_path(root)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    rec = '[%s] [%s] [%s] [%s] [%s] %s\n' % (
        _now(), direction,
        msg.get('from', '?'), msg.get('to', '?'),
        msg.get('type', '?'), msg.get('content', '').rstrip('\n'))
    atomic_append(path, rec)


class _Handler(socketserver.BaseRequestHandler):
    """每个连接一个 handler·单线程。
    One handler per connection · single-threaded."""
    def handle(self):
        buf = b''
        while True:
            try:
                data = self.request.recv(4096)
            except (ConnectionResetError, OSError):
                break
            if not data:
                break
            buf += data
            msgs, buf = decode_stream(buf)
            for m in msgs:
                _append_inbox(m, '收', root=getattr(self.server, 'root', None))
                # 广播回执 · broadcast acknowledgement
                if m.get('type') == 'broadcast':
                    ack = {'from': m.get('to'), 'to': m.get('from'),
                           'type': 'response', 'content': 'broadcast 已登记'}
                    try:
                        self.request.sendall(encode(ack))
                    except OSError:
                        pass


class AgentServer(socketserver.UnixStreamServer):
    """Unix socket 服务端·每 Agent 一个。
    Unix socket server · one per agent."""
    allow_reuse_address = True

    def __init__(self, agent_name, root=None):
        self.agent_name = agent_name
        self.root = root
        self.sock_path = sock_path(agent_name)
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        super().__init__(self.sock_path, _Handler)

    def server_close(self):
        super().server_close()
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass


def send(from_name, to_name, mtype, content, root=None):
    """客户端发送·返回 (ok, reply_or_error)。
    Client send · returns (ok, reply_or_error)."""
    msg = {'from': from_name, 'to': to_name, 'type': mtype, 'content': content}
    try:
        path = sock_path(to_name)
    except ValueError as exc:
        return False, str(exc)
    if not os.path.exists(path):
        return False, 'Agent %s 不在线（socket 不存在）' % to_name
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(path)
            s.sendall(encode(msg))
            # 等 reply（除非 notify） · wait for a reply (unless notify)
            if mtype == 'notify':
                _append_inbox(msg, '发', root=root)
                return True, 'notify 已送达'
            try:
                data = s.recv(4096)
                _append_inbox(msg, '发', root=root)
                if data:
                    msgs, _ = decode_stream(data)
                    if msgs:
                        return True, msgs[0]
                return True, None
            except socket.timeout:
                return True, '已送达·无回复（超时）'
    except OSError as e:
        return False, str(e)


def main():
    argv = list(sys.argv[1:])
    root = None
    if '--root' in argv:
        i = argv.index('--root')
        if i + 1 < len(argv):
            root = argv[i + 1]
            del argv[i:i + 2]
        else:
            print('--root 缺参数'); return 2
    if len(argv) < 1:
        print(__doc__); return 1
    cmd = argv[0]
    if cmd == 'serve' and len(argv) >= 2:
        name = argv[1]
        try:
            srv = AgentServer(name, root=root)
        except ValueError as exc:
            sys.stderr.write('%s\n' % exc)
            return 2
        print('Agent %s 监听 %s' % (name, srv.sock_path))
        print('消息卷 %s' % inbox_path(root))
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            srv.server_close()
            print('退出')
    elif cmd == 'send' and len(argv) >= 5:
        ok, reply = send(argv[1], argv[2], argv[3], argv[4], root=root)
        print('OK' if ok else 'FAIL', reply or '')
    elif cmd == 'tail':
        # 看消息卷 · view the message volume
        path = inbox_path(root)
        if not os.path.exists(path):
            print('（无）'); return 0
        from safeio import read_vol
        text, _enc, _why = read_vol(path)
        for line in text.splitlines():
            print(line.rstrip('\n'))
    else:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
