#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""压测公共件（随包带走版）：路径、规格、清单。
Bench common (portable): paths, record spec, manifest helpers.

★ 本文件是「期望记录」的独立规格实现；写入侧调被测件的
  daybook_append.append_one()。两边对不上 => 判红。
"""
import hashlib
import hmac
import json
import os
import sys
import sysconfig

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get('DBB_DATA', os.path.join(os.path.expanduser('~'), 'daybook-bench-data'))
VOL_DIR = os.path.join(DATA_ROOT, 'vol')
VOLUME = os.path.join(VOL_DIR, '压测卷.txt')
ROOT_ORCH = os.path.join(DATA_ROOT, 'run', 'orch')
ROOT_DB = os.path.join(DATA_ROOT, 'run', 'db')
MANIFEST_DIR = os.path.join(DATA_ROOT, 'manifest')
STATE_DIR = os.path.join(DATA_ROOT, 'state')
AGENTS_JSON = os.path.join(STATE_DIR, 'agents.json')

PIPE_BUF = 512
SIG_SCHEME = 'daybook-orch-entry-v1'
KIND = '压测'
NOW = '2026-11-14 00:00:00'


def sp_dir():
    """当前 venv 的 site-packages（随包带走版：由运行解释器自报，不写死 3.14）。"""
    return sysconfig.get_paths()['purelib']


def payload(name):
    return {'suite': os.path.join(sp_dir(), 'daybook_suite', 'payload'),
            'orch': os.path.join(sp_dir(), 'daybook_orch', 'payload'),
            'mcp': os.path.join(sp_dir(), 'daybook_mcp', 'payload')}[name]


def title(seq):
    return 'bench-%07d' % seq


def eid(seq):
    return 'm%016x' % seq


def body(seq, wid):
    plan = hashlib.sha256(('w%d|%d' % (wid, seq)).encode('utf-8')).hexdigest()[:16]
    return 'SEQ=%d PLAN=%s' % (seq, plan)


def payload_text(seq, wid, aid):
    return '\n'.join([SIG_SCHEME, NOW, KIND, title(seq), aid, '', eid(seq), '', body(seq, wid)])


def sign(seq, wid, aid, secret):
    return hmac.new(secret.encode('utf-8'), payload_text(seq, wid, aid).encode('utf-8'),
                    hashlib.sha256).hexdigest()


def record(seq, wid, aid, secret):
    return ('[%s] [%s] [%s] [%s] [id=%s] [sig=%s] %s\n\n'
            % (NOW, KIND, title(seq), aid, eid(seq), sign(seq, wid, aid, secret), body(seq, wid)))


def record_no_tail(seq, wid, aid, secret):
    return record(seq, wid, aid, secret)[:-2]


def writer_of(seq, writers, start=1):
    return (seq - start) % writers


def load_agents():
    with open(AGENTS_JSON, encoding='utf-8') as f:
        return json.load(f)


def agent_of(wid, agents):
    a = agents[str(wid)]
    return a['aid'], a['secret']


def manifest_path(name):
    return os.path.join(MANIFEST_DIR, 'manifest_%s.bin' % name)


def manifest_meta(name):
    return os.path.join(MANIFEST_DIR, 'manifest_%s.json' % name)


def ensure_dirs():
    for d in (DATA_ROOT, VOL_DIR, ROOT_ORCH, ROOT_DB, MANIFEST_DIR, STATE_DIR):
        os.makedirs(d, exist_ok=True)


CONF_ENTRIES = """[entries]
head_regex=^(?:\\[#\\d+\\][ ]*)?\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}(?::\\d{2})?)\\]
extra_head_regex=
tag_regex=^(?:\\[#\\d+\\][ ]*)?\\[\\d{4}[^\\]]*\\][ ]*\\[([^\\]]+)\\][ ]*\\[([^\\]]*)\\](?:[ ]*\\[([^\\]]*)\\])?
fields=volume,line,time,category,title,author

[rules]
category=tag:1
title=tag:2
author=tag:3

[index]
root=
out_dir=
index_prefix=index_
manifest=volumes.md

[trigger]
auto_index=是
incremental=是

[multilevel]
multilevel_enabled=是
out_dir=
level2_field=category
"""


def write_confs():
    """两个根：orch 写卷根、daybook 索引根；卷文件同一份（相对路径指到 vol/）。"""
    ensure_dirs()
    with open(os.path.join(ROOT_ORCH, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[volumes]\nledger=../../vol/压测卷.txt\n\n' + CONF_ENTRIES)
    with open(os.path.join(ROOT_DB, 'daybook.conf'), 'w', encoding='utf-8') as f:
        f.write('[volumes]\n压测=../../vol/压测卷.txt\n\n' + CONF_ENTRIES)
