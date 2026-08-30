"""하늘다람쥐 모델 · 뼈대 · 애니메이션을 만들어 .glb 로 내보낸다.

기획서 명세:
  - 주인공, Playable
  - 하늘색 몸통
  - 귀여운 외모

몸통은 스킨 모디파이어로 만든다. 뼈대처럼 이어진 정점에 살을 붙이는
방식이라 프리미티브를 겹쳐 놓는 것보다 훨씬 유기적인 형태가 나온다.
활공막은 정점을 직접 찍어 만들고, 자동 웨이트로 앞뒤 다리에 물려서
다리를 벌리면 막이 함께 늘어난다.

실행:
  blender --background --python blender/build_flying_squirrel.py -- \
      --out models/flying_squirrel.glb --preview 미리보기.png
"""
import math
import os
import sys

import bpy
from mathutils import Vector

# --- 기획서에 명시된 색 ------------------------------------------------------
FUR = (0.45, 0.72, 0.92, 1.0)        # 하늘색 몸통
BELLY = (0.93, 0.97, 1.00, 1.0)
MEMBRANE = (0.40, 0.62, 0.85, 1.0)
EAR_INNER = (0.98, 0.78, 0.83, 1.0)
EYE = (0.05, 0.05, 0.07, 1.0)
GLINT = (1.0, 1.0, 1.0, 1.0)

# 블렌더는 Z 가 위, 캐릭터는 -Y 를 향한다.
# glTF 로 내보내면 -Y(앞) 가 Godot 의 +Z 가 되므로 player.gd 의 가정과 맞는다.

# --- 몸통 골격: (이름, 위치, 굵기) -------------------------------------------
SPINE = [
    ("neck",   Vector((0.00, -0.52, 0.52)), 0.21),
    ("chest",  Vector((0.00, -0.26, 0.46)), 0.27),
    ("mid",    Vector((0.00,  0.02, 0.45)), 0.28),
    ("hips",   Vector((0.00,  0.30, 0.42)), 0.26),
    ("tail1",  Vector((0.00,  0.58, 0.48)), 0.14),
    ("tail2",  Vector((0.00,  0.88, 0.62)), 0.20),
    ("tail3",  Vector((0.00,  1.14, 0.76)), 0.16),
]

LIMBS = [
    # (이름, 몸통의 어느 마디에서, 어깨/골반 위치, 손발 위치, 굵기)
    ("arm",  "chest", Vector((0.24, -0.24, 0.42)), Vector((0.60, -0.38, 0.26)), 0.130, 0.075),
    ("leg",  "hips",  Vector((0.24,  0.28, 0.40)), Vector((0.58,  0.44, 0.22)), 0.140, 0.080),
]

## 머리는 스킨 모디파이어에 맡기지 않고 명시적인 구로 만든다.
## 스킨+섭디비전이 만드는 표면 크기는 예측이 어려워, 눈·귀를 얹을 기준면이
## 흔들린다. 구로 분리하면 반지름이 확정값이라 얼굴이 정확히 붙는다.
HEAD_POS = Vector((0.00, -0.74, 0.60))
HEAD_R = 0.31


def log(msg):
    print(f"[블렌더] {msg}")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = "models/flying_squirrel.glb"
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


# =============================================================================
# 몸통 — 스킨 모디파이어
# =============================================================================
def build_body():
    verts = []
    edges = []
    radii = []
    index = {}

    for name, pos, r in SPINE:
        index[name] = len(verts)
        verts.append(pos)
        radii.append(r)

    # 척추를 순서대로 잇는다
    for i in range(len(SPINE) - 1):
        edges.append((i, i + 1))

    # 좌우 팔다리
    for limb, attach, upper, lower, r_up, r_low in LIMBS:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            a = index[attach]
            u = len(verts)
            verts.append(Vector((upper.x * sx, upper.y, upper.z)))
            radii.append(r_up)
            d = len(verts)
            verts.append(Vector((lower.x * sx, lower.y, lower.z)))
            radii.append(r_low)
            edges.append((a, u))
            edges.append((u, d))
            index[f"{limb}_{side}_upper"] = u
            index[f"{limb}_{side}_lower"] = d

    mesh = bpy.data.meshes.new("BodyMesh")
    mesh.from_pydata([tuple(v) for v in verts], edges, [])
    mesh.update()

    obj = bpy.data.objects.new("Body", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    skin = obj.modifiers.new("Skin", "SKIN")
    skin.use_smooth_shade = True
    skin.branch_smoothing = 0.35

    layer = mesh.skin_vertices[0].data
    for i, r in enumerate(radii):
        layer[i].radius = (r, r)
    layer[index["mid"]].use_root = True

    # 꼬리는 납작하고 넓게 (하늘다람쥐 꼬리는 막대가 아니라 깃털에 가깝다)
    layer[index["tail2"]].radius = (0.22, 0.11)
    layer[index["tail3"]].radius = (0.17, 0.09)

    sub = obj.modifiers.new("Subdiv", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 2

    obj.data.materials.append(make_material("Fur", FUR))
    log(f"몸통 생성: 정점 {len(verts)}개")
    return obj, index, verts


# =============================================================================
# 활공막 — 앞다리와 뒷다리 사이의 곡면
# =============================================================================
def build_patagium(verts, index):
    objs = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        front = verts[index[f"arm_{side}_lower"]]
        back = verts[index[f"leg_{side}_lower"]]
        body_f = Vector((0.14 * sx, -0.30, 0.44))
        body_b = Vector((0.14 * sx, 0.36, 0.40))

        cols, rows = 9, 6
        grid = []
        for r in range(rows):
            tr = r / (rows - 1)
            inner = body_f.lerp(body_b, tr)
            outer = front.lerp(back, tr)
            row = []
            for c in range(cols):
                tc = c / (cols - 1)
                p = inner.lerp(outer, tc)
                # 공기를 받아 가운데가 처지고 끝이 살짝 들린다
                p.z -= math.sin(tc * math.pi) * math.sin(tr * math.pi) * 0.10
                p.z += (tc ** 3) * 0.06
                row.append(p)
            grid.append(row)

        vlist = []
        for row in grid:
            for p in row:
                vlist.append(tuple(p))

        faces = []
        for r in range(rows - 1):
            for c in range(cols - 1):
                a = r * cols + c
                b = r * cols + c + 1
                d = (r + 1) * cols + c
                e = (r + 1) * cols + c + 1
                faces.append((a, b, e, d) if sx > 0 else (a, d, e, b))

        mesh = bpy.data.meshes.new(f"PatagiumMesh{side}")
        mesh.from_pydata(vlist, [], faces)
        mesh.update()

        obj = bpy.data.objects.new(f"Patagium{side}", mesh)
        bpy.context.collection.objects.link(obj)

        solid = obj.modifiers.new("Solidify", "SOLIDIFY")
        solid.thickness = 0.022
        solid.offset = 0.0
        sub = obj.modifiers.new("Subdiv", "SUBSURF")
        sub.levels = 1

        obj.data.materials.append(make_material("Membrane", MEMBRANE, 0.65))
        objs.append(obj)

    log("활공막 생성: 좌우 2장")
    return objs


# =============================================================================
# 얼굴 — 큰 눈, 귀, 코 (귀여운 외모)
# =============================================================================
def add_sphere(name, loc, scale, mat, segments=24, rings=14):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, segments=segments,
                                         ring_count=rings, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.shade_smooth()
    obj.data.materials.append(mat)
    return obj


def build_face():
    parts = []
    m_eye = make_material("Eye", EYE, 0.25)
    m_glint = make_material("Glint", GLINT, 0.1)
    m_ear = make_material("EarInner", EAR_INNER, 0.8)
    m_belly = make_material("Belly", BELLY)
    m_fur = make_material("FurHead", FUR)

    head = HEAD_POS
    R = HEAD_R   # 확정된 머리 반지름. 모든 얼굴 부위를 여기에 비례시킨다.

    # 머리통 — 목(스킨 메시)과 충분히 겹치도록 배치되어 있다
    parts.append(add_sphere("Skull", head, (R, R * 0.96, R * 0.94), m_fur, 32, 18))

    # 주둥이
    parts.append(add_sphere("Snout", head + Vector((0, -0.78 * R, -0.30 * R)),
                            (0.50 * R, 0.55 * R, 0.42 * R), m_belly))
    parts.append(add_sphere("Nose", head + Vector((0, -1.22 * R, -0.24 * R)),
                            (0.15 * R, 0.13 * R, 0.12 * R), m_eye))

    for side, sx in (("L", 1.0), ("R", -1.0)):
        # 큰 눈 = 귀여움. 중심은 머리 안쪽에 두고 반지름으로 표면을 뚫고 나오게 한다.
        parts.append(add_sphere(f"Eye{side}", head + Vector((0.52 * R * sx, -0.66 * R, 0.20 * R)),
                                (0.32 * R, 0.30 * R, 0.35 * R), m_eye))
        parts.append(add_sphere(f"Glint{side}",
                                head + Vector((0.62 * R * sx, -0.90 * R, 0.36 * R)),
                                (0.12 * R, 0.11 * R, 0.12 * R), m_glint, 16, 10))
        parts.append(add_sphere(f"Glint2{side}",
                                head + Vector((0.40 * R * sx, -0.94 * R, -0.02 * R)),
                                (0.065 * R, 0.06 * R, 0.065 * R), m_glint, 12, 8))
        # 귀 — 머리 표면 위에 얹힌다
        parts.append(add_sphere(f"Ear{side}", head + Vector((0.58 * R * sx, 0.10 * R, 0.84 * R)),
                                (0.20 * R, 0.38 * R, 0.46 * R), m_fur))
        parts.append(add_sphere(f"EarInner{side}",
                                head + Vector((0.62 * R * sx, -0.06 * R, 0.84 * R)),
                                (0.13 * R, 0.27 * R, 0.33 * R), m_ear))

    log(f"얼굴 부위 {len(parts)}개")
    return parts


# =============================================================================
# 뼈대
# =============================================================================
def build_armature(verts, index):
    arm_data = bpy.data.armatures.new("SquirrelRig")
    rig = bpy.data.objects.new("Rig", arm_data)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")

    eb = arm_data.edit_bones

    def bone(name, head, tail, parent=None, connect=False):
        b = eb.new(name)
        b.head = head
        b.tail = tail
        if parent:
            b.parent = eb[parent]
            b.use_connect = connect
        return b

    v = lambda k: Vector(verts[index[k]])

    bone("root", Vector((0, 0.02, 0.0)), Vector((0, 0.02, 0.30)))
    bone("hips", v("hips"), v("mid"), "root")
    bone("spine", v("mid"), v("chest"), "hips", True)
    bone("neck", v("chest"), v("neck"), "spine", True)
    bone("head", v("neck"), HEAD_POS + Vector((0, -0.20, 0.12)), "neck", True)

    bone("tail1", v("hips"), v("tail1"), "hips")
    bone("tail2", v("tail1"), v("tail2"), "tail1", True)
    bone("tail3", v("tail2"), v("tail3"), "tail2", True)

    for side in ("L", "R"):
        bone(f"arm.{side}", v(f"arm_{side}_upper"), v(f"arm_{side}_lower"), "spine")
        bone(f"leg.{side}", v(f"leg_{side}_upper"), v(f"leg_{side}_lower"), "hips")

    bpy.ops.object.mode_set(mode="OBJECT")
    log(f"뼈대 생성: {len(arm_data.bones)}개")
    return rig


def skin_to_rig(rig, meshes):
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    log(f"자동 웨이트 스키닝: 메시 {len(meshes)}개")


# =============================================================================
# 애니메이션 — 클립 이름은 player.gd 의 CLIP 상수와 맞춰야 한다
# =============================================================================
def rad(d):
    return math.radians(d)


def make_animations(rig):
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")

    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"

    if rig.animation_data is None:
        rig.animation_data_create()

    def reset_pose():
        """이전 클립의 포즈가 다음 클립으로 새지 않게 한다."""
        for pb in rig.pose.bones:
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.location = (0.0, 0.0, 0.0)

    def clip(name, length, poses):
        """poses: {프레임: {뼈이름: (rx, ry, rz [, (dx,dy,dz)])}}"""
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

        # 액션을 NLA 트랙으로 밀어넣는다.
        # 액션을 그냥 만들어두기만 하면 glTF 내보내기가 찾지 못해 클립이 0개가 된다.
        # 트랙 하나 = 내보내진 클립 하나.
        rig.animation_data.action = None
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, 1, action)
        return action

    actions = []

    # --- idle: 숨쉬기, 꼬리 살랑 ---
    actions.append(clip("idle", 60, {
        1:  {"spine": (0, 0, 0), "tail1": (-6, 0, 0), "tail2": (-8, 0, 0),
             "head": (0, 0, 0)},
        30: {"spine": (2.5, 0, 0), "tail1": (-2, 0, 8), "tail2": (-3, 0, 10),
             "head": (-3, 0, 0)},
        60: {"spine": (0, 0, 0), "tail1": (-6, 0, 0), "tail2": (-8, 0, 0),
             "head": (0, 0, 0)},
    }))

    # --- walk: 대각선 다리쌍이 교대 ---
    actions.append(clip("walk", 32, {
        1:  {"arm.L": (25, 0, 0), "leg.R": (22, 0, 0),
             "arm.R": (-25, 0, 0), "leg.L": (-22, 0, 0),
             "spine": (0, 0, 3), "tail1": (-8, 0, 6)},
        16: {"arm.L": (-25, 0, 0), "leg.R": (-22, 0, 0),
             "arm.R": (25, 0, 0), "leg.L": (22, 0, 0),
             "spine": (0, 0, -3), "tail1": (-8, 0, -6)},
        32: {"arm.L": (25, 0, 0), "leg.R": (22, 0, 0),
             "arm.R": (-25, 0, 0), "leg.L": (-22, 0, 0),
             "spine": (0, 0, 3), "tail1": (-8, 0, 6)},
    }))

    # --- run: 보폭을 키우고 몸을 낮춘다 ---
    actions.append(clip("run", 20, {
        1:  {"arm.L": (42, 0, 0), "leg.R": (38, 0, 0),
             "arm.R": (-42, 0, 0), "leg.L": (-38, 0, 0),
             "spine": (6, 0, 0), "hips": (-4, 0, 0), "tail1": (-18, 0, 0),
             "tail2": (-14, 0, 0)},
        10: {"arm.L": (-42, 0, 0), "leg.R": (-38, 0, 0),
             "arm.R": (42, 0, 0), "leg.L": (38, 0, 0),
             "spine": (10, 0, 0), "hips": (-8, 0, 0), "tail1": (-24, 0, 0),
             "tail2": (-18, 0, 0)},
        20: {"arm.L": (42, 0, 0), "leg.R": (38, 0, 0),
             "arm.R": (-42, 0, 0), "leg.L": (-38, 0, 0),
             "spine": (6, 0, 0), "hips": (-4, 0, 0), "tail1": (-18, 0, 0),
             "tail2": (-14, 0, 0)},
    }))

    # --- jump: 웅크렸다 펴기 ---
    actions.append(clip("jump", 24, {
        1:  {"arm.L": (-40, 0, 0), "arm.R": (-40, 0, 0),
             "leg.L": (40, 0, 0), "leg.R": (40, 0, 0),
             "spine": (12, 0, 0), "tail1": (-30, 0, 0)},
        12: {"arm.L": (-15, 0, -25), "arm.R": (-15, 0, 25),
             "leg.L": (20, 0, -18), "leg.R": (20, 0, 18),
             "spine": (-6, 0, 0), "tail1": (-14, 0, 0)},
        24: {"arm.L": (-40, 0, 0), "arm.R": (-40, 0, 0),
             "leg.L": (40, 0, 0), "leg.R": (40, 0, 0),
             "spine": (12, 0, 0), "tail1": (-30, 0, 0)},
    }))

    # --- glide: 네 다리를 활짝 펴 막을 팽팽하게 ---
    actions.append(clip("glide", 48, {
        1:  {"arm.L": (0, 0, -52), "arm.R": (0, 0, 52),
             "leg.L": (0, 0, -40), "leg.R": (0, 0, 40),
             "spine": (-8, 0, 0), "head": (-12, 0, 0),
             "tail1": (8, 0, -6), "tail2": (6, 0, -8)},
        24: {"arm.L": (0, 0, -60), "arm.R": (0, 0, 60),
             "leg.L": (0, 0, -46), "leg.R": (0, 0, 46),
             "spine": (-4, 0, 0), "head": (-6, 0, 0),
             "tail1": (10, 0, 6), "tail2": (8, 0, 8)},
        48: {"arm.L": (0, 0, -52), "arm.R": (0, 0, 52),
             "leg.L": (0, 0, -40), "leg.R": (0, 0, 40),
             "spine": (-8, 0, 0), "head": (-12, 0, 0),
             "tail1": (8, 0, -6), "tail2": (6, 0, -8)},
    }))

    bpy.ops.object.mode_set(mode="OBJECT")
    log("애니메이션 클립: " + ", ".join(a.name for a in actions))
    return actions


# =============================================================================
# 내보내기 / 미리보기
# =============================================================================
def export_glb(path):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_apply=True,          # 모디파이어(스킨/섭디비전)를 구워서 내보낸다
        export_animations=True,
        export_animation_mode="NLA_TRACKS",   # 트랙 하나가 클립 하나로 나간다
        export_yup=True,
    )
    log(f"내보내기: {path} ({os.path.getsize(path):,} bytes)")


def scene_bounds():
    """모디파이어까지 적용된 실제 형상의 경계 상자를 구한다."""
    deps = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    found = False

    for obj in bpy.context.scene.objects:
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
            found = True
        ev.to_mesh_clear()

    if not found:
        return Vector((0, 0, 0)), 1.0
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

    key = bpy.data.lights.new("Key", "SUN")
    key.energy = 4.0
    key_obj = bpy.data.objects.new("Key", key)
    key_obj.rotation_euler = (rad(52), rad(12), rad(35))
    bpy.context.collection.objects.link(key_obj)

    fill = bpy.data.lights.new("Fill", "SUN")
    fill.energy = 1.5
    fill_obj = bpy.data.objects.new("Fill", fill)
    fill_obj.rotation_euler = (rad(64), 0, rad(-125))
    bpy.context.collection.objects.link(fill_obj)

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.58, 0.66, 0.72, 1.0)
    bg.inputs[1].default_value = 0.8
    scene.world = world
    return scene


## 보는 방향 (구면 좌표: 방위각, 고도) — 모델을 여러 각도에서 확인하기 위한 것
VIEWS = [
    ("정면",   -90.0, 6.0),
    ("측면",     0.0, 6.0),
    ("3/4앞",  -50.0, 22.0),
    ("위",     -70.0, 68.0),
]


def render_preview(path, size=520):
    import numpy as np

    scene = setup_render_world()
    center, radius = scene_bounds()
    log(f"경계: 중심 {tuple(round(c, 2) for c in center)} 반지름 {radius:.2f}")

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 55
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam

    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    dist = radius * 3.1
    tiles = []
    tmp_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(tmp_dir, exist_ok=True)

    for name, azim, elev in VIEWS:
        a, e = rad(azim), rad(elev)
        offset = Vector((math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e))) * dist
        cam.location = center + offset
        direction = center - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

        tmp = os.path.join(tmp_dir, f"_view_{name}.png")
        scene.render.filepath = tmp
        bpy.ops.render.render(write_still=True)

        img = bpy.data.images.load(tmp)
        w, h = img.size
        arr = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        tiles.append(arr)
        bpy.data.images.remove(img)
        os.remove(tmp)

    # 블렌더 픽셀은 아래에서 위로 쌓이므로, 위쪽 줄이 뒤에 와야 한다
    top = np.concatenate(tiles[0:2], axis=1)
    bottom = np.concatenate(tiles[2:4], axis=1)
    sheet = np.concatenate([bottom, top], axis=0)

    H, W = sheet.shape[0], sheet.shape[1]
    out = bpy.data.images.new("sheet", W, H, alpha=True)
    out.pixels = sheet.reshape(-1).tolist()
    out.filepath_raw = os.path.abspath(path)
    out.file_format = "PNG"
    out.save()
    log(f"미리보기: {out.filepath_raw} ({W}x{H}, {'/'.join(v[0] for v in VIEWS)})")


def main():
    out, preview = parse_args()
    clear_scene()

    body, index, verts = build_body()
    membranes = build_patagium(verts, index)
    face = build_face()

    rig = build_armature(verts, index)
    skin_to_rig(rig, [body] + membranes + face)

    # 미리보기는 애니메이션을 얹기 전에 찍는다.
    # NLA 트랙을 깔고 나면 리그가 특정 포즈로 눌려서 기본 형태를 볼 수 없다.
    if preview:
        render_preview(preview)

    make_animations(rig)
    export_glb(out)
    log("완료")


main()
