#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
"""明文人可读 / 可查验 / 可追溯：只用标准库，直接读账本文件。
Plain-text reading and verification with the standard library only.

不导入任何 daybook 模块、不读 conf、不联网：只给一个账卷文件（可再给索引 TSV），
逐行按五段格式解析，打印最后一条记录的时间／类别／标题／作者，给出完整性结论与下一步动作。
No daybook module, no conf, no network: give it one volume file (optionally an index TSV) and it
parses the five-field line format, prints the last record's time/category/title/author, an
integrity conclusion, and the next action.

用法 / Usage:
  python3 verify_plain.py 账卷.txt
  python3 verify_plain.py 账卷.txt 索引/index_账.tsv
退出码：0 = 完整性 OK；1 = 有坏行/索引不一致；2 = 用法错。
"""
import os
import re
import sys

_LINE = re.compile(r'^\[([^\]]*)\] \[([^\]]*)\] \[([^\]]*)\] \[([^\]]*)\] (.*)$')


def main(argv):
    if len(argv) < 2:
        sys.stderr.write('用法：python3 verify_plain.py <账卷.txt> [索引 TSV]\n')
        return 2
    vol = argv[1]
    idx = argv[2] if len(argv) > 2 else None
    try:
        with open(vol, 'rb') as f:
            raw = f.read()
    except OSError as exc:
        sys.stderr.write('读不到账卷（%s）：%s\n' % (vol, exc))
        return 1
    binary = b'\x00' in raw
    text = raw.decode('utf-8', 'replace')
    lines = text.splitlines()
    good = []
    bad = []
    for i, line in enumerate(lines, 1):
        m = _LINE.match(line)
        if m:
            good.append((i, m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)))
        else:
            bad.append(i)
    print('账卷：%s' % os.path.abspath(vol))
    print('行数=%d 可解析=%d 坏行=%d%s' % (len(lines), len(good), len(bad),
                                          '' if not bad else '（行号 %s）'
                                          % ','.join(str(i) for i in bad[:5])))
    if good:
        ln, ts, cat, title, author, body = good[-1]
        print('最后一条：时间=%s 类别=%s 标题=%s 作者=%s' % (ts, cat, title, author))
        print('正文：%s' % body)
    else:
        print('最后一条：（空账本）')
    index_ok = True
    if idx:
        try:
            with open(idx, 'rb') as f:
                iraw = f.read()
            ilines = [x for x in iraw.decode('utf-8', 'replace').splitlines() if x.strip()]
            same = len(ilines) == len(good)
            index_ok = same
            print('索引：%s 行数=%d（账卷可解析 %d）·%s'
                  % (os.path.abspath(idx), len(ilines), len(good),
                     '一致' if same else '不一致（差 %d）' % (len(ilines) - len(good))))
        except OSError as exc:
            index_ok = False
            print('索引：读不到（%s）' % exc)
    ok = not binary and not bad and index_ok
    print('完整性：%s' % ('OK' if ok else 'BAD（%s）'
                      % ('含二进制字节; ' if binary else '')
                      + ('坏行 %d; ' % len(bad) if bad else '')
                      + ('' if index_ok else '索引与账卷不一致')))
    if ok:
        print('下一步：无需动作（账卷与索引一致；需要新条目请运行 daybook_append.py）')
    elif bad or binary:
        print('下一步：先人工检查上方坏行/二进制位置，再运行 daybook.py index 重建索引')
    else:
        print('下一步：运行 daybook.py index 重建索引（账卷本身可解析）')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
