extends Node3D
## 3인칭 추적 카메라 (기획서: "3인칭 액션 퍼즐 어드벤쳐").
##
## SpringArm3D 를 써서 벽이나 지형에 카메라가 파묻히지 않게 한다.
## 활공 중에는 속도감을 위해 팔을 조금 늘리고 시야각을 넓힌다.
##
## 게임 시작 시에는 오프닝 인트로가 먼저 돈다 (기획서 I5):
## 멀리 떨어진 별도 카메라에서 시작해 서서히 이 3인칭 카메라 위치로 수렴한 뒤
## 조작을 넘긴다. 아무 버튼이나 누르면 즉시 넘어간다.

const Layers = preload("res://scripts/physics_layers.gd")

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

@export_group("오프닝 인트로")
## 기획서에는 "멀리 있는 카메라가 줌인하면서 서서히" 라고만 적혀 있고 수치가 없다.
## 아래는 PD 잠정치이며 사용자 확인 후 바뀔 수 있어 전부 export 로 뺐다.
@export var intro_enabled := true
@export var intro_distance := 40.0     ## 시작 지점이 대상에서 떨어진 수평 거리(m)
@export var intro_height := 10.0       ## 시작 지점이 대상보다 높은 정도(m)
@export var intro_yaw_offset := 28.0   ## 평소 카메라 방향에서 비껴 시작하는 각도(도)
@export var intro_duration := 4.0      ## 평소 3인칭 위치까지 오는 데 걸리는 시간(초)
@export var intro_fov := 38.0          ## 시작 시야각(망원). 끝나면 base_fov 로 수렴한다

var _yaw := 0.0
# _pitch 는 라디안이다 (clamp 도 rotation.x 대입도 라디안 기준).
# 초기값만 도 단위로 들어가 있어 시작 시점의 시점이 엉뚱했다 (-12rad = 약 +32도, 머리 위에서 내려다봄).
var _pitch := deg_to_rad(-12.0)
var _target: Node3D
var _arm: SpringArm3D
var _cam: Camera3D

var _intro_cam: Camera3D       ## 인트로 전용 카메라. 끝나면 해제한다
var _intro_from := Vector3.ZERO   ## 인트로 시작 지점 (고정)
var _intro_time := 0.0
var _intro_active := false


func _ready() -> void:
	_target = get_node_or_null(target_path) as Node3D

	_arm = SpringArm3D.new()
	_arm.name = "SpringArm"
	_arm.spring_length = distance
	_arm.margin = 0.3
	# 플레이어(레이어 1)는 무시하고 지형(2)/나무(3)만 카메라를 밀어내게 한다
	# 레이어 규약: scripts/physics_layers.gd
	_arm.collision_mask = Layers.SOLID
	add_child(_arm)

	_cam = Camera3D.new()
	_cam.name = "Camera"
	_cam.fov = base_fov
	_arm.add_child(_cam)

	if _target:
		global_position = _target.global_position + Vector3.UP * height

	if intro_enabled and _target != null:
		_begin_intro()
	else:
		_hand_over_to_play_camera()


# --- 오프닝 인트로 -----------------------------------------------------------
## 대상에서 멀리 떨어진 지점에 인트로 카메라를 놓고 그쪽을 바라보게 한다.
## 플레이어가 무엇을 하고 있든(서 있든, 나중에 나무에 매달리든) 대상 위치만 보므로
## 시작 상태에 의존하지 않는다.
func _begin_intro() -> void:
	var look := _target.global_position + Vector3.UP * height
	# 스프링암은 자식을 자기 로컬 +Z 로 밀어낸다(측정 확인). 평소 카메라가 있는 쪽이다.
	var yaw := _yaw + deg_to_rad(intro_yaw_offset)
	var behind := Vector3(sin(yaw), 0.0, cos(yaw))
	var from := look + behind * intro_distance + Vector3.UP * intro_height

	if from.distance_to(look) < 0.5:
		# 거리가 0에 가까우면 바라볼 방향이 정해지지 않는다. 인트로를 건너뛴다.
		_hand_over_to_play_camera()
		return

	_intro_from = from

	_intro_cam = Camera3D.new()
	_intro_cam.name = "IntroCamera"
	_intro_cam.top_level = true       # 리그의 회전/이동에 끌려다니지 않게 한다
	_intro_cam.fov = intro_fov
	add_child(_intro_cam)
	_intro_cam.global_transform = Transform3D(_aim_basis(from, look), from)
	_intro_cam.make_current()

	_intro_time = 0.0
	_intro_active = true
	# 인트로 중에는 마우스를 잡지 않는다 (입력이 카메라를 흔들지 않도록)
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


## 인트로 카메라를 평소 3인칭 카메라 자세로 수렴시킨다.
##
## 위치는 시작 지점 -> 플레이 카메라 위치로 보간한다.
## 방향은 "대상을 정면에 두는 자세" 와 "플레이 카메라 자세" 를 진행도로 섞는다.
## 시작 자세를 고정해 두고 슬러프하면 도중에 대상이 화면 밖으로 밀려나고
## 지평선이 기우는데(중간 자세에 롤이 생긴다), 매 프레임 대상을 겨누면 그게 없다.
##
## 목표가 매 프레임 갱신되는 '살아있는' 플레이 카메라 자세라서 진행도 1 에서
## 양쪽이 정확히 같은 자세가 된다. 그래서 넘길 때 화면이 튀지 않는다.
func _update_intro(delta: float) -> void:
	_intro_time += delta
	var span := maxf(intro_duration, 0.001)
	var p := clampf(_intro_time / span, 0.0, 1.0)
	var eased := smoothstep(0.0, 1.0, p)   # 시작과 끝을 부드럽게

	var play := _cam.global_transform
	var look := _target.global_position + Vector3.UP * height
	var pos := _intro_from.lerp(play.origin, eased)

	# 방향은 위치보다 늦게 플레이 카메라 쪽으로 넘어가게 한다(eased 의 제곱).
	# 그래야 인트로 내내 대상이 화면 가운데에 가깝게 남는다. e=1 에서는 여전히 정확히 일치한다.
	var aim := _aim_basis(pos, look)
	var b := Basis(aim.get_rotation_quaternion().slerp(play.basis.get_rotation_quaternion(), eased * eased))
	_intro_cam.global_transform = Transform3D(b.orthonormalized(), pos)
	_intro_cam.fov = lerpf(intro_fov, _cam.fov, eased)

	if p >= 1.0:
		_hand_over_to_play_camera()


## from 에서 look 을 정면에 두는 회전 (수평 유지).
func _aim_basis(from: Vector3, look: Vector3) -> Basis:
	if from.distance_squared_to(look) < 0.0025:
		return _intro_cam.global_transform.basis if _intro_cam != null else Basis.IDENTITY
	return Transform3D(Basis.IDENTITY, from).looking_at(look, Vector3.UP).basis


## 평소 3인칭 카메라로 인계하고 조작을 시작한다. (인트로 종료 / 스킵 / 인트로 없음)
func _hand_over_to_play_camera() -> void:
	_intro_active = false
	if _intro_cam != null:
		_intro_cam.queue_free()
		_intro_cam = null
	_cam.make_current()
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if _intro_active:
		# 아무 버튼이나 누르면 인트로를 건너뛴다 (마우스 움직임은 스킵으로 치지 않는다)
		var pressed_button: bool = (
			(event is InputEventKey and event.pressed and not event.echo)
			or (event is InputEventMouseButton and event.pressed)
			or (event is InputEventJoypadButton and event.pressed)
		)
		if pressed_button:
			_hand_over_to_play_camera()
		return

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

	# 게임패드 우스틱 (인트로 중에는 시점을 흔들지 않는다)
	var pad := Vector2(
		Input.get_joy_axis(0, JOY_AXIS_RIGHT_X),
		Input.get_joy_axis(0, JOY_AXIS_RIGHT_Y)
	)
	if not _intro_active and pad.length() > 0.15:
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

	if _intro_active:
		_update_intro(delta)
