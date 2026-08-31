extends CharacterBody3D
## 플레이어블 하늘다람쥐.
##
## 모델과 애니메이션은 블렌더에서 만든 것을 쓴다.
## (blender/ 폴더의 파이썬 스크립트가 원본, models/*.glb 가 산출물)
##
## 조작(기획서에 조작 항목이 없어 정한 값 — claudedocs/요구사항.md F1~F4):
##   WASD    이동
##   Shift   달리기
##   Space   지상 점프 / 나무에 붙었을 때 뛰어내리기 / 공중에서 눌러 활공 켜기·끄기
##   마우스  카메라 회전
##   R       게임오버 후 다시 시작
##   F1      조작 안내 표시 켜기·끄기
##
## 모델의 앞쪽은 +Z 다. 자세는 yaw 하나가 아니라 basis 로 들고 있는다
## (수직 기둥에 배를 붙인 자세처럼 yaw 외의 축이 필요한 자세를 담기 위해).

const Layers = preload("res://scripts/physics_layers.gd")
const WorldScale = preload("res://scripts/world_scale.gd")

const MODEL_PATH := "res://models/flying_squirrel.glb"

## 발밑 지면을 찾는 레이의 길이(m). **월드를 훑는 거리라 축척을 곱한다.**
##
## 18 m 나무 시절의 50 m 를 그대로 옮긴 값 = 967.4 m. 나무 높이 348 m + 지면
## 기복(±29 m) + 밑동이 지면에 묻힌 깊이를 다 덮고도 남는다. 짧게 두면 높은
## 곳에서 레이가 허공만 찌르고 "지면 없음" 으로 돌아와 실제 높이를 알 수 없다.
## (N=16 재축척 때 50 m 가 그대로 남아 기능 테스트 5건이 깨졌다.)
const GROUND_PROBE_RANGE := 50.0 * WorldScale.FACTOR

## 레이 사거리 안에 지면이 없을 때의 반환값. "무한히 높다" 로 취급해 활공을 막지 않는다.
## 사거리보다 큰 상수를 박아 두면 축척이 바뀔 때 둘의 대소가 뒤집히므로 INF 를 쓴다.
const NO_GROUND := INF

## GROUND 지상 · AIR 공중 · GLIDE 활공 · CLING 기둥에 붙어 있음 · BURIED 눈에 파묻히는 중
enum State { GROUND, AIR, GLIDE, CLING, BURIED }

## 블렌더 쪽과 맞춘 애니메이션 클립 이름. 양쪽 다 이 이름을 지켜야 한다.
##
## CLING / BURIED 전용 클립은 아직 없다(모델러 영역, 요구사항 H10). 기존 5종
## (idle/walk/run/jump/glide) 중 가장 덜 어색한 "idle" 을 임시로 돌려 쓴다.
const CLIP := {
	State.GROUND: "idle",
	State.AIR: "jump",
	State.GLIDE: "glide",
	State.CLING: "idle",
	State.BURIED: "idle",
}
const CLIP_WALK := "walk"
const CLIP_RUN := "run"

## 눈에 파묻혀 게임오버로 갈 때 (world.gd 가 받아서 연출과 UI 를 띄운다)
signal bury_started
signal bury_finished

@export_group("지상 이동")
@export var walk_speed := 4.5
@export var run_speed := 8.0
@export var ground_accel := 12.0
@export var turn_speed := 12.0

@export_group("점프와 중력")
@export var jump_velocity := 6.2
@export var gravity := 20.0
@export var air_accel := 5.0

@export_group("활공")
@export var glide_gravity := 2.6          ## 활공 중 훨씬 약해지는 중력
@export var glide_max_fall := 2.4         ## 활공 중 최대 하강 속도
@export var glide_speed := 10.5           ## 활공 중 전진 속도
@export var glide_turn_speed := 2.2       ## 활공 중 선회 (지상보다 둔하게)
@export var glide_min_height := 0.8       ## 이 높이 아래에서는 활공 시작 불가

@export_group("나무 부착")
## 기획서 I4 의 시작 포즈(소나무에 매달려 있음)를 위한 **최소한의 정지 부착**이다.
## 기둥 오르내리기·가지 이동·상호 전환(요구사항 H3~H7)은 미정 6-A/7/8 이 정해진 뒤의 일이다.
## 한 번 떨어지면 다시 붙지 않는다 — 재부착도 그때 함께 만든다.
@export var cling_release_push := 2.6     ## 부착을 풀 때 기둥 바깥으로 밀어내는 속도(m/s)
@export var cling_release_lift := 1.4     ## 부착을 풀 때 위로 살짝 띄우는 속도(m/s)

@export_group("눈에 파묻힘")
## 지면(레이어 2)에 닿으면 눈에 파묻히고 게임오버가 된다. 나무(레이어 3)는 해당 없음.
@export var bury_time := 0.75             ## 완전히 잠기기까지 걸리는 시간(초)
## 몸 반지름의 몇 배까지 가라앉는가. 절대 깊이가 아니라 몸 크기에 비례한다.
## (지금은 캡슐 반지름 0.38 보다 모델이 크므로 넉넉히 잡았다. 모델 크기가 정리되면
##  캡슐과 함께 다시 볼 값이다 — 머리까지 눈 아래로 들어가야 「파묻혔다」로 읽힌다.)
@export var bury_depth_ratio := 3.6

var state: State = State.GROUND

## 지면에 닿았을 때 파묻힘 판정을 할지. 오프닝 인트로가 도는 동안에는 world.gd 가 꺼 둔다.
var death_enabled := false

var _model: Node3D
var _anim: AnimationPlayer
var _current_clip := ""
var _body_radius := 0.38

## 몸의 자세. yaw 하나(rotation.y)로는 "수직 기둥에 배를 붙인 자세" 같은 것을
## 표현할 수 없어 임의 회전을 담을 수 있는 basis 로 다룬다.
## 규약: 이 basis 의 +Z 가 모델이 바라보는 앞, +Y 가 등(back) 쪽이다.
var _orientation := Basis.IDENTITY

## 붙어 있는 면의 바깥쪽 법선 (부착 중에만 의미가 있다)
var _cling_normal := Vector3.ZERO

## 활공 스위치. Space 를 눌러 켜고 다시 눌러 끈다(토글).
## 켜져 있어도 상승 중이거나 지면이 가까우면 실제 활공에 들어가지 않고 대기한다.
var _glide_armed := false
## 입력 에지 검출용. is_action_just_pressed 의 보조 (아래 _jump_edge 주석 참조)
var _jump_held_prev := false

var _bury_t := 0.0
var _bury_from := Vector3.ZERO
var _bury_done := false


func _ready() -> void:
	# 충돌 레이어 규약: scripts/physics_layers.gd
	# 플레이어는 레이어 1, 지형(2)/나무(3) 와만 부딪힌다.
	collision_layer = Layers.PLAYER
	collision_mask = Layers.SOLID

	_build_body()
	_orientation = basis.orthonormalized()


# --- 몸체 구성 ---------------------------------------------------------------
func _build_body() -> void:
	if ResourceLoader.exists(MODEL_PATH):
		var packed: PackedScene = load(MODEL_PATH)
		_model = packed.instantiate()
		_model.name = "Model"
		add_child(_model)
		_anim = _find_anim_player(_model)
		if _anim == null:
			push_warning("[플레이어] %s 에 AnimationPlayer 가 없습니다. 애니메이션 없이 진행합니다." % MODEL_PATH)
	else:
		# 블렌더 산출물이 아직 없어도 이동/충돌은 검증할 수 있어야 한다
		push_warning("[플레이어] 모델을 찾지 못했습니다: %s (블렌더 내보내기 필요)" % MODEL_PATH)

	var shape := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.38
	cap.height = 1.10
	shape.shape = cap
	shape.position = Vector3(0, 0.05, 0)
	shape.rotation.x = deg_to_rad(90.0)   # 네 발로 엎드린 자세라 캡슐을 눕힌다
	add_child(shape)
	_body_radius = cap.radius


func _find_anim_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node
	for child in node.get_children():
		var found := _find_anim_player(child)
		if found:
			return found
	return null


## 몸통의 반지름(눕힌 캡슐의 굵기). 기둥 표면에서 얼마나 띄울지, 눈에 얼마나
## 가라앉힐지를 이 값에서 계산한다. 나중에 모델 크기가 바뀌면 캡슐만 고치면 된다.
func body_radius() -> float:
	return _body_radius


# --- 입력 --------------------------------------------------------------------
## 카메라가 보는 방향을 기준으로 한 이동 입력 (월드 XZ 평면)
func _movement_dir() -> Vector3:
	var input := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	if input.length_squared() < 0.01:
		return Vector3.ZERO

	var cam := get_viewport().get_camera_3d()
	if cam == null:
		return Vector3(input.x, 0, input.y).normalized()

	var b := cam.global_transform.basis
	var fwd := -b.z
	var right := b.x
	fwd.y = 0.0
	right.y = 0.0
	var dir := right * input.x + fwd * input.y
	dir.y = 0.0
	return dir.normalized() if dir.length_squared() > 0.0001 else Vector3.ZERO


## 이번 물리 프레임에 점프 키가 '새로 눌렸는가'.
##
## is_action_just_pressed() 만 쓰지 않는 이유: 이 값은 눌린 프레임 번호를 비교하는데,
## 헤드리스 테스트가 _process 안에서 Input.action_press() 로 입력을 주입하면
## 프레임 경계에 따라 물리 프레임에서 놓칠 수 있다. 그래서 눌림 상태의 에지도 함께 본다.
## 둘 중 하나만 참이어도 한 번만 발동하므로 중복 토글은 생기지 않는다.
func _jump_edge() -> bool:
	var held := Input.is_action_pressed("jump")
	var edge := held and not _jump_held_prev
	_jump_held_prev = held
	return Input.is_action_just_pressed("jump") or edge


## 발밑 '지면' 까지의 거리. 활공 진입 판정(glide_min_height)에만 쓴다.
##
## 레이 대상을 지형 레이어로 한정하는 것이 핵심이다. 소나무 숲에서는 플레이어
## 바로 아래를 나뭇가지가 지나가는데, 그 가지가 레이에 걸리면 "지면이 코앞"으로
## 잘못 읽혀 활공이 시작되지 않는다. 나무는 레이어 3(TREE)이라 여기 걸리지 않는다.
func _height_above_ground() -> float:
	var space := get_world_3d().direct_space_state
	var from := global_position
	var q := PhysicsRayQueryParameters3D.create(from, from + Vector3.DOWN * GROUND_PROBE_RANGE)
	q.collision_mask = Layers.TERRAIN
	q.exclude = [get_rid()]
	var hit := space.intersect_ray(q)
	if hit.is_empty():
		return NO_GROUND
	return from.distance_to(hit.position)


# --- 물리 -------------------------------------------------------------------
func _physics_process(delta: float) -> void:
	if state == State.BURIED:
		_process_bury(delta)
		_update_animation()
		return

	var jumped := _jump_edge()

	if state == State.CLING:
		velocity = Vector3.ZERO
		if jumped:
			release_cling()
		_update_animation()
		return

	var dir := _movement_dir()

	if is_on_floor():
		state = State.GROUND
		_glide_armed = false          # 착지하면 활공 스위치는 초기화된다
	else:
		# 공중에서 Space 는 활공 토글이다. 상승 중에 눌러도 스위치는 켜지고,
		# 하강으로 바뀌는 순간 아래 조건이 통과하며 실제 활공에 들어간다(입력이 씹히지 않는다).
		if jumped:
			_glide_armed = not _glide_armed
		var can_glide := _glide_armed and velocity.y < 0.5 and _height_above_ground() > glide_min_height
		state = State.GLIDE if can_glide else State.AIR

	match state:
		State.GROUND:
			_process_ground(dir, delta, jumped)
		State.AIR:
			_process_air(dir, delta)
		State.GLIDE:
			_process_glide(dir, delta)

	move_and_slide()

	if death_enabled and _touched_terrain():
		_begin_bury()

	_update_animation()


func _process_ground(dir: Vector3, delta: float, jumped: bool) -> void:
	var speed := run_speed if Input.is_action_pressed("sprint") else walk_speed
	var target := dir * speed
	velocity.x = move_toward(velocity.x, target.x, ground_accel * delta * speed)
	velocity.z = move_toward(velocity.z, target.z, ground_accel * delta * speed)
	velocity.y = -0.5   # 경사면에 붙어 있도록 살짝 눌러준다

	if jumped:
		velocity.y = jump_velocity

	if dir != Vector3.ZERO:
		_face_toward(dir, turn_speed * delta)


func _process_air(dir: Vector3, delta: float) -> void:
	velocity.y -= gravity * delta
	var target := dir * run_speed
	velocity.x = move_toward(velocity.x, target.x, air_accel * delta * run_speed)
	velocity.z = move_toward(velocity.z, target.z, air_accel * delta * run_speed)
	if dir != Vector3.ZERO:
		_face_toward(dir, turn_speed * 0.5 * delta)


func _process_glide(dir: Vector3, delta: float) -> void:
	velocity.y -= glide_gravity * delta
	velocity.y = maxf(velocity.y, -glide_max_fall)

	# 활공 중에는 바라보는 방향으로 꾸준히 나아가고, 입력은 선회에만 쓴다
	if dir != Vector3.ZERO:
		_face_toward(dir, glide_turn_speed * delta)

	var fwd := _orientation.z   # basis 의 +Z 가 모델의 앞
	velocity.x = move_toward(velocity.x, fwd.x * glide_speed, 8.0 * delta)
	velocity.z = move_toward(velocity.z, fwd.z * glide_speed, 8.0 * delta)


# --- 나무 부착 (시작 포즈용 최소 구현) --------------------------------------
## 기둥 표면 point 에 배를 붙이고 머리를 위로 둔 자세로 고정한다.
## normal 은 기둥 표면의 바깥쪽 법선 — 등(basis 의 +Y)이 이 방향을 본다.
func cling_to(point: Vector3, normal: Vector3) -> void:
	var n := normal
	n.y = 0.0                       # 기둥은 수직이므로 부착 법선도 수평으로 본다
	n = n.normalized()
	if n.length_squared() < 0.5:
		n = Vector3.BACK
	_cling_normal = n

	global_position = point
	velocity = Vector3.ZERO
	state = State.CLING
	_glide_armed = false
	_jump_held_prev = Input.is_action_pressed("jump")
	_bury_t = 0.0
	_bury_done = false

	# 앞(+Z) = 월드 위쪽(머리가 위), 등(+Y) = 기둥 바깥쪽 법선 → 배가 기둥을 향한다
	_orientation = basis_facing(Vector3.UP, n)
	basis = _orientation


## 부착을 푼다. 기둥 바깥으로 살짝 밀어내며 공중 상태로 넘어간다.
## 한 번 풀리면 스스로 다시 붙지 않는다 (재부착은 요구사항 H2/H9, 미정 8).
func release_cling() -> void:
	if state != State.CLING:
		return
	var n := _cling_normal
	state = State.AIR
	_glide_armed = false
	velocity = n * cling_release_push + Vector3.UP * cling_release_lift

	# 기둥에서 떨어지면 다시 '등이 하늘을 보는' 평상 자세로 돌아온다
	var fwd := Vector3(n.x, 0.0, n.z)
	if fwd.length_squared() < 0.000001:
		fwd = Vector3.BACK
	_orientation = basis_facing(fwd.normalized(), Vector3.UP)
	basis = _orientation
	_cling_normal = Vector3.ZERO


## 부착 지점을 못 찾아 지면에서 다시 시작할 때 쓰는 초기화 (예비 경로).
func reset_for_respawn() -> void:
	velocity = Vector3.ZERO
	state = State.AIR
	_glide_armed = false
	_jump_held_prev = Input.is_action_pressed("jump")
	_cling_normal = Vector3.ZERO
	_bury_t = 0.0
	_bury_done = false


func is_clinging() -> bool:
	return state == State.CLING


## 붙어 있는 면의 바깥쪽 법선 (검증용)
func cling_normal() -> Vector3:
	return _cling_normal


# --- 눈에 파묻힘 ------------------------------------------------------------
## 이번 프레임에 '지면'(레이어 2)에 닿았는가.
## 나무(레이어 3)는 밟고 서 있어도 게임오버가 아니므로 여기서 걸러진다.
func _touched_terrain() -> bool:
	for i in get_slide_collision_count():
		var col := get_slide_collision(i)
		var obj: Object = col.get_collider()
		if obj is CollisionObject3D:
			if ((obj as CollisionObject3D).collision_layer & Layers.TERRAIN) != 0:
				return true
	return false


func _begin_bury() -> void:
	if state == State.BURIED:
		return
	state = State.BURIED
	velocity = Vector3.ZERO
	_bury_t = 0.0
	_bury_from = global_position
	_bury_done = false
	_spawn_snow_burst()
	bury_started.emit()


## 눈 표면 아래로 서서히 가라앉는다. 이 동안 조작은 받지 않는다.
func _process_bury(delta: float) -> void:
	_bury_t += delta
	var p := clampf(_bury_t / maxf(bury_time, 0.001), 0.0, 1.0)
	var depth := _body_radius * bury_depth_ratio
	global_position = _bury_from - Vector3.UP * (depth * smoothstep(0.0, 1.0, p))
	if p >= 1.0 and not _bury_done:
		_bury_done = true
		bury_finished.emit()


func is_buried() -> bool:
	return state == State.BURIED


## 눈이 튀는 파티클. 흰 점을 잠깐 뿌리고 스스로 사라진다.
## 렌더링이 없는 헤드리스에서도 노드 생성만 하고 조용히 지나간다.
func _spawn_snow_burst() -> void:
	var host := get_parent()
	if host == null:
		return

	var mat := ParticleProcessMaterial.new()
	mat.direction = Vector3(0, 1, 0)
	mat.spread = 60.0
	mat.initial_velocity_min = 1.2
	mat.initial_velocity_max = 4.0
	mat.gravity = Vector3(0, -7.0, 0)
	mat.scale_min = 0.5
	mat.scale_max = 1.4
	mat.color = Color(1, 1, 1)
	# 눈 위에서 흰 사각형이 그대로 남으면 블록처럼 보인다. 수명 끝에서 사라지게 한다.
	var grad := Gradient.new()
	grad.set_color(0, Color(1, 1, 1, 1))
	grad.set_color(1, Color(1, 1, 1, 0))
	var ramp := GradientTexture1D.new()
	ramp.gradient = grad
	mat.color_ramp = ramp
	var shrink := Curve.new()
	shrink.add_point(Vector2(0.0, 1.0))
	shrink.add_point(Vector2(1.0, 0.15))
	var shrink_tex := CurveTexture.new()
	shrink_tex.curve = shrink
	mat.scale_curve = shrink_tex

	var quad := QuadMesh.new()
	quad.size = Vector2(0.08, 0.08)
	var sm := StandardMaterial3D.new()
	sm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	sm.albedo_color = Color(1, 1, 1)
	sm.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
	sm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	quad.material = sm

	var fx := GPUParticles3D.new()
	fx.name = "SnowBurst"
	fx.process_material = mat
	fx.draw_pass_1 = quad
	fx.amount = 56
	fx.lifetime = 0.9
	fx.one_shot = true
	fx.explosiveness = 0.9
	host.add_child(fx)
	fx.global_position = global_position
	fx.emitting = true

	# one_shot 파티클은 스스로 지워지지 않는다. 수명이 지나면 정리한다.
	var timer := get_tree().create_timer(fx.lifetime + 1.0)
	timer.timeout.connect(fx.queue_free)


# --- 자세 -------------------------------------------------------------------
## 모델의 앞(+Z)이 dir 을 향하도록 부드럽게 돌린다 (등은 하늘 쪽으로 유지).
func _face_toward(dir: Vector3, weight: float) -> void:
	var flat := Vector3(dir.x, 0.0, dir.z)
	if flat.length_squared() < 0.000001:
		return
	_turn_to(basis_facing(flat.normalized(), Vector3.UP), weight)


## 자세를 목표 basis 로 최단 경로 보간한다.
## yaw 만 다른 두 자세 사이에서는 lerp_angle 과 같은 결과가 나온다.
func _turn_to(target: Basis, weight: float) -> void:
	var w := clampf(weight, 0.0, 1.0)
	var q := _orientation.get_rotation_quaternion().slerp(target.get_rotation_quaternion(), w)
	_orientation = Basis(q.normalized())
	basis = _orientation


## 앞(+Z)이 fwd, 등(+Y)이 up_hint 쪽인 정규직교 basis.
## up_hint 를 바꾸면 벽/기둥에 붙은 자세도 같은 함수로 만들 수 있다.
static func basis_facing(fwd: Vector3, up_hint: Vector3) -> Basis:
	var z := fwd.normalized()
	var x := up_hint.cross(z)
	if x.length_squared() < 0.000001:
		# up_hint 와 fwd 가 평행하면 축이 정해지지 않는다. 다른 축으로 다시 잡는다.
		x = Vector3.FORWARD.cross(z)
		if x.length_squared() < 0.000001:
			x = Vector3.RIGHT.cross(z)
	x = x.normalized()
	return Basis(x, z.cross(x), z)


# --- 애니메이션 -------------------------------------------------------------
func _update_animation() -> void:
	if _anim == null:
		return

	var clip: String = CLIP.get(state, "idle")
	if state == State.GROUND:
		var planar := Vector2(velocity.x, velocity.z).length()
		if planar > run_speed * 0.6:
			clip = CLIP_RUN
		elif planar > 0.4:
			clip = CLIP_WALK

	if clip == _current_clip:
		return
	if not _anim.has_animation(clip):
		return

	_anim.play(clip, 0.18)
	_current_clip = clip


## 검증용: 모델에 실제로 들어온 애니메이션 클립 목록.
## 블렌더 쪽 계약(CLIP 상수)이 지켜졌는지 게임 안에서 확인하는 데 쓴다.
func animation_names() -> PackedStringArray:
	if _anim == null:
		return PackedStringArray()
	return _anim.get_animation_list()


## 디버그/검증용 상태 문자열
func state_name() -> String:
	match state:
		State.GROUND: return "지상"
		State.AIR: return "공중"
		State.GLIDE: return "활공"
		State.CLING: return "부착"
		State.BURIED: return "파묻힘"
	return "?"


## 활공 스위치가 켜져 있는가 (아직 실제 활공에 못 들어갔어도 참일 수 있다).
## HUD 의 안내 문구와 테스트가 쓴다.
func glide_armed() -> bool:
	return _glide_armed
