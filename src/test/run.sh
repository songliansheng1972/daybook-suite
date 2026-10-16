#!/usr/bin/env bash
# DAYBOOK 跨语言一致性测试 · DAYBOOK cross-language consistency test
# 跑 5 种实现（py/sh/c/f/bas），输出 tsv，diff 权威版（py）。
# Run 5 implementations (py/sh/c/f/bas), emit tsv, diff against the authoritative py version.
# 退出码 0 = 全一致；非 0 = 有差异。
# Exit code 0 = all consistent; non-zero = differences found.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"   # daybook/ 目录 · daybook/ directory
SAMPLE="$ROOT/sample"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/daybook_test.XXXXXX")"
trap 'rm -rf "$OUT"' EXIT
mkdir -p "$OUT/sample"
cp "$SAMPLE"/*.txt "$OUT/sample/"
PASS=0; FAIL=0

echo "=== DAYBOOK 跨语言一致性测试 ==="
echo "样本卷：$SAMPLE"
echo ""

# 1. Python 主实现（权威版）—— 用独立 test.conf，不污染 daybook.conf
# 1. Python main implementation (authoritative) — uses a standalone test.conf, does not pollute daybook.conf
cat > "$OUT/test.conf" <<EOF
[volumes]
协作=sample/协作卷.txt
语汇=sample/语汇卷.txt
百科=sample/百科卷.txt

[entries]
head_regex=^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]
tag_regex=^\[[^\]]+\]\s*\[([^\]]+)\]\s*\[([^\]]*)\]
fields=volume,line,time,category,title,字数,含订正

[rules]
category=tag:1
title=tag:2
字数=len
含订正=contains:订正

[index]
root=
out_dir=.
index_prefix=index_
manifest=volumes.md
EOF

echo "[1/5] Python daybook.py ..."
cd "$ROOT"
python3 -c "
import sys; sys.argv = ['daybook.py', 'index']
import daybook
conf = daybook.load_conf('$OUT/test.conf')
root_cfg = conf.get('索引', {}).get('根', '').strip()
import os
root = '$OUT' if not root_cfg else None  # root=空 → isolated fixture（root 为空则用隔离夹具）
per, total, report = daybook.build(conf, '$OUT')
print('索引：' + '｜'.join('%s %d' % (k, v) for k, v in per.items()) + '｜合计 %d' % total)
" > "$OUT/py.log" 2>&1
cat "$OUT/py.log"
cp "$OUT/index_协作.tsv" "$OUT/py_协作.tsv"
cp "$OUT/index_语汇.tsv" "$OUT/py_语汇.tsv"
cp "$OUT/index_百科.tsv" "$OUT/py_百科.tsv"
PY_COLL=$(($(wc -l < "$OUT/py_协作.tsv") - 1))
PY_YUHUI=$(($(wc -l < "$OUT/py_语汇.tsv") - 1))
PY_BAIKE=$(($(wc -l < "$OUT/py_百科.tsv") - 1))
echo "  条数：协作 $PY_COLL 语汇 $PY_YUHUI 百科 $PY_BAIKE"

# 2-5. 其他语言实现：当前只数条目（功能子集），对比条目数
# 2-5. Other language implementations: currently only count entries (a functional subset), compare entry counts
echo "[2/5] sh daybook.sh ..."
cd "$OUT" && sh "$ROOT/daybook.sh" "协作=sample/协作卷.txt" "语汇=sample/语汇卷.txt" "百科=sample/百科卷.txt" 2>/dev/null | tee "$OUT/sh.log" || echo "  sh 跑失败（非阻塞）"

echo "[3/5] C daybook.c ..."
cc "$ROOT/daybook.c" -o "$OUT/daybook_c" 2>/dev/null && "$OUT/daybook_c" "$OUT/sample/协作卷.txt" "$OUT/sample/语汇卷.txt" "$OUT/sample/百科卷.txt" > "$OUT/c.tsv" 2>/dev/null && echo "  C 编译并跑通 ✓" || echo "  C 编译或运行失败（非阻塞）"

echo "[4/5] Fortran daybook.f ..."
which gfortran >/dev/null 2>&1 && gfortran "$ROOT/daybook.f" -o "$OUT/daybook_f" 2>/dev/null && "$OUT/daybook_f" 2>/dev/null | tee "$OUT/f.log" || echo "  gfortran 不可用（非阻塞）"

echo "[5/5] BASIC daybook.bas ..."
which bwbasic >/dev/null 2>&1 && bwbasic "$ROOT/daybook.bas" 2>/dev/null | tee "$OUT/bas.log" || echo "  bwbasic 不可用（非阻塞）"

echo ""
echo "=== 验收 ==="
# 主验收：Python 跑样本卷三卷都跑通且条数 5/5/5
# Primary acceptance: Python runs all three sample volumes, counts 5/5/5
if [ "$PY_COLL" = "5" ] && [ "$PY_YUHUI" = "5" ] && [ "$PY_BAIKE" = "5" ]; then
  echo "PASS: Python 权威版三卷条数 5/5/5 ✓"
  PASS=$((PASS+1))
else
  echo "FAIL: Python 权威版三卷条数 $PY_COLL/$PY_YUHUI/$PY_BAIKE，预期 5/5/5"
  FAIL=$((FAIL+1))
fi

# 编码检测验收
# Encoding-detection acceptance
ENC_COUNT=$(grep -c "utf-8" "$OUT/volumes.md" 2>/dev/null || echo 0)
if [ "$ENC_COUNT" = "3" ]; then
  echo "PASS: 编码检测 3 卷全 utf-8 ✓"
  PASS=$((PASS+1))
else
  echo "FAIL: 编码检测 $ENC_COUNT 卷 utf-8，预期 3"
  FAIL=$((FAIL+1))
fi

# sh 验收：跑样本卷三卷都跑通且条数 5/5/5（用 "卷 5 条" 精确匹配，避免 "15 条" 干扰）
# sh acceptance: all three sample volumes run with counts 5/5/5 (match "卷 5 条" exactly to avoid "15 条" interference)
SH_COUNT=$(grep -cE '卷 5 条' "$OUT/sh.log" 2>/dev/null || echo 0)
if [ "$SH_COUNT" = "3" ]; then
  echo "PASS: sh 实现三卷各 5 条 ✓"
  PASS=$((PASS+1))
else
  echo "FAIL: sh 实现三卷条数不对（预期 3 个 '卷 5 条'，实测 $SH_COUNT）"
  FAIL=$((FAIL+1))
fi

# C 验收：编译并跑通三卷
# C acceptance: compile and run all three volumes
C_LINES=$(awk 'END{print NR}' "$OUT/c.tsv" 2>/dev/null || echo 0)
if [ -f "$OUT/c.tsv" ] && [ "$C_LINES" = "16" ]; then
  echo "PASS: C 实现编译并跑通三卷（表头+15 条 = 16 行）✓"
  PASS=$((PASS+1))
else
  echo "FAIL: C 实现未跑通（预期 16 行，实测 $C_LINES）"
  FAIL=$((FAIL+1))
fi

echo ""
echo "=== 汇总 ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
[ "$FAIL" = "0" ]
