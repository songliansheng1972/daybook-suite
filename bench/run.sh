#!/usr/bin/env bash
# daybook 并发与容量压测 · 仓内一键入口
# 默认从 PyPI 安装 SUITE_VERSION（src/pack.py）；离线时用 --wheel-dir 指向本地 wheel 目录。
#
#   bench/run.sh                     # 全档：自证 + 10万×64 + 100万×256 + 1000并发
#   bench/run.sh --quick             # 自证 + 10万×64
#   bench/run.sh --only 1m           # 单档（100k|1m|1000|selfcheck）
#   bench/run.sh --version 4.0.4     # 指定版本（默认 src/pack.py 的 SUITE_VERSION）
#   bench/run.sh --wheel-dir DIR     # 离线：从本地 wheel 目录装（不访问网络）
#   bench/run.sh --clean             # 跑完删临时数据（读数先归档到 ~/daybook-bench-results/）
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python3}"
ONLY=""
QUICK=0
CLEAN=0
DATA=""
VERSION=""
WHEEL_DIR=""

usage() { sed -n '2,15p' "$0"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --only)       ONLY="${2:-}"; shift 2 ;;
    --only=*)     ONLY="${1#*=}"; shift ;;
    --quick)      QUICK=1; shift ;;
    --clean)      CLEAN=1; shift ;;
    --data-dir)   DATA="${2:-}"; shift 2 ;;
    --data-dir=*) DATA="${1#*=}"; shift ;;
    --version)    VERSION="${2:-}"; shift 2 ;;
    --version=*)  VERSION="${1#*=}"; shift ;;
    --wheel-dir)  WHEEL_DIR="${2:-}"; shift 2 ;;
    --wheel-dir=*) WHEEL_DIR="${1#*=}"; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "未知参数：$1"; usage; exit 2 ;;
  esac
done

[[ -f "$ROOT/src/pack.py" ]] || { echo "✗ 未找到 $ROOT/src/pack.py，bench/ 必须在仓根下"; exit 3; }
if [[ -z "$VERSION" ]]; then
  VERSION="$(awk -F"'" '/^SUITE_VERSION/{print $2; exit}' "$ROOT/src/pack.py")"
fi
[[ -n "$VERSION" ]] || { echo "✗ 读不到 SUITE_VERSION，可用 --version 指定"; exit 3; }
echo "✓ 版本：${VERSION}（源：src/pack.py）"

if [[ "$QUICK" == "1" ]]; then
  STAGES="selfcheck 100k"
elif [[ -n "$ONLY" ]]; then
  STAGES="${ONLY//,/ }"
else
  STAGES="selfcheck 100k 1m 1000"
fi

# ── 预检 1：Python ────────────────────────────────────────────────
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ 找不到 python3（可用 PYTHON=/path/to/python3 bench/run.sh 指定）"; exit 3
fi
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "✗ Python 版本过低：$("$PY" -V 2>&1)，需 ≥ 3.9"; exit 3
fi
echo "✓ Python $("$PY" -V 2>&1 | awk '{print $2}')"

# ── 预检 2：ulimit -n ─────────────────────────────────────────────
maxw=8
for s in $STAGES; do
  case "$s" in
    selfcheck) need=8 ;;
    100k) need=64 ;;
    1m) need=256 ;;
    1000) need=1000 ;;
    *) echo "✗ 未知档位：${s}（可选 selfcheck|100k|1m|1000）"; exit 2 ;;
  esac
  [[ "$need" -gt "$maxw" ]] && maxw="$need"
done
NOF=$(ulimit -n)
if [[ "$NOF" != "unlimited" && "$NOF" -lt $((maxw + 64)) ]]; then
  echo "✗ ulimit -n=$NOF 不够：本档需要 ≥ $((maxw + 64))"
  echo "  请先执行：ulimit -n 8192"
  exit 3
fi
echo "✓ ulimit -n=${NOF}（本档峰值并发 ${maxw}）"

# ── 预检 3：磁盘剩余 ─────────────────────────────────────────────
if [[ -z "$DATA" ]]; then
  DATA="$(mktemp -d "${TMPDIR:-/tmp}/daybook-bench.XXXXXX")"
else
  mkdir -p "$DATA"
fi
VENV="$DATA/venv"
DFS_DEV=$(df -m "$DATA" | tail -1 | awk '{print $4}')
max_mb=300
for s in $STAGES; do
  case "$s" in
    selfcheck) m=300 ;;
    100k)      m=600 ;;
    1m)        m=3000 ;;
    1000)      m=800 ;;
  esac
  [[ "$m" -gt "$max_mb" ]] && max_mb="$m"
done
need_mb=$((max_mb * 13 / 10))
if [[ "$DFS_DEV" -lt "$need_mb" ]]; then
  echo "✗ 磁盘不足：$DATA 可用 ${DFS_DEV} MB，本档至少需要 ${need_mb} MB。"
  echo "  请清理磁盘，或用 --data-dir 指到更大的卷。"
  exit 3
fi
echo "✓ 磁盘可用 ${DFS_DEV} MB（门槛 ${need_mb} MB）"
echo "  数据目录：$DATA"

# ── 预检 4：离线 wheels（仅 --wheel-dir 时）─────────────────────
if [[ -n "$WHEEL_DIR" ]]; then
  [[ -d "$WHEEL_DIR" ]] || { echo "✗ --wheel-dir 不是目录：$WHEEL_DIR"; exit 3; }
  missing=0
  for pkg in daybook_suite daybook_mcp daybook_orch; do
    if ! ls "$WHEEL_DIR"/${pkg}-${VERSION}-*.whl >/dev/null 2>&1; then
      echo "✗ 缺 wheel：$WHEEL_DIR/${pkg}-${VERSION}-*.whl"; missing=1
    fi
  done
  [[ "$missing" == "0" ]] || { echo "✗ wheels 不完整，拒绝开跑"; exit 3; }
  echo "✓ 离线 wheels 三件齐全（${VERSION}）"
fi

# ── 安装（venv 复用按版本+来源打标记）────────────────────────────
MARK="$DATA/.installed"
STAMP="$VERSION|$WHEEL_DIR"
if [[ -x "$VENV/bin/python" && -f "$MARK" && "$(cat "$MARK")" == "$STAMP" ]] \
   && "$VENV/bin/python" -c 'import daybook_suite, daybook_orch, daybook_mcp' >/dev/null 2>&1; then
  echo "✓ 复用已有 venv：${VENV}（${VERSION}）"
else
  rm -rf "$VENV"
  echo "→ 建临时 venv 并安装 $VERSION"
  "$PY" -m venv "$VENV" >/dev/null
  if [[ -n "$WHEEL_DIR" ]]; then
    "$VENV/bin/python" -m pip install --no-index --disable-pip-version-check \
        --find-links "$WHEEL_DIR" \
        "daybook-suite==$VERSION" "daybook-mcp==$VERSION" "daybook-orch==$VERSION" \
        >"$DATA/install.log" 2>&1 || { echo "✗ 离线安装失败，见 $DATA/install.log"; exit 4; }
  else
    "$VENV/bin/python" -m pip install --disable-pip-version-check \
        "daybook-suite==$VERSION" "daybook-mcp==$VERSION" "daybook-orch==$VERSION" \
        >"$DATA/install.log" 2>&1 || { echo "✗ PyPI 安装失败，见 $DATA/install.log"; exit 4; }
  fi
  printf '%s' "$STAMP" > "$MARK"
fi

ARGS=(--data-dir "$DATA")
if [[ "$QUICK" == "1" ]]; then
  ARGS+=(--quick)
elif [[ -n "$ONLY" ]]; then
  ARGS+=(--only "$ONLY")
fi
if [[ "$CLEAN" == "1" ]]; then
  ARGS+=(--clean)
fi

export DBB_DATA="$DATA"
export DBB_VERSION="$VERSION"
exec "$VENV/bin/python" "$HERE/runner.py" "${ARGS[@]}"
