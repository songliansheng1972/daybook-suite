#!/bin/sh
# Daybook · 哨（sentinel）
# 职：不写，只看。监视你指定的卷，有变动就报。
#     —— 记的人与被记的人必须分开；钩子与签名都是写的人自己的机制，哨是第三方。
# 用法：
#   sh sentinel.sh 卷1.txt 卷2.txt ...   监视并常驻
#   sh sentinel.sh --one 卷1.txt         只查一次
# 日志：.sentinel.log
ROOT=$(cd "$(dirname "$0")" && pwd)
LOG="$ROOT/.sentinel.log"
ONE=0
[ "$1" = "--one" ] && ONE=1 && shift
[ $# -eq 0 ] && { echo "Usage: sh sentinel.sh [--one] volume-file..."; exit 1; }

sig() {                        # 每个卷的 字节数:mtime
  for f in "$@"; do
    if [ -f "$f" ]; then
      printf '%s:%s:%s ' "$f" "$(wc -c < "$f" | tr -d ' ')" "$(stat -f%m "$f" 2>/dev/null || stat -c%Y "$f")"
    fi
  done
}
report() {                     # 报：哪一卷动了、字节数、最后一条签发人
  for f in "$@"; do
    [ -f "$f" ] || continue
    n=$(wc -c < "$f" | tr -d ' ')
    last=$(grep -oE '^\[[0-9-]+ [0-9:]+]' "$f" | tail -1)
    who=$(tail -40 "$f" | grep -oE '^[^（(]{1,6}（' | tail -1 | tr -d '（')
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 变动 $f 字节 $n 最后条 $last 签发 ${who:-?}" >> "$LOG"
  done
}
last=$(sig "$@")
report "$@"
[ $ONE -eq 1 ] && exit 0
echo "Sentinel started, watching $# volume(s). Log: $LOG"
while :; do
  sleep 5
  cur=$(sig "$@")
  [ "$cur" != "$last" ] && { report "$@"; last="$cur"; }
done
