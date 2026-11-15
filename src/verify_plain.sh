#!/bin/sh
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 手艺人老宋 <songliansheng@vip.sina.com>
# 明文人可读·可查验（裸终端版）：只依赖 POSIX sh + tail/grep/awk/od。
# Plain-text reading/verification (bare terminal): POSIX sh + tail/grep/awk/od only.
#
# 用法 / Usage:
#   sh verify_plain.sh 账卷.txt [索引/index_账.tsv]
# 退出码 / Exit: 0 = 完整性 OK; 1 = 有坏行/二进制/末行不完整/索引不一致; 2 = 用法错。
set -u

if [ $# -lt 1 ]; then
    echo "用法: sh verify_plain.sh <账卷.txt> [索引 TSV]"
    exit 2
fi
vol=$1
idx=${2:-}

if [ ! -f "$vol" ]; then
    echo "读不到账卷: $vol"
    exit 1
fi

if od -An -tx1 "$vol" | grep -q ' 00'; then
    bin=1
else
    bin=0
fi

res=$(awk '
BEGIN { n = 0; good = 0; bad = 0; bl = "" }
{
    n++
    s = $0
    if (s ~ /^\[[^]]*\] \[[^]]*\] \[[^]]*\] \[[^]]*\] /) {
        good++
        t = s
        sub(/^\[/, "", t); p = index(t, "]"); ts = substr(t, 1, p - 1); t = substr(t, p + 2)
        sub(/^\[/, "", t); p = index(t, "]"); cat = substr(t, 1, p - 1); t = substr(t, p + 2)
        sub(/^\[/, "", t); p = index(t, "]"); title = substr(t, 1, p - 1); t = substr(t, p + 2)
        sub(/^\[/, "", t); p = index(t, "]"); author = substr(t, 1, p - 1); t = substr(t, p + 2)
        body = t
    } else {
        bad++
        if (bl == "") bl = n; else bl = bl "," n
    }
}
END {
    printf "行数=%d 可解析=%d 坏行=%d", n, good, bad
    if (bad) printf " (行号 %s)", bl
    printf "\n"
    if (good) printf "最后一条：时间=%s 类别=%s 标题=%s 作者=%s\n正文：%s\n", ts, cat, title, author, body
    else print "最后一条：（空账本）"
    printf "BADCOUNT=%d\nGOODCOUNT=%d\n", bad, good
}' "$vol")

badmark=$(printf '%s\n' "$res" | grep '^BADCOUNT=')
bad=${badmark#BADCOUNT=}
goodmark=$(printf '%s\n' "$res" | grep '^GOODCOUNT=')
good=${goodmark#GOODCOUNT=}

nb=$(tail -c 1 "$vol" | od -An -c | tr -d ' \n')
if [ "$nb" = '\n' ]; then
    nl_ok=1
else
    nl_ok=0
fi

printf '%s\n' "$res" | grep -v '^BADCOUNT=' | grep -v '^GOODCOUNT='

index_ok=1
if [ -n "$idx" ]; then
    if [ -f "$idx" ]; then
        ic=$(awk 'NF { n++ } END { print n + 0 }' "$idx")
        if [ "$ic" = "$good" ]; then
            echo "索引: $idx 行数=$ic (账卷可解析 $good) 一致"
        else
            index_ok=0
            echo "索引: $idx 行数=$ic (账卷可解析 $good) 不一致"
        fi
    else
        index_ok=0
        echo "索引: 读不到 $idx"
    fi
fi

why=''
sep=''
if [ "$bin" = 1 ]; then why="$why${sep}含二进制字节"; sep='; '; fi
if [ "$bad" != 0 ]; then why="$why${sep}坏行 $bad"; sep='; '; fi
if [ "$nl_ok" = 0 ]; then why="$why${sep}末字节不是换行（最后一条可能被截断）"; sep='; '; fi
if [ "$index_ok" = 0 ]; then why="$why${sep}索引与账卷不一致"; sep='; '; fi

if [ -z "$why" ]; then
    echo "完整性：OK"
    echo "下一步：无需动作（账卷与索引一致；需要新条目请运行 daybook_append.py）"
    exit 0
fi
echo "完整性：BAD（${why}）"
echo "下一步：先备份账卷；坏行按行号人工修复，末字节补一个换行；索引重跑 daybook.py index"
exit 1
