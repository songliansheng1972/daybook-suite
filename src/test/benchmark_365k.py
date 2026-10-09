#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducible local full-read and index benchmark for a one-year daybook."""
import os
import platform
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daybook


RECORDS = 365000
RECORD_BYTES = 117
HEADER = '[2026-01-01 00:00] [实验] [记录 %06d]\n'
BODY_PREFIX = '正文 '.encode('utf-8')


def create_volume(path):
    header_bytes = HEADER % 0
    prefix = header_bytes.encode('utf-8') + BODY_PREFIX
    padding = RECORD_BYTES - len(prefix) - 1
    if padding < 0:
        raise ValueError('Record template exceeds target record size')
    with open(path, 'wb') as volume:
        for number in range(RECORDS):
            volume.write((HEADER % number).encode('utf-8'))
            volume.write(BODY_PREFIX)
            volume.write(b'x' * padding)
            volume.write(b'\n')
    return os.path.getsize(path)


def make_conf():
    return {
        '卷': {'年度基准': '365k.txt'},
        '条目': {
            '头正则': r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]',
            '标正则': r'^\[[^\]]+\]\s*\[([^\]]+)\]\s*\[([^\]]*)\]',
            '字段': '卷,行号,时间,类,标题',
        },
        '规则': {'类': 'tag:1', '标题': 'tag:2'},
        '索引': {
            '输出目录': '开发卷',
            '索引前缀': '索引_',
            '清单名': 'volumes.md',
        },
        '触发': {'增量索引': '是'},
    }


def verify_index(path):
    with open(path, encoding='utf-8') as index_file:
        header = next(index_file).rstrip('\n').split('\t')
        if header != ['卷', '行号', '时间', '类', '标题']:
            raise AssertionError('Unexpected index header: %r' % header)
        count = 0
        for count, line in enumerate(index_file, 1):
            columns = line.rstrip('\n').split('\t')
            expected = [
                '年度基准',
                str((count - 1) * 2 + 1),
                '2026-01-01 00:00',
                '实验',
                '记录 %06d' % (count - 1),
            ]
            if columns != expected:
                raise AssertionError(
                    'Index mismatch at record %d: %r != %r' % (count, columns, expected))
        return count


def main():
    with tempfile.TemporaryDirectory(prefix='daybook-365k-') as root:
        source = os.path.join(root, '365k.txt')
        size = create_volume(source)
        expected_size = RECORDS * RECORD_BYTES
        if size != expected_size:
            raise AssertionError('Expected %d bytes, got %d' % (expected_size, size))

        start = time.perf_counter()
        with open(source, 'rb') as volume:
            contents = volume.read()
        newline_count = contents.count(b'\n')
        full_read_seconds = time.perf_counter() - start
        if len(contents) != expected_size or newline_count != RECORDS * 2:
            raise AssertionError('Full-read validation failed')
        del contents

        build_seconds = []
        conf = make_conf()
        index_path = os.path.join(root, '开发卷', '索引_年度基准卷.tsv')
        cursor_path = os.path.join(root, '开发卷', '.游标_年度基准.json')
        for _ in range(3):
            for path in (index_path, cursor_path):
                if os.path.exists(path):
                    os.remove(path)
            start = time.perf_counter()
            per_volume, total, _report = daybook.build(conf, root)
            build_seconds.append(time.perf_counter() - start)
            if total != RECORDS or per_volume.get('年度基准') != RECORDS:
                raise AssertionError('Index count mismatch: %r, total=%d' % (per_volume, total))

        indexed_rows = verify_index(index_path)
        if indexed_rows != RECORDS:
            raise AssertionError('Expected %d index rows, got %d' % (RECORDS, indexed_rows))
        index_size = os.path.getsize(index_path)

        print('Host: %s; %s' % (platform.platform(), platform.processor()))
        print('Python: %s' % sys.version.split()[0])
        print('Records: %d; source bytes: %d (%.3f MB, %.3f MiB)' % (
            RECORDS, size, size / 1000000.0, size / (1024.0 * 1024.0)))
        print('Full read + newline validation: %.3f s (%d bytes, %d newlines)' % (
            full_read_seconds, size, newline_count))
        print('Full index build: min %.3f s; median %.3f s; max %.3f s' % (
            min(build_seconds), statistics.median(build_seconds), max(build_seconds)))
        print('Index verification: %d rows, all fields checked (PASS); index bytes: %d' % (
            indexed_rows, index_size))


if __name__ == '__main__':
    main()
