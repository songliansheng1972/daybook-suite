#!/usr/bin/env python3
"""
D 3.0 极简聊天室·后端
- 黑色 IDE 风格
- append-only 聊天室.txt
- 多角色: 汤姆/老宋/史泰龙
- 工单流转测试
"""
import http.server
import json
import os
import socketserver
from datetime import datetime
from urllib.parse import parse_qs

PORT = 8765
CHAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "聊天室.txt")
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatroom.html")


def append_chat(role, author, text):
    """原子 append 到聊天室.txt"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{role}] [{author}] {text}\n"
    with open(CHAT_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    return line


class ChatHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path.startswith("/read"):
            self._serve_chat()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/send":
            self._handle_send()
        else:
            self.send_error(404)

    def _serve_html(self):
        try:
            with open(HTML_FILE, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "chatroom.html not found")

    def _serve_chat(self):
        try:
            with open(CHAT_FILE, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            # 空聊天室
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()

    def _handle_send(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(body)
            role = data.get("role", "议")
            author = data.get("author", "匿名")
            text = data.get("text", "").strip()
            if not text:
                self.send_error(400, "empty text")
                return
            line = append_chat(role, author, text)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "line": line}).encode("utf-8"))
        except Exception as e:
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        # 静默日志
        pass


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    if not os.path.exists(CHAT_FILE):
        # 初始化聊天室·卷首
        append_chat("系统", "D3.0", "聊天室启动·黑色IDE风格·append-only持久")
        append_chat("系统", "D3.0", "参与者: 汤姆[判]/老宋[裁]/史泰龙[施]")

    print(f"D 3.0 极简聊天室·启动")
    print(f"  聊天室文件: {CHAT_FILE}")
    print(f"  HTML 文件: {HTML_FILE}")
    print(f"  端口: {PORT}")
    print(f"  浏览器打开: http://localhost:{PORT}/")
    print(f"  Ctrl+C 退出")

    with ReusableTCPServer(("127.0.0.1", PORT), ChatHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
