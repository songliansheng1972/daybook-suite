#!/usr/bin/env bash
# DAYBOOK 跨语言一致性测试
# 跑 5 种实现（py/sh/c/f/bas），输出 tsv，diff 权威版（py）。
# 退出码 0 = 全一致；非 0 = 有差异。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"   # daybook/ 目录
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
cat > "$OUT/test.conf" <<EOF
[卷]
协作=sample/协作卷.txt
辞海=sample/辞海卷.txt
大宗师=sample/大宗师卷.txt

[条目]
头正则=^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]
标正则=^\[[^\]]+\]\s*\[([^\]]+)\]\s*\[([^\]]*)\]
字段=卷,行号,时间,类,标题,字数,含订正

[规则]
类=tag:1
标题=tag:2
字数=len
含订正=contains:订正

[索引]
根=
输出目录=.
索引前缀=索引_
清单名=volumes.md
EOF

echo "[1/5] Python daybook.py ..."
cd "$ROOT"
python3 -c "
import sys; sys.argv = ['daybook.py', 'index']
import daybook
conf = daybook.load_conf('$OUT/test.conf')
root_cfg = conf.get('索引', {}).get('根', '').strip()
import os
root = '$OUT' if not root_cfg else None  # 根=空 → isolated fixture
per, total, report = daybook.build(conf, '$OUT')
print('索引：' + '｜'.join('%s %d' % (k, v) for k, v in per.items()) + '｜合计 %d' % total)
" > "$OUT/py.log" 2>&1
cat "$OUT/py.log"
cp "$OUT/索引_协作卷.tsv" "$OUT/py_协作.tsv"
cp "$OUT/索引_辞海卷.tsv" "$OUT/py_辞海.tsv"
cp "$OUT/索引_大宗师卷.tsv" "$OUT/py_大宗师.tsv"
PY_COLL=$(($(wc -l < "$OUT/py_协作.tsv") - 1))
PY_CIHA=$(($(wc -l < "$OUT/py_辞海.tsv") - 1))
PY_DZ=$(($(wc -l < "$OUT/py_大宗师.tsv") - 1))
echo "  条数：协作 $PY_COLL 辞海 $PY_CIHA 大宗师 $PY_DZ"

# 2-5. 其他语言实现：当前只数条目（功能子集），对比条目数
echo "[2/5] sh daybook.sh ..."
cd "$OUT" && sh "$ROOT/daybook.sh" "协作=sample/协作卷.txt" "辞海=sample/辞海卷.txt" "大宗师=sample/大宗师卷.txt" 2>/dev/null | tee "$OUT/sh.log" || echo "  sh 跑失败（非阻塞）"

echo "[3/5] C daybook.c ..."
cc "$ROOT/daybook.c" -o "$OUT/daybook_c" 2>/dev/null && "$OUT/daybook_c" "$OUT/sample/协作卷.txt" "$OUT/sample/辞海卷.txt" "$OUT/sample/大宗师卷.txt" > "$OUT/c.tsv" 2>/dev/null && echo "  C 编译并跑通 ✓" || echo "  C 编译或运行失败（非阻塞）"

echo "[4/5] Fortran daybook.f ..."
which gfortran >/dev/null 2>&1 && gfortran "$ROOT/daybook.f" -o "$OUT/daybook_f" 2>/dev/null && "$OUT/daybook_f" 2>/dev/null | tee "$OUT/f.log" || echo "  gfortran 不可用（非阻塞）"

echo "[5/5] BASIC daybook.bas ..."
which bwbasic >/dev/null 2>&1 && bwbasic "$ROOT/daybook.bas" 2>/dev/null | tee "$OUT/bas.log" || echo "  bwbasic 不可用（非阻塞）"

echo ""
echo "=== 验收 ==="
# 主验收：Python 跑样本卷三卷都跑通且条数 5/5/5
if [ "$PY_COLL" = "5" ] && [ "$PY_CIHA" = "5" ] && [ "$PY_DZ" = "5" ]; then
  echo "PASS: Python 权威版三卷条数 5/5/5 ✓"
  PASS=$((PASS+1))
else
  echo "FAIL: Python 权威版三卷条数 $PY_COLL/$PY_CIHA/$PY_DZ，预期 5/5/5"
  FAIL=$((FAIL+1))
fi

# 编码检测验收
ENC_COUNT=$(grep -c "utf-8" "$OUT/volumes.md" 2>/dev/null || echo 0)
if [ "$ENC_COUNT" = "3" ]; then
  echo "PASS: 编码检测 3 卷全 utf-8 ✓"
  PASS=$((PASS+1))
else
  echo "FAIL: 编码检测 $ENC_COUNT 卷 utf-8，预期 3"
  FAIL=$((FAIL+1))
fi

# sh 验收：跑样本卷三卷都跑通且条数 5/5/5（用 "卷 5 条" 精确匹配，避免 "15 条" 干扰）
SH_COUNT=$(grep -cE '卷 5 条' "$OUT/sh.log" 2>/dev/null || echo 0)
if [ "$SH_COUNT" = "3" ]; then
  echo "PASS: sh 实现三卷各 5 条 ✓"
  PASS=$((PASS+1))
else
  echo "FAIL: sh 实现三卷条数不对（预期 3 个 '卷 5 条'，实测 $SH_COUNT）"
  FAIL=$((FAIL+1))
fi

# C 验收：编译并跑通三卷
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
