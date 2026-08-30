#!/usr/bin/env bash
# =============================================================================
# build_models.sh - 블렌더 소스에서 게임용 .glb 를 전부 다시 만든다.
#
# blender/build_*.py 하나가 모델 하나를 담당한다.
# 파이썬 스크립트가 원본이고 models/*.glb 는 산출물이므로,
# 모델을 고치려면 .glb 가 아니라 blender/ 의 스크립트를 고친다.
#
# 사용:
#   bash tools/build_models.sh            # 전부 다시 빌드
#   bash tools/build_models.sh squirrel   # 이름에 squirrel 이 든 것만
#   bash tools/build_models.sh --preview  # 미리보기 렌더도 함께
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_UNIX="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJ="$(cygpath -m "$PROJ_UNIX" 2>/dev/null || echo "$PROJ_UNIX")"

FILTER=""
PREVIEW=0
for arg in "$@"; do
  case "$arg" in
    --preview) PREVIEW=1 ;;
    *) FILTER="$arg" ;;
  esac
done

resolve_blender() {
  if [ -n "${BLENDER_BIN:-}" ] && [ -x "$BLENDER_BIN" ]; then echo "$BLENDER_BIN"; return 0; fi
  local found
  found=$(ls -1d "/c/Program Files/Blender Foundation/Blender "*/blender.exe 2>/dev/null | sort -V | tail -1)
  [ -n "$found" ] && { echo "$found"; return 0; }
  command -v blender >/dev/null 2>&1 && { command -v blender; return 0; }
  return 1
}

BLENDER="$(resolve_blender)" || {
  echo "블렌더를 찾지 못했습니다. BLENDER_BIN 환경변수로 지정하세요." >&2
  exit 2
}
echo "블렌더: $BLENDER"
echo

fail=0
built=0

for script in "$PROJ_UNIX"/blender/build_*.py; do
  [ -e "$script" ] || { echo "blender/build_*.py 가 없습니다."; exit 2; }
  base="$(basename "$script" .py)"
  name="${base#build_}"

  if [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]]; then
    continue
  fi

  out="$PROJ/models/${name}.glb"
  args=(--out "$out")
  if [ "$PREVIEW" -eq 1 ]; then
    args+=(--preview "$PROJ/blender/_preview/${name}.png")
  fi

  echo "── $name ──────────────────────────────────────────"
  log="$(mktemp)"
  "$BLENDER" --background --python "$script" -- "${args[@]}" >"$log" 2>&1
  code=$?

  grep -a '^\[블렌더\]' "$log" | sed 's/^/  /'

  if [ $code -ne 0 ] || grep -qaE 'Traceback|^[A-Za-z]*Error:' "$log"; then
    echo "  실패 (종료 코드 $code):"
    grep -aE 'Traceback|Error|line [0-9]+' "$log" | head -12 | sed 's/^/    /'
    fail=$((fail + 1))
  else
    built=$((built + 1))
  fi
  rm -f "$log"
  echo
done

echo "======================================================================"
if [ "$fail" -eq 0 ]; then
  echo "모델 빌드 완료: ${built}개"
  exit 0
else
  echo "모델 빌드 실패: ${fail}개 (성공 ${built}개)"
  exit 1
fi
