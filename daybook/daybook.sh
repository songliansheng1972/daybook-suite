#!/bin/sh
# Daybook · 起居注索引器（POSIX sh + awk）
# 只用 sh、awk、cat —— 凡有 Unix 的地方皆有。1970s 至今。
# 用法：sh daybook.sh [卷名=路径 ...]
#   不给参数则读 daybook.conf（若有）。
# 输出：开发卷/索引_<卷>卷.tsv 与 开发卷/volumes.md

OUT=开发卷
[ -d "$OUT" ] || mkdir -p "$OUT"
LIST=""
if [ $# -gt 0 ]; then
  for a in "$@"; do LIST="$LIST $a"; done
elif [ -f daybook.conf ]; then
  LIST=$(awk -F= '/^\[卷\]/{s=1;next} /^\[/{s=0} s&&NF==2&&$1!~/^#/{printf "%s=%s ",$1,$2}' daybook.conf)
fi
: > "$OUT/volumes.md"
echo "# 开发卷·卷首清单" >> "$OUT/volumes.md"
echo "" >> "$OUT/volumes.md"
echo "| 卷 | 条数 | 索引文件 |" >> "$OUT/volumes.md"
echo "|---|---|---|" >> "$OUT/volumes.md"
TOTAL=0
for pair in $LIST; do
  VOL=${pair%%=*}; PATHV=${pair#*=}
  [ -f "$PATHV" ] || continue
  IDF="$OUT/索引_${VOL}卷.tsv"
  printf '卷\t行号\t时间\t类\t标题\n' > "$IDF"
  awk -v vol="$VOL" '
    /^\[[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]\]/ {
      t=substr($0,2,16)
      rest=substr($0,20)
      cls=""; title=rest
      if (match(rest,/^ *\[[^]]*\] *\[[^]]*\]/)) {
        s=substr(rest,RSTART,RLENGTH)
        gsub(/^ *\[/,"",s); i=index(s,"]")
        cls=substr(s,1,i-1)
        s=substr(s,i+1); gsub(/^ *\[/,"",s); gsub(/\].*$/,"",s)
        title=s
      }
      gsub(/\t/," ",title)
      if (length(title)>60) title=substr(title,1,60)
      printf "%s\t%d\t%s\t%s\t%s\n", vol, NR, t, cls, title
    }' "$PATHV" >> "$IDF"
  N=$(awk 'END{print NR-1}' "$IDF")
  TOTAL=$((TOTAL+N))
  echo "| ${VOL}卷 | $N | 索引_${VOL}卷.tsv |" >> "$OUT/volumes.md"
  echo "  ${VOL}卷 $N 条"
done
echo "| **合计** | **$TOTAL** | |" >> "$OUT/volumes.md"
echo "合计 $TOTAL 条"
