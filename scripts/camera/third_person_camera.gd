extends Node3D
## 3인칭 추적 카메라 (기획서: "3인칭 액션 퍼즐 어드벤쳐").
##
## SpringArm3D 를 써서 벽이나 지형에 카메라가 파묻히지 않게 한다.
## 활공 중에는 속도감을 위해 팔을 조금 늘리고 시야각을 넓힌다.

@export var target_path: NodePath
@export var height := 1.15                ## 대상의 어느 높이를 바라볼지
@export var distance := 5.0
@export var glide_distance := 6.8
@export var mouse_sensitivity := 0.0032
@export var pad_sensitivity := 2.6
@export var min_pitch := -60.0
@export var max_pitch := 32.0
@export var follow_speed := 9.0
@export var base_fov := 62.0
@export var glide_fov := 74.0

var _yaw := 0.0
var _pitch := -12.0
var _target: Node3D
var _arm: SpringArm3D
var _cam: Camera3D


func _ready() -> void:
	_target = get_node_or_null(target_path) as Node3D

	_arm = SpringArm3D.new()
	_arm.name = "SpringArm"
	_arm.spring_length = distance
	_arm.margin = 0.3
	# 플레이어(레이어 1)는 무시하고 지형/구조물만 카메라를 밀어내게 한다
	_arm.collision_mask = 0xFFFFFFFF & ~1
	add_child(_arm)

	_cam = Camera3D.new()
	_cam.name = "Camera"
	_cam.fov = base_fov
	_arm.add_child(_cam)
	_cam.make_current()

	if _target:
		global_position = _target.global_position + Vector3.UP * height

	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_yaw -= event.relative.x * mouse_sensitivity
		_pitch -= event.relative.y * mouse_sensitivity
		_pitch = clampf(_pitch, deg_to_rad(min_pitch), deg_to_rad(max_pitch))

	if event.is_action_pressed("ui_release_mouse"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _process(delta: float) -> void:
	if _target == null:
		return

	# 게임패드 우스틱
	var pad := Vector2(
		Input.get_joy_axis(0, JOY_AXIS_RIGHT_X),
		Input.get_joy_axis(0, JOY_AXIS_RIGHT_Y)
	)
	if pad.length() > 0.15:
		_yaw -= pad.x * pad_sensitivity * delta
		_pitch -= pad.y * pad_sensitivity * delta
		_pitch = clampf(_pitch, deg_to_rad(min_pitch), deg_to_rad(max_pitch))

	# 대상 추적
	var want := _target.global_position + Vector3.UP * height
	global_position = global_position.lerp(want, clampf(follow_speed * delta, 0.0, 1.0))

	rotation.y = _yaw
	_arm.rotation.x = _pitch

	# 활공 중에는 조금 물러나고 시야를 넓혀 속도감을 준다
	# _target 은 Node3D 라 state_name() 의 반환형이 Variant 다. 타입을 명시해야 한다.
	var gliding: bool = _target.has_method("state_name") and _target.state_name() == "활공"
	var want_len := glide_distance if gliding else distance
	var want_fov := glide_fov if gliding else base_fov
	var w := clampf(delta * 3.0, 0.0, 1.0)
	_arm.spring_length = lerpf(_arm.spring_length, want_len, w)
	_cam.fov = lerpf(_cam.fov, want_fov, w)
