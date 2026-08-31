"""축척 검토 전용 렌더 스크립트 (일회성 조사 도구, 모델을 만들지 않는다).

사용자 요구: "나무에 비해 다람쥐가 너무 커. 나무 단면의 1/32 정도 사이즈로 해줘."
그 요구를 그대로 적용하면 나무가 어떻게 되는지 PD 가 눈으로 판단하기 위한 자료를 만든다.

★ 이 스크립트는 models/*.glb 를 절대 내보내지 않는다. 렌더만 한다.
★ build_pine_tree.py / build_area_forest.py 를 고치지 않는다. import 해서 읽기만 한다.

나무를 키우는 방법은 '균일 스케일 S 를 준 부모 Empty' 다.
균일 스케일은 높이:지름 비율을 그대로 보존하므로, S 배 키운 나무는
build_pine_tree.py 의 상수를 전부 S 배 한 나무와 형상이 동일하다.

실행:
  blender --background --python blender/_scalestudy.py -- \
      --out blender/_preview/scale_study [--measure-only]
"""
import math
import os
import sys

import bpy
from mathutils import Vector, Matrix

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import build_pine_tree as PT           # noqa: E402


# =============================================================================
# 조사 대상 비율
# =============================================================================
N_LIST = (4, 8, 16, 32)
GLIDE_RATIO = 10.5 / 2.4               # player.gd: glide_speed / glide_max_fall
WALK_SPEED = 4.5                       # player.gd: walk_speed
HUMAN_H = 1.70                         # 비교용 사람 실루엣 키 (m)
PERCH_U = 0.10                         # 다람쥐를 붙이는 높이 = 나무 높이의 10%

MARK = (1.0, 0.15, 0.45)               # 마커 색 (자홍)
MARK2 = (1.0, 0.85, 0.10)              # 사람 마커 색 (노랑)

# 카메라 방위각. 다람쥐와 사람 막대를 이 방위각의 기둥 면에 붙여
# 기둥 뒤로 숨지 않게 한다 (첫 렌더에서 실제로 숨었다).
CAM_AZ_DEG = -78.0


def log(m):
    print(f"[축척] {m}")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = "blender/_preview/scale_study"
    measure_only = "--measure-only" in argv
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
    return os.path.abspath(out), measure_only


# =============================================================================
# 씬 구성
# =============================================================================
def build_scene():
    """나무 한 그루(스케일용 Empty 아래) + 다람쥐 한 마리 + 사람 막대."""
    PT.clear_scene()
    trunk, branches, items = PT.build_tree()

    root = bpy.data.objects.new("나무루트", None)
    bpy.context.collection.objects.link(root)
    tree_objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in tree_objs:
        o.parent = root
    bpy.context.view_layer.update()

    got = PT.import_squirrel()
    if got is None:
        raise RuntimeError("하늘다람쥐 임포트 실패 — 축척 비교를 할 수 없다")
    sq_objs, sq_roots = got

    return dict(root=root, trunk=trunk, tree_objs=tree_objs,
                items=items, sq_objs=sq_objs, sq_roots=sq_roots)


def group_bounds(objs):
    return PT.object_group_bounds(objs)


def set_scale(root, S):
    root.scale = (S, S, S)
    bpy.context.view_layer.update()


# --- 기둥 실측 ---------------------------------------------------------------
def trunk_axis_and_radius(S, zw):
    """스케일 S 인 나무의 월드 높이 zw 에서 기둥 축 위치와 반지름 (해석값)."""
    y = zw / S
    c = PT.trunk_center(y)
    return Vector((c.x * S, c.y * S, 0.0)), PT.trunk_radius(y) * S


def measure_trunk_radius(trunk, zw, band):
    """기둥 메시 정점에서 실제로 잰 반지름 (최소/평균/최대). 축은 그 높이의 정점 평균."""
    deps = bpy.context.evaluated_depsgraph_get()
    ev = trunk.evaluated_get(deps)
    mesh = ev.to_mesh()
    pts = []
    for v in mesh.vertices:
        p = trunk.matrix_world @ v.co
        if abs(p.z - zw) <= band:
            pts.append(p)
    ev.to_mesh_clear()
    if not pts:
        return None
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    ds = [math.hypot(p.x - cx, p.y - cy) for p in pts]
    return min(ds), sum(ds) / len(ds), max(ds), Vector((cx, cy, 0.0)), len(pts)


# --- 다람쥐 배치 -------------------------------------------------------------
# 기둥에 매달린 자세: 배(로컬 -Z)를 기둥 쪽으로, 머리(로컬 -Y)를 위(+Z)로.
# 방위각 th 의 기둥 면에 붙일 때 로컬→월드 열벡터는
#   X → (sin th, -cos th, 0)      (기둥 접선)
#   Y → (0, 0, -1)                (머리가 +Z 를 향한다)
#   Z → (cos th, sin th, 0)       (등이 기둥 바깥을 향한다)
def cling_matrix(th):
    s, c = math.sin(th), math.cos(th)
    return Matrix(((s, 0.0, c),
                   (-c, 0.0, s),
                   (0.0, -1.0, 0.0)))


def group_extent(objs, axis):
    """월드 정점을 단위벡터 axis 에 투영한 (최소, 최대)."""
    deps = bpy.context.evaluated_depsgraph_get()
    lo, hi = 1e18, -1e18
    for obj in objs:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(deps)
        try:
            mesh = ev.to_mesh()
        except RuntimeError:
            continue
        for v in mesh.vertices:
            d = (obj.matrix_world @ v.co).dot(axis)
            lo = min(lo, d)
            hi = max(hi, d)
        ev.to_mesh_clear()
    return lo, hi


def place_squirrel_on_trunk(sq_roots, sq_objs, S, zw, th=0.0, sink=0.03):
    """방위각 th 쪽 기둥 표면에 매달리게 놓는다. 반환: (lo, hi) 월드 AABB."""
    # ★ glTF 임포터가 만든 루트는 rotation_mode 가 QUATERNION 이다.
    #   rotation_euler 에 넣으면 아무 일도 일어나지 않는다 (조용한 실패).
    quat = cling_matrix(th).to_quaternion()
    for r in sq_roots:
        r.rotation_mode = "QUATERNION"
        r.rotation_quaternion = quat
        r.scale = (1.0, 1.0, 1.0)
        r.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    n = Vector((math.cos(th), math.sin(th), 0.0))
    t = Vector((-math.sin(th), math.cos(th), 0.0))
    z = Vector((0.0, 0.0, 1.0))
    axis, rad = trunk_axis_and_radius(S, zw)

    nlo, _ = group_extent(sq_objs, n)
    tlo, thi = group_extent(sq_objs, t)
    zlo, zhi = group_extent(sq_objs, z)
    delta = (n * ((axis.dot(n) + rad - sink) - nlo)
             + t * (axis.dot(t) - (tlo + thi) * 0.5)
             + z * (zw - (zlo + zhi) * 0.5))
    for r in sq_roots:
        r.location = Vector(r.location) + delta
    bpy.context.view_layer.update()
    return group_bounds(sq_objs)


def hide(objs, state):
    for o in objs:
        o.hide_render = state


# --- 사람 막대 ---------------------------------------------------------------
_HUMAN = None


def make_human():
    """1.7m 사람 크기 막대 실루엣 (머리 + 몸통)."""
    global _HUMAN
    if _HUMAN is not None:
        return _HUMAN
    mat = PT.make_material("HumanSil", (0.05, 0.02, 0.10, 1.0), 0.9)
    body_h, body_w = HUMAN_H * 0.80, 0.46
    head_r = HUMAN_H * 0.115
    verts, faces = [], []

    def box(cx, cy, z0, z1, hw, hd):
        o = len(verts)
        for z in (z0, z1):
            verts.extend([(cx - hw, cy - hd, z), (cx + hw, cy - hd, z),
                          (cx + hw, cy + hd, z), (cx - hw, cy + hd, z)])
        faces.extend([(o, o + 1, o + 2, o + 3), (o + 7, o + 6, o + 5, o + 4),
                      (o, o + 4, o + 5, o + 1), (o + 1, o + 5, o + 6, o + 2),
                      (o + 2, o + 6, o + 7, o + 3), (o + 3, o + 7, o + 4, o)])

    box(0, 0, 0.0, body_h, body_w * 0.5, 0.15)
    box(0, 0, body_h, body_h + head_r * 2, head_r, head_r)
    _HUMAN = PT.build_mesh_object("사람막대", verts, faces, mat, smooth=False)
    return _HUMAN


# =============================================================================
# 렌더
# =============================================================================
import numpy as np                     # noqa: E402
from bpy_extras.object_utils import world_to_camera_view   # noqa: E402

_GROUND = None


def make_ground(radius=6000.0):
    global _GROUND
    if _GROUND is not None:
        return _GROUND
    n = 64
    ring = [Vector((math.cos(2 * math.pi * i / n) * radius,
                    math.sin(2 * math.pi * i / n) * radius, 0.0)) for i in range(n)]
    inner = [Vector((p.x * 0.0002, p.y * 0.0002, 0.0)) for p in ring]
    mat = PT.make_material("StudyGround", (0.82, 0.87, 0.94, 1.0), 0.9)
    _GROUND = PT.build_loft("검토용바닥", [inner, ring], mat, smooth=False,
                            cap_start=False, cap_end=False)
    return _GROUND


def make_camera(vfov_deg, clip_end=40000.0):
    cd = bpy.data.cameras.new("StudyCam")
    cd.sensor_fit = "VERTICAL"
    cd.angle_y = math.radians(vfov_deg)
    cd.clip_start = 0.03
    cd.clip_end = clip_end
    cam = bpy.data.objects.new("StudyCam", cd)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def aim(cam, loc, target):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()


_LABEL_MAT = None


def label_material():
    global _LABEL_MAT
    if _LABEL_MAT is None:
        m = bpy.data.materials.new("LabelMat")
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0, 0, 0, 1)
        b.inputs["Emission Color"].default_value = (1, 1, 1, 1)
        b.inputs["Emission Strength"].default_value = 1.0
        _LABEL_MAT = m
    return _LABEL_MAT


def add_label_bg(cam, w, h, band_frac, dist=1.06):
    """라벨 뒤에 깔 어두운 띠. 카메라에 붙여 화면 상단을 덮는다."""
    half_h = dist * math.tan(cam.data.angle_y * 0.5) * 1.02
    half_w = half_h * (w / h)
    y1 = half_h
    y0 = half_h - 2.0 * half_h * band_frac
    verts = [(-half_w, y0, -dist), (half_w, y0, -dist),
             (half_w, y1, -dist), (-half_w, y1, -dist)]
    m = bpy.data.materials.new("LabelBG")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0, 0, 0, 1)
    b.inputs["Emission Color"].default_value = (0.055, 0.065, 0.095, 1.0)
    b.inputs["Emission Strength"].default_value = 1.0
    obj = PT.build_mesh_object("라벨배경", verts, [(0, 1, 2, 3)], m, smooth=False)
    obj.parent = cam
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.location = (0, 0, 0)
    obj.visible_shadow = False        # 그림자를 끄지 않으면 글자 그림자가 유령처럼 찍힌다
    bpy.context.view_layer.update()
    return obj


def add_label(cam, text, w, h, size_frac=0.040, corner="TL", dist=1.0, color=None):
    """카메라에 붙은 3D 텍스트. 화면 고정 위치에 나온다. (ASCII 만 — 기본 폰트에 한글 없음)"""
    cu = bpy.data.curves.new("Label", type="FONT")
    cu.body = text
    half_h = dist * math.tan(cam.data.angle_y * 0.5)
    half_w = half_h * (w / h)
    cu.size = 2.0 * half_h * size_frac
    cu.align_x = "LEFT" if corner[1] == "L" else "RIGHT"
    cu.align_y = "TOP" if corner[0] == "T" else "BOTTOM"
    obj = bpy.data.objects.new("Label", cu)
    mat = label_material()
    if color is not None:
        mat = mat.copy()
        mat.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = \
            (color[0], color[1], color[2], 1.0)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    obj.parent = cam
    x = -half_w * 0.93 if corner[1] == "L" else half_w * 0.93
    y = half_h * 0.93 if corner[0] == "T" else -half_h * 0.93
    obj.location = (x, y, -dist)
    obj.rotation_euler = (0, 0, 0)
    obj.visible_shadow = False
    bpy.context.view_layer.update()
    return obj


def fit_frame(cam, objs, w, h, az, elev, top_frac, bot_frac=0.025, iters=14):
    """objs 가 화면 세로 [bot_frac, top_frac] 안에 들어오도록 카메라 거리와 주시 높이를 맞춘다.

    추측하지 않는다. 실제로 투영해서 픽셀을 재고, 어긋난 만큼 고쳐 되풀이한다.
    """
    lo, hi = group_bounds(objs)
    d = max((hi - lo).length * 1.6, 1.0)
    zc = (lo.z + hi.z) * 0.5
    a, e = math.radians(az), math.radians(elev)
    dirv = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e)))
    axis_xy = Vector(((lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5, 0.0))
    want_c = (top_frac + bot_frac) * 0.5 * h
    want_span = (top_frac - bot_frac) * h

    for _ in range(iters):
        tgt = Vector((axis_xy.x, axis_xy.y, zc))
        aim(cam, tgt + dirv * d, tgt)
        _, cy, _, ry, _ = screen_box(cam, w, h, lo, hi)
        span = max(2.0 * ry, 1.0)
        frame_world = 2.0 * d * math.tan(cam.data.angle_y * 0.5)
        if abs(span - want_span) / want_span < 0.01 and abs(cy - want_c) < 0.005 * h:
            break
        zc += (want_c - cy) / h * frame_world
        d *= span / want_span
    tgt = Vector((axis_xy.x, axis_xy.y, zc))
    aim(cam, tgt + dirv * d, tgt)
    cx, cy, rx, ry, _ = screen_box(cam, w, h, lo, hi)
    return d, (cy - ry) / h, (cy + ry) / h


def render_tile(w, h, tmp):
    sc = bpy.context.scene
    sc.render.resolution_x = w
    sc.render.resolution_y = h
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.film_transparent = False
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(tmp)
    iw, ih = img.size
    arr = np.array(img.pixels[:], dtype=np.float32).reshape(ih, iw, 4)
    bpy.data.images.remove(img)
    os.remove(tmp)
    return arr


def save_png(arr, path):
    H, W = arr.shape[0], arr.shape[1]
    out = bpy.data.images.new(os.path.basename(path), W, H, alpha=True)
    out.pixels = arr.reshape(-1).tolist()
    out.filepath_raw = os.path.abspath(path)
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    log(f"저장: {path} ({W}x{H})")
    return W, H


# --- 마커 그리기 (블렌더 픽셀은 아래→위. 행 0 이 화면 맨 아래) ----------------
def screen_box(cam, w, h, lo, hi):
    """월드 AABB 8꼭짓점을 화면 픽셀로. 반환 (cx, cy, rx, ry, 앞쪽여부)"""
    sc = bpy.context.scene
    xs, ys, ok = [], [], False
    for i in range(8):
        p = Vector((lo.x if i & 1 else hi.x,
                    lo.y if i & 2 else hi.y,
                    lo.z if i & 4 else hi.z))
        n = world_to_camera_view(sc, cam, p)
        if n.z > 0:
            ok = True
        xs.append(n.x * w)
        ys.append(n.y * h)
    return ((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5,
            (max(xs) - min(xs)) * 0.5, (max(ys) - min(ys)) * 0.5, ok)


def draw_ring(img, cx, cy, r, color, thick=2.0):
    h, w = img.shape[:2]
    y0, y1 = int(max(0, cy - r - thick - 2)), int(min(h, cy + r + thick + 3))
    x0, x1 = int(max(0, cx - r - thick - 2)), int(min(w, cx + r + thick + 3))
    if y1 <= y0 or x1 <= x0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx - cx, yy - cy)
    m = np.abs(d - r) <= thick
    sub = img[y0:y1, x0:x1]
    sub[m, 0] = color[0]
    sub[m, 1] = color[1]
    sub[m, 2] = color[2]


def draw_seg(img, p0, p1, color, thick=2.0):
    h, w = img.shape[:2]
    n = int(max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1]))) + 1
    t = int(math.ceil(thick))
    for i in range(n + 1):
        u = i / max(n, 1)
        x = int(round(p0[0] + (p1[0] - p0[0]) * u))
        y = int(round(p0[1] + (p1[1] - p0[1]) * u))
        x0, x1 = max(0, x - t), min(w, x + t + 1)
        y0, y1 = max(0, y - t), min(h, y + t + 1)
        if x1 > x0 and y1 > y0:
            img[y0:y1, x0:x1, 0] = color[0]
            img[y0:y1, x0:x1, 1] = color[1]
            img[y0:y1, x0:x1, 2] = color[2]


def mark(img, cx, cy, rx, ry, color, min_r=13.0, arrow=True):
    """대상을 원으로 감싸고, 원이 작으면 위에서 화살표를 내려 꽂는다."""
    r = max(math.hypot(rx, ry) * 1.35, min_r)
    draw_ring(img, cx, cy, r, color, thick=1.8)
    if arrow:
        tip_y = cy + r + 4
        top_y = min(img.shape[0] - 4, tip_y + max(46.0, r * 2.2))
        draw_seg(img, (cx, top_y), (cx, tip_y), color, thick=1.6)
        wing = (top_y - tip_y) * 0.22
        draw_seg(img, (cx, tip_y), (cx - wing * 0.6, tip_y + wing), color, thick=1.6)
        draw_seg(img, (cx, tip_y), (cx + wing * 0.6, tip_y + wing), color, thick=1.6)
    return r


def border(img, color=(0.15, 0.15, 0.18), t=2):
    img[:t, :, 0:3] = color
    img[-t:, :, 0:3] = color
    img[:, :t, 0:3] = color
    img[:, -t:, 0:3] = color


# =============================================================================
# 수치표
# =============================================================================
def build_table(sq_w, trunk_dia_now, tree_h_now, crown_w_now):
    rows = []
    ratio_now = trunk_dia_now / sq_w
    cases = [("NOW", ratio_now, 1.0)] + [
        (f"N={n}", float(n), n * sq_w / trunk_dia_now) for n in N_LIST]
    for name, n, S in cases:
        dia = trunk_dia_now * S
        h = tree_h_now * S
        rows.append(dict(
            name=name, N=n, S=S, dia=dia, height=h,
            lowest=PT.WHORL_LOWEST_Y * S,
            branch=PT.BRANCH_LENGTH * S,
            crown=crown_w_now * S,
            circ=math.pi * dia,
            climb=h / WALK_SPEED,
            glide=h * GLIDE_RATIO,
        ))
    return rows


def print_table(rows):
    hdr = (f"{'case':>6} {'N':>6} {'scale S':>8} {'base dia':>9} {'height':>9} "
           f"{'lowbranch':>10} {'branchlen':>10} {'crown W':>9} {'circumf':>9} "
           f"{'climb s':>8} {'glide m':>10}")
    log("=" * len(hdr))
    log(hdr)
    log("-" * len(hdr))
    for r in rows:
        log(f"{r['name']:>6} {r['N']:>6.2f} {r['S']:>8.3f} {r['dia']:>8.2f}m "
            f"{r['height']:>8.1f}m {r['lowest']:>9.1f}m {r['branch']:>9.1f}m "
            f"{r['crown']:>8.1f}m {r['circ']:>8.1f}m {r['climb']:>7.1f}s "
            f"{r['glide']:>9.0f}m")
    log("=" * len(hdr))


# =============================================================================
# 시트 A — 전신 비교
# =============================================================================
def sheet_full(ctx, rows, outdir, tile_w=520, tile_h=1240):
    cam = make_camera(34.0)
    tiles = []
    tmp = os.path.join(outdir, "_tmp.png")
    human = make_human()
    human.hide_render = True
    th = math.radians(CAM_AZ_DEG)
    band = 0.250
    bg = add_label_bg(cam, tile_w, tile_h, band)

    for r in rows:
        set_scale(ctx["root"], r["S"])
        zw = r["height"] * PERCH_U
        slo, shi = place_squirrel_on_trunk(ctx["sq_roots"], ctx["sq_objs"], r["S"], zw, th)
        H = r["height"]
        d, f0, f1 = fit_frame(cam, ctx["tree_objs"], tile_w, tile_h,
                              CAM_AZ_DEG, 7.0, 1.0 - band - 0.012)
        lab = add_label(
            cam,
            f"{r['name']}   squirrel : trunk = 1 : {r['N']:.2f}\n"
            f"tree height   {r['height']:8.1f} m\n"
            f"base diameter {r['dia']:8.2f} m\n"
            f"crown width   {r['crown']:8.1f} m\n"
            f"lowest branch {r['lowest']:8.1f} m\n"
            f"climb to top  {r['climb']:8.1f} s\n"
            f"glide range   {r['glide']:8.0f} m",
            tile_w, tile_h, size_frac=0.0285)
        img = render_tile(tile_w, tile_h, tmp)
        bpy.data.objects.remove(lab, do_unlink=True)

        cx, cy, rx, ry, ok = screen_box(cam, tile_w, tile_h, slo, shi)
        rr = mark(img, cx, cy, rx, ry, MARK, min_r=15.0)
        log(f"[A] {r['name']:>5}  나무높이 {r['height']:8.1f}m  카메라거리 {d:8.1f}m  "
            f"나무 화면세로 {f0 * 100:.1f}~{f1 * 100:.1f}% (라벨띠 아래 {(1 - band) * 100:.1f}%)  "
            f"다람쥐 화면크기 {rx * 2:6.1f}x{ry * 2:6.1f}px  마커반경 {rr:.0f}px")
        border(img)
        tiles.append(img)

    bpy.data.objects.remove(bg, do_unlink=True)
    bpy.data.objects.remove(cam, do_unlink=True)
    path = os.path.join(outdir, "A_전신비교_5단계.png")
    save_png(np.concatenate(tiles, axis=1), path)
    return path


# =============================================================================
# 시트 B — 근접(3인칭 카메라) 비교
# =============================================================================
def sheet_closeup(ctx, rows, outdir, tile_w=820, tile_h=620):
    # 게임의 third_person_camera.gd: distance 5.0, height 1.15, fov 62 (수직)
    cam = make_camera(62.0)
    tiles = []
    tmp = os.path.join(outdir, "_tmp.png")
    th = math.radians(CAM_AZ_DEG)
    n = Vector((math.cos(th), math.sin(th), 0.0))
    bg = add_label_bg(cam, tile_w, tile_h, 0.135)

    for r in rows:
        set_scale(ctx["root"], r["S"])
        zw = r["height"] * PERCH_U
        slo, shi = place_squirrel_on_trunk(ctx["sq_roots"], ctx["sq_objs"], r["S"], zw, th)
        c = (slo + shi) * 0.5
        axis, rad_here = trunk_axis_and_radius(r["S"], zw)
        # 기둥에 매달린 플레이어의 '뒤' = 기둥 바깥. 살짝 위에서 내려다본다.
        look = Vector((c.x, c.y, c.z + 0.20))
        loc = look + n * 5.0 + Vector((0.0, 0.0, 1.15))
        aim(cam, loc, look)
        sq_w_here = group_extent(
            ctx["sq_objs"], Vector((-math.sin(th), math.cos(th), 0.0)))
        sq_w_here = sq_w_here[1] - sq_w_here[0]
        lab = add_label(
            cam,
            f"{r['name']}   squirrel : trunk = 1 : {r['N']:.2f}\n"
            f"trunk dia here {rad_here * 2:.2f} m  (base {r['dia']:.2f} m)   "
            f"squirrel width {sq_w_here:.2f} m",
            tile_w, tile_h, size_frac=0.048)
        img = render_tile(tile_w, tile_h, tmp)
        bpy.data.objects.remove(lab, do_unlink=True)
        log(f"[B] {r['name']:>5}  매단높이 {zw:8.1f}m  그 지점 기둥지름 {rad_here * 2:8.2f}m  "
            f"다람쥐폭 {sq_w_here:.3f}m  기둥지름/다람쥐폭 = {rad_here * 2 / sq_w_here:6.2f}")
        border(img)
        tiles.append(img)

    bpy.data.objects.remove(bg, do_unlink=True)
    bpy.data.objects.remove(cam, do_unlink=True)
    path = os.path.join(outdir, "B_근접비교_3인칭시점.png")
    save_png(np.concatenate(tiles, axis=1), path)
    return path


# =============================================================================
# 시트 C — N=32 전용 + 사람(1.7m)
# =============================================================================
def sheet_n32(ctx, rows, outdir, w=1100, h=1500):
    r = [x for x in rows if x["name"] == "N=32"][0]
    th = math.radians(CAM_AZ_DEG)
    n = Vector((math.cos(th), math.sin(th), 0.0))
    set_scale(ctx["root"], r["S"])
    zw = r["height"] * PERCH_U
    slo, shi = place_squirrel_on_trunk(ctx["sq_roots"], ctx["sq_objs"], r["S"], zw, th)

    human = make_human()
    human.hide_render = False
    human.rotation_euler = (0.0, 0.0, th)
    axis, rad0 = trunk_axis_and_radius(r["S"], 0.9)
    human.location = tuple(axis + n * (rad0 + 3.0))
    bpy.context.view_layer.update()
    hlo, hhi = group_bounds([human])
    log(f"[C] 사람 막대 실측 높이 {hhi.z - hlo.z:.2f}m  위치 "
        f"({human.location.x:.1f}, {human.location.y:.1f})  "
        f"(밑동 반지름 {rad0:.1f}m 바깥 3m, 카메라 방위각 위)")

    cam = make_camera(34.0)
    tmp = os.path.join(outdir, "_tmp.png")
    band = 0.285
    hide(ctx["sq_objs"], True)
    human.hide_render = True
    d, f0, f1 = fit_frame(cam, ctx["tree_objs"], w, h, CAM_AZ_DEG, 6.0,
                          1.0 - band - 0.012)
    hide(ctx["sq_objs"], False)
    human.hide_render = False
    log(f"[C] 나무 화면세로 {f0 * 100:.1f}~{f1 * 100:.1f}% / 라벨띠 아래 {(1 - band) * 100:.1f}%")
    bg = add_label_bg(cam, w, h, band)
    lab = add_label(
        cam,
        f"N=32   squirrel : trunk = 1 : 32\n"
        f"tree height     {r['height']:8.1f} m\n"
        f"base diameter   {r['dia']:8.2f} m\n"
        f"base circumf.   {r['circ']:8.1f} m\n"
        f"crown width     {r['crown']:8.1f} m\n"
        f"lowest branch   {r['lowest']:8.1f} m\n"
        f"branch length   {r['branch']:8.1f} m\n"
        f"climb to top    {r['climb']:8.1f} s\n"
        f"glide from top  {r['glide']:8.0f} m\n"
        f"magenta = squirrel 1.21 m\n"
        f"yellow  = human 1.70 m",
        w, h, size_frac=0.0225)
    img = render_tile(w, h, tmp)
    bpy.data.objects.remove(lab, do_unlink=True)

    cx, cy, rx, ry, _ = screen_box(cam, w, h, slo, shi)
    mark(img, cx, cy, rx, ry, MARK, min_r=16.0)
    hx, hy, hrx, hry, _ = screen_box(cam, w, h, hlo, hhi)
    mark(img, hx, hy, hrx, hry, MARK2, min_r=16.0)
    log(f"[C] 화면상 다람쥐 {rx * 2:.2f}x{ry * 2:.2f}px, 사람 {hrx * 2:.2f}x{hry * 2:.2f}px "
        f"(이미지 {w}x{h})")
    border(img)
    save_png(img, os.path.join(outdir, "C_N32_전체_사람1.7m비교.png"))

    bpy.data.objects.remove(bg, do_unlink=True)

    # 추가: 밑동만. 기둥 지름 38.7m 가 화면 폭에 겨우 들어오는 거리에서 본다.
    #      사람(1.7m)이 그 앞에 서 있는 그림 = 이 나무가 무엇인지 가장 정직하게 보여준다.
    d2 = 95.0
    tgt2 = axis + Vector((0.0, 0.0, 26.0))
    aim(cam, axis + n * (rad0 + d2) + Vector((0.0, 0.0, 34.0)), tgt2)
    frame_h = 2.0 * d2 * math.tan(cam.data.angle_y * 0.5)
    bg2 = add_label_bg(cam, w, h, 0.145)
    lab = add_label(cam,
                    f"N=32  trunk base\n"
                    f"frame {frame_h:.0f} m tall, {frame_h * w / h:.0f} m wide\n"
                    f"trunk dia {r['dia']:.1f} m, circumf. {r['circ']:.0f} m\n"
                    f"yellow ring = human 1.70 m",
                    w, h, size_frac=0.030)
    img2 = render_tile(w, h, tmp)
    bpy.data.objects.remove(lab, do_unlink=True)
    bpy.data.objects.remove(bg2, do_unlink=True)
    hx, hy, hrx, hry, _ = screen_box(cam, w, h, hlo, hhi)
    mark(img2, hx, hy, hrx, hry, MARK2, min_r=18.0)
    log(f"[C2] 카메라 거리 {d2:.0f}m  화면 높이 {frame_h:.1f}m  "
        f"사람 화면크기 {hrx * 2:.1f}x{hry * 2:.1f}px")
    border(img2)
    save_png(img2, os.path.join(outdir, "C2_N32_밑동_사람1.7m.png"))

    human.hide_render = True
    bpy.data.objects.remove(cam, do_unlink=True)


# =============================================================================
# 시트 D — 같은 축척으로 5그루를 나란히 (덤. 나무들끼리의 크기 차이를 본다)
# =============================================================================
def sheet_lineup(ctx, rows, outdir, w=2600, h=1300):
    th = math.radians(CAM_AZ_DEG)
    n = Vector((math.cos(th), math.sin(th), 0.0))
    tan = Vector((-math.sin(th), math.cos(th), 0.0))
    set_scale(ctx["root"], 1.0)
    hide(ctx["sq_objs"], True)

    # 접선 방향으로 늘어놓는다. 이웃한 수관이 안 겹치게 간격을 잡는다.
    pos, s = [], 0.0
    for i, r in enumerate(rows):
        if i:
            s += (rows[i - 1]["crown"] + r["crown"]) * 0.5 * 1.06
        pos.append(s)
    mid = (pos[0] + pos[-1]) * 0.5
    pos = [p - mid for p in pos]

    dups, empties, groups = [], [], []
    for r, p in zip(rows, pos):
        e = bpy.data.objects.new(f"줄_{r['name']}", None)
        bpy.context.collection.objects.link(e)
        e.location = tuple(tan * p)
        e.scale = (r["S"], r["S"], r["S"])
        empties.append(e)
        grp = []
        for o in ctx["tree_objs"]:
            c = o.copy()          # linked duplicate: 메시 공유, 모디파이어 복사
            bpy.context.collection.objects.link(c)
            c.parent = e
            c.matrix_parent_inverse = Matrix.Identity(4)
            dups.append(c)
            grp.append(c)
        groups.append(grp)
    bpy.context.view_layer.update()

    tallest = rows[-1]["height"]
    span = pos[-1] - pos[0] + rows[-1]["crown"]
    cam = make_camera(30.0)
    band = 0.085
    d, f0, f1 = fit_frame(cam, dups, w, h, CAM_AZ_DEG, 5.0, 1.0 - band - 0.012)
    bg = add_label_bg(cam, w, h, band)
    lab = add_label(cam,
                    "SAME SCALE, left to right:  NOW 18.1 m / N=4 87.4 m / "
                    "N=8 174.7 m / N=16 349.4 m / N=32 698.8 m\n"
                    "magenta ring = NOW tree, yellow ring = N=4  (spaced crown-to-"
                    "crown here; the forest script uses 18-26 m)",
                    w, h, size_frac=0.026)
    tmp = os.path.join(outdir, "_tmp.png")
    img = render_tile(w, h, tmp)
    for o in (lab, bg):
        bpy.data.objects.remove(o, do_unlink=True)

    for r, grp, col in zip(rows, groups, (MARK, MARK2, MARK2, MARK2, MARK2)):
        glo, ghi = group_bounds(grp)
        cx, cy, rx, ry, _ = screen_box(cam, w, h, glo, ghi)
        log(f"[D] {r['name']:>5} 화면크기 {rx * 2:7.1f}x{ry * 2:7.1f}px")
        if r["name"] in ("NOW", "N=4"):
            mark(img, cx, cy, rx, ry, col, min_r=13.0)
    bpy.data.objects.remove(cam, do_unlink=True)
    log(f"[D] 카메라 거리 {d:.0f}m  늘어놓은 폭 {span:.0f}m  가장 큰 나무 {tallest:.0f}m  "
        f"화면세로 {f0 * 100:.1f}~{f1 * 100:.1f}%")
    border(img)
    save_png(img, os.path.join(outdir, "D_같은축척_5그루_나란히.png"))

    for o in dups + empties:
        bpy.data.objects.remove(o, do_unlink=True)
    hide(ctx["sq_objs"], False)


# =============================================================================
def main():
    outdir, measure_only = parse_args()
    os.makedirs(outdir, exist_ok=True)

    ctx = build_scene()

    # ---- 실측 -------------------------------------------------------------
    set_scale(ctx["root"], 1.0)
    hide(ctx["sq_objs"], True)
    tlo, thi = group_bounds(ctx["tree_objs"])
    hide(ctx["sq_objs"], False)
    tree_h = thi.z - tlo.z
    crown_w = max(thi.x - tlo.x, thi.y - tlo.y)

    trlo, trhi = group_bounds([ctx["trunk"]])
    trunk_aabb_w = max(trhi.x - trlo.x, trhi.y - trlo.y)

    for r in ctx["sq_roots"]:
        r.rotation_mode = "QUATERNION"
        r.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        r.location = (0, 0, 0)
    bpy.context.view_layer.update()
    qlo, qhi = group_bounds(ctx["sq_objs"])
    sq_w, sq_h, sq_l = qhi.x - qlo.x, qhi.z - qlo.z, qhi.y - qlo.y

    log("── 실측 (스케일 1.0, 모디파이어 적용 후) ─────────────────────────")
    log(f"나무 전체 AABB : 높이 {tree_h:.3f}m  수관 폭 {crown_w:.3f}m  "
        f"(x {thi.x - tlo.x:.3f} / y {thi.y - tlo.y:.3f})")
    log(f"기둥_main AABB : 폭 {trunk_aabb_w:.3f}m (뿌리 벌어짐 포함)  "
        f"높이 {trhi.z - trlo.z:.3f}m")
    log(f"하늘다람쥐 AABB: 폭 {sq_w:.3f}m  높이 {sq_h:.3f}m  꼬리포함 길이 {sq_l:.3f}m")

    log("기둥 반지름 — 해석값 vs 메시 실측:")
    for zw in (0.0, 0.30, 1.0, 1.806, 3.0, 5.5, 9.0, 14.0):
        _, ra = trunk_axis_and_radius(1.0, zw)
        got = measure_trunk_radius(ctx["trunk"], zw, 0.45)
        if got:
            mn, av, mx, _, cnt = got
            log(f"  z={zw:6.2f}m  해석 {ra:6.3f}m   메시 최소 {mn:6.3f} 평균 {av:6.3f} "
                f"최대 {mx:6.3f}  (정점 {cnt}개)")
        else:
            log(f"  z={zw:6.2f}m  해석 {ra:6.3f}m   메시 정점 없음")

    _, r0 = trunk_axis_and_radius(1.0, 0.0)
    trunk_dia_now = PT.TRUNK_R_BASE * 2.0
    log(f"기준 밑동 지름(뿌리 벌어짐 제외) = TRUNK_R_BASE*2 = {trunk_dia_now:.3f}m  "
        f"/ 벌어짐 포함 z=0 지름 {r0 * 2:.3f}m")
    log(f"현재 비 : 다람쥐 폭 {sq_w:.3f}m 이 밑동 지름 {trunk_dia_now:.3f}m 의 "
        f"{sq_w / trunk_dia_now:.3f}배 → N = {trunk_dia_now / sq_w:.3f}")

    rows = build_table(sq_w, trunk_dia_now, tree_h, crown_w)
    print_table(rows)
    log("숲 배치 참고: build_area_forest.py 는 9그루 / 이웃 간격 18~26m / 100m 사방")
    for r in rows:
        need = r["crown"]
        log(f"  {r['name']:>5}: 수관 폭 {need:7.1f}m → 수관이 안 겹치려면 간격 "
            f"{need:7.1f}m 이상 (현재 배치 18~26m: "
            f"{'가능' if need <= 18 else '불가'})")

    # ---- 매달린 자세가 정말 의도대로인지 확인 (추측 금지) ------------------
    set_scale(ctx["root"], 1.0)
    clo, chi = place_squirrel_on_trunk(ctx["sq_roots"], ctx["sq_objs"], 1.0, 1.806)
    _, rr = trunk_axis_and_radius(1.0, 1.806)
    log("── 매달린 자세 검증 (기둥 +X 면, z=1.806m) ─────────────────────────")
    log(f"  월드 X 폭 {chi.x - clo.x:.3f}m (몸 두께 {sq_h:.3f} 이어야 함)  "
        f"월드 Y 폭 {chi.y - clo.y:.3f}m (몸 폭 {sq_w:.3f} 이어야 함)  "
        f"월드 Z 폭 {chi.z - clo.z:.3f}m (코~꼬리 {sq_l:.3f} 이어야 함)")
    log(f"  배쪽 X 최소 {clo.x:.3f}m / 그 높이 기둥 반지름 {rr:.3f}m "
        f"→ 파묻힘 {(rr - clo.x) * 100:+.1f}cm")
    ok = (abs((chi.y - clo.y) - sq_w) < 0.02 and abs((chi.z - clo.z) - sq_l) < 0.02)
    log(f"  자세 검증: {'통과' if ok else '★실패★ — 회전이 먹지 않았다'}")

    if measure_only:
        log("측정만 하고 종료")
        return

    make_ground()
    PT.setup_render_world()
    a = sheet_full(ctx, rows, outdir)
    b = sheet_closeup(ctx, rows, outdir)
    sheet_n32(ctx, rows, outdir)
    sheet_lineup(ctx, rows, outdir)
    log(f"완료: {a} / {b}")


main()
