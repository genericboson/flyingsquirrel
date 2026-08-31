#!/usr/bin/env bash
# =============================================================================
# verify.sh - 하늘다람쥐 프로젝트 헤드리스 검증 하네스
#
# 루프 개발의 판정 게이트. 게임 창을 띄우지 않고도 "지금 빌드가 깨졌는가"를
# 기계적으로 판정한다. 실패하면 종료 코드 1과 함께 원인을 출력한다.
#
#   1. import : 에셋 임포트 (.godot 캐시 생성)
#   2. check  : 모든 .gd 파일 구문 검사
#   3. smoke  : 메인 씬을 N 프레임 돌린 뒤 종료, 런타임 에러 수집
#   4. tests  : tools/tests/*.gd 기능 테스트 (종료 코드로 합격/불합격)
#
# 사용:
#   bash tools/verify.sh
#   bash tools/verify.sh --frames 300
#   bash tools/verify.sh --scene res://scenes/Level1.tscn
#   GODOT_BIN=/c/other/godot.exe bash tools/verify.sh
# =============================================================================
set -uo pipefail

FRAMES=180
SCENE=""
SKIP_IMPORT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --frames)      FRAMES="$2"; shift 2 ;;
    --scene)       SCENE="$2";  shift 2 ;;
    --skip-import) SKIP_IMPORT=1; shift ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_UNIX="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJ="$(cygpath -m "$PROJ_UNIX" 2>/dev/null || echo "$PROJ_UNIX")"
LOG_DIR="$(mktemp -d 2>/dev/null || echo /tmp/fs-verify)"
REPORT="$SCRIPT_DIR/verify-report.txt"
mkdir -p "$LOG_DIR"
trap 'rm -rf "$LOG_DIR"' EXIT

# --- Godot 실행 파일 탐색 ----------------------------------------------------
resolve_godot() {
  if [ -n "${GODOT_BIN:-}" ] && [ -x "$GODOT_BIN" ]; then echo "$GODOT_BIN"; return 0; fi
  for c in \
    "/c/Godot_v4.7.2/Godot_v4.7.2-stable_mono_win64_console.exe" \
    "/c/Godot_v4.7.2/Godot_v4.7.2-stable_win64_console.exe"
  do
    [ -x "$c" ] && { echo "$c"; return 0; }
  done
  if command -v godot >/dev/null 2>&1; then command -v godot; return 0; fi
  return 1
}

GODOT="$(resolve_godot)" || {
  echo "Godot 실행 파일을 찾지 못했습니다. GODOT_BIN 환경변수로 지정하세요." >&2
  exit 2
}

# --- 헤드리스 잡음 (디스플레이/오디오/GPU 부재로 인한 무해한 경고) -----------
BENIGN='Unable to initialize (video|audio)|AudioDriverDummy|DisplayServerHeadless|Headless display|No display server|Vulkan|D3D12|GLES|TextServerDummy|Your video card driver|blit_render_targets_to_screen|--headless|editor_settings|OpenXR|Creating Godot project|Godot Engine v'

# --- 실제 결함 신호 ----------------------------------------------------------
FAILSIG='SCRIPT ERROR|Parse Error|Parser Error|Compile Error|Invalid call|Invalid access|Invalid get index|Invalid set index|Nonexistent function|Cannot call method|Attempt to call|Failed to load|Failed to instantiate|Failed to open|Cannot open file|Cannot load|Resource file not found|Stack overflow|Trying to assign|Node not found|Can.t open dynamic library|Can.t run project|no main scene|ERROR:|[Ee]rror:|USER ERROR'

# Godot 실행. 결과는 전역 RUN_LOG / RUN_EXIT 로 전달한다.
# (명령 치환으로 호출하면 서브셸이 생겨 전역 대입이 유실되므로 실행과 파싱을 분리한다)
run_godot() {
  local tag="$1"; shift
  RUN_LOG="$LOG_DIR/$tag.log"
  timeout 180 "$GODOT" "$@" >"$RUN_LOG" 2>&1
  RUN_EXIT=$?
}

# 로그에서 결함 신호만 추출 (Godot 출력은 CRLF 이므로 \r 제거)
problems_from() {
  tr -d '\r' < "$1" 2>/dev/null | grep -aE "$FAILSIG" | grep -avE "$BENIGN" | sed 's/[[:space:]]*$//' | sort -u
}

# 로그 매칭이 비어도 종료 코드가 0이 아니면 실패다.
# (침묵은 성공이 아니다 - 크래시/타임아웃/미지의 실패를 놓치지 않기 위한 안전망)
exit_code_problem() {
  local head_lines
  head_lines="$(tr -d '\r' < "$RUN_LOG" 2>/dev/null | grep -v '^[[:space:]]*$' | head -3 | tr '\n' ' ')"
  echo "종료 코드 $RUN_EXIT — ${head_lines:-출력 없음}"
}

FAIL_COUNT=0
{
  echo "하늘다람쥐 검증 리포트"
  echo "실행 시각 : $(date '+%Y-%m-%d %H:%M:%S')"
  echo "Godot     : $GODOT"
  echo "프로젝트  : $PROJ"
  echo "======================================================================"
} > "$REPORT"

emit() { echo "$1" | tee -a "$REPORT"; }

# --- 1) 임포트 ---------------------------------------------------------------
emit ""
if [ "$SKIP_IMPORT" -eq 1 ]; then
  emit "[1] 임포트 : 건너뜀"
else
  run_godot import --headless --path "$PROJ" --import
  problems="$(problems_from "$RUN_LOG")"
  [ -z "$problems" ] && [ "$RUN_EXIT" -ne 0 ] && problems="$(exit_code_problem)"
  if [ -z "$problems" ]; then
    emit "[1] 임포트 : 통과"
  else
    n=$(printf '%s\n' "$problems" | wc -l)
    FAIL_COUNT=$((FAIL_COUNT + n))
    emit "[1] 임포트 : 실패 (${n}건)"
    printf '%s\n' "$problems" | sed 's/^/    - /' | tee -a "$REPORT"
  fi
fi

# --- 2) GDScript 구문 검사 ---------------------------------------------------
emit ""
mapfile -t SCRIPTS < <(find "$PROJ_UNIX" -name '*.gd' -type f -not -path '*/.godot/*' | sort)

if [ "${#SCRIPTS[@]}" -eq 0 ]; then
  emit "[2] 구문 검사 : 대상 없음 (.gd 파일 0개)"
else
  detail=""
  sn=0
  for s in "${SCRIPTS[@]}"; do
    rel="${s#$PROJ_UNIX/}"
    tag="check_$(echo "$rel" | tr -c 'A-Za-z0-9' '_')"
    run_godot "$tag" --headless --path "$PROJ" --check-only --script "res://$rel"
    problems="$(problems_from "$RUN_LOG")"
    [ -z "$problems" ] && [ "$RUN_EXIT" -ne 0 ] && problems="$(exit_code_problem)"
    if [ -n "$problems" ]; then
      n=$(printf '%s\n' "$problems" | wc -l)
      sn=$((sn + n))
      detail="${detail}    [X] ${rel}"$'\n'"$(printf '%s\n' "$problems" | sed 's/^/        - /')"$'\n'
    fi
  done
  if [ "$sn" -eq 0 ]; then
    emit "[2] 구문 검사 : 통과  (스크립트 ${#SCRIPTS[@]}개)"
  else
    FAIL_COUNT=$((FAIL_COUNT + sn))
    emit "[2] 구문 검사 : 실패 (${sn}건, 스크립트 ${#SCRIPTS[@]}개)"
    printf '%s' "$detail" | tee -a "$REPORT"
  fi
fi

# --- 3) 스모크 런 ------------------------------------------------------------
emit ""
if [ -n "$SCENE" ]; then
  run_godot smoke --headless --path "$PROJ" --quit-after "$FRAMES" "$SCENE"
else
  run_godot smoke --headless --path "$PROJ" --quit-after "$FRAMES"
fi
SMOKE_LOG="$RUN_LOG"
SMOKE_EXIT="$RUN_EXIT"
problems="$(problems_from "$SMOKE_LOG")"
[ -z "$problems" ] && [ "$SMOKE_EXIT" -ne 0 ] && problems="$(exit_code_problem)"

if [ -z "$problems" ]; then
  emit "[3] 스모크 런 : 통과"
else
  n=$(printf '%s\n' "$problems" | wc -l)
  FAIL_COUNT=$((FAIL_COUNT + n))
  emit "[3] 스모크 런 : 실패 (${n}건)"
fi
emit "    씬       : ${SCENE:-메인 씬(project.godot)}"
emit "    프레임   : $FRAMES"
emit "    종료코드 : $SMOKE_EXIT"
[ -n "$problems" ] && printf '%s\n' "$problems" | sed 's/^/    - /' | tee -a "$REPORT"

# 게임이 남긴 자체 진단 출력 ([진단] 접두사) 은 따로 보여준다
diag="$(grep -a '^\[진단\]' "$SMOKE_LOG" 2>/dev/null | sort -u)"
if [ -n "$diag" ]; then
  emit ""
  emit "게임 자체 진단:"
  printf '%s\n' "$diag" | sed 's/^/    /' | tee -a "$REPORT"
fi

# --- 4) 기능 테스트 ----------------------------------------------------------
# tools/tests/*.gd 는 SceneTree 스크립트다. 스스로 판정해 종료 코드로 알려 준다
# (0 = 통과, 그 밖 = 불합격). 구문 검사·스모크 런이 잡지 못하는 "동작이 맞는가" 를 본다.
emit ""
mapfile -t TESTS < <(find "$PROJ_UNIX/tools/tests" -name '*.gd' -type f 2>/dev/null | sort)

if [ "${#TESTS[@]}" -eq 0 ]; then
  emit "[4] 기능 테스트 : 대상 없음 (tools/tests/*.gd 0개)"
else
  detail=""
  tn=0
  measured=""
  for t in "${TESTS[@]}"; do
    rel="${t#$PROJ_UNIX/}"
    tag="test_$(echo "$rel" | tr -c 'A-Za-z0-9' '_')"
    run_godot "$tag" --headless --path "$PROJ" --script "res://$rel"
    problems="$(problems_from "$RUN_LOG")"
    # 테스트는 불합격을 종료 코드로 알린다. 로그에 아는 결함 패턴이 없어도
    # 코드가 0이 아니면 실패다. 그때는 테스트가 스스로 남긴 판정 줄을 보여준다.
    if [ -z "$problems" ] && [ "$RUN_EXIT" -ne 0 ]; then
      verdict="$(tr -d '\r' < "$RUN_LOG" 2>/dev/null | grep -aE '^\[[^]]+\] (X |판정=)' | head -5)"
      problems="${verdict:-$(exit_code_problem)}"
    fi
    if [ -n "$problems" ]; then
      n=$(printf '%s\n' "$problems" | wc -l)
      tn=$((tn + n))
      detail="${detail}    [X] ${rel}"$'\n'"$(printf '%s\n' "$problems" | sed 's/^/        - /')"$'\n'
    fi
    measured="${measured}$(tr -d '\r' < "$RUN_LOG" 2>/dev/null | grep -a '^\[측정\]')"$'\n'
  done
  if [ "$tn" -eq 0 ]; then
    emit "[4] 기능 테스트 : 통과  (테스트 ${#TESTS[@]}개)"
  else
    FAIL_COUNT=$((FAIL_COUNT + tn))
    emit "[4] 기능 테스트 : 실패 (${tn}건, 테스트 ${#TESTS[@]}개)"
    printf '%s' "$detail" | tee -a "$REPORT"
  fi

  # 테스트가 남긴 측정값 ([측정] 접두사) 은 통과/실패와 무관하게 보여준다.
  # 스모크 런의 [진단] 블록과 같은 취지 — 수치가 조용히 변하는 것을 눈에 띄게 한다.
  measured="$(printf '%s' "$measured" | grep -a '^\[측정\]' | sort -u)"
  if [ -n "$measured" ]; then
    emit ""
    emit "기능 테스트 측정값:"
    printf '%s\n' "$measured" | sed 's/^/    /' | tee -a "$REPORT"
  fi
fi

# --- 결과 --------------------------------------------------------------------
emit ""
emit "======================================================================"
if [ "$FAIL_COUNT" -eq 0 ]; then
  emit "결과: 통과 - 검출된 문제 없음"
  echo ""
  echo "VERIFY: PASS"
  exit 0
else
  emit "결과: 실패 - 총 ${FAIL_COUNT}건"
  echo ""
  echo "VERIFY: FAIL ($FAIL_COUNT)"
  exit 1
fi
