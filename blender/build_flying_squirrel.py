"""하늘다람쥐(Pteromys momonga) 모델 · 뼈대 · 애니메이션을 만들어 .glb 로 내보낸다.

기획서 명세:
  - 주인공, Playable
  - 하늘색 몸통  (FUR 상수 — 임의로 바꾸지 않는다)
  - 귀여운 외모

실사 참고 사진(tools/_docx/flyingsquirrel/media/image1.jpg, image2.jpg)에서 읽은 특징:
  - 몸통이 거의 공처럼 둥글고 통통하다. 목이 보이지 않는다.
  - 머리가 몸에 비해 매우 크고, 눈이 얼굴 폭의 30% 를 차지한다.
  - 귀는 작고 둥글며 머리에 바짝 붙어 거의 안 튀어나온다.
  - 주둥이는 아주 짧고 뭉툭하다. 코는 작다.
  - 손발에 발가락이 뚜렷하다.
  - 활공막은 손목~발목을 잇는 부드러운 곡선이고, 가운데가 처진다.
  - 꼬리는 납작하고 넓은 깃털 모양이며 가장자리가 부스스하다.
  - 등이 어둡고 배가 크림색인 카운터셰이딩.

형상 전략:
  * 색은 **정점 색 블렌딩**으로 낸다. 등/옆/배를 0~1 연속 스코어로 재고
    이웃 정점끼리 평균 내(라플라시안) 부드럽게 만든 뒤 색으로 구워 넣는다.
    재질은 털 하나뿐이고 Base Color 가 그 속성을 읽는다.
    (면 단위로 재질 인덱스를 하드 컷오프하면 경계가 체크무늬처럼 각진다)
  * 몸통·머리 모두 파라메트릭 구를 직접 빚는다. 스킨 모디파이어는 단면이
    사각형이라 섭디비전을 걸어도 옆·위에서 보면 각진 상자로 보인다.
  * 팔다리는 몸통에서 떼어 따로 만들고 뼈 하나에 100% 물린다.
  * 손발·발가락·수염을 따로 만들어 실루엣의 "소시지" 인상을 없앤다.
  * 기본 자세(rest)를 **활공 자세**로 잡는다. 활공막이 펴진 상태로 만들어지므로
    막이 자연스럽고, idle/walk/run/jump 에서 팔다리를 접어 사진처럼 동그랗게 만든다.

실행:
  blender --background --python blender/build_flying_squirrel.py -- \
      --out models/flying_squirrel.glb --preview 미리보기.png
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector, Matrix

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# =============================================================================
# 색
# =============================================================================
def _mix(a, b, t):
    return tuple(a[i] * (1.0 - t) + b[i] * t for i in range(4))


def _desat(c, k):
    """색상(hue)은 그대로 두고 채도만 k 배로 낮춘다.

    자기 자신의 휘도(=회색)를 향해 선형으로 당긴다. R-G, G-B, B-R 차이가 전부
    같은 비율로 줄어들므로 HSV 색상각이 **정확히** 보존되고 채도만 줄어든다.
    (밝기 V 는 조금 내려간다 — 쨍한 원색이 털처럼 가라앉는 데 필요하다)
    """
    y = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    return tuple(y + (c[i] - y) * k for i in range(3)) + (c[3],)


# ★ 기획서 명세는 "하늘색 몸통". 색상각(205.5도)은 그대로 지키고 채도만 낮춰서
#   "장난감 플라스틱"이 아니라 "부드러운 털"로 읽히게 한다. 회갈색으로 바꾸지 않는다.
FUR_HUE = (0.45, 0.72, 0.92, 1.0)          # 원래의 만화적 하늘색 — 채도 51%
FUR_DARK_HUE = (0.275, 0.495, 0.715, 1.0)  # 등쪽 (카운터셰이딩)
COAT_SAT = 0.58                            # 채도 배율 → 실제 채도 약 33% (원래 51%)
COAT_VAL = 0.92                            # 밝기 배율 — 창백한 물빛이 아니라 가라앉은 하늘색

FUR = _desat(FUR_HUE, COAT_SAT)
FUR = tuple(FUR[i] * COAT_VAL for i in range(3)) + (1.0,)
FUR_DARK = _desat(FUR_DARK_HUE, COAT_SAT)
FUR_DARK = tuple(FUR_DARK[i] * COAT_VAL for i in range(3)) + (1.0,)
# 배는 순백에 가까우면 조명에서 날아가 플라스틱으로 보인다. 살짝 내린 크림빛 흰색.
BELLY = (0.885, 0.905, 0.930, 1.0)         # 배 · 뺨 · 활공막 아랫면

FUR_MID = _mix(FUR, BELLY, 0.42)       # 옆구리 — 하늘색에서 크림으로 넘어가는 중간

# 활공막 가장자리. 사진의 하늘다람쥐도 막의 테두리만 뚜렷하게 진하다.
# 균일 배율이라 색상각은 FUR_DARK 와 똑같고 명도만 내려간다.
MEM_EDGE = tuple(FUR_DARK[i] * 0.62 for i in range(3)) + (1.0,)

EAR_INNER = (0.93, 0.70, 0.72, 1.0)
PAW = (0.96, 0.82, 0.80, 1.0)          # 손발바닥 — 사진의 연한 분홍
NOSE = (0.42, 0.26, 0.29, 1.0)
EYE = (0.028, 0.026, 0.035, 1.0)
GLINT = (1.0, 1.0, 1.0, 1.0)
WHISKER = (0.80, 0.83, 0.88, 1.0)

# 블렌더는 Z 가 위, 캐릭터는 -Y 를 향한다.
# glTF 로 내보내면 -Y(앞) 가 Godot 의 +Z 가 되므로 player.gd 의 가정과 맞는다.


# =============================================================================
# 형상 기준점 — 뼈대와 메시가 같은 숫자를 본다
# =============================================================================
#  사진의 실루엣: 머리(큰 공) + 몸통(큰 공) 이 목 없이 바로 붙어 있다.
SPINE = [
    #  이름       위치                            굵기
    ("chestF", Vector((0.00, -0.320, 0.535)), 0.275),
    ("chest",  Vector((0.00, -0.105, 0.550)), 0.370),
    ("mid",    Vector((0.00,  0.105, 0.548)), 0.392),
    ("hips",   Vector((0.00,  0.320, 0.508)), 0.340),
    ("rump",   Vector((0.00,  0.470, 0.470)), 0.205),
]

HEAD = Vector((0.00, -0.628, 0.668))
HR = 0.352                       # ★ 확정된 머리 반지름. 얼굴 부위는 전부 이 배수.

SHOULDER = Vector((0.245, -0.155, 0.505))
WRIST = Vector((0.552, -0.300, 0.348))
HIPJ = Vector((0.238, 0.322, 0.472))
ANKLE = Vector((0.545, 0.462, 0.288))

R_SHOULDER, R_WRIST = 0.132, 0.072
R_HIP, R_ANKLE = 0.158, 0.082

# 활공막 안쪽 부착선 (몸통 안에 묻어 자연스럽게 솟아오르게 한다)
MEM_IN_F = Vector((0.150, -0.340, 0.592))
MEM_IN_B = Vector((0.165, 0.420, 0.566))
MEM_CTRL = Vector((0.668, 0.070, 0.346))   # 손목~발목 사이 바깥으로 부푸는 조절점

# 꼬리 중심선 (s: 0=몸통 안쪽, 1=꼬리 끝)
TAIL_S_BONE = (0.10, 0.40, 0.70, 1.00)


def tail_center(s):
    return Vector((0.0,
                   0.360 + 1.040 * s,
                   0.468 + 0.205 * s - 0.055 * math.sin(math.pi * s)))


def log(msg):
    print(f"[블렌더] {msg}")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = "models/flying_squirrel.glb"
    preview = ""
    posefile = ""
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
        elif a == "--preview" and i + 1 < len(argv):
            preview = argv[i + 1]
        elif a == "--posepreview" and i + 1 < len(argv):
            posefile = argv[i + 1]
    return out, preview, posefile


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


# =============================================================================
# 노이즈 — 털 느낌을 내는 데 쓴다 (파티클 헤어는 glTF 로 안 나가므로 지오메트리로)
# =============================================================================
def _grid3(n, seed):
    return np.random.default_rng(seed).random((n, n, n)).astype(np.float32)


def value_noise3(pts, freq, seed, grid=16):
    """[0,1) 값 노이즈. pts: (N,3) 월드 좌표."""
    g = _grid3(grid, seed)
    p = np.asarray(pts, dtype=np.float32) * freq
    i = np.floor(p).astype(np.int64)
    f = (p - i).astype(np.float32)
    f = f * f * (3.0 - 2.0 * f)
    i0 = i % grid
    i1 = (i + 1) % grid
    x0, y0, z0 = i0[:, 0], i0[:, 1], i0[:, 2]
    x1, y1, z1 = i1[:, 0], i1[:, 1], i1[:, 2]
    fx, fy, fz = f[:, 0], f[:, 1], f[:, 2]
    c00 = g[x0, y0, z0] * (1 - fx) + g[x1, y0, z0] * fx
    c10 = g[x0, y1, z0] * (1 - fx) + g[x1, y1, z0] * fx
    c01 = g[x0, y0, z1] * (1 - fx) + g[x1, y0, z1] * fx
    c11 = g[x0, y1, z1] * (1 - fx) + g[x1, y1, z1] * fx
    c0 = c00 * (1 - fy) + c10 * fy
    c1 = c01 * (1 - fy) + c11 * fy
    return c0 * (1 - fz) + c1 * fz


def fbm3(pts, freq, seed, octaves=3):
    total = np.zeros(len(pts), dtype=np.float32)
    amp, norm, f = 1.0, 0.0, freq
    for o in range(octaves):
        total += amp * value_noise3(pts, f, seed + o * 977)
        norm += amp
        amp *= 0.5
        f *= 2.07
    return total / norm


# =============================================================================
# 메시 만들기
# =============================================================================
def new_obj(name, verts, faces, mats):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()
    for m in mats:
        mesh.materials.append(m)
    for p in mesh.polygons:
        p.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def sphere_verts_faces(seg, ring, deform=None):
    """단위 구. 극은 정점 하나로 모아 이음매를 없앤다."""
    verts = [Vector((0.0, 0.0, 1.0))]
    for i in range(1, ring):
        phi = math.pi * i / ring
        z, r = math.cos(phi), math.sin(phi)
        for j in range(seg):
            th = 2.0 * math.pi * j / seg
            verts.append(Vector((r * math.cos(th), r * math.sin(th), z)))
    verts.append(Vector((0.0, 0.0, -1.0)))
    south = len(verts) - 1

    def idx(i, j):
        return 1 + (i - 1) * seg + (j % seg)

    # 감기 방향은 바깥 법선 기준이다(반시계). 뒤집히면 Godot 의 후면 컬링에서
    # 안이 보이는 사고가 난다. mesh_signed_volume() 으로 반드시 검사한다.
    faces = []
    for j in range(seg):
        faces.append((0, idx(1, j), idx(1, j + 1)))
    for i in range(1, ring - 1):
        for j in range(seg):
            faces.append((idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)))
    for j in range(seg):
        faces.append((south, idx(ring - 1, j + 1), idx(ring - 1, j)))

    if deform is not None:
        verts = [deform(v) for v in verts]
    return verts, faces


def make_sphere(name, center, radii, mats, seg=20, ring=12, basis=None, deform=None):
    v, f = sphere_verts_faces(seg, ring, deform)
    R = Vector(radii)
    out = []
    for p in v:
        q = Vector((p.x * R.x, p.y * R.y, p.z * R.z))
        if basis is not None:
            q = basis @ q
        out.append(center + q)
    return new_obj(name, out, f, mats)


def make_tube(name, path, radii, mats, seg=8, cap=True):
    """path 를 따라가는 원형 단면 관. radii 는 마디마다의 반지름."""
    verts, faces = [], []
    n = len(path)
    for i in range(n):
        c = Vector(path[i])
        fwd = (Vector(path[min(i + 1, n - 1)]) - Vector(path[max(i - 1, 0)]))
        if fwd.length < 1e-6:
            fwd = Vector((0, 0, 1))
        fwd.normalize()
        up = Vector((0, 0, 1))
        if abs(fwd.dot(up)) > 0.95:
            up = Vector((0, 1, 0))
        a = fwd.cross(up).normalized()
        b = fwd.cross(a).normalized()
        for j in range(seg):
            th = 2 * math.pi * j / seg
            verts.append(c + (a * math.cos(th) + b * math.sin(th)) * radii[i])
    for i in range(n - 1):
        for j in range(seg):
            p0 = i * seg + j
            p1 = i * seg + (j + 1) % seg
            p2 = (i + 1) * seg + (j + 1) % seg
            p3 = (i + 1) * seg + j
            faces.append((p0, p1, p2, p3))
    if cap:
        tip = len(verts)
        verts.append(Vector(path[-1]) + (Vector(path[-1]) - Vector(path[-2])).normalized() * radii[-1])
        base = (n - 1) * seg
        for j in range(seg):
            faces.append((tip, base + j, base + (j + 1) % seg))
        s0 = len(verts)
        verts.append(Vector(path[0]) - (Vector(path[1]) - Vector(path[0])).normalized() * radii[0] * 0.6)
        for j in range(seg):
            faces.append((s0, (j + 1) % seg, j))
    return new_obj(name, verts, faces, mats)


def bake_modifiers(obj):
    """모디파이어를 실제 면으로 굽는다. 이렇게 해야 면 단위 색 구역과 정점 노이즈를 쓸 수 있다."""
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    me = bpy.data.meshes.new_from_object(ev)
    old = obj.data
    obj.modifiers.clear()
    obj.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    for p in me.polygons:
        p.use_smooth = True
    return me




def vertex_normals(me):
    n = len(me.vertices)
    a = np.empty(n * 3, dtype=np.float32)
    try:
        me.vertex_normals.foreach_get("vector", a)
    except (AttributeError, TypeError, RuntimeError):
        me.vertices.foreach_get("normal", a)
    return a.reshape(n, 3)


def vertex_coords(me):
    n = len(me.vertices)
    a = np.empty(n * 3, dtype=np.float32)
    me.vertices.foreach_get("co", a)
    return a.reshape(n, 3)


def read_float_attr(me, name):
    """정점 FLOAT 속성을 읽는다. 모디파이어를 구운 뒤에도 살아 있는지 여기서 확인한다.

    솔리디파이가 속성을 복제 정점으로 옮겨 주지 않으면 색 계산이 통째로 틀어지는데,
    그건 렌더를 봐도 "왜 이상한지"를 알 수 없다. 없거나 전부 0이면 빌드를 실패시킨다.
    """
    att = me.attributes.get(name)
    if att is None or att.domain != "POINT":
        raise RuntimeError(f"정점 속성 '{name}' 이 굽는 과정에서 사라졌다")
    n = len(me.vertices)
    a = np.empty(n, dtype=np.float32)
    att.data.foreach_get("value", a)
    if float(np.ptp(a)) < 1e-4:
        raise RuntimeError(f"정점 속성 '{name}' 이 상수다 (min={a.min():.4f} max={a.max():.4f})")
    return a


def sstep(x, a, b):
    """a~b 구간에서 0→1 로 부드럽게(3t²-2t³). 각진 경계를 만들지 않는다."""
    t = np.clip((np.asarray(x, dtype=np.float32) - a) / max(b - a, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def mesh_signed_volume(me):
    """부호 있는 부피. 닫힌 메시의 법선이 바깥을 향하면 양수다.

    이걸 안 재면 감기 방향이 뒤집힌 것을 눈으로는 못 잡는다. 블렌더 렌더는
    뒷면도 알아서 뒤집어 셰이딩하기 때문에 미리보기가 멀쩡해 보인다.
    Godot 은 기본이 후면 컬링이라 그대로 내보내면 모델이 뒤집혀 보인다.
    """
    co = vertex_coords(me)
    vol = 0.0
    for p in me.polygons:
        vs = list(p.vertices)
        for k in range(1, len(vs) - 1):
            a, b, c = co[vs[0]], co[vs[k]], co[vs[k + 1]]
            vol += float(a[0] * (b[1] * c[2] - b[2] * c[1])
                         - a[1] * (b[0] * c[2] - b[2] * c[0])
                         + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return vol / 6.0


def check_winding(objs):
    bad = []
    for o in objs:
        if o.type != "MESH" or len(o.data.polygons) == 0:
            continue
        if mesh_signed_volume(o.data) <= 0.0:
            bad.append(o.name)
    if bad:
        raise RuntimeError("법선이 안쪽을 향하는 메시: " + ", ".join(bad))
    log(f"감기 방향 검사 통과: 닫힌 메시 {len(objs)}개 모두 바깥 법선")


def set_coords(me, co):
    me.vertices.foreach_set("co", np.asarray(co, dtype=np.float32).reshape(-1))
    me.update()


def fur_displace(obj, amp=0.008, freq=11.0, seed=7, octaves=3, mask=None):
    """법선 방향 미세 요철. 플라스틱처럼 매끈한 실루엣을 깬다."""
    me = obj.data
    co = vertex_coords(me)
    nr = vertex_normals(me)
    d = (fbm3(co, freq, seed, octaves) - 0.5) * 2.0
    a = amp if mask is None else amp * mask(co)
    set_coords(me, co + nr * (d * a)[:, None])


# -----------------------------------------------------------------------------
# 정점 색 블렌딩
#
# 예전 방식은 면마다 재질 인덱스를 하드 컷오프로 골랐다. 면이 크면 경계가
# 조각보처럼 각지고, 노이즈를 섞으면 체크무늬가 된다.
# 지금은 "얼마나 배 쪽인가"를 0~1 연속값으로 재고, 이웃 정점끼리 여러 번
# 평균 내어(라플라시안) 부드럽게 만든 뒤, 그 값으로 색을 직접 보간해서
# 정점 색 속성에 굽는다. 재질은 하나뿐이고 Base Color 는 이 속성을 읽는다.
# -----------------------------------------------------------------------------
BLEND_ATTR = "Blend"


def mesh_edge_array(me):
    n = len(me.edges)
    if n == 0:
        return np.zeros((0, 2), dtype=np.int64)
    a = np.empty(n * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", a)
    return a.reshape(n, 2).astype(np.int64)


def smooth_scalar(me, s, iters=10, w=0.72):
    """이웃 정점 평균으로 스칼라장을 문지른다. 경계의 '각짐'은 여기서 사라진다."""
    e = mesh_edge_array(me)
    s = np.asarray(s, dtype=np.float32).copy()
    if len(e) == 0:
        return s
    n = len(s)
    cnt = np.zeros(n, dtype=np.float32)
    np.add.at(cnt, e[:, 0], 1.0)
    np.add.at(cnt, e[:, 1], 1.0)
    cnt = np.maximum(cnt, 1.0)
    for _ in range(iters):
        acc = np.zeros(n, dtype=np.float32)
        np.add.at(acc, e[:, 0], s[e[:, 1]])
        np.add.at(acc, e[:, 1], s[e[:, 0]])
        s = s * (1.0 - w) + (acc / cnt) * w
    return s


COAT_STOPS = [
    (0.00, FUR_DARK),   # 등 한가운데
    (0.44, FUR),        # 어깨·옆구리 위쪽 — 기획서의 하늘색
    (0.76, FUR_MID),    # 옆구리
    (1.00, BELLY),      # 배·턱
]

# 활공막 전용 그러데이션. 몸통 그러데이션 앞에 더 진한 단을 하나 덧대서
# 막의 바깥 테두리가 색으로 읽히게 한다. 나머지 단은 몸통과 같은 색이라
# 부착선에서는 몸통 색과 자연스럽게 이어진다.
MEM_STOPS = [
    (0.00, MEM_EDGE),   # 바깥 테두리 — 사진의 진한 가장자리 선
    (0.30, FUR_DARK),
    (0.62, FUR),
    (0.86, FUR_MID),
    (1.00, BELLY),
]


def ramp_rgb(g, stops=COAT_STOPS):
    """0~1 값을 색 그러데이션으로 바꾼다."""
    g = np.clip(np.asarray(g, dtype=np.float32), 0.0, 1.0)
    pos = np.array([p for p, _ in stops], dtype=np.float32)
    out = np.empty((len(g), 3), dtype=np.float32)
    for ch in range(3):
        out[:, ch] = np.interp(g, pos, np.array([c[ch] for _, c in stops], dtype=np.float32))
    return out


def set_vertex_colors(obj, rgb):
    """(N,3) 선형 RGB 를 정점 색 속성으로 굽는다. glTF 는 이것을 COLOR_0 으로 내보낸다."""
    me = obj.data
    ca = me.color_attributes.get(BLEND_ATTR)
    if ca is None:
        ca = me.color_attributes.new(name=BLEND_ATTR, type="FLOAT_COLOR", domain="POINT")
    arr = np.concatenate([np.asarray(rgb, dtype=np.float32).reshape(-1, 3),
                          np.ones((len(me.vertices), 1), dtype=np.float32)], axis=1)
    ca.data.foreach_set("color", arr.reshape(-1))
    for i, c in enumerate(me.color_attributes):
        if c.name == BLEND_ATTR:
            me.color_attributes.active_color_index = i
            me.color_attributes.render_color_index = i
    me.update()
    return ca


def fill_vertex_colors(obj, color):
    """색이 일정한 작은 부속(귀 등)도 같은 재질을 쓰므로 속성을 채워 둔다."""
    n = len(obj.data.vertices)
    rgb = np.tile(np.array(color[:3], dtype=np.float32), (n, 1))
    return set_vertex_colors(obj, rgb)


def shade_coat(obj, field, iters=10, w=0.72, stops=COAT_STOPS):
    """field(정점좌표, 정점법선) -> 0~1 스코어. 스무딩 후 색으로 구워 넣는다."""
    me = obj.data
    co = vertex_coords(me)
    nr = vertex_normals(me)
    g = np.asarray(field(co, nr), dtype=np.float32)
    g = smooth_scalar(me, g, iters=iters, w=w)
    set_vertex_colors(obj, ramp_rgb(g, stops))
    return g


# =============================================================================
# 재질
# =============================================================================
def set_in(bsdf, key, val):
    if key in bsdf.inputs:
        bsdf.inputs[key].default_value = val
        return True
    return False


def vertex_fur_material(name, roughness=0.88, sheen=0.55, sss=0.14):
    """털 재질 하나. Base Color 를 정점 색 속성에서 읽으므로 색 경계가 연속이다.

    glTF 로 나갈 때: Base Color 가 Color Attribute 에 직접 물려 있으면 익스포터가
    baseColorFactor 를 흰색으로 두고 정점 색을 COLOR_0 으로 내보낸다.
    Godot 의 glTF 임포터는 COLOR_0 을 읽어 vertex_color_use_as_albedo 를 켠다.
    (Sheen/SSS 는 블렌더 미리보기용 보조다. Godot 까지 간다고 보장하지 않는다.)
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    ca = nt.nodes.new("ShaderNodeVertexColor")
    ca.layer_name = BLEND_ATTR
    nt.links.new(ca.outputs["Color"], b.inputs["Base Color"])
    set_in(b, "Roughness", roughness)
    set_in(b, "Metallic", 0.0)
    set_in(b, "Specular IOR Level", 0.16)
    set_in(b, "IOR", 1.35)
    set_in(b, "Sheen Weight", sheen)
    set_in(b, "Sheen Roughness", 0.35)
    set_in(b, "Sheen Tint", (1.0, 1.0, 1.0, 1.0))
    set_in(b, "Subsurface Weight", sss)
    set_in(b, "Subsurface Radius", (0.30, 0.16, 0.12))
    set_in(b, "Subsurface Scale", 0.05)
    return mat




def plain_material(name, color, roughness, spec=0.5, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    set_in(b, "Base Color", color)
    set_in(b, "Roughness", roughness)
    set_in(b, "Metallic", 0.0)
    set_in(b, "Specular IOR Level", spec)
    if emission > 0.0:
        set_in(b, "Emission Color", color)
        set_in(b, "Emission Strength", emission)
    return mat


class Mats:
    pass


def build_materials():
    m = Mats()
    # 털은 재질 하나로 통일한다. 색 구역은 정점 색이 담당한다.
    m.fur = vertex_fur_material("Fur")
    m.ear = plain_material("EarInner", EAR_INNER, 0.80, 0.25)
    m.paw = plain_material("Paw", PAW, 0.62, 0.35)
    m.nose = plain_material("Nose", NOSE, 0.30, 0.55)
    m.eye = plain_material("Eye", EYE, 0.055, 0.85)
    m.glint = plain_material("Glint", GLINT, 0.08, 1.0, emission=0.55)
    m.whisker = plain_material("Whisker", WHISKER, 0.55, 0.3)
    return m


# =============================================================================
# 털결 텍스처 — 노멀맵 + 러프니스 변화 (glTF 로 확실히 나가는 방식)
# =============================================================================
def tileable_noise2(size, freq_u, freq_v, seed, octaves=4):
    """가로세로 주기가 맞는 2D 값 노이즈. freq 가 다르면 결이 한 방향으로 늘어난다."""
    total = np.zeros((size, size), dtype=np.float32)
    amp, norm = 1.0, 0.0
    fu, fv = freq_u, freq_v
    for o in range(octaves):
        g = np.random.default_rng(seed + o * 131).random((max(int(fv), 1), max(int(fu), 1)))
        g = g.astype(np.float32)
        gy, gx = g.shape
        v = (np.arange(size, dtype=np.float32) / size) * gy
        u = (np.arange(size, dtype=np.float32) / size) * gx
        iy = np.floor(v).astype(int)
        ix = np.floor(u).astype(int)
        fy = v - iy
        fx = u - ix
        fy = (fy * fy * (3 - 2 * fy))[:, None]
        fx = (fx * fx * (3 - 2 * fx))[None, :]
        y0, y1 = iy % gy, (iy + 1) % gy
        x0, x1 = ix % gx, (ix + 1) % gx
        c00 = g[np.ix_(y0, x0)]
        c01 = g[np.ix_(y0, x1)]
        c10 = g[np.ix_(y1, x0)]
        c11 = g[np.ix_(y1, x1)]
        lay = (c00 * (1 - fx) + c01 * fx) * (1 - fy) + (c10 * (1 - fx) + c11 * fx) * fy
        total += amp * lay
        norm += amp
        amp *= 0.55
        fu *= 2.0
        fv *= 2.0
    return total / norm


def build_fur_textures(size=256):
    """세로로 늘어난 노이즈 = 털 가닥 결. 높이맵에서 노멀맵을 직접 계산한다."""
    h = tileable_noise2(size, freq_u=44, freq_v=17, seed=20260901, octaves=4)
    h = (h - h.min()) / max(h.max() - h.min(), 1e-6)
    # 가닥 느낌을 살리려고 대비를 올린다
    h = np.clip((h - 0.5) * 1.5 + 0.5, 0.0, 1.0)

    strength = 2.6
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * strength
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * strength
    nx, ny, nz = -dx, -dy, np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / ln, ny / ln, nz / ln

    nrm = np.stack([nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5,
                    np.ones_like(h)], axis=-1).astype(np.float32)
    img_n = bpy.data.images.new("FurNormal", size, size, alpha=False, float_buffer=False)
    img_n.colorspace_settings.name = "Non-Color"
    img_n.pixels = nrm.reshape(-1)
    img_n.pack()

    # 러프니스: 털 가닥 사이가 더 거칠다. glTF metallicRoughness 의 G 채널로 나간다.
    r = 0.845 + 0.075 * (1.0 - h)
    rough = np.stack([r, r, r, np.ones_like(h)], axis=-1).astype(np.float32)
    img_r = bpy.data.images.new("FurRough", size, size, alpha=False, float_buffer=False)
    img_r.colorspace_settings.name = "Non-Color"
    img_r.pixels = rough.reshape(-1)
    img_r.pack()
    return img_n, img_r


def attach_fur_textures(mat, img_n, img_r):
    """Principled 의 Normal / Roughness 에 이미지 연결. 둘 다 glTF 표준 항목이라 내보내진다."""
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]

    tex_n = nt.nodes.new("ShaderNodeTexImage")
    tex_n.image = img_n
    tex_n.interpolation = "Smart"
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.inputs["Strength"].default_value = 0.55
    nt.links.new(tex_n.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], b.inputs["Normal"])

    tex_r = nt.nodes.new("ShaderNodeTexImage")
    tex_r.image = img_r
    nt.links.new(tex_r.outputs["Color"], b.inputs["Roughness"])


def uv_and_texture(objs, mats_with_fur, img_n, img_r, uv_scale=6.0):
    """스마트 UV 전개 후 UV 를 배로 늘려 텍스처가 촘촘히 반복되게 한다."""
    for mat in mats_with_fur:
        attach_fur_textures(mat, img_n, img_r)

    for obj in objs:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.20, island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        uvl = obj.data.uv_layers.active
        if uvl is None:
            continue
        n = len(uvl.data)
        arr = np.empty(n * 2, dtype=np.float32)
        uvl.data.foreach_get("uv", arr)
        uvl.data.foreach_set("uv", arr * uv_scale)
    bpy.ops.object.select_all(action="DESELECT")


# =============================================================================
# 몸통 — 파라메트릭 구를 빚는다
#
# 예전에는 스킨 모디파이어 + 섭디비전으로 만들었는데, 스킨의 단면이 사각형이라
# 섭디비전을 2단계 걸어도 둥글어지지 않는다. 옆·위에서 보면 각진 식빵 덩어리가
# 되어 "골판지 상자" 처럼 보였다. 사진의 몸은 거의 공이므로 구를 직접 빚는다.
# 팔다리는 몸통 메시에서 떼어 내 따로 만들고 뼈 하나에 100% 물린다.
# =============================================================================
TORSO_C = Vector((0.00, 0.055, 0.545))
TORSO_R = Vector((0.402, 0.492, 0.380))


def torso_shape(p):
    """단위 구 위의 점을 통통한 몸통 모양으로 옮긴다."""
    q = Vector(p)
    k_rear = max(0.0, q.y)          # 엉덩이 쪽
    k_front = max(0.0, -q.y)        # 목 쪽
    s = 1.0 - 0.34 * k_rear ** 1.7 - 0.16 * k_front ** 2.4
    q.x *= s
    q.z *= s
    if q.z < 0.0:                   # 배는 살짝 납작
        q.z *= 0.93
    q.z += 0.055 * max(0.0, -q.y) ** 2.0    # 가슴이 조금 부풀어 오른다
    return q


def build_body(m):
    obj = make_sphere("Body", TORSO_C, TORSO_R, [m.fur],
                      seg=40, ring=26, deform=torso_shape)
    me = obj.data

    # 카운터셰이딩: 위(등)에서 아래(배)로 연속으로 밝아진다.
    # 노이즈는 경계를 "자르는" 데가 아니라 그러데이션을 살짝 얼룩지게 하는 데만 쓴다.
    def field(co, nr):
        g = 0.50 - 0.58 * nr[:, 2]                     # 0=위 1=아래
        g += (fbm3(co, 5.5, 33, 3) - 0.5) * 0.16       # 털 얼룩
        g += np.clip(-(co[:, 1] + 0.10) * 0.34, 0.0, 0.22)   # 가슴은 조금 더 밝다
        return g

    shade_coat(obj, field, iters=4, w=0.55)
    fur_displace(obj, amp=0.0075, freq=13.0, seed=11, octaves=3)
    log(f"몸통: 면 {len(me.polygons)}개")
    return obj


def build_limbs(m):
    """팔다리. 뿌리를 몸통 안에 묻고 뼈 하나에 100% 물릴 목록으로 돌려준다."""
    parts = []
    specs = [("Arm", SHOULDER, WRIST, "arm",
              [0.152, 0.130, 0.108, 0.090, 0.076], Vector((0.02, -0.05, -0.02))),
             ("Leg", HIPJ, ANKLE, "leg",
              [0.176, 0.152, 0.126, 0.104, 0.086], Vector((0.02, 0.06, -0.02)))]
    for name, joint, tip, bone, radii, bow in specs:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            a = Vector((joint.x * sx, joint.y, joint.z))
            b = Vector((tip.x * sx, tip.y, tip.z))
            ctrl = a.lerp(b, 0.5) + Vector((bow.x * sx, bow.y, bow.z))
            path = [bezier2(a, ctrl, b, s / (len(radii) - 1)) for s in range(len(radii))]
            o = make_tube(f"{name}{side}", path, radii, [m.fur], seg=12, cap=True)
            # 팔다리는 몸통 옆구리 색과 이어져야 한다
            shade_coat(o, lambda co, nr: 0.52 - 0.30 * nr[:, 2]
                       + (fbm3(co, 7.0, 91, 2) - 0.5) * 0.14, iters=3, w=0.5)
            fur_displace(o, amp=0.0045, freq=15.0, seed=83, octaves=2)
            parts.append((o, f"{bone}.{side}"))
    log(f"팔다리 {len(parts)}개")
    return parts


# =============================================================================
# 머리 — 파라메트릭 구를 직접 빚는다 (짧고 뭉툭한 주둥이, 통통한 볼)
# =============================================================================
MUZZLE_DIR = Vector((0.0, -1.0, -0.34)).normalized()
EYE_DIR = Vector((0.615, -0.605, 0.255)).normalized()
EAR_DIR = Vector((0.760, 0.135, 0.610)).normalized()


def head_shape(p):
    """단위 구 위의 점 p 를 하늘다람쥐 머리 모양으로 옮긴다 (아직 반지름 1 기준)."""
    q = Vector((p.x * 1.035, p.y * 1.015, p.z * 0.975))

    # 주둥이: 앞아래로 짧고 뭉툭하게. 지수를 크게 잡아 좁은 범위만 밀린다.
    k = max(0.0, p.dot(MUZZLE_DIR))
    q += MUZZLE_DIR * (k ** 3.4) * 0.185
    # 코끝은 살짝 눌러 납작하게
    q -= Vector((0, 0, 1)) * (k ** 8.0) * 0.05

    # 볼: 옆아래를 부풀린다
    for sx in (1.0, -1.0):
        cd = Vector((0.80 * sx, -0.44, -0.40)).normalized()
        kc = max(0.0, p.dot(cd))
        q += cd * (kc ** 3.0) * 0.085

    # 이마: 눈 위쪽을 살짝 올려 동그란 인상
    fd = Vector((0.0, -0.42, 0.90)).normalized()
    kf = max(0.0, p.dot(fd))
    q += fd * (kf ** 3.0) * 0.045

    # 턱 아래는 평평하게 (목과 이어지는 부분)
    if q.z < -0.62:
        q.z = -0.62 - (q.z + 0.62) * 0.55
    return q


def head_radius_at(direction):
    """그 방향의 머리 표면까지의 거리(반지름 1 기준). 눈·귀를 정확히 얹기 위한 값."""
    d = Vector(direction).normalized()
    return head_shape(d).length


def build_head(m):
    obj = make_sphere("Head", HEAD, (HR, HR, HR), [m.fur],
                      seg=36, ring=22, deform=head_shape)
    me = obj.data

    eyeL = HEAD + EYE_DIR * (head_radius_at(EYE_DIR) * HR)
    eyeR = Vector((-eyeL.x, eyeL.y, eyeL.z))

    # 사진의 얼굴은 거의 전체가 크림색이고, 정수리·뒤통수만 살짝 어둡다.
    hc = np.array([HEAD.x, HEAD.y, HEAD.z], dtype=np.float32)
    face_dir = np.array([0.0, -0.62, -0.42], dtype=np.float32)
    face_dir /= np.linalg.norm(face_dir)
    crown_dir = np.array([0.0, 0.34, 0.94], dtype=np.float32)
    crown_dir /= np.linalg.norm(crown_dir)

    def field(co, nr):
        rel = (co - hc) / HR
        u = rel / np.maximum(np.linalg.norm(rel, axis=1, keepdims=True), 1e-6)
        g = 0.42 - 0.42 * nr[:, 2]
        kf = np.clip(u @ face_dir, 0.0, 1.0)
        g += 1.15 * kf ** 2.1                              # 주둥이·뺨·턱은 크림
        kc = np.clip(u @ crown_dir, 0.0, 1.0)
        g -= 0.46 * kc ** 1.8                              # 정수리·뒤통수는 진하게
        g += (fbm3(co, 7.0, 71, 3) - 0.5) * 0.14
        return g

    shade_coat(obj, field, iters=4, w=0.55)
    fur_displace(obj, amp=0.0055, freq=15.0, seed=23, octaves=3)
    log(f"머리: 면 {len(me.polygons)}개, 반지름 {HR}")
    return obj, eyeL, eyeR


def build_face(m, eyeL, eyeR):
    """눈 · 하이라이트 · 귀 · 코 · 수염."""
    parts = []
    ER = 0.300 * HR                      # 눈 반지름 = 머리 폭의 30%

    for side, sx in (("L", 1.0), ("R", -1.0)):
        e = eyeL if sx > 0 else eyeR
        d = Vector((EYE_DIR.x * sx, EYE_DIR.y, EYE_DIR.z))
        # 눈알 중심을 표면보다 안쪽에 두어 반지름으로 볼록 튀어나오게 한다
        c = HEAD + d * (head_radius_at(d) * HR - 0.185 * HR)
        parts.append(make_sphere(f"Eye{side}", c, (ER, ER, ER * 1.02), [m.eye], 22, 14))

        # 하이라이트 — 눈 표면 바로 위. 사진에서 눈은 젖어 반짝인다.
        gd = Vector((d.x * 0.55 + 0.25 * sx, d.y - 0.55, d.z + 0.62)).normalized()
        parts.append(make_sphere(f"Glint{side}", c + gd * (ER * 0.93),
                                 (ER * 0.235, ER * 0.235, ER * 0.235), [m.glint], 12, 8))
        gd2 = Vector((d.x * 0.6 - 0.30 * sx, d.y - 0.45, d.z - 0.62)).normalized()
        parts.append(make_sphere(f"Glint2{side}", c + gd2 * (ER * 0.95),
                                 (ER * 0.105, ER * 0.105, ER * 0.105), [m.glint], 10, 6))

        # 귀 — 작고 둥글고 머리에 바짝 붙는다. 방향 d 를 로컬 Z 로 삼은 납작한 원반.
        ed = Vector((EAR_DIR.x * sx, EAR_DIR.y, EAR_DIR.z)).normalized()
        basis = ed.to_track_quat("Z", "Y").to_matrix()
        base = head_radius_at(ed) * HR
        ec = HEAD + ed * (base - 0.015 * HR)
        ear = make_sphere(f"Ear{side}", ec, (0.255 * HR, 0.215 * HR, 0.135 * HR),
                          [m.fur], 20, 12, basis=basis)
        # 귀도 같은 털 재질을 쓰므로 정점 색을 채워 둔다 (안 채우면 검게 나온다).
        shade_coat(ear, lambda co, nr: 0.30 - 0.22 * nr[:, 2] + 0.30, iters=4, w=0.6)
        parts.append(ear)
        parts.append(make_sphere(f"EarInner{side}", ec + ed * (0.045 * HR),
                                 (0.150 * HR, 0.125 * HR, 0.120 * HR),
                                 [m.ear], 14, 9, basis=basis))

        # 수염 — 사진에서 뚜렷하다. 한 점에서 부챗살처럼 나오면 철사 뭉치로 보이므로
        # 뿌리를 주둥이 옆으로 흩어 놓고, 끝으로 갈수록 아래로 처지게 한다.
        for w in range(5):
            t = w / 4.0
            wd = Vector((0.66 * sx + 0.20 * sx * t,
                         -0.70 + 0.30 * t, 0.22 - 0.50 * t)).normalized()
            start = HEAD + Vector((0.275 * sx + 0.060 * sx * t,
                                   -0.90 + 0.10 * t, 0.04 - 0.26 * t)) * HR
            L = 0.30 + 0.08 * math.sin(t * math.pi)
            path = [start + wd * (L * s / 4.0)
                    + Vector((0, 0, -0.10 * L * (s / 4.0) ** 2)) for s in range(5)]
            rad = [0.0038, 0.0030, 0.0022, 0.0013, 0.0005]
            parts.append(make_tube(f"Whisker{side}{w}", path, rad, [m.whisker], seg=5, cap=False))

    # 코 — 작고 살짝 눌린 하트 모양 흉내
    nd = MUZZLE_DIR
    nc = HEAD + nd * (head_radius_at(nd) * HR - 0.025 * HR)
    parts.append(make_sphere("Nose", nc, (0.088 * HR, 0.070 * HR, 0.062 * HR),
                             [m.nose], 16, 10))

    log(f"얼굴 부위 {len(parts)}개")
    return parts


# =============================================================================
# 손 · 발 — 발가락이 보여야 소시지 인상이 사라진다
# =============================================================================
def build_paws(m):
    """(오브젝트, 물릴 뼈 이름) 목록을 돌려준다. 이름에서 뼈를 추측하지 않는다."""
    parts = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        arm_bone, leg_bone = f"arm.{side}", f"leg.{side}"
        # 앞손: 작고 손가락 4개
        palm = Vector((WRIST.x * sx + 0.030 * sx, WRIST.y - 0.055, WRIST.z - 0.028))
        parts.append((make_sphere(f"Hand{side}", palm,
                                  (0.072, 0.082, 0.042), [m.paw], 16, 10), arm_bone))
        for f in range(4):
            t = f / 3.0
            d = Vector((0.30 * sx - 0.34 * sx * t, -0.90, -0.16)).normalized()
            base = palm + Vector((0.052 * sx * (t - 0.5) * 2.0, -0.030, 0.0))
            L = 0.082 - 0.014 * abs(t - 0.45) * 2.0
            path = [base + d * (L * s / 3.0) for s in range(4)]
            parts.append((make_tube(f"Finger{side}{f}", path,
                                    [0.0175, 0.0160, 0.0135, 0.0090], [m.paw], seg=6),
                          arm_bone))

        # 뒷발: 조금 크고 발가락 5개
        sole = Vector((ANKLE.x * sx + 0.024 * sx, ANKLE.y + 0.062, ANKLE.z - 0.030))
        parts.append((make_sphere(f"Foot{side}", sole,
                                  (0.084, 0.096, 0.046), [m.paw], 16, 10), leg_bone))
        for f in range(5):
            t = f / 4.0
            d = Vector((0.34 * sx - 0.40 * sx * t, 0.90, -0.16)).normalized()
            base = sole + Vector((0.060 * sx * (t - 0.5) * 2.0, 0.034, 0.0))
            L = 0.094 - 0.018 * abs(t - 0.45) * 2.0
            path = [base + d * (L * s / 3.0) for s in range(4)]
            parts.append((make_tube(f"Toe{side}{f}", path,
                                    [0.0190, 0.0172, 0.0145, 0.0095], [m.paw], seg=6),
                          leg_bone))
    log(f"손발 부위 {len(parts)}개")
    return parts


# =============================================================================
# 활공막 — 손목~발목을 잇는 부드러운 곡선. 각진 패널이 아니다.
# =============================================================================
def bezier2(a, b, c, t):
    return a * (1 - t) ** 2 + b * (2 * (1 - t) * t) + c * t ** 2


def catmull(pts, t):
    """끊김 없는 곡선. 양 끝 마디를 복제해 통과점 보간을 만든다."""
    n = len(pts) - 1
    x = min(max(t, 0.0), 1.0) * n
    i = min(int(x), n - 1)
    f = x - i
    p0 = pts[max(i - 1, 0)]
    p1, p2 = pts[i], pts[i + 1]
    p3 = pts[min(i + 2, n)]
    return ((p1 * 2.0) + (p2 - p0) * f
            + (p0 * 2.0 - p1 * 5.0 + p2 * 4.0 - p3) * (f * f)
            + (p1 * 3.0 - p0 - p2 * 3.0 + p3) * (f * f * f)) * 0.5


# 막의 앞뒤 끝은 손목·발목이 아니라 목 옆과 꼬리 밑동이다.
# 여기서 폭이 거의 0 으로 좁아져야 "직사각형 판" 인상이 사라진다.
MEM_NECK_IN = Vector((0.058, -0.494, 0.604))
MEM_NECK_OUT = Vector((0.132, -0.480, 0.576))
MEM_LEAD_IN = Vector((0.108, -0.420, 0.598))
MEM_LEAD_OUT = Vector((0.358, -0.436, 0.474))    # 앞 테두리가 앞으로 볼록하게
MEM_RUMP_IN = Vector((0.052, 0.516, 0.548))
MEM_RUMP_OUT = Vector((0.124, 0.506, 0.520))
MEM_TRAIL_IN = Vector((0.112, 0.480, 0.556))
MEM_TRAIL_OUT = Vector((0.360, 0.532, 0.428))    # 뒤 테두리도 뒤로 볼록하게
MEM_IN_MID = Vector((0.182, 0.040, 0.590))

MEM_U_ATTR = "MemU"      # 부착선 0 → 바깥 테두리 1. 솔리디파이를 건너 색 계산까지 간다.


def build_patagium(m):
    objs = []
    COLS, ROWS = 15, 37          # COLS: 안쪽→바깥쪽, ROWS: 앞→뒤
    for side, sx in (("L", 1.0), ("R", -1.0)):
        mir = lambda v: Vector((v.x * sx, v.y, v.z))
        # 통과점: 목 옆 → 앞테두리 → 손목 → 바깥 최대 → 발목 → 뒤테두리 → 꼬리 밑동
        outer_knots = [mir(MEM_NECK_OUT), mir(MEM_LEAD_OUT), mir(WRIST), mir(MEM_CTRL),
                       mir(ANKLE), mir(MEM_TRAIL_OUT), mir(MEM_RUMP_OUT)]
        inner_knots = [mir(MEM_NECK_IN), mir(MEM_LEAD_IN), mir(MEM_IN_F), mir(MEM_IN_MID),
                       mir(MEM_IN_B), mir(MEM_TRAIL_IN), mir(MEM_RUMP_IN)]

        verts = []
        uu = []                      # 정점마다 "부착선(0) → 바깥 테두리(1)" 값
        for r in range(ROWS):
            t = r / (ROWS - 1)
            inner = catmull(inner_knots, t)
            outer = catmull(outer_knots, t)
            span = outer - inner
            chord = span.length
            # 가장자리 술: 폭에 비례해 흔들어 끝쪽 뾰족한 부분은 흐트러지지 않게 한다
            fringe = (math.sin(t * 17.0) * 0.5 + math.sin(t * 29.0 + 1.3) * 0.5) * 0.055
            outer = outer + span.normalized() * (fringe * chord)
            # 단면: 옆구리에서 수평으로 빠져나온 뒤 늘어졌다가 손목/발목으로 올라간다.
            # 직선으로 이으면 몸통에서 나오는 자리에 각진 접힘선이 생겨 판때기로 보인다.
            cs_ctrl = Vector((inner.x + span.x * 0.5,
                              inner.y + span.y * 0.5,
                              inner.z + 0.012))
            for c in range(COLS):
                u = c / (COLS - 1)
                p = bezier2(inner, cs_ctrl, outer, u)
                # 공기를 받아 가운데가 처진다. 처짐은 그 자리의 폭에 비례한다
                # (좁아지는 앞뒤 끝이 늘어지면 오히려 이상해진다).
                p.z -= 0.22 * chord * (math.sin(math.pi * u) ** 0.85)
                # 바깥 테두리는 살짝 말려 올라간다 — 얇은 막의 인상
                p.z += (u ** 4) * 0.14 * chord
                verts.append(p)
                uu.append(u)

        faces = []
        for r in range(ROWS - 1):
            for c in range(COLS - 1):
                i0 = r * COLS + c
                i1 = r * COLS + c + 1
                i2 = (r + 1) * COLS + c + 1
                i3 = (r + 1) * COLS + c
                faces.append((i0, i1, i2, i3) if sx > 0 else (i0, i3, i2, i1))

        obj = new_obj(f"Patagium{side}", verts, faces, [])
        # 색을 칠하려면 "부착선에서 얼마나 바깥인가"(u)를 굽고 난 뒤에도 알아야 한다.
        # 좌표에서 되계산하면 앞뒤 끝처럼 폭이 0 에 가까운 데서 무너지므로,
        # 솔리디파이 전에 정점 속성으로 심어 두고 구운 뒤 읽는다.
        att = obj.data.attributes.new(MEM_U_ATTR, "FLOAT", "POINT")
        att.data.foreach_set("value", np.asarray(uu, dtype=np.float32))

        sol = obj.modifiers.new("Solidify", "SOLIDIFY")
        sol.thickness = 0.009          # 얇은 막. 두꺼우면 판때기로 보인다.
        sol.offset = 0.0
        sol.use_rim = True
        bake_modifiers(obj)
        me = obj.data
        me.materials.append(m.fur)

        u_all = read_float_attr(me, MEM_U_ATTR)

        # 활공막을 몸통과 구분되게 한다. 활공이 이 게임의 핵심 메커니즘이라
        # 막의 경계가 실루엣이 아니라 **색으로** 읽혀야 한다.
        #
        # 다만 예전처럼 각진 판때기로 되돌아가면 안 되므로 경계를 선으로 긋지 않는다.
        #   · 부착선(u=0)에서는 몸통 옆구리 색 그대로 → 몸에서 이어져 나온 것으로 보인다
        #   · 안쪽에서 바깥으로 가며 서서히 가라앉는다 (smoothstep, 각짐 없음)
        #   · 바깥 테두리에 진한 띠를 넣는다 — 사진 속 하늘다람쥐의 막 가장자리가
        #     실제로 진한 선으로 보인다. 이게 날개 윤곽을 그려 준다.
        def field(co, nr):
            u = np.clip(u_all, 0.0, 1.0)
            core = sstep(u, 0.00, 0.45)      # 부착선에서 멀어지며 가라앉는 정도
            edge = sstep(u, 0.55, 0.90)      # 바깥 테두리 띠
            g = 0.70 - 0.24 * nr[:, 2]       # 윗면 진하게 / 아랫면(배 쪽)은 밝게
            g -= 0.18 * core
            g -= 0.52 * edge
            g += (fbm3(co, 6.0, 41, 2) - 0.5) * 0.10
            return g

        shade_coat(obj, field, iters=3, w=0.45, stops=MEM_STOPS)
        fur_displace(obj, amp=0.0040, freq=17.0, seed=41, octaves=2)
        objs.append(obj)
    log(f"활공막: 좌우 2장, 면 {len(objs[0].data.polygons)}개씩")
    return objs


# =============================================================================
# 꼬리 — 넓고 납작한 깃털. 가장자리를 부스스하게 만든다.
# =============================================================================
def build_tail(m):
    STEPS, SEG = 32, 20
    # 사진의 꼬리는 칼날이 아니라 "납작하지만 폭신한 솔"이다.
    # 두께가 폭의 0.6 배쯤 되고, 끝이 뾰족하지 않고 뭉툭하게 마무리된다.
    s_ctrl = np.array([0.00, 0.12, 0.30, 0.50, 0.70, 0.88, 1.00])
    w_ctrl = np.array([0.110, 0.172, 0.212, 0.224, 0.212, 0.170, 0.082])
    h_ctrl = np.array([0.118, 0.126, 0.132, 0.134, 0.126, 0.104, 0.052])

    verts, faces = [], []
    for i in range(STEPS):
        s = i / (STEPS - 1)
        c = tail_center(s)
        w = float(np.interp(s, s_ctrl, w_ctrl))
        h = float(np.interp(s, s_ctrl, h_ctrl))
        # 깃털 술: 폭을 잘게 물결치게 한다
        w *= 1.0 + 0.070 * math.sin(s * 27.0) + 0.040 * math.sin(s * 43.0 + 2.1)
        h *= 1.0 + 0.055 * math.sin(s * 31.0 + 0.7)
        for j in range(SEG):
            th = 2 * math.pi * j / SEG
            ct, st = math.cos(th), math.sin(th)
            # 납작한 타원 단면 + 털뭉치가 삐죽 나온 느낌의 각도별 요철
            tuft = 1.0 + 0.085 * math.sin(th * 5.0 + s * 9.0) \
                       + 0.055 * math.sin(th * 9.0 - s * 14.0)
            verts.append(Vector((w * ct * tuft, c.y,
                                 c.z + h * st * (1.0 - 0.18 * ct * ct) * tuft)))
    for i in range(STEPS - 1):
        for j in range(SEG):
            i0 = i * SEG + j
            i1 = i * SEG + (j + 1) % SEG
            i2 = (i + 1) * SEG + (j + 1) % SEG
            i3 = (i + 1) * SEG + j
            faces.append((i0, i3, i2, i1))
    # 끝 마감
    tip = len(verts)
    verts.append(tail_center(1.0) + Vector((0, 0.075, 0)))
    base = (STEPS - 1) * SEG
    for j in range(SEG):
        faces.append((tip, base + (j + 1) % SEG, base + j))
    st0 = len(verts)
    verts.append(tail_center(0.0) - Vector((0, 0.05, 0)))
    for j in range(SEG):
        faces.append((st0, j, (j + 1) % SEG))

    obj = new_obj("Tail", verts, faces, [m.fur])

    # 사진의 꼬리는 몸통보다 살짝 진한 회갈색이고, 끝으로 갈수록 어두워지며
    # 가장자리 털만 빛을 받아 하얗게 뜬다. 흰 칼날이 되지 않게 전체를 하늘색 쪽에 둔다.
    y0, y1 = tail_center(0.0).y, tail_center(1.0).y

    def field(co, nr):
        s = np.clip((co[:, 1] - y0) / max(y1 - y0, 1e-6), 0.0, 1.0)
        g = 0.40 - 0.22 * nr[:, 2]                    # 윗면 진하게 / 아랫면 밝게
        g -= 0.20 * s ** 1.6                          # 끝으로 갈수록 진하게
        g += 0.30 * np.clip(np.abs(co[:, 0]) / 0.20, 0.0, 1.0) ** 2.0   # 가장자리 털은 밝다
        g += (fbm3(co, 8.0, 57, 3) - 0.5) * 0.18
        return g

    shade_coat(obj, field, iters=4, w=0.55)

    def mask(co):
        return 0.45 + 0.55 * np.clip(np.abs(co[:, 0]) / 0.22, 0.0, 1.0) ** 2

    fur_displace(obj, amp=0.030, freq=16.0, seed=63, octaves=3, mask=mask)
    log(f"꼬리: 면 {len(obj.data.polygons)}개")
    return obj


# =============================================================================
# 뼈대 — 이름은 계약이다. 바꾸지 않는다.
# =============================================================================
def build_armature():
    arm = bpy.data.armatures.new("SquirrelRig")
    rig = bpy.data.objects.new("Rig", arm)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones

    def bone(name, head, tail, parent=None, connect=False):
        b = eb.new(name)
        b.head = head
        b.tail = tail
        if parent:
            b.parent = eb[parent]
            b.use_connect = connect
        return b

    P = {n: p for n, p, _ in SPINE}

    bone("root", Vector((0, 0.05, 0.0)), Vector((0, 0.05, 0.30)))
    bone("hips", P["hips"], P["mid"], "root")
    bone("spine", P["mid"], P["chest"], "hips", True)
    bone("neck", P["chest"], P["chestF"], "spine", True)
    bone("head", P["chestF"], HEAD + Vector((0, -0.16, 0.06)), "neck", True)

    bone("tail1", tail_center(TAIL_S_BONE[0]), tail_center(TAIL_S_BONE[1]), "hips")
    bone("tail2", tail_center(TAIL_S_BONE[1]), tail_center(TAIL_S_BONE[2]), "tail1", True)
    bone("tail3", tail_center(TAIL_S_BONE[2]), tail_center(TAIL_S_BONE[3]), "tail2", True)

    for side, sx in (("L", 1.0), ("R", -1.0)):
        bone(f"arm.{side}", Vector((SHOULDER.x * sx, SHOULDER.y, SHOULDER.z)),
             Vector((WRIST.x * sx, WRIST.y, WRIST.z)), "spine")
        bone(f"leg.{side}", Vector((HIPJ.x * sx, HIPJ.y, HIPJ.z)),
             Vector((ANKLE.x * sx, ANKLE.y, ANKLE.z)), "hips")

    bpy.ops.object.mode_set(mode="OBJECT")
    log("뼈대: " + ", ".join(b.name for b in arm.bones))
    return rig


def bind_auto(rig, meshes):
    bpy.ops.object.select_all(action="DESELECT")
    for mo in meshes:
        mo.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    bpy.ops.object.select_all(action="DESELECT")


def bind_rigid(rig, obj, bone_name):
    """작은 부속은 자동 웨이트에 맡기지 않고 뼈 하나에 100% 물린다.
    (눈·귀·손발가락처럼 떨어져 있는 작은 메시는 본 히트 계산이 실패하거나
     엉뚱한 뼈에 물려 얼굴이 흩어질 수 있다)"""
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()
    vg = obj.vertex_groups.new(name=bone_name)
    vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    md = obj.modifiers.new("Armature", "ARMATURE")
    md.object = rig
    md.use_vertex_groups = True


def bind_tail(rig, obj):
    """꼬리는 중심선을 따라 tail1/2/3 에 부드럽게 나눠 물린다."""
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()
    groups = {n: obj.vertex_groups.new(name=n) for n in ("hips", "tail1", "tail2", "tail3")}
    y0, y1 = tail_center(0.0).y, tail_center(1.0).y
    knots = [tail_center(s).y for s in TAIL_S_BONE]
    for i, v in enumerate(obj.data.vertices):
        y = v.co.y
        s = (y - y0) / max(y1 - y0, 1e-6)
        if y <= knots[0]:
            groups["hips"].add([i], 1.0, "REPLACE")
            continue
        for k in range(3):
            lo, hi = knots[k], knots[k + 1]
            if y <= hi or k == 2:
                t = min(max((y - lo) / max(hi - lo, 1e-6), 0.0), 1.0)
                name = ("tail1", "tail2", "tail3")[k]
                nxt = ("tail2", "tail3", "tail3")[k]
                groups[name].add([i], 1.0 - t * 0.5, "REPLACE")
                groups[nxt].add([i], t * 0.5, "ADD")
                break
    md = obj.modifiers.new("Armature", "ARMATURE")
    md.object = rig
    md.use_vertex_groups = True


# =============================================================================
# 애니메이션 — 클립 이름은 player.gd 의 CLIP 상수와의 계약이다
# =============================================================================
def rad(d):
    return math.radians(d)


# 기본 자세는 활공 자세다(팔다리가 벌어져 활공막이 펴진 상태).
# 땅 위 자세는 팔다리를 접어 사진처럼 동그란 덩어리로 만든다.
TUCK_A, TUCK_L = 52.0, 40.0          # 접는 양(도)


def tuck(a=1.0, l=1.0, extra=None):
    """팔다리를 몸쪽으로 접은 기본 포즈를 만든다."""
    d = {
        "arm.L": (0, 0, TUCK_A * a), "arm.R": (0, 0, -TUCK_A * a),
        "leg.L": (0, 0, TUCK_L * l), "leg.R": (0, 0, -TUCK_L * l),
    }
    if extra:
        d.update(extra)
    return d


def merge(base, over):
    d = dict(base)
    for k, v in over.items():
        if k in d and len(d[k]) == 3 and len(v) == 3:
            d[k] = (d[k][0] + v[0], d[k][1] + v[1], d[k][2] + v[2])
        else:
            d[k] = v
    return d


def make_animations(rig):
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    if rig.animation_data is None:
        rig.animation_data_create()

    def reset_pose():
        for pb in rig.pose.bones:
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.location = (0.0, 0.0, 0.0)

    def clip(name, length, poses):
        assert max(poses) == length, \
            f"{name}: 마지막 키프레임 {max(poses)} 이 선언한 길이 {length} 와 다릅니다"
        reset_pose()
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        rig.animation_data.action = action
        for frame, bones in sorted(poses.items()):
            for bone_name, val in bones.items():
                pb = rig.pose.bones.get(bone_name)
                if pb is None:
                    continue
                pb.rotation_euler = (rad(val[0]), rad(val[1]), rad(val[2]))
                pb.keyframe_insert("rotation_euler", frame=frame)
                if len(val) > 3:
                    pb.location = Vector(val[3])
                    pb.keyframe_insert("location", frame=frame)
        # 액션만 만들면 glTF 에 클립이 0개로 나간다. NLA 트랙 하나 = 클립 하나.
        rig.animation_data.action = None
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, 1, action)
        return action

    actions = []

    # --- idle: 몸을 접고 숨쉬기, 꼬리 살랑, 이따금 고개 갸웃 ---
    actions.append(clip("idle", 96, {
        1:  tuck(1.00, 1.00, {"spine": (0, 0, 0), "head": (2, 0, 0),
                              "tail1": (-14, 0, 0), "tail2": (-16, 0, 4),
                              "tail3": (-10, 0, 6)}),
        32: tuck(1.02, 1.02, {"spine": (2.5, 0, 0), "head": (-2, 0, 5),
                              "tail1": (-8, 0, 10), "tail2": (-10, 0, 14),
                              "tail3": (-6, 0, 12)}),
        64: tuck(0.98, 0.98, {"spine": (0.5, 0, 0), "head": (1, 0, -4),
                              "tail1": (-16, 0, -8), "tail2": (-18, 0, -12),
                              "tail3": (-12, 0, -10)}),
        96: tuck(1.00, 1.00, {"spine": (0, 0, 0), "head": (2, 0, 0),
                              "tail1": (-14, 0, 0), "tail2": (-16, 0, 4),
                              "tail3": (-10, 0, 6)}),
    }))

    # --- walk: 대각선 다리쌍이 교대 ---
    base_w = tuck(0.94, 0.94)
    actions.append(clip("walk", 32, {
        1:  merge(base_w, {"arm.L": (26, 0, 0), "leg.R": (22, 0, 0),
                           "arm.R": (-26, 0, 0), "leg.L": (-22, 0, 0),
                           "spine": (0, 0, 3), "head": (2, 0, -2),
                           "tail1": (-12, 0, 8), "tail2": (-12, 0, 10)}),
        16: merge(base_w, {"arm.L": (-26, 0, 0), "leg.R": (-22, 0, 0),
                           "arm.R": (26, 0, 0), "leg.L": (22, 0, 0),
                           "spine": (0, 0, -3), "head": (2, 0, 2),
                           "tail1": (-12, 0, -8), "tail2": (-12, 0, -10)}),
        32: merge(base_w, {"arm.L": (26, 0, 0), "leg.R": (22, 0, 0),
                           "arm.R": (-26, 0, 0), "leg.L": (-22, 0, 0),
                           "spine": (0, 0, 3), "head": (2, 0, -2),
                           "tail1": (-12, 0, 8), "tail2": (-12, 0, 10)}),
    }))

    # --- run: 보폭을 키우고 몸을 낮춘다 ---
    base_r = tuck(0.90, 0.90)
    actions.append(clip("run", 20, {
        1:  merge(base_r, {"arm.L": (44, 0, 0), "leg.R": (40, 0, 0),
                           "arm.R": (-44, 0, 0), "leg.L": (-40, 0, 0),
                           "spine": (7, 0, 0), "hips": (-5, 0, 0), "head": (-6, 0, 0),
                           "tail1": (-26, 0, 0), "tail2": (-20, 0, 0), "tail3": (-14, 0, 0)}),
        10: merge(base_r, {"arm.L": (-44, 0, 0), "leg.R": (-40, 0, 0),
                           "arm.R": (44, 0, 0), "leg.L": (40, 0, 0),
                           "spine": (11, 0, 0), "hips": (-9, 0, 0), "head": (-9, 0, 0),
                           "tail1": (-32, 0, 0), "tail2": (-24, 0, 0), "tail3": (-16, 0, 0)}),
        20: merge(base_r, {"arm.L": (44, 0, 0), "leg.R": (40, 0, 0),
                           "arm.R": (-44, 0, 0), "leg.L": (-40, 0, 0),
                           "spine": (7, 0, 0), "hips": (-5, 0, 0), "head": (-6, 0, 0),
                           "tail1": (-26, 0, 0), "tail2": (-20, 0, 0), "tail3": (-14, 0, 0)}),
    }))

    # --- jump: 웅크렸다 펴기. 정점에서 팔다리가 반쯤 벌어진다 ---
    actions.append(clip("jump", 24, {
        1:  tuck(1.05, 1.05, {"arm.L": (-38, 0, 0), "arm.R": (-38, 0, 0),
                              "leg.L": (42, 0, 0), "leg.R": (42, 0, 0),
                              "spine": (13, 0, 0), "head": (-10, 0, 0),
                              "tail1": (-34, 0, 0), "tail2": (-24, 0, 0)}),
        12: tuck(0.35, 0.42, {"arm.L": (-14, 0, 0), "arm.R": (-14, 0, 0),
                              "leg.L": (18, 0, 0), "leg.R": (18, 0, 0),
                              "spine": (-7, 0, 0), "head": (-16, 0, 0),
                              "tail1": (-12, 0, 0), "tail2": (-8, 0, 0)}),
        24: tuck(1.05, 1.05, {"arm.L": (-38, 0, 0), "arm.R": (-38, 0, 0),
                              "leg.L": (42, 0, 0), "leg.R": (42, 0, 0),
                              "spine": (13, 0, 0), "head": (-10, 0, 0),
                              "tail1": (-34, 0, 0), "tail2": (-24, 0, 0)}),
    }))

    # --- glide: 기본 자세가 이미 활공 자세다. 여기서는 미세하게 흔들린다 ---
    actions.append(clip("glide", 60, {
        1:  {"arm.L": (0, 0, -3), "arm.R": (0, 0, 3),
             "leg.L": (0, 0, -2), "leg.R": (0, 0, 2),
             "spine": (-7, 0, 0), "head": (-13, 0, 0),
             "tail1": (9, 0, -5), "tail2": (7, 0, -7), "tail3": (5, 0, -6)},
        30: {"arm.L": (0, 0, -8), "arm.R": (0, 0, 8),
             "leg.L": (0, 0, -6), "leg.R": (0, 0, 6),
             "spine": (-4, 0, 0), "head": (-8, 0, 0),
             "tail1": (11, 0, 5), "tail2": (9, 0, 7), "tail3": (6, 0, 6)},
        60: {"arm.L": (0, 0, -3), "arm.R": (0, 0, 3),
             "leg.L": (0, 0, -2), "leg.R": (0, 0, 2),
             "spine": (-7, 0, 0), "head": (-13, 0, 0),
             "tail1": (9, 0, -5), "tail2": (7, 0, -7), "tail3": (5, 0, -6)},
    }))

    reset_pose()
    bpy.ops.object.mode_set(mode="OBJECT")
    log("애니메이션 클립: " + ", ".join(a.name for a in actions))
    return actions


# =============================================================================
# 내보내기 / 측정 / 미리보기
# =============================================================================
def export_glb(path):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_apply=True,
        export_animations=True,
        export_animation_mode="NLA_TRACKS",
        export_yup=True,
    )
    log(f"내보내기: {path} ({os.path.getsize(path):,} bytes)")


def scene_bounds(verbose=False):
    """모디파이어까지 적용된 실제 형상의 경계 상자."""
    deps = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    tris = verts = 0
    found = False
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(deps)
        try:
            mesh = ev.to_mesh()
        except RuntimeError:
            continue
        verts += len(mesh.vertices)
        tris += sum(max(len(p.vertices) - 2, 0) for p in mesh.polygons)
        for v in mesh.vertices:
            p = obj.matrix_world @ v.co
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
            found = True
        ev.to_mesh_clear()
    if not found:
        return Vector((0, 0, 0)), 1.0
    if verbose:
        size = hi - lo
        log(f"AABB min ({lo.x:.6f}, {lo.y:.6f}, {lo.z:.6f})")
        log(f"AABB max ({hi.x:.6f}, {hi.y:.6f}, {hi.z:.6f})")
        log(f"AABB 크기 X(폭)={size.x:.6f} m  Y(길이)={size.y:.6f} m  Z(높이)={size.z:.6f} m")
        log(f"삼각형 {tris:,}개 / 정점 {verts:,}개")
    center = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 0.1)
    return center, radius


def setup_render_world():
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue

    # 기본 뷰 트랜스폼(AgX)은 밝고 채도 높은 색을 흰색으로 밀어버려서
    # 실제 베이스 컬러를 눈으로 판단할 수 없다. 미리보기는 Standard 로 본다.
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except TypeError:
        pass

    key = bpy.data.lights.new("Key", "SUN")
    key.energy = 2.1
    key_obj = bpy.data.objects.new("Key", key)
    key_obj.rotation_euler = (rad(52), rad(12), rad(35))
    bpy.context.collection.objects.link(key_obj)

    fill = bpy.data.lights.new("Fill", "SUN")
    fill.energy = 0.85
    fill_obj = bpy.data.objects.new("Fill", fill)
    fill_obj.rotation_euler = (rad(64), 0, rad(-125))
    bpy.context.collection.objects.link(fill_obj)

    rim = bpy.data.lights.new("Rim", "SUN")
    rim.energy = 1.15
    rim_obj = bpy.data.objects.new("Rim", rim)
    rim_obj.rotation_euler = (rad(104), 0, rad(190))
    bpy.context.collection.objects.link(rim_obj)

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.55, 0.62, 0.69, 1.0)
    bg.inputs[1].default_value = 0.55
    scene.world = world
    return scene


VIEWS = [
    ("정면",   -90.0, 6.0),
    ("측면",     0.0, 6.0),
    ("3/4앞",  -50.0, 22.0),
    ("위",     -70.0, 68.0),
]


def _get_camera(scene, size):
    cam = scene.camera
    if cam is None:
        cam_data = bpy.data.cameras.new("Cam")
        cam_data.lens = 62
        cam = bpy.data.objects.new("Cam", cam_data)
        bpy.context.collection.objects.link(cam)
        scene.camera = cam
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    return cam


def _shoot(scene, cam, center, dist, azim, elev, tmp):
    a, e = rad(azim), rad(elev)
    offset = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e))) * dist
    cam.location = center + offset
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(tmp)
    w, h = img.size
    arr = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    os.remove(tmp)
    return arr


def _save_sheet(tiles, cols, path):
    rows = []
    for i in range(0, len(tiles), cols):
        rows.append(np.concatenate(tiles[i:i + cols], axis=1))
    # 블렌더 픽셀은 아래에서 위로 쌓이므로 위쪽 줄이 배열 뒤에 와야 한다
    sheet = np.concatenate(list(reversed(rows)), axis=0)
    H, W = sheet.shape[0], sheet.shape[1]
    out = bpy.data.images.new("sheet", W, H, alpha=True)
    out.pixels = sheet.reshape(-1).tolist()
    out.filepath_raw = os.path.abspath(path)
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    return W, H


def render_preview(path, size=700):
    scene = setup_render_world()
    center, radius = scene_bounds(verbose=True)
    cam = _get_camera(scene, size)
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(tmp_dir, exist_ok=True)

    dist = radius * 3.05
    tiles = [_shoot(scene, cam, center, dist, az, el,
                    os.path.join(tmp_dir, "_v.png")) for _, az, el in VIEWS]
    W, H = _save_sheet(tiles, 2, path)
    log(f"미리보기: {os.path.abspath(path)} ({W}x{H}, {'/'.join(v[0] for v in VIEWS)})")

    # 얼굴 클로즈업 — 눈·코·귀가 사진과 얼마나 닮았는지 보려면 따로 필요하다
    face_path = os.path.splitext(path)[0] + "_face.png"
    fcam = _get_camera(scene, 600)
    fcam.data.lens = 85
    fdist = HR * 4.1
    ftiles = [_shoot(scene, fcam, HEAD, fdist, az, el, os.path.join(tmp_dir, "_f.png"))
              for az, el in ((-90.0, 4.0), (-52.0, 14.0), (-16.0, 6.0), (-90.0, 46.0))]
    W, H = _save_sheet(ftiles, 2, face_path)
    fcam.data.lens = 62
    log(f"얼굴 클로즈업: {os.path.abspath(face_path)} ({W}x{H})")


def render_poses(rig, path, size=520):
    """애니메이션을 얹기 전에, 접은 자세(지상)와 편 자세(활공)를 확인한다."""
    scene = bpy.context.scene
    if scene.world is None:
        setup_render_world()
    cam = _get_camera(scene, size)
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(tmp_dir, exist_ok=True)

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, 0, 0)
    for name, val in tuck(1.0, 1.0, {"spine": (0, 0, 0), "tail1": (-14, 0, 0),
                                     "tail2": (-16, 0, 0)}).items():
        pb = rig.pose.bones.get(name)
        if pb:
            pb.rotation_euler = (rad(val[0]), rad(val[1]), rad(val[2]))
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    center, radius = scene_bounds()
    dist = radius * 3.05
    tiles = [_shoot(scene, cam, center, dist, az, el,
                    os.path.join(tmp_dir, "_p.png"))
             for az, el in ((-90.0, 6.0), (0.0, 6.0), (-50.0, 20.0), (-60.0, 60.0))]
    W, H = _save_sheet(tiles, 2, path)
    log(f"접은 자세 미리보기: {os.path.abspath(path)} ({W}x{H})")

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    for pb in rig.pose.bones:
        pb.rotation_euler = (0, 0, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


# =============================================================================
def main():
    out, preview, posefile = parse_args()
    clear_scene()

    m = build_materials()
    body = build_body(m)
    limbs = build_limbs(m)
    head, eyeL, eyeR = build_head(m)
    face = build_face(m, eyeL, eyeR)
    paws = build_paws(m)
    wings = build_patagium(m)
    tail = build_tail(m)

    # 닫힌 메시는 전부 바깥 법선이어야 한다 (수염은 열린 원뿔이라 제외).
    check_winding([o for o in bpy.context.scene.objects
                   if o.type == "MESH" and not o.name.startswith("Whisker")])

    # 털결 텍스처 (노멀맵 + 러프니스). 파티클 헤어는 glTF 로 안 나가므로 이쪽으로 낸다.
    img_n, img_r = build_fur_textures(256)
    fur_objs = [o for o in bpy.context.scene.objects
                if o.type == "MESH" and any(mm is m.fur for mm in o.data.materials)]
    uv_and_texture(fur_objs, [m.fur], img_n, img_r, uv_scale=7.0)

    rig = build_armature()
    bind_auto(rig, [body] + wings)
    bind_tail(rig, tail)
    for o in [head] + face:
        bind_rigid(rig, o, "head")
    for o, bone in paws + limbs:
        bind_rigid(rig, o, bone)

    if preview:
        render_preview(preview)
    if posefile:
        render_poses(rig, posefile)

    make_animations(rig)
    export_glb(out)
    log("완료")


if __name__ == "__main__":
    main()
