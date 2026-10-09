#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP Subscribe（W-DB-023-G2·新增·修复版 r2）
================================================
对照审核报告 P1+ 实现：
- resources/subscribe：客户端订阅指定卷
- 文件 mtime 轮询（零依赖·不引 watchdog）
- mtime 变 → 服务器主动 push notifications/resources/updated 到所有订阅该卷的客户端
- resources/unsubscribe：取消订阅
- 内存订阅表·不持久化（服务器重启即清·符合 MCP 协议）
- 零依赖：仅 Python 3 标准库（os/time/threading）
"""
import os, sys, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mcp_resources as _res
import mcp_transport as _tr


class SubscriptionManager:
    """订阅表 + 后台 watch 线程。
    每个 subscriber 用一个 callable push(msg) 表示"如何把消息送达客户端"。
    服务器侧的 push 通常是 write_message(outfile, msg)·由 mcp_server 注入。"""

    POLL_INTERVAL = 2.0  # 秒·mtime 轮询周期

    def __init__(self):
        self._lock = threading.Lock()
        # {uri: set(push_callable)}·内存表
        self._subs = {}
        # {uri: last_mtime}
        self._mtimes = {}
        self._thread = None
        self._stop = threading.Event()

    def subscribe(self, uri, push_callable):
        """订阅 uri·push_callable(msg) 用于推送。
        返回 True 表示新订阅·False 表示已订阅。"""
        with self._lock:
            subs = self._subs.setdefault(uri, set())
            if push_callable in subs:
                return False
            subs.add(push_callable)
            # 记初始 mtime·避免订阅瞬间触发推送
            self._mtimes.setdefault(uri, self._cur_mtime(uri))
        self._ensure_thread()
        return True

    def unsubscribe(self, uri, push_callable):
        """取消订阅。"""
        with self._lock:
            subs = self._subs.get(uri)
            if not subs:
                return False
            if push_callable not in subs:
                return False
            subs.discard(push_callable)
            if not subs:
                self._subs.pop(uri, None)
                self._mtimes.pop(uri, None)
            return True

    def unsubscribe_all(self, push_callable):
        """客户端断连·清掉它所有订阅。"""
        with self._lock:
            empty_uris = []
            for uri, subs in list(self._subs.items()):
                subs.discard(push_callable)
                if not subs:
                    empty_uris.append(uri)
            for uri in empty_uris:
                self._subs.pop(uri, None)
                self._mtimes.pop(uri, None)

    def _cur_mtime(self, uri):
        """取 uri 对应文件的 mtime·不存在返 None。"""
        if not uri.startswith('daybook://'):
            return None
        name = uri[len('daybook://'):]
        path = _res._vol_path(name)
        if not path or not os.path.exists(path):
            return None
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    def _ensure_thread(self):
        """启动后台 watch 线程·已启动则 no-op。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def _watch_loop(self):
        """后台轮询 mtime·变 → push notifications/resources/updated。"""
        while not self._stop.is_set():
            with self._lock:
                snapshot = list(self._subs.items())
            for uri, subs in snapshot:
                if not subs:
                    continue
                cur = self._cur_mtime(uri)
                if cur is None:
                    continue
                last = self._mtimes.get(uri)
                if last is not None and cur != last:
                    # 触发 push
                    self._mtimes[uri] = cur
                    msg = {
                        'jsonrpc': '2.0',
                        'method': 'notifications/resources/updated',
                        'params': {'uri': uri},
                    }
                    # 推到所有订阅者·单点失败不阻塞其他
                    dead = []
                    with self._lock:
                        subs_copy = list(subs)
                    for push in subs_copy:
                        try:
                            push(msg)
                        except Exception:
                            dead.append(push)
                    if dead:
                        with self._lock:
                            for p in dead:
                                subs.discard(p)
                else:
                    self._mtimes[uri] = cur
            time.sleep(self.POLL_INTERVAL)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def stats(self):
        """返回订阅统计·调试用。"""
        with self._lock:
            return {uri: len(subs) for uri, subs in self._subs.items()}


# 单例（模块级·mcp_server 注入到 dispatch）
MANAGER = SubscriptionManager()


def main():
    """CLI 调试：打印当前订阅状态。"""
    print('订阅统计：', MANAGER.stats())


if __name__ == '__main__':
    main()
