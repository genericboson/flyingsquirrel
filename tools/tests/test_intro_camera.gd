extends SceneTree
## 회귀 테스트 — 오프닝 인트로 카메라 (요구사항 I5).
##
##   godot --headless --path . --script res://tools/tests/test_intro_camera.gd
##   godot --headless --path . --script res://tools/tests/test_intro_camera.gd -- --skip 1.0
##   종료 코드 0 = 통과, 1 = 실패
##
## 기획서 원문: 「멀리 있는 카메라가 줌인하면서 서서히 하늘다람쥐에 대한
## 3인칭 플레이 카메라 시점으로 바뀐다.」
##
## 여기서 기계로 지킬 수 있는 것은 네 가지다:
##   ① 시작할 때 인트로 전용 카메라가 현재 카메라다 (플레이 카메라가 아니다)
##   ② 대상까지의 거리가 **줄어든다** (「줌인」) — 늘거나 제자리면 실패
##   ③ 끝나면 플레이 카메라로 넘어가고 인트로 카메라 노드가 남지 않는다
##   ④ --skip 을 주면 그 시점에 즉시 넘어간다
##
## 인트로 수치(거리·시간·시야각)는 아직 잠정치라(요구사항 미정 10) 값을 박아 두지 않고
## CameraRig 의 export 값을 읽어 상대적으로 판정한다.

var _t := 0.0
var _marks: Array = [0.2, 1.0, 2.0, 3.0, 4.2]
var _i := 0
var _skip_at := -1.0
var _skipped := false
var _fail := 0

var _dists: Array[float] = []
var _fovs: Array[float] = []
var _saw_intro_cam := false


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	for k in args.size():
		if args[k] == "--skip" and k + 1 < args.size():
			_skip_at = float(args[k + 1])
	change_scene_to_file("res://scenes/World.tscn")


func _bad(msg: String) -> void:
	_fail += 1
	print("[인트로] X %s" % msg)


func _rig() -> Node:
	if current_scene == null:
		return null
	return current_scene.get_node_or_null("CameraRig")


func _process(delta: float) -> bool:
	_t += delta
	var rig := _rig()
	if rig == null:
		return false

	if _skip_at > 0.0 and not _skipped and _t >= _skip_at:
		_skipped = true
		var ev := InputEventKey.new()
		ev.physical_keycode = KEY_SPACE
		ev.pressed = true
		Input.parse_input_event(ev)
		print("[인트로] t=%.2f 키 입력 주입 (직후 진행중=%s)" % [_t, rig.get("_intro_active")])
		# 스킵은 '즉시' 여야 한다. 입력 처리 뒤 몇 프레임 안에 끝나는지만 본다.
		_marks = [_t + 0.0001, _t + 0.02, _t + 0.05, _t + 0.2]
		_i = 0

	if _i < _marks.size() and _t >= _marks[_i]:
		_i += 1
		_observe(rig)

	if _i >= _marks.size():
		_judge(rig)
		print("[인트로] 판정=%s (실패 %d건)" % ["통과" if _fail == 0 else "실패", _fail])
		quit(0 if _fail == 0 else 1)
		return true
	return false


func _observe(rig: Node) -> void:
	var player: Node3D = current_scene.get_node_or_null("Player")
	var cam := get_root().get_camera_3d()
	var active: bool = rig.get("_intro_active")
	var d := 0.0
	if cam != null and player != null:
		d = cam.global_position.distance_to(player.global_position)
	if cam != null and cam.name == "IntroCamera":
		_saw_intro_cam = true
		_dists.append(d)
		_fovs.append(cam.fov)
	print("[인트로] t=%.2f 진행중=%s 현재카메라=%s 대상거리=%6.2fm fov=%.1f 마우스=%d"
		% [_t, active, "없음" if cam == null else cam.name, d,
			0.0 if cam == null else cam.fov, Input.mouse_mode])


func _judge(rig: Node) -> void:
	var still: bool = rig.get("_intro_active")
	var leftover := rig.get_node_or_null("IntroCamera")

	# ③ 끝났는가 / 뒷정리가 됐는가
	if still:
		_bad("인트로가 끝나지 않았다 (intro_duration=%.1f 를 넘겼는데도 진행중)"
			% [rig.get("intro_duration")])
	if leftover != null:
		_bad("인트로 카메라 노드가 남아 있다 — 매 프레임 렌더 대상이 하나 더 산다")

	var cam := get_root().get_camera_3d()
	if cam != null and cam.name == "IntroCamera":
		_bad("아직 인트로 카메라가 현재 카메라다 — 플레이 카메라로 넘어가지 않았다")

	if _skipped:
		# ④ 스킵 경로에서는 줌인 표본이 없다. 여기까지 통과했으면 스킵이 먹은 것이다.
		print("[인트로] 스킵 경로: %.2f초 지점에서 즉시 인계됨" % _skip_at)
		return

	# ① 인트로 전용 카메라를 실제로 봤는가
	if not _saw_intro_cam:
		_bad("인트로 전용 카메라가 한 번도 현재 카메라가 아니었다 — 오프닝 연출이 안 돈다")
		return

	# ② 줌인 — 대상까지의 거리가 계속 줄어야 한다
	if _dists.size() < 2:
		_bad("인트로 표본이 %d개뿐이라 줌인을 판정할 수 없다" % _dists.size())
		return
	for k in range(1, _dists.size()):
		if _dists[k] >= _dists[k - 1]:
			_bad("대상까지의 거리가 줄지 않았다: %.2fm -> %.2fm" % [_dists[k - 1], _dists[k]])

	var far: float = _dists[0]
	var near: float = _dists[-1]
	var play_dist: float = rig.get("distance")
	if far < play_dist * 2.0:
		_bad("시작 거리 %.2fm 가 평소 카메라 거리 %.2fm 에 비해 '멀리' 라 하기 어렵다"
			% [far, play_dist])
	print("[인트로] 줌인 %.2fm -> %.2fm (평소 카메라 거리 %.2fm), 시야각 %.1f -> %.1f"
		% [far, near, play_dist, _fovs[0], _fovs[-1]])
	print("[측정] 인트로 줌인 %.1f m -> %.1f m, 시야각 %.1f -> %.1f, %.1f초에 플레이 카메라 인계"
		% [far, near, _fovs[0], _fovs[-1], rig.get("intro_duration")])

	# 「줌인」은 화각도 같이 넓어진다 (망원 -> 평소)
	if _fovs[-1] <= _fovs[0]:
		_bad("시야각이 넓어지지 않았다: %.1f -> %.1f (intro_fov=%.1f, base_fov=%.1f)"
			% [_fovs[0], _fovs[-1], rig.get("intro_fov"), rig.get("base_fov")])
