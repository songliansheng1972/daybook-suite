#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""签名代理审计的外部核对器（独立于代理进程，4.0.7 随包）。
=========================================================
不只信审计自己：每条成功记录都用两处产品侧证据复核——
  1) 产品签名边车 MCP签名边车.jsonl 的指定行（sha 必须一致，payload 必须一致，
     且能用本机密钥独立验签 HMAC-SHA256）；
  2) append 类另有账本卷的指定行（sha 必须一致，正文必须对得上）。
另外核对 prev/self 哈希链与 audit.head。

用法：python3 verify_audit.py [--base ~/.daybook-mailroom] [--root LEDGER]
输出只含指纹前缀，不打印密钥。
"""
import argparse
import hashlib
import hmac
import json
import os
import sys

ZERO = '0' * 64


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def sha(s):
    if isinstance(s, str):
        s = s.encode('utf-8')
    return hashlib.sha256(s).hexdigest()


def line_at(path, n):
    try:
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if i == n:
                    return line.rstrip('\n')
    except FileNotFoundError:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=os.path.expanduser('~/.daybook-mailroom'))
    ap.add_argument('--root', default=None, help='账本根，默认 <base>/ledger')
    a = ap.parse_args()
    base = os.path.abspath(os.path.expanduser(a.base))
    root = os.path.abspath(a.root or os.path.join(base, 'ledger'))
    audit = os.path.join(base, 'audit', 'sign_audit.jsonl')
    head_path = os.path.join(base, 'audit', 'audit.head')
    sidecar_path = os.path.join(root, 'MCP签名边车.jsonl')

    bad = []
    rows = []
    try:
        with open(audit, encoding='utf-8') as f:
            for n, line in enumerate(f, 1):
                try:
                    rows.append((n, json.loads(line)))
                except json.JSONDecodeError:
                    bad.append('audit L%d：不是合法 JSON' % n)
    except FileNotFoundError:
        print('审计行：0 ｜ 断链/锚点问题：1')
        print('  ✗ 审计文件不存在：%s' % audit)
        return 1

    prev = ZERO
    for n, rec in rows:
        if rec.get('prev') != prev:
            bad.append('audit L%d：prev 断链' % n)
        body = {k: v for k, v in rec.items() if k != 'self'}
        if sha(canon(body)) != rec.get('self'):
            bad.append('audit L%d：self 哈希不符' % n)
        prev = rec.get('self')
        if rec.get('result') != 'ok':
            continue

        # 1) 产品签名边车锚点
        sl = rec.get('sidecar_line')
        line = line_at(sidecar_path, sl) if sl else None
        if line is None:
            bad.append('audit L%d：sidecar 行不存在（%s）' % (n, sl))
        else:
            if sha(line) != rec.get('sidecar_sha256'):
                bad.append('audit L%d：sidecar 行 sha 不符' % n)
            try:
                sc = json.loads(line)
            except Exception:
                sc = {}
                bad.append('audit L%d：sidecar 行不是 JSON' % n)
            if sha(sc.get('payload', '')) != rec.get('payload_sha256'):
                bad.append('audit L%d：sidecar payload hash 不符' % n)
            if sc.get('agent_id') != rec.get('agent_id'):
                bad.append('audit L%d：sidecar agent 不符' % n)
            if sc.get('tool') != rec.get('tool'):
                bad.append('audit L%d：sidecar tool 不符' % n)
            key_path = os.path.join(root, '.daybook_keys',
                                    rec.get('agent_id', '') + '.key')
            try:
                key = open(key_path, encoding='utf-8').read().strip()
            except FileNotFoundError:
                key = ''
            if not key:
                bad.append('audit L%d：密钥缺失，无法独立验签' % n)
            else:
                if sha(key)[:8] != rec.get('key_fp'):
                    bad.append('audit L%d：密钥指纹不符' % n)
                want = hmac.new(key.encode(), sc.get('payload', '').encode(),
                                hashlib.sha256).hexdigest()
                if not hmac.compare_digest(want, sc.get('signature', '')):
                    bad.append('audit L%d：边车签名验签失败' % n)

        # 2) append 的账本行锚点（遍历卷表，找到 sha 相符的那一行）
        if rec.get('tool') == 'daybook_append':
            ll = rec.get('ledger_line')
            conf = os.path.join(root, 'daybook.conf')
            found = None
            try:
                with open(conf, encoding='utf-8') as f:
                    sec = None
                    for ln in f:
                        ln = ln.strip()
                        if ln.startswith('[') and ln.endswith(']'):
                            sec = ln[1:-1]
                        elif sec == 'volumes' and '=' in ln and not ln.startswith(('#', ';')):
                            k, v = ln.split('=', 1)
                            p = v.strip()
                            p = p if os.path.isabs(p) else os.path.join(root, p)
                            text = line_at(p, ll) if ll else None
                            if text and sha(text) == rec.get('ledger_sha256'):
                                found = (p, text)
                                break
            except FileNotFoundError:
                pass
            if not found:
                bad.append('audit L%d：找不到与 ledger_sha256 相符的账本行（L%s）'
                           % (n, ll))
            else:
                text = found[1]
                payload = sc.get('payload', '') if line else ''
                if 'content=' in payload:
                    content = payload.split('content=', 1)[1]
                    if content and content not in text:
                        bad.append('audit L%d：账本行正文与 payload 不符' % n)

    head = {}
    try:
        head = json.load(open(head_path, encoding='utf-8'))
    except FileNotFoundError:
        bad.append('audit.head 缺失')
    if head:
        if head.get('lines') != len(rows):
            bad.append('audit.head 行数不符：%s != %s' % (head.get('lines'), len(rows)))
        if rows and head.get('last') != rows[-1][1].get('self'):
            bad.append('audit.head 末哈希不符')

    print('审计行：%d ｜ 断链/锚点问题：%d' % (len(rows), len(bad)))
    for b in bad:
        print('  ✗', b)
    if not bad:
        print('  ✓ 哈希链、head、产品边车锚点、账本行锚点、HMAC 验签全部通过')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
