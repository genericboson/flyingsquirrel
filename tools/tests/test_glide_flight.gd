extends SceneTree
## 회귀 테스트 — 실제 숲에서 활공이 앞으로 나아가는가 (활공비 측정).
##
##   godot --headless --path . --script res://tools/tests/test_glide_flight.gd
##   종료 코드 0 = 통과, 1 = 실패
##
## test_glide_height.gd 는 "활공에 **진입할 수 있는가**" 를 보고,
## 이 테스트는 "진입한 뒤 **실제로 활강하는가**" 를 본다. 둘 다 있어야 기획서 I8
## (「소나무 사이를 활강하면서 목적지까지 이동」)이 살아 있다고 말할 수 있다.
##
## 측정 방법:
##   나무 꼭대기보다 높은 곳에 플레이어를 놓고 점프 키를 누른 채로 둔다.
##   속도가 정상 상태(수평 glide_speed / 하강 glide_max_fall)에 수렴한 뒤부터
##   5 m 하강하는 동안의 수평 이동 거리를 잰다.
##
## 기대값은 player.gd 의 수치에서 곧바로 나온다:
##   활공비 = glide_speed / glide_max_fall = 10.5 / 2.4 = 4.375 : 1
##   즉 5 m 하강에 21.9 m 전진. (요구사항 I-계약의 「약 4.4 : 1」)
## 그래서 이 테스트는 상수를 따로 박아 두지 않고 player.gd 에서 읽어 계산한다.
## 활공 수치를 조정하면 기대값도 같이 움직이고, 활공이 죽으면 그때만 실패한다.

const PlayerScript = preload("res://scripts/characters/player.gd")
const Layers = preload("res://scripts/physics_layers.gd")

## 나무 꼭대기 위로 이만큼 띄워서 시작한다 (가속 구간 + 측정 구간을 담을 여유)
const START_CLEARANCE := 9.0
## 측정 구간의 하강량
const MEASURE_DROP := 5.0
## 정상 상태 판정 허용 오차 (m/s)
const SETTLE_EPS := 0.02
## 활공비 허용 오차 (비율)
const RATIO_TOL := 0.05
## 이 프레임 안에 끝나지 않으면 실패 (무한 대기 방지)
const MAX_FRAMES := 3000

enum Phase { WAIT_SCENE, SETTLE, MEASURE, DONE }

var _phase: Phase = Phase.WAIT_SCENE
var _frames := 0
var _fail := 0

var _player: CharacterBody3D
var _tree_top := 0.0
var _start := Vector3.ZERO      ## 낙하 시작점
var _glide_from := Vector3.ZERO ## 활공 상태로 바뀐 지점
var _mark := Vector3.ZERO       ## 정상 상태 진입 지점 (측정 시작)
var _min_y := INF
var _hits := 0
var _glide_frames := 0


func _initialize() -> void:
	change_scene_to_file("res://scenes/World.tscn")


func _bad(msg: String) -> void:
	_fail += 1
	print("[활공비행] X %s" % msg)


func _process(_delta: float) -> bool:
	_frames += 1
	if _frames > MAX_FRAMES:
		_bad("%d 프레임 안에 측정이 끝나지 않았다 (활공이 시작조차 안 됐을 수 있다)" % MAX_FRAMES)
		return _finish()

	match _phase:
		Phase.WAIT_SCENE:
			if current_scene == null or _frames < 6:
				return false
			return _launch()
		Phase.SETTLE, Phase.MEASURE:
			return _step()
		Phase.DONE:
			return true
	return false


# --- 발사 -------------------------------------------------------------------
func _launch() -> bool:
	_player = current_scene.get_node_or_null("Player") as CharacterBody3D
	var area := current_scene.get_node_or_null("Area")
	if _player == null or area == null:
		_bad("Player 또는 Area 노드가 없다 — 숲 씬이 제대로 안 섰다")
		return _finish()

	var top_and_center := _tree_top_and_center(area)
	_tree_top = top_and_center[0]
	var center: Vector3 = top_and_center[1]
	if _tree_top <= 0.0:
		_bad("나무 메시를 찾지 못했다 (이름 계약 '기둥_' / '가지_' 확인 필요)")
		return _finish()

	# 모델의 앞(+Z)이 월드 +X 를 향하게 세운다. 활공은 이 방향으로 나아간다.
	var b: Basis = PlayerScript.basis_facing(Vector3.RIGHT, Vector3.UP)
	_player.set("_orientation", b)
	_player.basis = b

	_start = Vector3(center.x, _tree_top + START_CLEARANCE, center.z)
	_player.global_position = _start
	_player.velocity = Vector3.ZERO
	_phase = Phase.SETTLE
	print("[활공비행] 나무 꼭대기 y=%.2f, 시작점=(%.1f, %.1f, %.1f), 방향=+X"
		% [_tree_top, _start.x, _start.y, _start.z])
	return false


## 나무(기둥/가지) 메시의 최고점과 기둥들의 수평 중심.
func _tree_top_and_center(area: Node) -> Array:
	var top := 0.0
	var sum := Vector3.ZERO
	var n := 0
	var stack: Array[Node] = [area]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		if node is MeshInstance3D and Layers.layer_for_name(node.name) == Layers.TREE:
			var m := node as MeshInstance3D
			var ab := m.global_transform * m.get_aabb()
			top = maxf(top, ab.end.y)
			if String(m.name).begins_with("기둥_"):
				sum += Vector3(ab.get_center().x, 0.0, ab.get_center().z)
				n += 1
		for c in node.get_children():
			stack.append(c)
	return [top, sum / maxf(n, 1)]


# --- 비행 -------------------------------------------------------------------
func _step() -> bool:
	# 공중에 뜬 뒤에 점프 키를 누른다. 지상에서 누르면 점프로 소비된다.
	if not _player.is_on_floor() and not Input.is_action_pressed("jump"):
		Input.action_press("jump")

	var pos := _player.global_position
	_min_y = minf(_min_y, pos.y)
	_hits += _player.get_slide_collision_count()

	var st: int = _player.get("state")
	var gliding: bool = st == PlayerScript.State.GLIDE
	if gliding:
		_glide_frames += 1
		if _glide_from == Vector3.ZERO:
			_glide_from = pos

	var v: Vector3 = _player.velocity
	var vh := Vector2(v.x, v.z).length()
	var want_h: float = _player.get("glide_speed")
	var want_fall: float = _player.get("glide_max_fall")

	if _phase == Phase.SETTLE:
		if not gliding:
			return false
		# 수평 속도와 하강 속도가 둘 다 정상 상태에 닿았는가
		if absf(vh - want_h) < SETTLE_EPS and absf(v.y + want_fall) < SETTLE_EPS:
			_mark = pos
			_phase = Phase.MEASURE
			print("[활공비행] 정상 속도 도달: 수평 %.3f m/s, 하강 %.3f m/s (자유낙하 시작점에서 %.2f m 하강 뒤)"
				% [vh, -v.y, _start.y - pos.y])
		return false

	# --- 측정 중 ---
	if not gliding:
		_bad("측정 도중 활공이 끊겼다 (상태=%d) — 무언가에 부딪혔을 수 있다" % st)
		return _finish()

	var drop := _mark.y - pos.y
	if drop < MEASURE_DROP:
		return false

	var fwd := Vector2(pos.x - _mark.x, pos.z - _mark.z).length()
	var ratio := fwd / drop
	var want_ratio := want_h / want_fall

	print("[활공비행] 측정: %.3f m 하강 / %.3f m 전진 -> 활공비 %.3f : 1 (기대 %.3f)"
		% [drop, fwd, ratio, want_ratio])
	print("[활공비행] 5 m 하강 환산: 전진 %.2f m" % [ratio * MEASURE_DROP])
	print("[측정] 활공비 %.3f : 1 (%.2f m 하강에 %.2f m 전진, 기대 %.3f)"
		% [ratio, MEASURE_DROP, ratio * MEASURE_DROP, want_ratio])
	print("[활공비행] 활공 시작점(%.1f,%.1f,%.1f) -> 현재(%.1f,%.1f,%.1f), 활공 프레임 %d"
		% [_glide_from.x, _glide_from.y, _glide_from.z, pos.x, pos.y, pos.z, _glide_frames])

	# 정지 상태에서 활공에 들어간 순간부터 따진 실측치도 같이 남긴다 (가속 구간 포함)
	var raw_drop := _glide_from.y - pos.y
	var raw_fwd := Vector2(pos.x - _glide_from.x, pos.z - _glide_from.z).length()
	if raw_drop > 0.01:
		print("[활공비행] (참고) 정지 상태에서 진입한 순간부터: %.2f m 하강 / %.2f m 전진 -> %.2f : 1"
			% [raw_drop, raw_fwd, raw_fwd / raw_drop])

	if absf(ratio - want_ratio) > RATIO_TOL:
		_bad("활공비 %.3f 가 기대 %.3f 에서 벗어났다" % [ratio, want_ratio])
	if fwd < 1.0:
		_bad("수평으로 나아가지 않았다 (전진 %.3f m) — 활공이 아니라 낙하다" % fwd)
	if _hits > 0:
		_bad("측정 중 %d회 충돌했다 — 나무를 스쳤다면 수치를 믿을 수 없다" % _hits)
	if _min_y < _tree_top:
		_bad("비행 최저 고도 %.2f 가 나무 꼭대기 %.2f 보다 낮다 — 측정 구간이 숲에 잠겼다"
			% [_min_y, _tree_top])

	return _finish()


func _finish() -> bool:
	_phase = Phase.DONE
	if _player != null:
		Input.action_release("jump")
	print("[활공비행] 판정=%s (실패 %d건)" % ["통과" if _fail == 0 else "실패", _fail])
	quit(0 if _fail == 0 else 1)
	return true
