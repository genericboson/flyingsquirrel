"""시작 지역 「눈 덮인 설원」의 축소판 숲을 만들어 .glb 로 내보낸다.

기획서 원문:
  「눈덮인 소나무로 이루어진 소나무 숲이 무대이고, 시간상 겨울이다.」
  「하늘 다람쥐는 여기저기의 소나무 사이를 활강하면서 목적지까지 이동해야한다.」
  「이 지역의 반대편 쪽의 다음 지역으로 가는 병목지점까지 가면 다음 지역으로 전환된다.」

규모 (요구사항.md M2 — 축소판 / 2026-08-31 사용자가 축척 N=16 확정):
  소나무 9그루 / 나무는 1935m 사방 안 / 눈 지면은 여유를 둔 2515m 사방 /
  나무 간격 356~468m / 한쪽 구석에서 반대쪽 구석으로 이어지는 사슬 형태.
  옛 축척(100m 사방 / 간격 18~26m)에 build_pine_tree.SCALE = 19.347 을 곱한 값이다.
  왜 활공 거리(1529m)가 아니라 이 간격인지는 아래 LAYOUT_NOTE 에 적었다.
  병목 지점 오브젝트는 형태 미정이라 이번 범위 밖 (만들지 않는다).

코더와의 계약 (오브젝트 이름) — world.gd 가 이 접두사로 충돌 레이어를 나눈다:
  지면_눈          눈 지면. 충돌 생김. 레이어 2 (지형).
  기둥_NN          NN번 나무의 기둥. 충돌 생김. 레이어 3 (나무). NN = 01~09.
  가지_NN_MM       NN번 나무의 MM번 가지. 충돌 생김. 레이어 3 (나무).
                   ★ 각 오브젝트의 로컬 +X 축이 가지가 뻗어나간 방향이다.
                     그래서 배치 회전을 transform_apply 로 메시에 굽지 않는다.
                     나무 전체는 부모 Empty(나무_NN)의 트랜스폼으로만 놓는다.
  노충돌_*         솔잎·쌓인 눈 같은 장식. 충돌 없음.

형상의 원본은 build_pine_tree.py 하나뿐이다. 나무 모양 코드를 여기 복사하지 않고
import 해서 build_tree() 를 부른다. 나무를 고치면 숲도 같이 고쳐진다.

파일 크기: 9그루를 각각 따로 만들면 30MB 가 되므로, 서로 다른 나무 3종만
실제로 만들고 나머지는 **메시 데이터블록을 공유하는 linked duplicate** 로 놓는다.
glTF 익스포터가 같은 메시를 쓰는 오브젝트들을 mesh 하나 + node 여러 개로 내보낸다.

실행:
  blender --background --python blender/build_area_forest.py -- \
      --out models/area_forest.glb --preview 미리보기.png
  또는  bash tools/build_models.sh area_forest --preview
"""
import json
import math
import os
import struct
import sys

import bpy
from mathutils import Vector

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# --- build_pine_tree.py 를 모듈로 불러온다 -----------------------------------
def _blender_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        pass
    for a in sys.argv:
        if a.endswith("build_area_forest.py"):
            return os.path.dirname(os.path.abspath(a))
    return os.path.abspath("blender")


_HERE = _blender_dir()
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# import 때문에 blender/__pycache__/ 가 생기면 저장소가 지저분해진다
sys.dont_write_bytecode = True

import build_pine_tree as pine   # noqa: E402  (sys.path 를 먼저 손봐야 한다)

log = pine.log
rad = pine.rad


# =============================================================================
# 치수 — 요구사항.md 의 M2 정의와 I-계약에서 온 값.
# 나무 자체의 치수는 build_pine_tree.py 에 있다. 여기는 '배치' 만 정한다.
# =============================================================================

# 나무가 N=16 축척(높이 348m / 수관 폭 201m)으로 커졌다. 배치를 그대로 두면
# 9그루가 한 그루 굵기 안에 뭉친다. 배치 전체를 나무와 **같은 배율 S** 로 늘린다.
#
# 왜 활공 거리(1529m)에 맞추지 않는가 — 판단 근거는 이 파일 아래 LAYOUT_NOTE 참고.
S = pine.SCALE                 # 19.347353935 (build_pine_tree.py 가 계산한 값)

TREE_COUNT = 9                 # 소나무 그루 수 (M2: 8~10그루)
TREE_FIELD = 100.0 * S         # 나무가 들어가는 정사각 범위 (m) — 1934.7m
GROUND_SIZE = 130.0 * S        # 눈 지면 한 변 (m) — 2515.2m
GROUND_GRID = 80               # 지면 격자 분할 (칸 수). 한 칸 31.4m.
                               # 28 그대로 두면 한 칸이 90m 라 삼각형 하나가
                               # 다람쥐 74마리 폭이 되어 지면이 각진 판으로 보인다.
GROUND_AMP = (0.85 * S, 0.42 * S, 0.23 * S)   # 기복 진폭 (합 29.0m)
GROUND_WAVE_SCALE = S / 2.2    # 파장 배율. S 를 그대로 쓰면 파장이 2.2km 가 되어
                               # 2.5km 지면에 언덕이 하나뿐이다. 2.2 로 나눠
                               # 파장 360~1170m (나무 간격과 같은 자릿수)로 맞춘다.
TREE_SINK = 0.20 * S           # 밑동을 지면에 파묻는 깊이 (m) — 3.87m

# 나무 3종만 실제로 만들고 나머지는 메시를 공유한다.
# build_pine_tree.py 의 SEED 만 갈아끼우므로 형상 규격은 그대로다
# (가지 방위각·높이 흔들림과 껍질/솔잎 잡음이 달라진다).
VARIANT_SEEDS = (20260831, 71042, 330517)

# 사슬 배치. 지역을 가로지르는 대각축(CHAIN_AXIS_DEG) 위의 진행거리 s 와
# 그 축에 수직인 좌우 흔들림 w 로 적는다. 좌우로 지그재그를 넣어야
# 100m 사방 안에서도 이웃 간격을 18~26m 로 벌릴 수 있다.
CHAIN_AXIS_DEG = 45.0
CHAIN_UNIT = S                 # 아래 (s, w) 는 옛 축척의 m 값. 여기에 이 배율을 곱한다.
CHAIN = (
    # (s, w, 변종, Y축 회전(도), 균일 스케일)
    (-56.0,   6.0, 0,  17.0, 1.02),   # 01 시작 나무 (구석)
    (-42.5,  -6.5, 1, 143.0, 0.90),   # 02
    (-28.0,   7.5, 2, 262.0, 1.10),   # 03
    (-13.0, -11.5, 0,  78.0, 0.95),   # 04
    (  0.0,   6.0, 1, 310.0, 1.06),   # 05
    ( 14.0,  -7.0, 2, 195.0, 0.88),   # 06
    ( 28.5,   8.0, 0, 231.0, 1.13),   # 07
    ( 42.0,  -6.0, 1,  55.0, 0.99),   # 08
    ( 56.0,   7.0, 2, 128.0, 0.86),   # 09 반대쪽 구석 (병목 지점이 놓일 방향)
)

# --- 배치를 이렇게 정한 이유 --------------------------------------------------
LAYOUT_NOTE = """\
N=16 에서 서로 부딪히는 두 숫자:
  · 한 번 활공하면 1529m 를 간다 (활공비 4.375 × 나무 높이 348m).
  · 수관 폭이 201m 다.

간격을 활공 거리(1529m)에 맞추면 9그루 사슬이 12km 가 되고 지면은 13km 가 된다.
지면 폴리곤도, 안개 설정도, 이동 시간도 전부 무너진다. 그리고 실제로 그렇게 놓으면
'최고점에서 정확히 떠서 지면 높이까지 내려와야 겨우 닿는다' — 여유가 0 이라
한 번만 삐끗해도 추락이다. 게임으로서 나쁜 수치다.

그래서 **배치 전체를 나무와 같은 배율 S 로 늘렸다.** 결과:
  · 이웃 간격 356~468m (평균 395m)
  · 수관 폭 201m → 수관 사이가 155~267m 벌어져 서로 닿지는 않는다.
    다만 눈높이에서는 나무 한 그루가 화면을 가득 채우고 그 뒤로 다음 나무가 겹쳐
    보이므로 '숲' 으로 읽힌다 (_preview/area_forest.png 의 눈높이 컷).
  · 활공 예산이 나무 높이에 그대로 대응한다:
      가장 낮은 가지 106m 에서 뛰면 465m  → 딱 옆 나무 하나
      2층   가지 171m 에서 뛰면 748m  → 두 그루 건너
      꼭대기       348m 에서 뛰면 1523m → 사슬의 3분의 2
    즉 '얼마나 올라갔는가' 가 '몇 그루를 건너뛰는가' 로 바로 번역된다.
    간격을 수관 폭(201m)까지 좁히면 가장 낮은 가지에서도 두 그루를 건너뛰어
    이 대응이 무너지고, 높이를 올릴 이유가 사라진다.
  · 그루 수는 9 를 유지했다. 줄이면 사슬이 짧아져 지역이 더 빨리 끝나지만,
    요구사항 M2 가 8~10그루를 요구하고 폴리곤은 그루 수에 비례하므로
    성능 문제가 확인되기 전에는 명세를 지킨다.
"""

GROUND_SNOW_ROUGHNESS = 0.90   # 넓은 면이라 나무 위의 눈보다 무광으로

BRANCH_AXIS_TOL_DEG = 1.0      # 가지 +X 축 검증 허용 오차


# =============================================================================
# 지면
# =============================================================================
def ground_height(x, y):
    """지면의 높이(m). 나무를 앉힐 때도 이 함수를 쓴다. 최대 진폭 ±1.5m."""
    a0, a1, a2 = GROUND_AMP
    k = 1.0 / GROUND_WAVE_SCALE
    return (a0 * math.sin(x * 0.0555 * k + 0.70) * math.cos(y * 0.0472 * k - 0.31)
            + a1 * math.sin(x * 0.1080 * k - 1.90) * math.sin(y * 0.0930 * k + 2.20)
            + a2 * math.cos((x + y) * 0.1550 * k + 0.50))


def ground_mesh_height(x, y):
    """실제로 만들어진 격자 메시의 높이 (쌍선형 보간).

    ground_height() 는 매끄러운 곡면이고 메시는 그것을 격자로 근사한 것이라
    둘 사이에 몇 cm 차이가 난다. 나무가 뜨는지 파묻히는지는 이쪽으로 재야 한다.
    """
    half = GROUND_SIZE * 0.5
    step = GROUND_SIZE / GROUND_GRID
    fx = min(max((x + half) / step, 0.0), GROUND_GRID - 1e-6)
    fy = min(max((y + half) / step, 0.0), GROUND_GRID - 1e-6)
    i, j = int(fx), int(fy)
    tx, ty = fx - i, fy - j

    def gz(ii, jj):
        return ground_height(-half + ii * step, -half + jj * step)

    return ((gz(i, j) * (1 - tx) + gz(i + 1, j) * tx) * (1 - ty)
            + (gz(i, j + 1) * (1 - tx) + gz(i + 1, j + 1) * tx) * ty)


def build_ground(mat):
    half = GROUND_SIZE * 0.5
    step = GROUND_SIZE / GROUND_GRID
    n = GROUND_GRID + 1

    verts = []
    for j in range(n):
        for i in range(n):
            x = -half + i * step
            y = -half + j * step
            verts.append((x, y, ground_height(x, y)))

    faces = []
    for j in range(GROUND_GRID):
        for i in range(GROUND_GRID):
            a = j * n + i
            faces.append((a, a + 1, a + n + 1, a + n))

    obj = pine.build_mesh_object("지면_눈", verts, faces, mat, smooth=True)
    zs = [v[2] for v in verts]
    log(f"지면_눈: {GROUND_SIZE:.0f}m x {GROUND_SIZE:.0f}m, 격자 {GROUND_GRID}x{GROUND_GRID} "
        f"(한 칸 {step:.1f}m, 정점 {len(verts)}, 사각면 {len(faces)}), "
        f"높이 {min(zs):+.2f} ~ {max(zs):+.2f}m")
    return obj


# =============================================================================
# 나무 원본 3종 만들기
# =============================================================================
def bake_modifiers(obj):
    """모디파이어를 메시에 구워 넣는다.

    쌓인 눈에 SOLIDIFY 가 붙어 있는데, 모디파이어가 달린 채로 linked duplicate 를
    만들면 익스포터가 오브젝트마다 다른 메시로 볼 위험이 있다. 미리 구워서
    모디파이어 없는 순수 메시로 만들어 두면 메시 공유가 확실해진다.
    """
    if not obj.modifiers:
        return
    deps = bpy.context.evaluated_depsgraph_get()
    new_mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(deps))
    old = obj.data
    obj.modifiers.clear()
    obj.data = new_mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)


def build_variant(index, seed):
    """나무 한 종을 실제로 만든다. [(원래이름, 오브젝트)] 를 돌려준다."""
    before = set(bpy.data.objects)
    pine.SEED = seed
    log(f"── 나무 원본 {index + 1}종 (SEED={seed}) ──")
    pine.build_tree()
    created = [o for o in bpy.data.objects if o not in before]

    parts = []
    for obj in created:
        base = obj.name.split(".")[0]          # 두 번째 종부터 붙는 .001 을 뗀다
        bake_modifiers(obj)
        obj.name = f"_원본{index}_{base}"
        obj.data.name = f"원본{index}_{base}"
        parts.append((base, obj))
    return parts


def dedupe_materials():
    """3종을 만드느라 Bark.001 같은 복제 재질이 생겼다. 하나로 합친다."""
    removed = 0
    for mat in list(bpy.data.materials):
        base_name = mat.name.split(".")[0]
        if base_name == mat.name:
            continue
        base = bpy.data.materials.get(base_name)
        if base is None:
            continue
        mat.user_remap(base)
        bpy.data.materials.remove(mat)
        removed += 1
    log(f"재질 정리: 복제본 {removed}개 제거 → "
        + ", ".join(sorted(m.name for m in bpy.data.materials)))


# =============================================================================
# 배치 (linked duplicate)
# =============================================================================
def instance_name(base, nn):
    """원본 이름 → 숲에서 쓸 이름. 접두사는 그대로 두고 나무 번호를 끼워 넣는다."""
    if base.startswith("기둥_"):
        return f"기둥_{nn}"
    head, _, tail = base.rpartition("_")
    if head and tail.isdigit():
        return f"{head}_{nn}_{tail}"      # 가지_07 → 가지_03_07
    return f"{base}_{nn}"                 # 노충돌_솔잎_꼭대기 → ..._꼭대기_03


def chain_positions():
    """사슬 배치의 밑동 좌표 (블렌더 Z-up)."""
    a = rad(CHAIN_AXIS_DEG)
    ux, uy = math.cos(a), math.sin(a)
    px, py = -math.sin(a), math.cos(a)
    out = []
    for s, w, variant, yaw, scale in CHAIN:
        s, w = s * CHAIN_UNIT, w * CHAIN_UNIT
        x = s * ux + w * px
        y = s * uy + w * py
        z = ground_height(x, y) - TREE_SINK
        out.append((Vector((x, y, z)), variant, yaw, scale))
    return out


def place_tree(nn, parts, location, yaw_deg, scale):
    """원본의 메시를 공유하는 나무 한 그루를 놓는다.

    회전·이동은 전부 오브젝트 트랜스폼이고 메시에는 굽지 않는다.
    부모 Empty 는 균일 스케일이므로 자식 가지의 로컬 +X 방향이 보존된다.
    """
    empty = bpy.data.objects.new(f"나무_{nn}", None)
    empty.empty_display_size = 1.5 * S
    empty.location = location
    empty.rotation_euler = (0.0, 0.0, rad(yaw_deg))
    empty.scale = (scale, scale, scale)
    bpy.context.collection.objects.link(empty)

    made = []
    for base, master in parts:
        obj = bpy.data.objects.new(instance_name(base, nn), master.data)
        obj.location = master.location.copy()
        obj.rotation_euler = master.rotation_euler.copy()
        obj.scale = master.scale.copy()
        obj.parent = empty
        bpy.context.collection.objects.link(obj)
        made.append(obj)
    return empty, made


def build_forest():
    m_ground = pine.make_material("GroundSnow", pine.SNOW, GROUND_SNOW_ROUGHNESS)
    build_ground(m_ground)

    variants = [build_variant(i, s) for i, s in enumerate(VARIANT_SEEDS)]
    dedupe_materials()

    placements = chain_positions()
    trees = []
    for k, (loc, variant, yaw, scale) in enumerate(placements, start=1):
        nn = f"{k:02d}"
        empty, made = place_tree(nn, variants[variant], loc, yaw, scale)
        trees.append(dict(nn=nn, empty=empty, objs=made, variant=variant,
                          loc=loc, yaw=yaw, scale=scale))

    # 원본은 지운다. 메시 데이터블록은 인스턴스가 쓰고 있으므로 살아남는다.
    for parts in variants:
        for _, master in parts:
            bpy.data.objects.remove(master, do_unlink=True)

    bpy.context.view_layer.update()
    return trees


# =============================================================================
# 검증
# =============================================================================
def mesh_long_axis(obj):
    """메시 정점에서 직접 잰 가지의 진행 방향 (로컬).

    로컬 +X 를 '가정' 하지 않고, 밑동 쪽 고리와 끝 쪽 고리의 무게중심을 이어
    실제 형상이 어느 쪽으로 뻗었는지 잰다. 회전이 메시에 구워졌다면 여기서 어긋난다.
    """
    co = [v.co for v in obj.data.vertices]
    xs = [p.x for p in co]
    lo, hi = min(xs), max(xs)
    band = (hi - lo) * 0.08
    a = [p for p in co if p.x <= lo + band]
    b = [p for p in co if p.x >= hi - band]
    ca = sum(a, Vector()) / len(a)
    cb = sum(b, Vector()) / len(b)
    return (cb - ca).normalized()


def report_branch_axes(trees):
    """가지의 로컬 +X 가 실제로 뻗어나간 방향인지 블렌더 쪽에서 확인한다."""
    bpy.context.view_layer.update()
    worst = 0.0
    worst_name = ""
    ok = 0
    total = 0
    for tree in trees:
        for obj in tree["objs"]:
            if not obj.name.startswith("가지_"):
                continue
            total += 1
            m3 = obj.matrix_world.to_3x3()
            geo = (m3 @ mesh_long_axis(obj)).normalized()
            axis = (m3 @ Vector((1, 0, 0))).normalized()
            err = math.degrees(math.acos(max(-1.0, min(1.0, geo.dot(axis)))))
            if err <= BRANCH_AXIS_TOL_DEG:
                ok += 1
            if err > worst:
                worst, worst_name = err, obj.name
    log(f"[검증] 블렌더 씬: 가지 {total}개 중 {ok}개가 로컬 +X = 실제 가지 방향 "
        f"(허용 {BRANCH_AXIS_TOL_DEG:.1f}도, 최대 오차 {worst:.4f}도 @ {worst_name or '-'})")
    return total, ok, worst


def report_layout(trees):
    """밑동 좌표(Godot 기준)와 이웃 간격. 코더가 시작 위치를 잡는 데 쓴다."""
    log("[배치] 나무별 밑동 — Godot 좌표 (x, y=위, z) / 블렌더 (x, y, z)")
    embeds = []
    for t in trees:
        b = t["loc"]
        gz = ground_mesh_height(b.x, b.y)
        embed = gz - b.z          # 양수면 밑동이 지면 아래로 파묻힌 깊이
        embeds.append(embed)
        log(f"  나무_{t['nn']}  Godot=({b.x:+7.2f}, {b.z:+6.2f}, {-b.y:+7.2f})  "
            f"블렌더=({b.x:+7.2f}, {b.y:+7.2f}, {b.z:+6.2f})  "
            f"변종{t['variant'] + 1}  회전 {t['yaw']:5.1f}도  스케일 {t['scale']:.2f}  "
            f"높이 {pine.TREE_HEIGHT * t['scale']:5.2f}m  파묻힘 {embed * 100:+5.1f}cm")
    log(f"[배치] 밑동 파묻힘: 최소 {min(embeds) * 100:+.1f}cm  최대 {max(embeds) * 100:+.1f}cm "
        f"(음수면 떠 있는 것)")

    pos = [t["loc"] for t in trees]
    steps = [(pos[i + 1] - pos[i]).length for i in range(len(pos) - 1)]
    log("[배치] 이웃(사슬 순서) 간격: "
        + "  ".join(f"{i + 1}→{i + 2} {d:.1f}m" for i, d in enumerate(steps)))
    log(f"[배치] 간격 최소 {min(steps):.1f}m / 최대 {max(steps):.1f}m / 평균 "
        f"{sum(steps) / len(steps):.1f}m")

    allmin = min(((pos[i] - pos[j]).length, i + 1, j + 1)
                 for i in range(len(pos)) for j in range(i + 1, len(pos)))
    log(f"[배치] 사슬 순서를 무시한 최단 거리: {allmin[0]:.1f}m "
        f"(나무_{allmin[1]:02d} ↔ 나무_{allmin[2]:02d})")

    xs = [p.x for p in pos]
    ys = [p.y for p in pos]
    log(f"[배치] 나무가 차지한 범위: x {min(xs):+.1f}~{max(xs):+.1f}m  "
        f"y {min(ys):+.1f}~{max(ys):+.1f}m  (허용 ±{TREE_FIELD / 2:.0f}m)")
    return steps


def report_objects():
    names = [o.name for o in bpy.context.scene.objects if o.type == "MESH"]
    counts = dict(
        기둥=sum(1 for n in names if n.startswith("기둥_")),
        가지=sum(1 for n in names if n.startswith("가지_")),
        노충돌=sum(1 for n in names if n.startswith("노충돌")),
        지면=sum(1 for n in names if n.startswith("지면_")),
    )
    other = [n for n in names
             if not n.startswith(("기둥_", "가지_", "노충돌", "지면_"))]
    log(f"[씬] 메시 오브젝트 {len(names)}개 — 기둥_ {counts['기둥']}, 가지_ {counts['가지']}, "
        f"노충돌_ {counts['노충돌']}, 지면_눈 {counts['지면']}")
    if other:
        log(f"[씬] ★ 계약에 없는 이름: {', '.join(other)}")
    log(f"[씬] 메시 데이터블록 {len(bpy.data.meshes)}개 (공유되므로 오브젝트 수보다 적어야 정상)")
    return counts


# =============================================================================
# 내보낸 .glb 를 직접 열어 확인한다 (빌드 로그만 믿지 않는다)
# =============================================================================
def _glb_chunks(path):
    with open(path, "rb") as f:
        magic, _ver, _total = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise ValueError("glTF 파일이 아닙니다")
        js = None
        bin_ = b""
        while True:
            head = f.read(8)
            if len(head) < 8:
                break
            clen, ctype = struct.unpack("<I4s", head)
            data = f.read(clen)
            if ctype == b"JSON":
                js = json.loads(data.decode("utf-8"))
            elif ctype.startswith(b"BIN"):
                bin_ = data
    return js, bin_


def _accessor_vec3(j, blob, idx):
    import numpy as np
    acc = j["accessors"][idx]
    if acc["componentType"] != 5126 or acc["type"] != "VEC3":
        return None
    bv = j["bufferViews"][acc["bufferView"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    n = acc["count"]
    stride = bv.get("byteStride") or 12
    raw = np.frombuffer(blob, dtype=np.uint8,
                        count=stride * (n - 1) + 12, offset=start)
    idxs = (np.arange(n) * stride)[:, None] + np.arange(12)[None, :]
    return raw[idxs].copy().view(np.float32).reshape(n, 3)


def _node_matrices(j):
    """glTF 노드의 월드 행렬을 전부 계산한다 (Y-up 좌표계 = Godot 과 같은 축)."""
    import numpy as np
    nodes = j.get("nodes", [])
    parent = {}
    for i, nd in enumerate(nodes):
        for c in nd.get("children", []):
            parent[c] = i

    def local(nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], dtype=np.float64).reshape(4, 4).T
        m = np.eye(4)
        if "rotation" in nd:
            x, y, z, w = nd["rotation"]
            m[:3, :3] = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        if "scale" in nd:
            m[:3, :3] = m[:3, :3] @ np.diag(nd["scale"])
        if "translation" in nd:
            m[:3, 3] = nd["translation"]
        return m

    world = {}

    def solve(i):
        if i in world:
            return world[i]
        m = local(nodes[i])
        p = parent.get(i)
        world[i] = m if p is None else solve(p) @ m
        return world[i]

    for i in range(len(nodes)):
        solve(i)
    return world


def verify_glb(path, trees):
    """내보낸 결과를 다시 열어 이름 계약·배치·가지 +X 축을 확인한다."""
    import numpy as np

    j, blob = _glb_chunks(path)
    nodes = j.get("nodes", [])
    names = [nd.get("name", "") for nd in nodes]
    log(f"[glb] 노드 {len(nodes)}개, 메시 {len(j.get('meshes', []))}개, "
        f"재질 {len(j.get('materials', []))}개, 버퍼 {len(blob):,} bytes")
    log(f"[glb] 이름별: 기둥_ {sum(1 for n in names if n.startswith('기둥_'))}, "
        f"가지_ {sum(1 for n in names if n.startswith('가지_'))}, "
        f"노충돌 {sum(1 for n in names if n.startswith('노충돌'))}, "
        f"지면_눈 {sum(1 for n in names if n == '지면_눈')}, "
        f"나무_ {sum(1 for n in names if n.startswith('나무_'))}")

    world = _node_matrices(j)

    # 기둥 노드가 실제로 사슬 위치에 놓였는지 — 부모 Empty 가 내보내기에서
    # 빠지면 나무가 전부 원점에 겹치므로 여기서 반드시 걸린다.
    log("[glb] 기둥 노드의 월드 좌표 (Godot 축) vs 배치 의도:")
    worst_pos = 0.0
    for t in trees:
        idx = names.index(f"기둥_{t['nn']}")
        p = world[idx][:3, 3]
        b = t["loc"]
        want = np.array([b.x, b.z, -b.y])
        d = float(np.linalg.norm(p - want))
        worst_pos = max(worst_pos, d)
        log(f"[glb]   기둥_{t['nn']}  ({p[0]:+7.2f}, {p[1]:+6.2f}, {p[2]:+7.2f})  "
            f"오차 {d * 1000:.2f}mm")
    log(f"[glb] 밑동 위치 최대 오차 {worst_pos * 1000:.2f}mm "
        + ("(정상)" if worst_pos < 0.001 else "★ 어긋남!"))

    # 메시별 로컬 진행 방향은 한 번만 재고 인스턴스끼리 재사용한다
    axis_cache = {}

    def local_axis(mesh_idx):
        if mesh_idx in axis_cache:
            return axis_cache[mesh_idx]
        prim = j["meshes"][mesh_idx]["primitives"][0]
        pos = _accessor_vec3(j, blob, prim["attributes"]["POSITION"])
        xs = pos[:, 0]
        lo, hi = float(xs.min()), float(xs.max())
        band = (hi - lo) * 0.08
        a = pos[xs <= lo + band].mean(axis=0)
        b = pos[xs >= hi - band].mean(axis=0)
        d = b - a
        axis_cache[mesh_idx] = (d / np.linalg.norm(d), hi - lo,
                                float(np.ptp(pos[:, 1])), float(np.ptp(pos[:, 2])))
        return axis_cache[mesh_idx]

    total = ok = 0
    worst = 0.0
    worst_name = ""
    samples = []
    for i, nd in enumerate(nodes):
        name = nd.get("name", "")
        if not name.startswith("가지_") or "mesh" not in nd:
            continue
        total += 1
        d_local, ex, ey, ez = local_axis(nd["mesh"])
        m3 = world[i][:3, :3]
        geo = m3 @ d_local
        geo = geo / np.linalg.norm(geo)
        ax = m3 @ np.array([1.0, 0.0, 0.0])
        ax = ax / np.linalg.norm(ax)
        err = math.degrees(math.acos(max(-1.0, min(1.0, float(geo @ ax)))))
        if err <= BRANCH_AXIS_TOL_DEG:
            ok += 1
        if err > worst:
            worst, worst_name = err, name
        if len(samples) < 4:
            p = world[i][:3, 3]
            samples.append(
                f"{name} 원점=({p[0]:+.2f},{p[1]:+.2f},{p[2]:+.2f}) "
                f"+X=({ax[0]:+.3f},{ax[1]:+.3f},{ax[2]:+.3f}) 오차 {err:.3f}도 "
                f"[로컬 X폭 {ex:.2f}m ≫ Y{ey:.2f}/Z{ez:.2f}]")

    log(f"[glb] ★ 가지 +X 축 검증: {total}개 중 {ok}개 일치 "
        f"(허용 {BRANCH_AXIS_TOL_DEG:.1f}도, 최대 오차 {worst:.4f}도 @ {worst_name or '-'})")
    for s in samples:
        log(f"[glb]   예: {s}")
    return total, ok, worst


# =============================================================================
# 미리보기 렌더
# =============================================================================
def view_from(name, cam, target):
    """카메라 위치·주시점을 pine._render_views 가 받는 (방위각, 고도, 거리) 로 바꾼다."""
    off = cam - target
    dist = off.length
    return (name, math.degrees(math.atan2(off.y, off.x)),
            math.degrees(math.asin(off.z / dist)), dist, target)


def render_preview(path, trees, tile_w=680, tile_h=520):
    import numpy as np

    scene = pine.setup_render_world()
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (
        0.62, 0.73, 0.87, 1.0)

    lo, hi = pine.scene_bounds()
    log(f"[렌더] 씬 경계: min=({lo.x:.1f},{lo.y:.1f},{lo.z:.1f}) "
        f"max=({hi.x:.1f},{hi.y:.1f},{hi.z:.1f})")

    a = rad(CHAIN_AXIS_DEG)
    u = Vector((math.cos(a), math.sin(a), 0.0))
    p1 = trees[0]["loc"]
    p3 = trees[2]["loc"]
    p5 = trees[4]["loc"]

    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(tmp_dir, exist_ok=True)

    # 위에서 보는 시점은 지면 정사각형이 화면에서도 정사각형으로 보이게
    # 방위각을 -90도(= -Y 쪽)로 맞춘다. 비스듬히 보면 마름모가 되어 간격 판단이 어렵다.
    eye = 2.0            # 다람쥐 눈높이 (m). ★ 배율을 곱하지 않는다 — 다람쥐는 안 커졌다.
    low = pine.WHORL_LOWEST_Y      # 가장 낮은 가지 높이 106.4m
    top_views = [
        view_from("위에서(숲 전체)",
                  Vector((0.0, -16.0 * S, 114.0 * S)), Vector((-3.0 * S, 3.0 * S, 6.0 * S))),
        view_from("1층 가지 높이(106m)에서 사슬 방향",
                  p1 - u * 88.0 * S + Vector((0, 0, low)), p5 + Vector((0, 0, low))),
    ]
    bottom_views = [
        view_from("다람쥐 눈높이 2m (시작 나무 뒤)",
                  p1 - u * 15.0 * S + Vector((0, 0, eye)), p3 + Vector((0, 0, low * 0.9))),
        view_from("다람쥐 눈높이 2m (숲 한가운데)",
                  p5 + Vector((13.0 * S, -9.0 * S, eye)), p5 + Vector((0, 0, low * 0.9))),
    ]

    tiles_top = pine._render_views(scene, top_views, tile_w, tile_h, tmp_dir, lens=30)
    tiles_bot = pine._render_views(scene, bottom_views, tile_w, tile_h, tmp_dir, lens=30)

    top = np.concatenate(tiles_top, axis=1)
    bottom = np.concatenate(tiles_bot, axis=1)
    # 블렌더 픽셀은 아래에서 위로 쌓이므로 위쪽 줄이 배열 뒤에 와야 한다
    w, h = pine._save_sheet(np.concatenate([bottom, top], axis=0), path)
    log(f"[렌더] 미리보기: {os.path.abspath(path)} ({w}x{h}) — "
        + " / ".join(v[0] for v in top_views + bottom_views))

    # 눈높이 한 장을 크게 — 활강 거리 감각을 눈으로 재려면 넓은 화면이 필요하다
    wide = os.path.splitext(path)[0] + "_눈높이.png"
    tiles = pine._render_views(
        scene,
        [view_from("눈높이", p1 - u * 22.0 * S + Vector((0, 0, eye)),
                   p5 + Vector((0, 0, low * 0.55)))],
        1360, 620, tmp_dir, lens=34)
    w, h = pine._save_sheet(tiles[0], wide)
    log(f"[렌더] 눈높이 와이드: {os.path.abspath(wide)} ({w}x{h})")


# =============================================================================
def main():
    out, preview = pine.parse_args()
    if out == "models/pine_tree.glb":          # 기본값이 넘어온 경우
        out = "models/area_forest.glb"
    pine.clear_scene()

    trees = build_forest()

    report_objects()
    pine.report_polycount("숲 전체")
    report_layout(trees)
    report_branch_axes(trees)
    for line in LAYOUT_NOTE.rstrip().splitlines():
        log("[배치근거] " + line)

    pine.export_glb(out)
    size = os.path.getsize(os.path.abspath(out))
    log(f"[크기] {size / 1024 / 1024:.2f} MB "
        + ("— 12MB 초과! PD 에게 보고 필요" if size > 12 * 1024 * 1024 else "(12MB 이하)"))
    verify_glb(os.path.abspath(out), trees)

    if preview:
        render_preview(preview, trees)

    log("완료")


if __name__ == "__main__":
    main()
