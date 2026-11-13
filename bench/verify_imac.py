#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立复核 iMac 回包：整行严格解析 + 逐条校验位 + 逐写者序号覆盖。
用法：
  python3 verify_imac.py <卷文件> [--writers N]
不依赖回包里的 load.py，按报告公开的记录规格独立实现。
"""
import argparse
import collections
import hashlib
import json
import re
import sys

HEAD = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([^\]]*)\] \[([^\]]*)\] \[([^\]]*)\] (.*)$')
BODY_PAD = re.compile(r'^msg-w(\d+)-(\d+)-([0-9a-f]{8})(?:-(x*))?-body$')
BODY = re.compile(r'^msg-w(\d+)-(\d+)-([0-9a-f]{8})-body$')


def tag_of(w, s):
    return hashlib.md5(('w%d-%d' % (w, s)).encode()).hexdigest()[:8]


def verify(path):
    lines = bad_head = bad_body = bad_sum = 0
    counts = collections.Counter()
    seqs = collections.defaultdict(list)
    max_line = 0
    with open(path, encoding='utf-8') as f:
        for raw in f:
            line = raw.rstrip('\n')
            if not line:
                continue
            lines += 1
            max_line = max(max_line, len(line.encode('utf-8')))
            m = HEAD.match(line)
            if not m:
                bad_head += 1
                continue
            author, body = m.group(4), m.group(5)
            b = BODY_PAD.match(body)     # 允许超 PIPE_BUF 的 x 填充
            if not b:
                bad_body += 1
                continue
            w, s, tag = int(b.group(1)), int(b.group(2)), b.group(3)
            counts[w] += 1
            seqs[w].append(s)
            if author != 'w%d' % w:
                bad_head += 1
            if tag != tag_of(w, s):
                bad_sum += 1
    dups = sum(len(v) - len(set(v)) for v in seqs.values())
    disorder = sum(1 for v in seqs.values() for a, b in zip(v, v[1:]) if b <= a)
    out = {
        'file': path, 'lines': lines, 'records': sum(counts.values()),
        'writers': len(counts), 'bad_head': bad_head, 'bad_body': bad_body,
        'bad_sum': bad_sum, 'dup': dups, 'order_violations': disorder,
        'counts': dict(sorted(counts.items())), 'max_line_bytes': max_line,
        'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest(),
        'pass_strict': bad_head == 0 and bad_body == 0 and bad_sum == 0
                       and dups == 0 and disorder == 0,
    }
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('volume')
    ap.add_argument('--counts', action='store_true', help='输出逐写者条数')
    a = ap.parse_args()
    r = verify(a.volume)
    if not a.counts:
        r.pop('counts')
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r['pass_strict'] else 1)
