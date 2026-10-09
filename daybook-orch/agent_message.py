#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""Agent 间消息协议（W-DB-023-G3·第 4 项）
================================================
- 本地 Unix socket（Linux/macOS）或 TCP 回环（跨平台兜底）
- 消息格式：[from] [to] [type] [content]
  - type：notify/request/response/broadcast
- Agent A 写完卷 → notify Agent B
- 零依赖：仅用 Python 3 标准库（socketserver/socket/json/threading）

设计：
  - 每个 Agent 一个 socket 路径 /tmp/daybook_agent_<name>.sock
  - 消息以 '\n' 结尾·JSON 编码·单次 recv ≤ 65536
  - 服务端单线程接收·按 to 字段分发到 inbox 卷
  - inbox 卷 append-only：[时间] [收] [from] [to] [type] content

用法：
  # 服务端常驻
  python3 agent_message.py serve 汤姆
  # 客户端发消息
  python3 agent_message.py send 汤姆 史泰龙 notify "MCP resources/list 已实现"
"""
import os, sys, time, json, socket, socketserver, threading

HERE = os.path.dirname(os.path.abspath(__file__))

SOCK_DIR = '/tmp'
INBOX_VOL = os.path.join(HERE, '消息卷.txt')

MSG_TYPES = ('notify', 'request', 'response', 'broadcast')


def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def sock_path(agent_name):
    return os.path.join(SOCK_DIR, 'daybook_agent_%s.sock' % agent_name)


def encode(msg):
    """msg=dict{from,to,type,content}。返回 bytes（JSON + '\n'）。"""
    if not msg.get('type') in MSG_TYPES:
        raise ValueError('非法消息类型：%s' % msg.get('type'))
    return (json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8')


def decode_stream(buf):
    """从已收 buffer（bytes）里切出完整消息·返回 (list_of_msgs, remaining_buf)。
    按 b'\n' 切行后逐行 decode·避免多字节字符跨 recv 边界导致 UnicodeDecodeError。"""
    msgs = []
    while b'\n' in buf:
        line, buf = buf.split(b'\n', 1)
        if line.strip():
            try:
                msgs.append(json.loads(line.decode('utf-8')))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
    return msgs, buf


def _append_inbox(msg, direction='收'):
    """消息进 inbox 卷·append-only·白箱可审计。"""
    from safeio import atomic_append
    rec = '[%s] [%s] [%s] [%s] [%s] %s\n' % (
        _now(), direction,
        msg.get('from', '?'), msg.get('to', '?'),
        msg.get('type', '?'), msg.get('content', '').rstrip('\n'))
    atomic_append(INBOX_VOL, rec)


class _Handler(socketserver.BaseRequestHandler):
    """每个连接一个 handler·单线程。"""
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
                _append_inbox(m, '收')
                # 广播回执
                if m.get('type') == 'broadcast':
                    ack = {'from': m.get('to'), 'to': m.get('from'),
                           'type': 'response', 'content': 'broadcast 已登记'}
                    try:
                        self.request.sendall(encode(ack))
                    except OSError:
                        pass


class AgentServer(socketserver.UnixStreamServer):
    """Unix socket 服务端·每 Agent 一个。"""
    allow_reuse_address = True

    def __init__(self, agent_name):
        self.agent_name = agent_name
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


def send(from_name, to_name, mtype, content):
    """客户端发送·返回 (ok, reply_or_error)。"""
    msg = {'from': from_name, 'to': to_name, 'type': mtype, 'content': content}
    path = sock_path(to_name)
    if not os.path.exists(path):
        return False, 'Agent %s 不在线（socket 不存在）' % to_name
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(path)
            s.sendall(encode(msg))
            # 等 reply（除非 notify）
            if mtype == 'notify':
                _append_inbox(msg, '发')
                return True, 'notify 已送达'
            try:
                data = s.recv(4096)
                _append_inbox(msg, '发')
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
    if len(sys.argv) < 2:
        print(__doc__); return 1
    cmd = sys.argv[1]
    if cmd == 'serve' and len(sys.argv) >= 3:
        name = sys.argv[2]
        srv = AgentServer(name)
        print('Agent %s 监听 %s' % (name, srv.sock_path))
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            srv.server_close()
            print('退出')
    elif cmd == 'send' and len(sys.argv) >= 6:
        ok, reply = send(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
        print('OK' if ok else 'FAIL', reply or '')
    elif cmd == 'tail':
        # 看消息卷
        if not os.path.exists(INBOX_VOL):
            print('（无）'); return 0
        from safeio import read_vol
        text, _enc, _why = read_vol(INBOX_VOL)
        for line in text.splitlines():
            print(line.rstrip('\n'))
    else:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
