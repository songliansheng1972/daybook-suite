#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daybook · concurrency smoke test
Run 600 concurrent appends and verify that every record is complete exactly once.
This is an empirical test of the current local filesystem, not a POSIX PIPE_BUF
guarantee for regular files.
跑法：python3 daybook_test.py
退出码：0 = PASS，1 = FAIL。
"""
import os, sys, tempfile, subprocess, time
import re

NPROC = 20
NPER = 30
EXPECTED = NPROC * NPER  # 600


def run_concurrency_test(vol_path, append_path):
    """起 NPROC 进程各写 NPER 条，验证零交错。"""
    procs = []
    for i in range(1, NPROC + 1):
        author = 'p%d' % i
        for j in range(1, NPER + 1):
            msg = 'msg-%d-%d-body' % (i, j)
            procs.append(subprocess.Popen(
                [sys.executable, append_path, vol_path,
                 '并发', 'smoke', author, msg],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for p in procs:
        if p.wait() != 0:
            return False, '至少一个写入进程失败'
    return True, '所有写入进程成功'


def verify(vol_path):
    """数条目数、数 --- 分隔、验证每条完整性。"""
    with open(vol_path, encoding='utf-8') as f:
        content = f.read()
    record_re = re.compile(
        r'^\[[^\]]+\] \[并发\] \[smoke\] \[p(\d+)\] msg-(\d+)-(\d+)-body$',
        re.MULTILINE)
    records = record_re.findall(content)
    if len(records) != EXPECTED:
        return False, '完整记录数 = %d, 期望 %d' % (len(records), EXPECTED)
    seen = set()
    for process_id, author_id, message_id in records:
        if process_id != author_id or not 1 <= int(process_id) <= NPROC:
            return False, '记录作者与消息 ID 不匹配'
        key = (int(process_id), int(message_id))
        if not 1 <= key[1] <= NPER or key in seen:
            return False, '记录缺失或重复: %s' % (key,)
        seen.add(key)
    if len(seen) != EXPECTED:
        return False, '唯一记录数 = %d, 期望 %d' % (len(seen), EXPECTED)
    # Verify no partial/foreign non-empty lines were interleaved.
    valid_lines = len(records)
    actual_lines = sum(1 for line in content.splitlines() if line.strip())
    if actual_lines != valid_lines:
        return False, '非空行数 = %d, 完整记录数 = %d' % (actual_lines, valid_lines)
    return True, '完整、唯一记录 = %d' % len(seen)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    append_path = os.path.join(here, 'daybook_append.py')
    if not os.path.exists(append_path):
        print('找不到 daybook_append.py，请与本文件同目录。', file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        vol = os.path.join(tmp, 'test_卷.txt')
        t0 = time.time()
        ok, msg = run_concurrency_test(vol, append_path)
        elapsed = time.time() - t0
        verified, verify_msg = verify(vol)
        ok = ok and verified
        msg = '%s; %s' % (msg, verify_msg)
        print('=== 600 并发零交错烟雾测试 ===')
        print('  进程数 %d × 每进程 %d 条 = %d 条' % (NPROC, NPER, EXPECTED))
        print('  耗时 %.2fs' % elapsed)
        print('  %s' % msg)
        if ok:
            print('  PASS: 600 / 600 条完整，零交错 ✓')
            return 0
        else:
            print('  FAIL: %s ✗' % msg)
            return 1


if __name__ == '__main__':
    sys.exit(main())
