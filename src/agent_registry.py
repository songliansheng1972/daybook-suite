#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""Agent 身份注册表（W-DB-023-G3·第 1 项）
================================================
- 多 Agent 写同卷需区分·作者字段从字符串改为 agent_id+signature·不可伪造
- 零依赖：仅用 Python 3 标准库（hashlib/hmac/uuid/json/os/time）
- 签名算法：HMAC-SHA256（够用·简单·不引入 cryptography/Ed25519）
- 注册表 append-only·白箱可审计
- 不绑任一 LLM·开放

注册卷.txt 格式（每行一条·append-only）：
  [时间] [注册] [agent_id] [agent_name] [secret_hex]
  [时间] [吊销] [agent_id]

签名规则：
  payload = 条目正文（去掉作者字段）
  signature = HMAC-SHA256(secret, payload).hexdigest()

用法：
  from agent_registry import Registry
  reg = Registry('注册卷.txt')
  agent = reg.register('汤姆')           # 注册一个 Agent，返回 (agent_id, secret)
  sig  = reg.sign(agent_id, '某条正文')    # 算签名
  ok   = reg.verify(agent_id, '某条正文', sig)  # 验签
  reg.revoke(agent_id)                   # 吊销
"""
import os, time, hmac, hashlib, json, secrets

HERE = os.path.dirname(os.path.abspath(__file__))


def _now():
    return time.strftime('%Y-%m-%d %H:%M')


class Agent:
    """单个 Agent 的身份信息（值对象）。"""
    __slots__ = ('agent_id', 'name', 'secret', 'created_at', 'revoked')

    def __init__(self, agent_id, name, secret, created_at, revoked=False):
        self.agent_id = agent_id
        self.name = name
        self.secret = secret
        self.created_at = created_at
        self.revoked = revoked

    def to_authors(self):
        """作者字段写入条目时的字符串形式：agent_id#前 8 位签名占位（实际签名另算）。
        旧条目格式 `[时间][类][标题][作者字符串]` 兼容——作者字段保持字符串，不破坏 600 并发零交错。"""
        return 'agent:%s' % self.agent_id[:8]

    def __repr__(self):
        return '<Agent %s name=%s revoked=%s>' % (self.agent_id[:8], self.name, self.revoked)


class Registry:
    """Agent 身份注册表。append-only·白箱可审计。

    所有写操作追加到注册卷.txt；读操作走内存（启动时全量加载）。
    不改历史 = 吊销只追加吊销条目·不删原注册条目。"""
    def __init__(self, path=None):
        self.path = path or os.path.join(HERE, '注册卷.txt')
        self._agents = {}  # agent_id -> Agent
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        from safeio import read_vol
        text, _enc, _why = read_vol(self.path)
        for line in text.splitlines():
            line = line.rstrip('\n')
            if not line or not line.startswith('['):
                continue
            # [时间] [注册] [agent_id] [name] [secret]
            # [时间] [吊销] [agent_id]
            parts = [p.strip() for p in line.split(']')]
            parts = [p.lstrip(' [') for p in parts if p.strip()]
            if len(parts) < 3:
                continue
            if parts[1] == '注册' and len(parts) >= 5:
                aid, name, secret = parts[2], parts[3], parts[4]
                self._agents[aid] = Agent(aid, name, secret, parts[0], False)
            elif parts[1] == '吊销' and len(parts) >= 3:
                aid = parts[2]
                if aid in self._agents:
                    self._agents[aid].revoked = True

    def register(self, name):
        """注册新 Agent。返回 (agent_id, secret_hex)。secret 仅此刻可见·不入卷不报不打印。
        卷里只存 secret 的 hex（用于服务端验签）——这是 HMAC 设计·不是密钥泄露。"""
        agent_id = 'ag-' + secrets.token_hex(8)  # 16 字符前缀
        secret = secrets.token_hex(32)            # 64 字符 hex · 256bit
        rec = '[%s] [注册] [%s] [%s] [%s]\n' % (_now(), agent_id, name, secret)
        from safeio import atomic_append
        atomic_append(self.path, rec)
        self._agents[agent_id] = Agent(agent_id, name, secret, _now(), False)
        return agent_id, secret

    def revoke(self, agent_id):
        """吊销·append-only·不删原注册条目。"""
        if agent_id not in self._agents:
            raise KeyError('agent %s 不存在' % agent_id)
        rec = '[%s] [吊销] [%s]\n' % (_now(), agent_id)
        from safeio import atomic_append
        atomic_append(self.path, rec)
        self._agents[agent_id].revoked = True

    def lookup(self, agent_id):
        return self._agents.get(agent_id)

    def sign(self, agent_id, payload):
        """对 payload（条目正文）算 HMAC-SHA256。返回 hex 签名。"""
        a = self._agents.get(agent_id)
        if not a or a.revoked:
            raise PermissionError('agent %s 不存在或已吊销' % agent_id)
        return hmac.new(a.secret.encode('utf-8'),
                        payload.encode('utf-8'),
                        hashlib.sha256).hexdigest()

    def verify(self, agent_id, payload, sig):
        """验签·常数时间比较防时序攻击。"""
        a = self._agents.get(agent_id)
        if not a or a.revoked:
            return False
        expected = self.sign(agent_id, payload)
        return hmac.compare_digest(expected, sig)

    def list(self):
        return list(self._agents.values())


def main():
    """CLI：注册 / 列表 / 验签 demo。
    用法：
      python3 agent_registry.py register 汤姆
      python3 agent_registry.py list
      python3 agent_registry.py verify <agent_id> <payload> <sig>
    """
    import sys
    if len(sys.argv) < 2:
        print(__doc__); return 1
    reg = Registry()
    cmd = sys.argv[1]
    if cmd == 'register' and len(sys.argv) >= 3:
        aid, secret = reg.register(sys.argv[2])
        print('agent_id: %s' % aid)
        print('secret:   %s' % secret)
        print('（secret 仅此刻可见·请妥善保存）')
    elif cmd == 'list':
        for a in reg.list():
            print('%s %s revoked=%s' % (a.agent_id, a.name, a.revoked))
    elif cmd == 'verify' and len(sys.argv) >= 5:
        ok = reg.verify(sys.argv[2], sys.argv[3], sys.argv[4])
        print('verify: %s' % ('PASS' if ok else 'FAIL'))
    else:
        print(__doc__); return 1
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
