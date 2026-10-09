#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保存一条逐字消息/代码原件，并把其路径与摘要登记到 DAYBOOK。"""
import argparse
import hashlib
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def record(role, title, content, stamp=None, update_index=True):
    if not content:
        raise ValueError('拒绝记录空内容')

    archive_dir = os.path.join(HERE, '对话原件')
    os.makedirs(archive_dir, exist_ok=True)
    stamp = stamp or time.strftime('%Y%m%d_%H%M%S')
    digest = hashlib.sha256(content).hexdigest()
    safe_title = ''.join(
        ch if ch.isalnum() or ch in '-_' else '_' for ch in title
    ).strip('_')[:48] or '未命名'
    name = '%s_%s_%s_%s.txt' % (stamp, role, safe_title, digest[:12])
    archive_path = os.path.join(archive_dir, name)
    relative_path = os.path.relpath(archive_path, HERE)

    # Each original is a separate UTF-8 artifact; write through a temporary
    # file so an interrupted write cannot leave a half-written final artifact.
    temporary_path = archive_path + '.tmp'
    with open(temporary_path, 'xb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary_path, archive_path)

    entry_title = '%s %s' % (role, stamp)
    reference = '%s\nSHA256: %s' % (relative_path, digest)
    append_script = os.path.join(HERE, 'daybook_append.py')
    result = subprocess.run(
        [sys.executable, append_script, os.path.join(HERE, '对话卷.txt'),
         '对话', entry_title, reference],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode:
        raise RuntimeError(
            '原件已保存，但对话卷登记失败：%s%s' %
            (result.stdout, result.stderr)
        )

    index_output = ''
    if update_index:
        index_script = os.path.join(HERE, 'daybook.py')
        result = subprocess.run(
            [sys.executable, index_script, 'index'],
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if result.returncode:
            raise RuntimeError(
                '原件和对话卷已保存，但索引更新失败：%s%s' %
                (result.stdout, result.stderr)
            )
        index_output = result.stdout
    return relative_path, digest, index_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True,
                        choices=('用户', '助手', '实验代码'))
    parser.add_argument('--title', default='对话')
    parser.add_argument('--timestamp',
                        help='原始时间，格式 YYYYMMDD_HHMMSS；用于历史补录')
    parser.add_argument('--no-index', action='store_true',
                        help='批量补录时暂不更新索引')
    args = parser.parse_args()
    content = sys.stdin.buffer.read()
    try:
        if args.timestamp:
            time.strptime(args.timestamp, '%Y%m%d_%H%M%S')
        path, digest, index_output = record(
            args.role, args.title, content, args.timestamp, not args.no_index)
    except (OSError, ValueError, RuntimeError) as exc:
        print('记录失败：%s' % exc, file=sys.stderr)
        return 1
    print('原件已保存：%s' % path)
    print('SHA256：%s' % digest)
    print(index_output, end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
