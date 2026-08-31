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
# 치수 — 기획서에 수치가 없어 PD 가 정한 잠정치.
# 근거: player.gd 의 활공 성능(glide_speed 10.5 / glide_max_fall 2.4,
#       활공비 약 4.4:1). 사용자 확인 후 바뀔 수 있으므로 전부 여기 모아 둔다.
# 숫자를 아래 코드 본문에 흩뿌리지 말 것.
# =============================================================================

TREE_HEIGHT = 18.0            # 나무 전체 높이 (m)

# --- 기둥 -------------------------------------------------------------------
TRUNK_R_BASE = 0.50           # 밑동 반지름 (뿌리 벌어짐 제외)
TRUNK_R_TOP = 0.055           # 꼭대기 반지름
TRUNK_TAPER = 1.25            # 가늘어지는 곡선의 지수 (클수록 아래가 굵음)
TRUNK_FLARE = 0.42            # 밑동 뿌리 벌어짐 배율
TRUNK_FLARE_FALLOFF = 1.15    # 벌어짐이 사라지는 속도 (1/m)
TRUNK_LEAN = 0.16             # 기둥이 휘는 폭 (m)
TRUNK_SEGMENTS = 16           # 단면 분할
TRUNK_RINGS = 26              # 높이 분할
TRUNK_NOISE = 0.045           # 껍질 요철 (반지름 비율)

# --- 가지 층(윤생지) --------------------------------------------------------
WHORL_COUNT = 4               # 층 수
WHORL_LOWEST_Y = 5.5          # 가장 낮은 가지 높이 (지면에서 5m 이상)
WHORL_TOP_Y = 14.0            # 가장 높은 층의 높이
WHORL_SPACING_BIAS = 0.85     # <1 이면 위로 갈수록 층 간격이 좁아진다
WHORL_BRANCHES = (4, 4, 3, 3)   # 층별 가지 수 (아래→위, 층당 3~4개)
WHORL_TWIST = 41.0            # 층마다 방위각을 이만큼 돌려 가지가 겹치지 않게
WHORL_JITTER = 9.0            # 방위각 흔들림 (도)

# --- 가지 -------------------------------------------------------------------
BRANCH_LENGTH = 4.0           # 가지 기준 길이 (m)
BRANCH_LEN_FACTOR = (1.15, 1.00, 0.85, 0.70)   # 층별 길이 배율 (아래가 길다)
BRANCH_R_BASE = 0.12          # 밑동 쪽 반지름 — 플레이어가 올라탈 굵기
BRANCH_R_TIP_RATIO = 0.32     # 끝 반지름 / 밑동 반지름
BRANCH_PITCH = (-9.0, -5.0, 1.0, 6.0)          # 층별 기울기(도). 음수는 처짐.
BRANCH_INSET = 0.30           # 기둥 속으로 파묻는 길이 (틈 방지)
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
SPIRE_BOTTOM_Y = 13.6         # 첨탑 솔잎이 시작하는 높이
SPIRE_R = 0.95                # 첨탑 밑 반지름
SPIRE_RINGS = 10
SPIRE_SEGMENTS = 12

# --- 쌓인 눈 ----------------------------------------------------------------
SNOW_ARC = 64.0               # 솔잎 단면 중 눈이 덮이는 각도 (±도). 나머지는 녹색이 보인다.
SNOW_SWELL = 1.02             # 솔잎 표면에서 얼마나 부풀려 얹는가
SNOW_LIFT = 0.06              # 위로 띄우는 높이 (m)
SNOW_THICKNESS = 0.055        # 눈층 두께 (솔리디파이)
SNOW_CAP_FROM = 0.50          # 첨탑의 이 지점 위로만 눈이 덮인다 (0~1)

# --- 색 (텍스처 없는 단색 PBR) ----------------------------------------------
# 하늘다람쥐 몸통은 FUR = (0.45, 0.72, 0.92). 눈 위에서 묻히지 않도록
# 눈은 채도를 거의 없애고 밝기만 높인다.
BARK = (0.115, 0.072, 0.050, 1.0)     # 어두운 갈색
BRANCH_BARK = (0.145, 0.093, 0.064, 1.0)
NEEDLE = (0.032, 0.105, 0.062, 1.0)   # 어두운 침엽수 녹색
SNOW = (0.855, 0.900, 0.960, 1.0)     # 밝은 흰색, 약간 푸른기

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


def build_trunk(rng, mat):
    # 세로로 이어지는 골(ridge). 단면마다 무작위로 하면 껍질이 아니라
    # 노이즈처럼 보이므로, 각도별 배율을 한 번 정해 위아래로 이어지게 한다.
    ridge = [1.0 + rng.uniform(-TRUNK_NOISE, TRUNK_NOISE) for _ in range(TRUNK_SEGMENTS)]
    rings = []
    for i in range(TRUNK_RINGS):
        t = i / (TRUNK_RINGS - 1)
        y = t * TREE_HEIGHT
        c = trunk_center(y)
        r = trunk_radius(y)
        ring = []
        for j in range(TRUNK_SEGMENTS):
            a = 2.0 * math.pi * j / TRUNK_SEGMENTS
            rr = r * ridge[j] * (1.0 + rng.uniform(-TRUNK_NOISE, TRUNK_NOISE) * 0.4)
            ring.append(Vector((c.x + math.cos(a) * rr,
                                c.y + math.sin(a) * rr,
                                y)))
        rings.append(ring)

    obj = build_loft("기둥_main", rings, mat, smooth=True)
    log(f"기둥: 높이 {TREE_HEIGHT:.1f}m, 밑동 반지름 {trunk_radius(0.0):.2f}m "
        f"(벌어짐 포함) / {TRUNK_R_BASE:.2f}m (기준), 꼭대기 {TRUNK_R_TOP:.3f}m")
    return obj


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
            yy = y + rng.uniform(-0.18, 0.18)
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
    w = max(foliage_half_width(u, L) * w_s, 0.04)
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
    cols = 11
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
        r = max(spire_radius(t), 0.02)
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
        r = max(spire_radius(t) * SNOW_SWELL + 0.02, 0.015)
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
    m_branch = make_material("BranchBark", BRANCH_BARK, 0.90)
    m_needle = make_material("Needle", NEEDLE, 0.85)
    m_snow = make_material("Snow", SNOW, 0.55)

    trunk = build_trunk(rng, m_bark)

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


def add_render_ground(radius=30.0):
    """미리보기 전용 설원 바닥. 내보내기가 끝난 뒤에만 만든다 (지형은 이번 범위 밖)."""
    global _GROUND
    if _GROUND is not None:
        return _GROUND
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
        f"기둥 밑동 지름 {trunk_radius(0.3) * 2:.2f}m, 플레이어 캡슐 지름 0.76m")

    # 1) 가지 위 — 가지가 뻗은 방향(+X)을 바라보게 놓는다.
    #    모델의 앞쪽은 블렌더 -Y 이므로 yaw = az + 90도.
    a_lo, a_hi = place_squirrel(roots_a, objs_a, perch, az + math.pi / 2)
    # 2) 기둥 밑동 옆 — 기둥 굵기와의 비교
    base_at = Vector((trunk_radius(0.3) + 1.3, 0.0, 0.0))
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
        ("가지위접사",   cross,  6.0, 6.2, perch_center),
        ("밑동접사",     -55.0,  8.0, 7.0, Vector((base_at.x * 0.4, 0.0, 1.3))),
    ]
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    tiles = _render_views(scene, views, tile_w, tile_h, tmp_dir)

    W, H = _save_sheet(np.concatenate(tiles, axis=1), path)
    log(f"크기 비교: {os.path.abspath(path)} ({W}x{H}, {'/'.join(v[0] for v in views)})")


# =============================================================================
def main():
    out, preview = parse_args()
    clear_scene()

    trunk, branches, items = build_tree()
    report_branch_axes(branches)

    mesh_names = sorted(o.name for o in bpy.context.scene.objects if o.type == "MESH")
    log(f"오브젝트 {len(mesh_names)}개: " + ", ".join(mesh_names))

    export_glb(out)

    # 아래는 전부 내보내기 이후 — 렌더 전용 오브젝트가 glb 에 섞이지 않게 한다
    if preview:
        render_preview(preview)
        base, ext = os.path.splitext(preview)
        render_comparison(base + "_크기비교" + ext, items)

    log("완료")


# build_area_forest.py 가 이 파일을 모듈로 import 해서 build_tree() 를 재사용한다.
# 블렌더가 --python 으로 직접 실행하면 __name__ 은 "__main__" 이므로 기존 동작 그대로다.
if __name__ == "__main__":
    main()
