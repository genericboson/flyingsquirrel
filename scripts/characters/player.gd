extends CharacterBody3D
## 플레이어블 하늘다람쥐.
##
## 모델과 애니메이션은 블렌더에서 만들어 .glb 로 내보낸 것을 쓴다.
## (blender/ 폴더의 파이썬 스크립트가 원본, models/*.glb 가 산출물)
##
## 조작(기획서에 조작 항목이 없어 정한 값 — claudedocs/요구사항.md F1~F4):
##   WASD    이동
##   Shift   달리기
##   Space   지상에서 점프 / 공중에서 누르고 있으면 활공
##   마우스  카메라 회전
##
## 모델의 앞쪽은 +Z 이므로 방향 정렬에 atan2(d.x, d.z) 를 쓴다.

const MODEL_PATH := "res://models/flying_squirrel.glb"

enum State { GROUND, AIR, GLIDE }

## 블렌더 쪽과 맞춘 애니메이션 클립 이름. 양쪽 다 이 이름을 지켜야 한다.
const CLIP := {
	State.GROUND: "idle",
	State.AIR: "jump",
	State.GLIDE: "glide",
}
const CLIP_WALK := "walk"
const CLIP_RUN := "run"

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

var state: State = State.GROUND

var _model: Node3D
var _anim: AnimationPlayer
var _current_clip := ""
var _facing := 0.0


func _ready() -> void:
	_build_body()
	_facing = rotation.y


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


func _find_anim_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node
	for child in node.get_children():
		var found := _find_anim_player(child)
		if found:
			return found
	return null


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


func _height_above_ground() -> float:
	var space := get_world_3d().direct_space_state
	var from := global_position
	var q := PhysicsRayQueryParameters3D.create(from, from + Vector3.DOWN * 50.0)
	q.exclude = [get_rid()]
	var hit := space.intersect_ray(q)
	if hit.is_empty():
		return 999.0
	return from.distance_to(hit.position)


# --- 물리 -------------------------------------------------------------------
func _physics_process(delta: float) -> void:
	var dir := _movement_dir()

	if is_on_floor():
		state = State.GROUND
	else:
		var wants_glide := Input.is_action_pressed("jump") and velocity.y < 0.5
		state = State.GLIDE if (wants_glide and _height_above_ground() > glide_min_height) else State.AIR

	match state:
		State.GROUND:
			_process_ground(dir, delta)
		State.AIR:
			_process_air(dir, delta)
		State.GLIDE:
			_process_glide(dir, delta)

	move_and_slide()
	_update_animation()


func _process_ground(dir: Vector3, delta: float) -> void:
	var speed := run_speed if Input.is_action_pressed("sprint") else walk_speed
	var target := dir * speed
	velocity.x = move_toward(velocity.x, target.x, ground_accel * delta * speed)
	velocity.z = move_toward(velocity.z, target.z, ground_accel * delta * speed)
	velocity.y = -0.5   # 경사면에 붙어 있도록 살짝 눌러준다

	if Input.is_action_just_pressed("jump"):
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

	var fwd := Vector3(sin(_facing), 0.0, cos(_facing))
	velocity.x = move_toward(velocity.x, fwd.x * glide_speed, 8.0 * delta)
	velocity.z = move_toward(velocity.z, fwd.z * glide_speed, 8.0 * delta)


## 모델의 앞(+Z)이 dir 을 향하도록 부드럽게 돌린다
func _face_toward(dir: Vector3, weight: float) -> void:
	var target := atan2(dir.x, dir.z)
	_facing = lerp_angle(_facing, target, clampf(weight, 0.0, 1.0))
	rotation.y = _facing


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
	return "?"
