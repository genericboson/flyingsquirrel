"""눈 덮인 소나무 한 그루를 만들어 .glb 로 내보낸다.

기획서 명세:
  - Interactive Object > 나무
      · PC 가 기둥에 매달려 나무를 중심으로 이동할 수 있다
      · 나뭇가지로 가면 나뭇가지에 매달리고, 기둥으로 가면 기둥에 붙는다
      · 나뭇가지 위에서는 배(belly)면이 아래를 향하고, 가지가 뻗어나간
        방향으로만 이동할 수 있다
  - Level Design > 눈 덮인 설원 > 시작 지역
      · 눈덮인 소나무로 이루어진 소나무 숲, 시간상 겨울

코더와의 계약 (오브젝트 이름):
  기둥_main        기둥. 충돌 생김. 매달려 오르내리는 면.
  가지_01 ~ 가지_NN 가지. 충돌 생김. 가지 하나 = 오브젝트 하나.
                   ★ 각 오브젝트의 로컬 +X 축이 가지가 뻗어나간 방향이다.
                     원점은 가지가 기둥에서 시작하는 지점.
  노충돌_*         솔잎·쌓인 눈 같은 장식. world.gd 가 충돌을 만들지 않는다.
                   활공 중인 플레이어가 솔잎에 걸리면 안 되기 때문이다.

원점(0,0,0) 은 지면에 닿는 기둥 밑동. 블렌더는 Z 가 위이고
export_yup=True 로 내보내면 Godot 에서 +Y 가 위가 된다.

실행:
  blender --background --python blender/build_pine_tree.py -- \
      --out models/pine_tree.glb --preview 미리보기.png
"""
import math
import os
import random
import sys

import bpy
from mathutils import Vector

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# =============================================================================
# 축척 — 사용자가 확정한 값 (2026-08-31)
#
# 사용자 요구: "하늘다람쥐 폭 : 나무 밑동 지름 = 1 : N" 에서 **N = 16** 을 선택.
# blender/_scalestudy.py 가 만든 비교 렌더 5장을 보고 직접 고른 값이다.
#
#   S = N * (다람쥐 AABB 폭) / (이 파일의 원래 밑동 지름)
#     = 16 * 1.209209621 m / (0.50 * 2 = 1.000 m)
#     = 19.347353935
#
#   · 다람쥐 폭 1.209209621 m 는 models/flying_squirrel.glb 를 임포트해
#     기본 자세에서 모디파이어까지 적용한 AABB 의 X 폭을 실측한 값이다.
#   · 밑동 지름은 뿌리 벌어짐(TRUNK_FLARE)을 뺀 기준값 TRUNK_R_BASE*2 이다.
#
# 아래 상수는 "원래 값 * SCALE" 로 적는다. 무엇이 배율을 받았고 무엇이 안 받았는지
# 한눈에 보이게 하기 위해서다. 배율을 곱하면 안 되는 것:
#   각도(도) · 비율 · 지수 · 분할 수 · 개수.
# 배율의 역수를 받아야 하는 것: 길이의 역수인 값(1/m). TRUNK_FLARE_FALLOFF 뿐이다.
# =============================================================================

SCALE = 19.347353935

# =============================================================================
# 치수 — 기획서에 수치가 없어 PD 가 정한 잠정치.
# 근거: player.gd 의 활공 성능(glide_speed 10.5 / glide_max_fall 2.4,
#       활공비 약 4.4:1). 사용자 확인 후 바뀔 수 있으므로 전부 여기 모아 둔다.
# 숫자를 아래 코드 본문에 흩뿌리지 말 것.
# =============================================================================

TREE_HEIGHT = 18.0 * SCALE    # 나무 전체 높이 (m) — 348.25 m

# --- 기둥 -------------------------------------------------------------------
TRUNK_R_BASE = 0.50 * SCALE   # 밑동 반지름 (뿌리 벌어짐 제외) — 9.674 m
TRUNK_R_TOP = 0.055 * SCALE   # 꼭대기 반지름
TRUNK_TAPER = 1.25            # 가늘어지는 곡선의 지수 (클수록 아래가 굵음)
TRUNK_FLARE = 0.42            # 밑동 뿌리 벌어짐 배율
TRUNK_FLARE_FALLOFF = 1.15 / SCALE   # 벌어짐이 사라지는 속도 (1/m) ★ 역수
TRUNK_LEAN = 0.16 * SCALE     # 기둥이 휘는 폭 (m)
TRUNK_SEGMENTS = 56           # 단면 분할. 밑동 둘레 86m → 한 면 1.54m (다람쥐 폭 1.3배)
TRUNK_RINGS = 100             # 높이 분할. 348m → 한 마디 3.52m
TRUNK_NOISE = 0.038           # 껍질 요철 (반지름 비율)

# --- 기둥 표면 시각 단서 ----------------------------------------------------
# N=16 에서 기둥에 붙으면 화면이 통째로 갈색 벽이 되어 자기가 움직이는지
# 알 수 없다. 세 종류를 겹쳐 넣는다.
#   (가) 껍질 판(plate) — 기둥 면마다 색을 갈아 끼운 모자이크. 추가 정점 0.
#        상하좌우 어느 쪽으로 움직여도 화면이 바뀐다. 가장 값싸고 효과가 크다.
#   (나) 세로 홈(flute) — 기둥을 **돌 때** 그림자 선이 흘러간다.
#   (다) 옹이·껍질자국·눈 — 절대 위치를 알려주는 지형지물. 높이마다 다르다.
TRUNK_FLUTES = 7              # 한 바퀴에 들어가는 세로 홈 개수 (56면 ÷ 7 = 8면 주기)
TRUNK_FLUTE_DEPTH = 0.105     # 홈 깊이 / 반지름 — 밑동에서 1.4m 파인다
TRUNK_FLUTE_SHARP = 2.2       # 클수록 홈이 좁고 골이 뚜렷하다
TRUNK_FLUTE_TWIST = 34.0      # 꼭대기까지 홈이 도는 각도 (도). 나선으로 꼬인 껍질.
TRUNK_BARK_WAVES = 7          # 껍질 잡음을 만드는 각도 성분 수 (연속 함수)

# 껍질 판 모자이크. 면마다 세 색 중 하나를 준다. 색이 세 개면 서피스도 세 개라
# 드로우콜이 그루당 +2 늘어난다. 그 이상 늘리지 않는다.
BARK_PLATE_STICK_V = 0.20     # 아래 면의 색을 그대로 잇는 확률
BARK_PLATE_STICK_H = 0.55     # 옆 면의 색을 그대로 잇는 확률 (가로로 퍼진 판)
BARK_PLATE_GROOVE = 0.72      # 홈 바닥으로 판정하는 깊이
BARK_PLATE_GROOVE_P = 0.65    # 홈 바닥이라도 이 확률로만 어둡게 — 100%면
                              # 일정 간격의 세로 줄무늬(바코드)가 되어 눈에 거슬린다

MARK_TOP_U = 0.80             # 표면 자국이 붙는 최고 높이 (나무 높이 비율)
MARK_BOTTOM = 1.2 * SCALE     # 표면 자국이 시작하는 높이 (m)
KNOT_COUNT = 26               # 옹이 개수
KNOT_R = (0.055, 0.130)       # 옹이 반지름 범위 / 그 높이의 기둥 반지름
KNOT_BULGE = 0.34             # 옹이가 튀어나온 높이 / 옹이 반지름
SCAR_COUNT = 78               # 껍질 벗겨진 밝은 자국 개수
SCAR_W = (0.09, 0.24)         # 자국 반폭(호 길이) / 기둥 반지름
SCAR_H = (1.1, 3.4)           # 자국 반높이 / 자국 반폭 (세로로 길다)
SNOWMARK_COUNT = 52           # 기둥에 걸린 눈 자국 개수
SNOWMARK_W = (0.12, 0.30)     # 눈 자국 반폭 / 기둥 반지름
SNOWMARK_AZ = 118.0           # 눈이 붙는 쪽 방위각 (도) — 바람 방향
SNOWMARK_SPREAD = 74.0        # 그 방위각에서 좌우로 흩어지는 폭 (도)
MARK_LIFT = 0.006             # 자국을 표면에서 띄우는 높이 / 기둥 반지름
MARK_GRID = (9, 2)            # 자국 한 장의 극좌표 분할 (바퀴살 수, 고리 수).
                              # 자국 하나가 삼각형 27개다. 개수를 늘릴 때는
                              # 여기를 키우지 말고 개수만 늘리는 편이 싸다.

# --- 가지 층(윤생지) --------------------------------------------------------
WHORL_COUNT = 4               # 층 수
WHORL_LOWEST_Y = 5.5 * SCALE  # 가장 낮은 가지 높이 — 106.41 m
WHORL_TOP_Y = 14.0 * SCALE    # 가장 높은 층의 높이 — 270.86 m
WHORL_SPACING_BIAS = 0.85     # <1 이면 위로 갈수록 층 간격이 좁아진다
WHORL_BRANCHES = (4, 4, 3, 3)   # 층별 가지 수 (아래→위, 층당 3~4개)
WHORL_TWIST = 41.0            # 층마다 방위각을 이만큼 돌려 가지가 겹치지 않게
WHORL_JITTER = 9.0            # 방위각 흔들림 (도)
WHORL_Y_JITTER = 0.18 * SCALE   # 층 안에서 가지 높이가 흔들리는 폭 (m)

# --- 가지 -------------------------------------------------------------------
BRANCH_LENGTH = 4.0 * SCALE   # 가지 기준 길이 (m) — 77.39 m
BRANCH_LEN_FACTOR = (1.15, 1.00, 0.85, 0.70)   # 층별 길이 배율 (아래가 길다)
BRANCH_R_BASE = 0.12 * SCALE  # 밑동 쪽 반지름 — 플레이어가 올라탈 굵기
BRANCH_R_TIP_RATIO = 0.32     # 끝 반지름 / 밑동 반지름
BRANCH_PITCH = (-9.0, -5.0, 1.0, 6.0)          # 층별 기울기(도). 음수는 처짐.
BRANCH_INSET = 0.30 * SCALE   # 기둥 속으로 파묻는 길이 (틈 방지)
BRANCH_SEGMENTS = 8           # 단면 분할
BRANCH_RINGS = 7              # 길이 분할

# --- 솔잎 -------------------------------------------------------------------
# 솔잎 뭉치의 단면은 '윗면이 납작하고 아래로 처지는' 모양이다.
# 가지 윗면이 솔잎에 묻히면 플레이어가 가지 위를 걸을 때 파묻혀 보이므로,
# 윗면은 가지 굵기만큼만 덮고 눈이 그 위에 평평하게 쌓이게 한다.
FOLIAGE_W_RATIO = 0.30        # 솔잎 뭉치 최대 반폭 / 가지 길이
FOLIAGE_TOP = 0.11            # 윗면 높이 / 반폭 (작을수록 평평)
FOLIAGE_DROOP = 0.50          # 아랫면 깊이 / 반폭
FOLIAGE_SAG = 0.05            # 끝으로 갈수록 처지는 정도 (길이 비율)
FOLIAGE_START = 0.08          # 가지의 몇 % 지점부터 솔잎이 붙는가
FOLIAGE_END = 1.04            # 가지 끝을 살짝 넘어간다
FOLIAGE_RINGS = 11
FOLIAGE_SEGMENTS = 18
FOLIAGE_SPIKE = 0.24          # 단면을 톱니처럼 만들어 솔잎 느낌을 낸다
FOLIAGE_NOISE = 0.16
FOLIAGE_MIN_W = 0.04 * SCALE  # 다발 반폭의 하한 (m)

## 가지 하나에 달리는 솔잎 다발들 (곁가지 포함).
## (좌우 각도도, 가지 위 시작 지점 0~1, 길이 배율, 폭 배율, 처짐 각도도)
## 첫 줄이 가지를 따라가는 본 다발이고 나머지는 부챗살처럼 벌어진 곁가지다.
FOLIAGE_SPRAYS = (
    (  0.0, 0.00, 1.00, 1.00,  0.0),
    ( 31.0, 0.22, 0.66, 0.72, -7.0),
    (-31.0, 0.26, 0.62, 0.70, -7.0),
    ( 57.0, 0.12, 0.40, 0.55, -13.0),
    (-57.0, 0.15, 0.38, 0.53, -13.0),
)

# --- 꼭대기(수관 첨탑) ------------------------------------------------------
SPIRE_BOTTOM_Y = 13.6 * SCALE   # 첨탑 솔잎이 시작하는 높이
SPIRE_R = 0.95 * SCALE          # 첨탑 밑 반지름
SPIRE_MIN_R = 0.02 * SCALE      # 첨탑 반지름 하한 (m)
SPIRE_RINGS = 10
SPIRE_SEGMENTS = 12

# --- 쌓인 눈 ----------------------------------------------------------------
SNOW_ARC = 64.0               # 솔잎 단면 중 눈이 덮이는 각도 (±도). 나머지는 녹색이 보인다.
SNOW_SWELL = 1.02             # 솔잎 표면에서 얼마나 부풀려 얹는가
SNOW_LIFT = 0.06 * SCALE      # 위로 띄우는 높이 (m)
SNOW_THICKNESS = 0.055 * SCALE  # 눈층 두께 (솔리디파이)
SNOW_CAP_FROM = 0.50          # 첨탑의 이 지점 위로만 눈이 덮인다 (0~1)
SNOW_COLS = 9                 # 가지 위 눈 단면의 가로 분할. 이 오브젝트가 glb 용량의
                              # 44% 를 차지하므로(솔리디파이가 정점을 두 배로 만든다)
                              # 값을 올리기 전에 파일 크기를 다시 재야 한다.
SNOW_CAP_PAD = 0.02 * SCALE   # 첨탑 눈을 부풀리는 여유 (m)
SNOW_CAP_MIN_R = 0.015 * SCALE  # 첨탑 눈 반지름 하한 (m)

# --- 색 (텍스처 없는 단색 PBR) ----------------------------------------------
# 하늘다람쥐 몸통은 FUR = (0.45, 0.72, 0.92). 눈 위에서 묻히지 않도록
# 눈은 채도를 거의 없애고 밝기만 높인다.
BARK = (0.115, 0.072, 0.050, 1.0)     # 어두운 갈색 (기본 판)
BARK_DARK = (0.068, 0.042, 0.029, 1.0)   # 홈 바닥 / 그늘진 판
BARK_LIGHT = (0.216, 0.150, 0.098, 1.0)  # 밝은 판
BRANCH_BARK = (0.145, 0.093, 0.064, 1.0)
NEEDLE = (0.032, 0.105, 0.062, 1.0)   # 어두운 침엽수 녹색
SNOW = (0.855, 0.900, 0.960, 1.0)     # 밝은 흰색, 약간 푸른기
# 기둥 표면 자국용. BARK 대비 밝기가 4배 이상이라야 붙어 있을 때 눈에 띈다.
BARK_SCAR = (0.470, 0.360, 0.245, 1.0)   # 껍질이 벗겨진 밝은 속살
KNOT = (0.038, 0.022, 0.016, 1.0)        # 옹이 — 가장 어둡다. 볼록해서 명암으로 읽힌다

SEED = 20260831


# =============================================================================
# 공통 유틸
# =============================================================================
def log(msg):
    print(f"[블렌더] {msg}")


def rad(d):
    return math.radians(d)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = "models/pine_tree.glb"
    preview = ""
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
        elif a == "--preview" and i + 1 < len(argv):
            preview = argv[i + 1]
    return out, preview


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(name, color, roughness=0.75):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def loft_geometry(rings, offset=0, closed=True, cap_start=True, cap_end=True):
    """고리(ring) 목록을 이어붙인 정점/면을 만든다. offset 은 앞선 정점 개수."""
    verts = []
    faces = []
    n = len(rings[0])
    for ring in rings:
        for p in ring:
            verts.append(tuple(p))

    span = n if closed else n - 1
    for i in range(len(rings) - 1):
        for j in range(span):
            k = (j + 1) % n
            a = offset + i * n + j
            b = offset + i * n + k
            c = offset + (i + 1) * n + k
            d = offset + (i + 1) * n + j
            faces.append((a, b, c, d))

    if closed and cap_start:
        faces.append(tuple(range(offset + n - 1, offset - 1, -1)))
    if closed and cap_end:
        base = offset + (len(rings) - 1) * n
        faces.append(tuple(range(base, base + n)))
    return verts, faces


def build_mesh_object(name, verts, faces, mat, location=(0, 0, 0),
                      rotation=(0, 0, 0), smooth=True):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = rotation
    bpy.context.collection.objects.link(obj)

    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True

    obj.data.materials.append(mat)
    return obj


def build_loft(name, rings, mat, location=(0, 0, 0), rotation=(0, 0, 0),
               smooth=True, cap_start=True, cap_end=True, closed=True):
    """고리 하나짜리 로프트. 정점은 로컬 좌표이고 방향은 오브젝트 rotation 으로 준다."""
    verts, faces = loft_geometry(rings, 0, closed, cap_start, cap_end)
    return build_mesh_object(name, verts, faces, mat, location, rotation, smooth)


def build_multi_loft(name, groups, mat, location=(0, 0, 0), rotation=(0, 0, 0),
                     smooth=True, cap_start=True, cap_end=True, closed=True):
    """여러 덩어리(부챗살처럼 벌어진 솔잎 다발 등)를 한 오브젝트로 묶는다."""
    verts = []
    faces = []
    for rings in groups:
        v, f = loft_geometry(rings, len(verts), closed, cap_start, cap_end)
        verts.extend(v)
        faces.extend(f)
    return build_mesh_object(name, verts, faces, mat, location, rotation, smooth)


# =============================================================================
# 기둥
# =============================================================================
def trunk_radius(y):
    """높이 y 에서의 기둥 반지름."""
    t = min(max(y / TREE_HEIGHT, 0.0), 1.0)
    r = TRUNK_R_TOP + (TRUNK_R_BASE - TRUNK_R_TOP) * (1.0 - t) ** TRUNK_TAPER
    r *= 1.0 + TRUNK_FLARE * math.exp(-y * TRUNK_FLARE_FALLOFF)
    return r


def trunk_center(y):
    """높이 y 에서의 기둥 중심 (살짝 휘게 한다)."""
    t = y / TREE_HEIGHT
    return Vector((TRUNK_LEAN * math.sin(t * 2.1) * t,
                   TRUNK_LEAN * 0.6 * math.sin(t * 3.4 + 1.1) * t,
                   y))


def make_bark_coeffs(rng):
    """껍질 요철을 '각도의 연속 함수' 로 만드는 계수.

    예전에는 단면 정점마다 난수를 뽑았다. 그러면 껍질 표면이 정점 배열에만
    존재해서, 그 위에 옹이·자국을 얹을 때 표면 위치를 알 수 없다.
    각도의 연속 함수로 바꾸면 표면 반지름을 어디서든 정확히 계산할 수 있고,
    자국이 기둥에서 뜨거나 파묻히지 않는다.
    """
    return [(rng.uniform(0.35, 1.0), rng.uniform(0.0, 2.0 * math.pi),
             rng.randint(3, 17)) for _ in range(TRUNK_BARK_WAVES)]


def bark_relief(ang, coeffs):
    """-1 ~ +1 범위의 껍질 요철. 높이에 무관하므로 골이 세로로 이어진다."""
    s = 0.0
    w = 0.0
    for amp, ph, k in coeffs:
        s += amp * math.sin(k * ang + ph)
        w += amp
    return s / max(w, 1e-6)


def flute_depth_at(y, ang):
    """그 지점이 세로 홈의 바닥에 얼마나 가까운가 (0=마루, 1=골 바닥)."""
    tw = rad(TRUNK_FLUTE_TWIST) * min(max(y / TREE_HEIGHT, 0.0), 1.0)
    return (0.5 + 0.5 * math.cos(TRUNK_FLUTES * (ang - tw))) ** TRUNK_FLUTE_SHARP


def trunk_surface_r(y, ang, coeffs):
    """높이 y, 방위각 ang 에서 기둥 표면까지의 반지름 (홈·요철 포함)."""
    r = trunk_radius(y)
    r *= 1.0 - TRUNK_FLUTE_DEPTH * flute_depth_at(y, ang)
    r *= 1.0 + TRUNK_NOISE * bark_relief(ang, coeffs)
    return r


def trunk_surface_point(y, ang, coeffs, out=0.0):
    """표면에서 법선 방향으로 out 만큼 밀어낸 점 (out 은 m)."""
    c = trunk_center(y)
    r = trunk_surface_r(y, ang, coeffs) + out
    return Vector((c.x + math.cos(ang) * r, c.y + math.sin(ang) * r, y))


def bark_plate_shades(rng):
    """기둥 면(ring i, segment j)마다 재질 슬롯 번호를 정한다.

    0 = BARK(기본) / 1 = BARK_DARK(홈 바닥·그늘) / 2 = BARK_LIGHT(밝은 판).
    아래 면·옆 면의 색을 확률적으로 이어받게 해서 낱개 잡음이 아니라
    세로로 길쭉한 '껍질 판' 덩어리가 생기게 한다.
    """
    nseg = TRUNK_SEGMENTS
    grid = []
    for i in range(TRUNK_RINGS - 1):
        y = (i + 0.5) / (TRUNK_RINGS - 1) * TREE_HEIGHT
        row = []
        for j in range(nseg):
            a = 2.0 * math.pi * (j + 0.5) / nseg
            if (flute_depth_at(y, a) >= BARK_PLATE_GROOVE
                    and rng.random() < BARK_PLATE_GROOVE_P):
                row.append(1)
                continue
            if i > 0 and grid[i - 1][j] != 1 and rng.random() < BARK_PLATE_STICK_V:
                row.append(grid[i - 1][j])
            elif j > 0 and row[j - 1] != 1 and rng.random() < BARK_PLATE_STICK_H:
                row.append(row[j - 1])
            else:
                row.append(rng.choice((0, 0, 0, 2, 2, 1)))
        grid.append(row)
    return grid


def build_trunk(rng, mats, coeffs):
    rings = []
    for i in range(TRUNK_RINGS):
        t = i / (TRUNK_RINGS - 1)
        y = t * TREE_HEIGHT
        ring = []
        for j in range(TRUNK_SEGMENTS):
            a = 2.0 * math.pi * j / TRUNK_SEGMENTS
            ring.append(trunk_surface_point(y, a, coeffs))
        rings.append(ring)

    obj = build_loft("기둥_main", rings, mats[0], smooth=True)
    for m in mats[1:]:
        obj.data.materials.append(m)

    # loft_geometry 가 만든 면 순서: i번째 고리 사이의 j번째 면 = i*SEGMENTS + j.
    # 그 뒤에 위/아래 뚜껑 면 2개가 붙는다.
    grid = bark_plate_shades(rng)
    polys = obj.data.polygons
    used = [0, 0, 0]
    for i in range(TRUNK_RINGS - 1):
        for j in range(TRUNK_SEGMENTS):
            s = grid[i][j]
            polys[i * TRUNK_SEGMENTS + j].material_index = s
            used[s] += 1
    for k in range(TRUNK_SEGMENTS * (TRUNK_RINGS - 1), len(polys)):
        polys[k].material_index = 1        # 뚜껑은 어둡게

    tot = sum(used)
    log(f"기둥 껍질 판: 기본 {used[0] / tot * 100:.0f}% / 어두움 {used[1] / tot * 100:.0f}% / "
        f"밝음 {used[2] / tot * 100:.0f}%  (면 {tot}개, 한 면 "
        f"{2 * math.pi * trunk_radius(0.0) / TRUNK_SEGMENTS:.2f}m × "
        f"{TREE_HEIGHT / (TRUNK_RINGS - 1):.2f}m)")
    circ = 2.0 * math.pi * trunk_radius(0.0)
    log(f"기둥: 높이 {TREE_HEIGHT:.1f}m, 밑동 반지름 {trunk_radius(0.0):.2f}m "
        f"(벌어짐 포함) / {TRUNK_R_BASE:.2f}m (기준), 꼭대기 {TRUNK_R_TOP:.3f}m")
    log(f"기둥 분할: 단면 {TRUNK_SEGMENTS} × 높이 {TRUNK_RINGS} "
        f"→ 밑동 둘레 {circ:.1f}m 를 {TRUNK_SEGMENTS}면으로 나누면 한 면 {circ / TRUNK_SEGMENTS:.2f}m "
        f"(다람쥐 폭 1.21m 대비 {circ / TRUNK_SEGMENTS / 1.209:.1f}배), "
        f"높이 한 마디 {TREE_HEIGHT / (TRUNK_RINGS - 1):.2f}m")
    log(f"기둥 세로 홈: {TRUNK_FLUTES}줄, 깊이 반지름의 {TRUNK_FLUTE_DEPTH * 100:.1f}% "
        f"(밑동에서 {trunk_radius(0.0) * TRUNK_FLUTE_DEPTH:.2f}m), 꼭대기까지 {TRUNK_FLUTE_TWIST:.0f}도 비틈")
    return obj


# =============================================================================
# 기둥 표면 자국 (옹이 · 껍질자국 · 눈) — 장식이므로 충돌 없음
# =============================================================================
def build_surface_patch(marks, coeffs, rng):
    """(높이, 방위각, 각도반폭, 높이반폭, 돌출높이, 지수) 목록을 한 메시로 만든다.

    자국 하나는 **극좌표 원반**이다. 사각 격자로 만들면 화면에 네모난 종이를
    붙인 것처럼 보인다 (첫 시도에서 실제로 그렇게 나왔다). 바퀴살마다 반지름을
    흔들어 테두리를 울퉁불퉁하게 만든다.

    좌표는 기둥 표면을 (각도, 높이)로 떠서 만들므로 기둥이 아무리 울퉁불퉁해도
    정확히 밀착한다. 가장자리에서 돌출이 0 이 되어 들뜬 테두리가 없다.
    """
    na, nr = MARK_GRID
    verts = []
    faces = []
    for y0, az, daz, dh, bulge, power in marks:
        base = len(verts)
        wob = [rng.uniform(0.68, 1.22) for _ in range(na)]
        verts.append(tuple(trunk_surface_point(
            y0, az, coeffs, bulge + MARK_LIFT * trunk_radius(y0))))
        for ir in range(1, nr + 1):
            t = ir / nr
            for ia in range(na):
                phi = 2.0 * math.pi * ia / na
                rr = t * wob[ia]
                u = rr * math.cos(phi)
                v = rr * math.sin(phi)
                y = y0 + dh * v
                out = bulge * max(0.0, 1.0 - t * t) ** power + MARK_LIFT * trunk_radius(y)
                verts.append(tuple(trunk_surface_point(y, az + daz * u, coeffs, out)))
        for ia in range(na):
            b = (ia + 1) % na
            faces.append((base, base + 1 + ia, base + 1 + b))
        for ir in range(nr - 1):
            r0 = base + 1 + ir * na
            r1 = r0 + na
            for ia in range(na):
                b = (ia + 1) % na
                faces.append((r0 + ia, r1 + ia, r1 + b, r0 + b))
    return verts, faces


def _mark_span(rng, y_lo, y_hi, count, jitter=0.55):
    """높이를 고르게 흩되 완전히 규칙적이지 않게 — 오르내릴 때 리듬이 생긴다."""
    step = (y_hi - y_lo) / count
    return [y_lo + step * (i + 0.5 + rng.uniform(-jitter, jitter)) for i in range(count)]


def build_trunk_marks(rng, coeffs, m_knot, m_scar, m_snow):
    y_lo = MARK_BOTTOM
    y_hi = TREE_HEIGHT * MARK_TOP_U
    objs = []

    # --- 옹이: 어두운 혹. 실루엣이 살짝 튀어나와 가까이서 잘 읽힌다 -----------
    knots = []
    for y in _mark_span(rng, y_lo, y_hi, KNOT_COUNT):
        y = min(max(y, y_lo), y_hi)
        r = trunk_radius(y)
        w = r * rng.uniform(*KNOT_R)
        knots.append((y, rng.uniform(0.0, 2.0 * math.pi), w / r,
                      w * rng.uniform(0.85, 1.25), w * KNOT_BULGE, 0.65))
    v, f = build_surface_patch(knots, coeffs, rng)
    objs.append(build_mesh_object("노충돌_옹이", v, f, m_knot, smooth=True))

    # --- 껍질자국: 세로로 긴 밝은 반점. 대비가 가장 크다 ---------------------
    scars = []
    for y in _mark_span(rng, y_lo, y_hi, SCAR_COUNT):
        y = min(max(y, y_lo), y_hi)
        r = trunk_radius(y)
        w = r * rng.uniform(*SCAR_W)
        scars.append((y, rng.uniform(0.0, 2.0 * math.pi), w / r,
                      w * rng.uniform(*SCAR_H), w * 0.05, 1.0))
    v, f = build_surface_patch(scars, coeffs, rng)
    objs.append(build_mesh_object("노충돌_껍질자국", v, f, m_scar, smooth=True))

    # --- 기둥에 걸린 눈: 바람 부는 쪽에 몰아 방향 감각을 준다 ----------------
    snows = []
    for y in _mark_span(rng, y_lo, y_hi * 0.92, SNOWMARK_COUNT):
        y = min(max(y, y_lo), y_hi)
        r = trunk_radius(y)
        w = r * rng.uniform(*SNOWMARK_W)
        az = rad(SNOWMARK_AZ + rng.uniform(-SNOWMARK_SPREAD, SNOWMARK_SPREAD))
        snows.append((y, az, w / r, w * rng.uniform(0.45, 0.95), w * 0.16, 0.8))
    v, f = build_surface_patch(snows, coeffs, rng)
    objs.append(build_mesh_object("노충돌_기둥눈", v, f, m_snow, smooth=True))

    log(f"기둥 표면 자국: 옹이 {KNOT_COUNT}개 / 껍질자국 {SCAR_COUNT}개 / 눈 {SNOWMARK_COUNT}개 "
        f"— 높이 {y_lo:.0f}~{y_hi:.0f}m 에 걸쳐 평균 "
        f"{(y_hi - y_lo) / (KNOT_COUNT + SCAR_COUNT + SNOWMARK_COUNT):.1f}m 마다 하나")
    return objs


# =============================================================================
# 가지 층 배치
# =============================================================================
def whorl_height(i):
    t = i / (WHORL_COUNT - 1) if WHORL_COUNT > 1 else 0.0
    return WHORL_LOWEST_Y + (WHORL_TOP_Y - WHORL_LOWEST_Y) * (t ** WHORL_SPACING_BIAS)


def branch_layout(rng):
    """[(층, 방위각rad, 기울기rad, 길이, 밑동반지름, 원점)] 을 만든다."""
    items = []
    for layer in range(WHORL_COUNT):
        y = whorl_height(layer)
        count = WHORL_BRANCHES[layer]
        lenf = BRANCH_LEN_FACTOR[layer]
        length = BRANCH_LENGTH * lenf
        r_base = BRANCH_R_BASE * math.sqrt(lenf)
        pitch = rad(BRANCH_PITCH[layer])
        base_az = rad(WHORL_TWIST * layer)
        for k in range(count):
            az = base_az + 2.0 * math.pi * k / count + rad(rng.uniform(-WHORL_JITTER, WHORL_JITTER))
            yy = y + rng.uniform(-WHORL_Y_JITTER, WHORL_Y_JITTER)
            c = trunk_center(yy)
            # 원점 = 가지가 기둥에서 시작하는 지점 (기둥 표면)
            rt = trunk_radius(yy) * 0.92
            origin = Vector((c.x + math.cos(az) * rt,
                             c.y + math.sin(az) * rt,
                             yy))
            items.append(dict(layer=layer, az=az, pitch=pitch, length=length,
                              r_base=r_base, origin=origin))
    return items


def branch_rotation(az, pitch):
    """로컬 +X 가 (cos p cos az, cos p sin az, sin p) 를 향하도록 하는 오일러.

    블렌더 기본 XYZ 순서에서 R = Rz(rz) @ Ry(ry) @ Rx(rx) 이므로
    Ry(-pitch) 로 들어올린 뒤 Rz(az) 로 돌리면 된다.
    """
    return (0.0, -pitch, az)


def build_branch(name, item, mat):
    L = item["length"]
    r0 = item["r_base"]
    r1 = r0 * BRANCH_R_TIP_RATIO

    rings = []
    for i in range(BRANCH_RINGS):
        u = i / (BRANCH_RINGS - 1)
        x = -BRANCH_INSET + (L + BRANCH_INSET) * u
        # 반지름은 원점(기둥 표면)에서 끝까지의 진행도로 계산한다
        ur = max(0.0, x / L)
        r = r1 + (r0 - r1) * (1.0 - ur) ** 0.9
        if x < 0.0:
            r = r0 * 1.18   # 기둥에 파묻히는 부분은 살짝 굵게 (붙은 티)
        ring = []
        for j in range(BRANCH_SEGMENTS):
            a = 2.0 * math.pi * j / BRANCH_SEGMENTS
            ring.append(Vector((x, math.cos(a) * r, math.sin(a) * r)))
        rings.append(ring)

    return build_loft(name, rings, mat,
                      location=tuple(item["origin"]),
                      rotation=branch_rotation(item["az"], item["pitch"]),
                      smooth=True)


# =============================================================================
# 솔잎 (장식 — 충돌 없음)
# =============================================================================
def foliage_half_width(u, L):
    """다발 진행도 u(0~1) 에서 솔잎 뭉치의 반폭."""
    s = (u - FOLIAGE_START) / (1.0 - FOLIAGE_START)
    s = min(max(s, 0.0), 1.0)
    return FOLIAGE_W_RATIO * L * (math.sin(math.pi * s ** 0.75)) ** 0.7


def branch_radius_at(item, x):
    """가지 원점에서 x 만큼 나아간 지점의 나무 반지름."""
    L, r0 = item["length"], item["r_base"]
    r1 = r0 * BRANCH_R_TIP_RATIO
    ur = min(max(x / L, 0.0), 1.0)
    return r1 + (r0 - r1) * (1.0 - ur) ** 0.9


def spray_frame(yaw_deg, drop_deg, start_u, L):
    """곁가지 다발의 로컬 좌표를 가지 좌표로 옮기는 (기준점, 회전행렬)."""
    from mathutils import Matrix
    rot = (Matrix.Rotation(rad(yaw_deg), 3, "Z")
           @ Matrix.Rotation(rad(-drop_deg), 3, "Y"))
    return Vector((start_u * L, 0.0, 0.0)), rot


def spray_section(item, spray, u, w_ref):
    """다발 단면의 기준값 (반폭, 윗면 높이, 아랫면 깊이, 처짐)."""
    _, start_u, len_s, w_s, _ = spray
    L = item["length"] * len_s
    w = max(foliage_half_width(u, L) * w_s, FOLIAGE_MIN_W)
    # 가지 윗면이 솔잎에 파묻히지 않게, 윗면은 가지 굵기 언저리까지만 덮는다
    r_wood = branch_radius_at(item, (start_u + u * len_s) * item["length"])
    h_up = max(FOLIAGE_TOP * w, r_wood * 1.12)
    h_dn = FOLIAGE_DROOP * w
    sag = -FOLIAGE_SAG * L * (u ** 2)
    return L, w, h_up, h_dn, sag


def build_foliage(name, item, mat, rng):
    groups = []
    for spray in FOLIAGE_SPRAYS:
        yaw, start_u, len_s, w_s, drop = spray
        base, rot = spray_frame(yaw, drop, start_u, item["length"])
        rings = []
        for i in range(FOLIAGE_RINGS):
            u = FOLIAGE_START + (FOLIAGE_END - FOLIAGE_START) * i / (FOLIAGE_RINGS - 1)
            L, w, h_up, h_dn, sag = spray_section(item, spray, u, None)
            x = u * L
            ring = []
            for j in range(FOLIAGE_SEGMENTS):
                phi = 2.0 * math.pi * j / FOLIAGE_SEGMENTS
                c, s = math.cos(phi), math.sin(phi)
                # 톱니 + 잡음 → 매끈한 덩어리 대신 솔잎 다발처럼 보이게
                spike = 1.0 + (FOLIAGE_SPIKE if j % 2 == 0 else -FOLIAGE_SPIKE)
                spike *= 1.0 + rng.uniform(-FOLIAGE_NOISE, FOLIAGE_NOISE)
                p = Vector((x + rng.uniform(-0.05, 0.05) * L,
                            s * w * spike,
                            c * (h_up if c > 0 else h_dn) * spike + sag))
                ring.append(base + rot @ p)
            rings.append(ring)
        groups.append(rings)

    return build_multi_loft(name, groups, mat,
                            location=tuple(item["origin"]),
                            rotation=branch_rotation(item["az"], item["pitch"]),
                            smooth=False)


def build_branch_snow(name, item, mat, rng):
    """솔잎 윗면에 얹힌 눈. 위쪽 호(arc)만 덮는 판 + 솔리디파이로 두께를 준다.

    윗면이 납작하므로 결과는 '눈을 인 나뭇가지' 처럼 넓고 평평한 면이 되고,
    가지 위를 걷는 플레이어가 그 면 위에 올라선 것처럼 보인다.
    """
    arc = rad(SNOW_ARC)
    cols = SNOW_COLS
    groups = []
    for spray in FOLIAGE_SPRAYS:
        yaw, start_u, len_s, w_s, drop = spray
        base, rot = spray_frame(yaw, drop, start_u, item["length"])
        rings = []
        for i in range(FOLIAGE_RINGS):
            u = FOLIAGE_START + (FOLIAGE_END - FOLIAGE_START) * i / (FOLIAGE_RINGS - 1)
            L, w, h_up, h_dn, sag = spray_section(item, spray, u, None)
            x = u * L
            lift = SNOW_LIFT * (1.0 - 0.45 * u)
            ring = []
            for j in range(cols):
                phi = -arc + 2.0 * arc * j / (cols - 1)
                jit = 1.0 + rng.uniform(-0.05, 0.05)
                p = Vector((x,
                            math.sin(phi) * w * SNOW_SWELL * jit,
                            math.cos(phi) * h_up * SNOW_SWELL * jit + sag + lift))
                ring.append(base + rot @ p)
            rings.append(ring)
        groups.append(rings)

    obj = build_multi_loft(name, groups, mat,
                           location=tuple(item["origin"]),
                           rotation=branch_rotation(item["az"], item["pitch"]),
                           smooth=False, closed=False)
    sol = obj.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = SNOW_THICKNESS
    sol.offset = 0.0
    return obj


# =============================================================================
# 꼭대기 첨탑
# =============================================================================
def spire_radius(t):
    """t: 첨탑 밑(0) → 꼭대기(1)."""
    return SPIRE_R * (1.0 - t) ** 0.78


def build_spire(mat_needle, mat_snow, rng):
    h = TREE_HEIGHT - SPIRE_BOTTOM_Y
    objs = []

    rings = []
    for i in range(SPIRE_RINGS):
        t = i / (SPIRE_RINGS - 1)
        z = t * h
        c = trunk_center(SPIRE_BOTTOM_Y + z)
        r = max(spire_radius(t), SPIRE_MIN_R)
        ring = []
        for j in range(SPIRE_SEGMENTS):
            a = 2.0 * math.pi * j / SPIRE_SEGMENTS
            spike = 1.0 + (FOLIAGE_SPIKE if j % 2 == 0 else -FOLIAGE_SPIKE)
            spike *= 1.0 + rng.uniform(-FOLIAGE_NOISE, FOLIAGE_NOISE)
            rr = r * spike
            ring.append(Vector((c.x + math.cos(a) * rr - trunk_center(SPIRE_BOTTOM_Y).x,
                                c.y + math.sin(a) * rr - trunk_center(SPIRE_BOTTOM_Y).y,
                                z)))
        rings.append(ring)
    objs.append(build_loft("노충돌_솔잎_꼭대기", rings, mat_needle,
                           location=tuple(trunk_center(SPIRE_BOTTOM_Y)),
                           smooth=False))

    # 첨탑 위쪽에 얹힌 눈 — 같은 원뿔을 조금 부풀려 위로 올린 것
    srings = []
    n_cap = 7
    for i in range(n_cap):
        t = SNOW_CAP_FROM + (1.0 - SNOW_CAP_FROM) * i / (n_cap - 1)
        z = t * h
        r = max(spire_radius(t) * SNOW_SWELL + SNOW_CAP_PAD, SNOW_CAP_MIN_R)
        ring = []
        for j in range(SPIRE_SEGMENTS):
            a = 2.0 * math.pi * j / SPIRE_SEGMENTS
            jit = 1.0 + rng.uniform(-0.07, 0.07)
            ring.append(Vector((math.cos(a) * r * jit,
                                math.sin(a) * r * jit,
                                z + SNOW_LIFT)))
        srings.append(ring)
    objs.append(build_loft("노충돌_눈_꼭대기", srings, mat_snow,
                           location=tuple(trunk_center(SPIRE_BOTTOM_Y)),
                           smooth=False, cap_start=False))

    log(f"꼭대기 첨탑: {SPIRE_BOTTOM_Y:.1f}m → {TREE_HEIGHT:.1f}m, 밑 반지름 {SPIRE_R:.2f}m")
    return objs


# =============================================================================
# 조립
# =============================================================================
def build_tree():
    rng = random.Random(SEED)

    m_bark = make_material("Bark", BARK, 0.92)
    m_bark_dark = make_material("BarkDark", BARK_DARK, 0.95)
    m_bark_light = make_material("BarkLight", BARK_LIGHT, 0.88)
    m_branch = make_material("BranchBark", BRANCH_BARK, 0.90)
    m_needle = make_material("Needle", NEEDLE, 0.85)
    m_snow = make_material("Snow", SNOW, 0.55)
    m_scar = make_material("BarkScar", BARK_SCAR, 0.80)
    m_knot = make_material("Knot", KNOT, 0.95)

    coeffs = make_bark_coeffs(rng)
    trunk = build_trunk(rng, (m_bark, m_bark_dark, m_bark_light), coeffs)
    build_trunk_marks(rng, coeffs, m_knot, m_scar, m_snow)

    items = branch_layout(rng)
    branches = []
    for i, item in enumerate(items, start=1):
        tag = f"{i:02d}"
        branches.append(build_branch(f"가지_{tag}", item, m_branch))
        build_foliage(f"노충돌_솔잎_{tag}", item, m_needle, rng)
        build_branch_snow(f"노충돌_눈_{tag}", item, m_snow, rng)

    build_spire(m_needle, m_snow, rng)

    for layer in range(WHORL_COUNT):
        n = WHORL_BRANCHES[layer]
        log(f"  {layer + 1}층 y={whorl_height(layer):5.2f}m  가지 {n}개  "
            f"길이 {BRANCH_LENGTH * BRANCH_LEN_FACTOR[layer]:.2f}m  "
            f"밑동 반지름 {BRANCH_R_BASE * math.sqrt(BRANCH_LEN_FACTOR[layer]):.3f}m  "
            f"기울기 {BRANCH_PITCH[layer]:+.0f}도")
    log(f"가지 총 {len(branches)}개 (가지_01 ~ 가지_{len(branches):02d})")
    return trunk, branches, items


# =============================================================================
# 내보내기
# =============================================================================
def export_glb(path):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_apply=True,      # 솔리디파이 등 모디파이어를 구워서 내보낸다
        export_animations=False,
        export_yup=True,
    )
    log(f"내보내기: {path} ({os.path.getsize(path):,} bytes)")


def report_polycount(label="씬"):
    """삼각형 수와 서피스(=드로우콜) 수. 성능은 여기서 결정되므로 항상 찍는다."""
    deps = bpy.context.evaluated_depsgraph_get()
    groups = {}
    tris = 0
    surfaces = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(deps)
        try:
            mesh = ev.to_mesh()
        except RuntimeError:
            continue
        t = sum(len(p.vertices) - 2 for p in mesh.polygons)
        slots = len({p.material_index for p in mesh.polygons}) or 1
        ev.to_mesh_clear()
        tris += t
        surfaces += slots
        key = obj.name.split("_")[0]
        g = groups.setdefault(key, [0, 0, 0])
        g[0] += 1
        g[1] += t
        g[2] += slots
    log(f"[폴리] {label}: 삼각형 {tris:,}개 / 서피스(드로우콜) {surfaces}개 / "
        f"메시 데이터블록 {len(bpy.data.meshes)}개")
    for key in sorted(groups, key=lambda k: -groups[k][1]):
        n, t, sfc = groups[key]
        log(f"[폴리]   {key:<6} 오브젝트 {n:>3}개  삼각형 {t:>8,} ({t / max(tris, 1) * 100:4.1f}%)  "
            f"서피스 {sfc:>3}")
    return tris, surfaces


def report_branch_axes(branches):
    """가지의 로컬 +X 가 실제로 뻗어나간 방향인지 블렌더 쪽에서 먼저 확인한다."""
    # rotation_euler 를 직접 대입했으므로 matrix_world 는 아직 갱신 전이다.
    # 갱신하지 않고 읽으면 회전이 없는 것처럼 보인다.
    bpy.context.view_layer.update()
    log("가지 축 점검 (블렌더 Z-up 기준, 로컬 +X 의 월드 방향):")
    for obj in branches:
        ax = (obj.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()
        az = math.degrees(math.atan2(ax.y, ax.x))
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, ax.z))))
        log(f"  {obj.name}  원점=({obj.location.x:+.2f},{obj.location.y:+.2f},"
            f"{obj.location.z:5.2f})  +X=({ax.x:+.3f},{ax.y:+.3f},{ax.z:+.3f})  "
            f"방위각 {az:+7.1f}도  기울기 {pitch:+5.1f}도")


# =============================================================================
# 미리보기 렌더
# =============================================================================
_WORLD_READY = False


def setup_render_world():
    global _WORLD_READY
    scene = bpy.context.scene
    if _WORLD_READY:
        return scene
    _WORLD_READY = True

    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue

    key = bpy.data.lights.new("Key", "SUN")
    key.energy = 3.4
    key_obj = bpy.data.objects.new("Key", key)
    key_obj.rotation_euler = (rad(50), rad(10), rad(35))
    bpy.context.collection.objects.link(key_obj)

    fill = bpy.data.lights.new("Fill", "SUN")
    fill.energy = 1.4
    fill_obj = bpy.data.objects.new("Fill", fill)
    fill_obj.rotation_euler = (rad(66), 0, rad(-125))
    bpy.context.collection.objects.link(fill_obj)

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.55, 0.66, 0.80, 1.0)
    bg.inputs[1].default_value = 0.9
    scene.world = world
    return scene


def scene_bounds(skip_prefix=None):
    """모디파이어까지 적용된 실제 형상의 경계 상자."""
    deps = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    found = False
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if skip_prefix and obj.name.startswith(skip_prefix):
            continue
        ev = obj.evaluated_get(deps)
        try:
            mesh = ev.to_mesh()
        except RuntimeError:
            continue
        for v in mesh.vertices:
            p = obj.matrix_world @ v.co
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
            found = True
        ev.to_mesh_clear()
    if not found:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return lo, hi


_GROUND = None


def add_render_ground(radius=None):
    """미리보기 전용 설원 바닥. 내보내기가 끝난 뒤에만 만든다 (지형은 이번 범위 밖)."""
    global _GROUND
    if _GROUND is not None:
        return _GROUND
    if radius is None:
        radius = TREE_HEIGHT * 4.0
    n = 48
    ring = [Vector((math.cos(2 * math.pi * i / n) * radius,
                    math.sin(2 * math.pi * i / n) * radius, 0.0)) for i in range(n)]
    inner = [Vector((p.x * 0.001, p.y * 0.001, 0.0)) for p in ring]
    mat = make_material("RenderGround", (0.80, 0.85, 0.93, 1.0), 0.85)
    _GROUND = build_loft("렌더용바닥", [inner, ring], mat, smooth=False,
                         cap_start=False, cap_end=False)
    return _GROUND


def _render_views(scene, views, tile_w, tile_h, tmp_dir, lens=55):
    """views: (이름, 방위각도, 고도도, 거리m, 주시점Vector) 목록."""
    import numpy as np
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = lens
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x = tile_w
    scene.render.resolution_y = tile_h
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    tiles = []
    for idx, (name, azim, elev, dist, target) in enumerate(views):
        a, e = rad(azim), rad(elev)
        offset = Vector((math.cos(a) * math.cos(e),
                         math.sin(a) * math.cos(e),
                         math.sin(e))) * dist
        cam.location = target + offset
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()

        tmp = os.path.join(tmp_dir, f"_view_{idx}.png")
        scene.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(tmp)
        w, h = img.size
        tiles.append(np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4))
        bpy.data.images.remove(img)
        os.remove(tmp)

    bpy.data.objects.remove(cam, do_unlink=True)
    return tiles


def _save_sheet(sheet, path):
    H, W = sheet.shape[0], sheet.shape[1]
    out = bpy.data.images.new(os.path.basename(path), W, H, alpha=True)
    out.pixels = sheet.reshape(-1).tolist()
    out.filepath_raw = os.path.abspath(path)
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    return W, H


## 보는 방향 (이름, 방위각, 고도, 거리배율)
## 이름에 '/' 를 쓰면 임시 파일 경로가 폴더로 갈라지므로 쓰지 않는다.
VIEWS = [
    ("정면",   -90.0,  4.0, 2.75),
    ("측면",     0.0,  4.0, 2.75),
    ("3-4앞",  -50.0, 16.0, 2.75),
    ("위",     -70.0, 62.0, 2.75),
]


def render_preview(path, tile_w=400, tile_h=680):
    import numpy as np

    scene = setup_render_world()
    lo, hi = scene_bounds()
    center = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 0.1)
    log(f"경계: min=({lo.x:.2f},{lo.y:.2f},{lo.z:.2f}) max=({hi.x:.2f},{hi.y:.2f},{hi.z:.2f})  "
        f"크기=({hi.x - lo.x:.2f}, {hi.y - lo.y:.2f}, {hi.z - lo.z:.2f})")

    add_render_ground()
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(tmp_dir, exist_ok=True)

    views = [(n, a, e, radius * f, center) for n, a, e, f in VIEWS]
    tiles = _render_views(scene, views, tile_w, tile_h, tmp_dir)
    top = np.concatenate(tiles[0:2], axis=1)
    bottom = np.concatenate(tiles[2:4], axis=1)
    # 블렌더 픽셀은 아래에서 위로 쌓이므로 위쪽 줄이 배열 뒤에 와야 한다
    W, H = _save_sheet(np.concatenate([bottom, top], axis=0), path)
    log(f"미리보기: {os.path.abspath(path)} ({W}x{H}, {'/'.join(v[0] for v in VIEWS)})")
    return lo, hi


# =============================================================================
# 크기 비교 렌더 — 하늘다람쥐를 나무 옆에 놓아 비율을 확인한다
# (내보내기가 끝난 뒤에만 부른다. 다람쥐가 pine_tree.glb 에 섞이면 안 된다)
# =============================================================================
SQUIRREL_GLB = "models/flying_squirrel.glb"


def import_squirrel():
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(SQUIRREL_GLB))
    except Exception as exc:      # noqa: BLE001 - 비교 렌더는 부가 기능이다
        log(f"비교 렌더 건너뜀: 하늘다람쥐 임포트 실패 ({exc})")
        return None
    new = [o for o in bpy.data.objects if o not in before]

    # glTF 임포터는 본 표시용 'Icosphere' 를 'glTF_not_exported' 컬렉션에
    # 만들어 씬에 남긴다. 원점에 반지름 1짜리 구가 생기므로 경계 계산과
    # 렌더를 모두 망친다. 지우고 간다.
    junk = [o for o in new
            if any(c.name.startswith("glTF_not_exported") for c in o.users_collection)]
    junk_names = sorted(o.name for o in junk)
    new = [o for o in new if o not in junk]
    for o in junk:
        bpy.data.objects.remove(o, do_unlink=True)
    if junk_names:
        log("임포트 부산물 제거: " + ", ".join(junk_names))

    roots = [o for o in new if o.parent is None]
    for o in new:
        o.name = "비교용_" + o.name
        # 임포트하면 NLA 트랙(idle/walk/.../glide)이 함께 딸려와 리그가 눌린다.
        # 비교 렌더는 기본 자세로 봐야 하므로 애니메이션을 떼어내고 포즈를 편다.
        if o.animation_data is not None:
            o.animation_data_clear()
        if o.type == "ARMATURE":
            for pb in o.pose.bones:
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                pb.rotation_euler = (0.0, 0.0, 0.0)
                pb.location = (0.0, 0.0, 0.0)
                pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    return new, roots


def object_group_bounds(objs):
    deps = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for obj in objs:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(deps)
        try:
            mesh = ev.to_mesh()
        except RuntimeError:
            continue
        for v in mesh.vertices:
            p = obj.matrix_world @ v.co
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
        ev.to_mesh_clear()
    return lo, hi


def place_squirrel(roots, objs, location, yaw):
    """다람쥐 무리를 yaw 만큼 돌린 뒤, 발밑이 location.z 에 오도록 놓는다."""
    for r in roots:
        r.rotation_euler = (0.0, 0.0, yaw)
        r.location = Vector((location.x, location.y, 0.0))
    bpy.context.view_layer.update()
    lo, hi = object_group_bounds(objs)
    dz = location.z - lo.z
    for r in roots:
        r.location = Vector((location.x, location.y, dz))
    bpy.context.view_layer.update()
    return object_group_bounds(objs)


def render_comparison(path, items, tile_w=480, tile_h=720):
    import numpy as np

    scene = setup_render_world()

    # 가장 낮은 층에서 가장 긴 가지를 고른다
    item = min(items, key=lambda it: (it["layer"], -it["length"]))
    az, pitch, L = item["az"], item["pitch"], item["length"]
    d = Vector((math.cos(pitch) * math.cos(az),
                math.cos(pitch) * math.sin(az),
                math.sin(pitch)))
    along = L * 0.40
    r_here = branch_radius_at(item, along)
    perch = item["origin"] + d * along + Vector((0, 0, r_here))

    first = import_squirrel()
    if first is None:
        return
    objs_a, roots_a = first
    objs_b, roots_b = import_squirrel()

    slo, shi = object_group_bounds(objs_a)
    log(f"하늘다람쥐 실측(기본 자세): 폭 {shi.x - slo.x:.2f}m  길이 {shi.y - slo.y:.2f}m  "
        f"높이 {shi.z - slo.z:.2f}m")
    log(f"가지 굵기 비교: 앉힌 지점 반지름 {r_here:.3f}m (지름 {r_here * 2:.3f}m), "
        f"기둥 밑동 지름 {trunk_radius(0.3 * SCALE) * 2:.2f}m, 플레이어 캡슐 지름 0.76m")

    # 1) 가지 위 — 가지가 뻗은 방향(+X)을 바라보게 놓는다.
    #    모델의 앞쪽은 블렌더 -Y 이므로 yaw = az + 90도.
    a_lo, a_hi = place_squirrel(roots_a, objs_a, perch, az + math.pi / 2)
    # 2) 기둥 밑동 옆 — 기둥 굵기와의 비교
    base_at = Vector((trunk_radius(0.3 * SCALE) + 1.3 * SCALE, 0.0, 0.0))
    place_squirrel(roots_b, objs_b, base_at, rad(205.0))

    lo, hi = scene_bounds()
    center = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 0.1)

    add_render_ground()

    perch_center = (a_lo + a_hi) * 0.5
    # 가지를 가로질러 보는 각도라야 굵기가 보인다
    cross = math.degrees(az) + 118.0

    views = [
        ("전체",        -75.0, 12.0, radius * 2.7, center),
        ("가지위접사",   cross,  6.0, 6.2 * SCALE, perch_center),
        ("밑동접사",     -55.0,  8.0, 7.0 * SCALE,
         Vector((base_at.x * 0.4, 0.0, 1.3 * SCALE))),
    ]
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    tiles = _render_views(scene, views, tile_w, tile_h, tmp_dir)

    W, H = _save_sheet(np.concatenate(tiles, axis=1), path)
    log(f"크기 비교: {os.path.abspath(path)} ({W}x{H}, {'/'.join(v[0] for v in views)})")


# =============================================================================
# 기둥 밀착 렌더 — "붙어 있을 때 자기가 움직이는지 알 수 있는가" 를 확인한다.
# 한 장만 봐서는 알 수 없다. 카메라를 조금씩 옮긴 연속 컷을 나란히 놓고,
# 프레임 사이에 화면이 실제로 달라지는지 본다.
# =============================================================================
CLING_CAM_GAP = 6.0        # 기둥 표면에서 카메라까지 거리 (m). 3인칭 카메라 거리.
CLING_BASE_Y = 120.0       # 관찰 높이 (m) — 가장 낮은 가지 언저리
CLING_CLIMB_STEP = 9.0     # 오르내림 컷 사이의 높이 차 (m) = walk_speed 4.5 로 2초
CLING_TURN_STEP = 11.0     # 도는 컷 사이의 방위각 차 (도)


def _cling_quat(th):
    """기둥의 방위각 th 면에 배를 대고 머리를 위로 든 자세.

    모델은 -Y 가 앞, +Z 가 위다. 배(-Z)가 기둥 축(-반경 방향)을 향하고
    앞(-Y)이 하늘(+Z)을 향하게 돌린다. 열은 각각 모델의 X/Y/Z 축이 갈 방향.
    """
    from mathutils import Matrix
    s, c = math.sin(th), math.cos(th)
    return Matrix(((s, 0.0, c), (-c, 0.0, s), (0.0, -1.0, 0.0))).to_quaternion()


def _put_squirrel_on_trunk(roots, objs, y, az):
    """다람쥐 무리를 높이 y, 방위각 az 인 기둥 표면에 붙인다. 배쪽을 3cm 파묻는다."""
    quat = _cling_quat(az)
    for r in roots:
        r.rotation_mode = "QUATERNION"      # glTF 루트는 쿼터니언이다. 오일러는 무시된다.
        r.rotation_quaternion = quat
        r.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    n = Vector((math.cos(az), math.sin(az), 0.0))
    lo, hi = object_group_bounds(objs)
    center = (lo + hi) * 0.5
    surf = trunk_radius(y)
    delta = (n * (surf - 0.03 - (lo - center).dot(n) - center.dot(n))
             + Vector((0.0, 0.0, y - center.z)))
    for r in roots:
        r.location = Vector(r.location) + delta
    bpy.context.view_layer.update()
    return object_group_bounds(objs)


def render_cling(path, tile_w=430, tile_h=560):
    """기둥에 바짝 붙은 카메라. 위 줄 = 기둥을 오르는 4컷, 아래 줄 = 도는 4컷.

    ★ 다람쥐를 실제로 붙여 놓고 찍는다. 크기 기준이 화면에 없으면
      '움직임이 읽히는가' 를 판단할 수 없다.
    """
    import numpy as np

    scene = setup_render_world()
    add_render_ground()
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(tmp_dir, exist_ok=True)

    got = import_squirrel()
    sq_objs, sq_roots = got if got else ([], [])

    def view(name, y, az_deg):
        az = rad(az_deg)
        c = trunk_center(y)
        r = trunk_radius(y)
        target = Vector((c.x + math.cos(az) * r, c.y + math.sin(az) * r, y))
        return (name, az_deg, 0.0, CLING_CAM_GAP, target)

    def shots(views):
        out = []
        for v in views:
            if sq_roots:
                _put_squirrel_on_trunk(sq_roots, sq_objs, v[4].z,
                                       math.atan2(v[4].y - trunk_center(v[4].z).y,
                                                  v[4].x - trunk_center(v[4].z).x))
            out.extend(_render_views(scene, [v], tile_w, tile_h, tmp_dir, lens=32))
        return out

    climb = [view(f"오름 +{i * CLING_CLIMB_STEP:.0f}m",
                  CLING_BASE_Y + i * CLING_CLIMB_STEP, 24.0) for i in range(4)]
    turn = [view(f"돎 +{i * CLING_TURN_STEP:.0f}도",
                 CLING_BASE_Y, 24.0 + i * CLING_TURN_STEP) for i in range(4)]

    tiles_c = shots(climb)
    tiles_t = shots(turn)

    # 프레임 사이 화면 변화량을 수치로 잰다. 눈으로만 보면 자기기만하기 쉽다.
    def diff(tiles):
        return [float(np.abs(tiles[i + 1][..., :3] - tiles[i][..., :3]).mean())
                for i in range(len(tiles) - 1)]

    dc, dt = diff(tiles_c), diff(tiles_t)
    log(f"[밀착] 기둥 표면에서 {CLING_CAM_GAP:.1f}m 떨어진 카메라, 높이 {CLING_BASE_Y:.0f}m")
    log(f"[밀착] 오름 {CLING_CLIMB_STEP:.0f}m 마다 화면 평균 변화 "
        + " / ".join(f"{d * 100:.2f}%" for d in dc))
    log(f"[밀착] 돎 {CLING_TURN_STEP:.0f}도 마다 화면 평균 변화 "
        + " / ".join(f"{d * 100:.2f}%" for d in dt))

    top = np.concatenate(tiles_c, axis=1)
    bottom = np.concatenate(tiles_t, axis=1)
    w, h = _save_sheet(np.concatenate([bottom, top], axis=0), path)
    log(f"[밀착] {os.path.abspath(path)} ({w}x{h}) — 위줄 오름 4컷 / 아래줄 돎 4컷")


# =============================================================================
def main():
    out, preview = parse_args()
    clear_scene()

    trunk, branches, items = build_tree()
    report_branch_axes(branches)
    report_polycount("소나무 1그루")

    mesh_names = sorted(o.name for o in bpy.context.scene.objects if o.type == "MESH")
    log(f"오브젝트 {len(mesh_names)}개: " + ", ".join(mesh_names))

    export_glb(out)

    # 아래는 전부 내보내기 이후 — 렌더 전용 오브젝트가 glb 에 섞이지 않게 한다
    if preview:
        render_preview(preview)
        base, ext = os.path.splitext(preview)
        render_cling(base + "_기둥밀착" + ext)
        render_comparison(base + "_크기비교" + ext, items)

    log("완료")


# build_area_forest.py 가 이 파일을 모듈로 import 해서 build_tree() 를 재사용한다.
# 블렌더가 --python 으로 직접 실행하면 __name__ 은 "__main__" 이므로 기존 동작 그대로다.
if __name__ == "__main__":
    main()
