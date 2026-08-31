extends SceneTree
## 회귀 테스트 — 활공이 '누르고 있기' 가 아니라 '눌러서 켜기(토글)' 인가.
##
##   godot --headless --path . --script res://tools/tests/test_glide_toggle.gd
##   종료 코드 0 = 통과, 1 = 실패
##
## 사용자 요구: 「키보드 키 매핑이 직관적이지 않아」
## 바꾼 규칙 (player.gd):
##   · 공중에서 Space 를 한 번 누르면 활공 시작, 다시 누르면 해제
##   · 상승 중에 눌러도 입력이 씹히지 않고 **예약**되었다가 하강 시점에 펴진다
##   · 착지하면 활공 스위치가 초기화된다
##
## ★ 기대값을 상수로 박지 않는다. 활공 진입 조건(velocity.y < 0.5, glide_min_height)은
##   player.gd 의 export 값에서 읽고, 시작 고도는 씬의 나무 높이에서 구한다.

const PlayerScript = preload("res://scripts/characters/player.gd")
const Layers = preload("res://scripts/physics_layers.gd")

## 나무 꼭대기 위로 이만큼 띄워 시작한다 (지면이 멀어야 활공 진입 조건이 성립한다).
## **다람쥐 쪽 값이라 월드 축척을 곱하지 않는다** — 진입 문턱 glide_min_height(0.8 m)와
## 토글 왕복에 필요한 낙하 시간만 담으면 되고, 나무 높이와는 무관하다.
const START_CLEARANCE := 12.0
## 키를 이만큼 프레임 동안 눌렀다 뗀다 (한 번의 '탭')
const TAP_HOLD := 4
const TAP_GAP := 4
## 한 단계가 이 프레임 안에 안 끝나면 실패
const STAGE_FRAMES := 900
## 상승 중이라고 볼 최소 상승 속도 (m/s). player.gd 의 진입 문턱(0.5)보다 넉넉히 위.
const RISE_SPEED := 6.0

enum Stage { WAIT, FALL, TAP_ON, EXPECT_GLIDE, TAP_OFF, EXPECT_AIR, RISE, TAP_RISING, EXPECT_RESERVED, EXPECT_LATE_GLIDE, DONE }

var _stage: Stage = Stage.WAIT
var _frames := 0
var _stage_frames := 0
var _fail := 0
var _tap := 0

var _player: CharacterBody3D
var _rising_checks := 0


func _initialize() -> void:
	change_scene_to_file("res://scenes/World.tscn")


func _bad(msg: String) -> void:
	_fail += 1
	print("[활공토글] X %s" % msg)


func _go(next: Stage) -> void:
	_stage = next
	_stage_frames = 0
	_tap = 0


## 실패 메시지에 쓸 단계 이름
func _stage_name() -> String:
	match _stage:
		Stage.WAIT: return "씬 대기"
		Stage.FALL: return "자유낙하 대기"
		Stage.TAP_ON: return "활공 켜기 입력"
		Stage.EXPECT_GLIDE: return "한 번 눌러 활공 진입"
		Stage.TAP_OFF: return "활공 끄기 입력"
		Stage.EXPECT_AIR: return "다시 눌러 활공 해제"
		Stage.RISE: return "상승 대기"
		Stage.TAP_RISING: return "상승 중 입력"
		Stage.EXPECT_RESERVED: return "상승 중 예약 유지"
		Stage.EXPECT_LATE_GLIDE: return "하강 시점에 예약된 활공 펴짐"
		Stage.DONE: return "끝"
	return "?"


func _state() -> int:
	return int(_player.get("state"))


func _armed() -> bool:
	return bool(_player.call("glide_armed"))


## 키를 눌렀다 떼는 한 번의 탭. 다 끝나면 true.
func _tap_jump() -> bool:
	_tap += 1
	if _tap <= TAP_HOLD:
		Input.action_press("jump")
		return false
	Input.action_release("jump")
	return _tap > TAP_HOLD + TAP_GAP


func _process(_delta: float) -> bool:
	_frames += 1
	_stage_frames += 1
	if current_scene == null or _frames < 8:
		return false
	if _stage_frames > STAGE_FRAMES:
		_bad("단계 '%s' 가 %d 프레임 안에 끝나지 않았다 (상태=%s, 스위치=%s)"
			% [_stage_name(), STAGE_FRAMES, _player.call("state_name"), _armed()])
		return _finish()

	match _stage:
		Stage.WAIT:
			return _launch()
		Stage.FALL:
			# 자유낙하로 하강이 확실해질 때까지 기다린다 (누르지 않았으니 활공하면 안 된다)
			if _state() == PlayerScript.State.GLIDE:
				_bad("아무것도 안 눌렀는데 활공에 들어갔다 — 토글이 아니라 자동 활공이다")
				return _finish()
			if _player.velocity.y < -2.0:
				print("[활공토글] 자유낙하 확인 (하강 %.2f m/s, 상태=%s)"
					% [-_player.velocity.y, _player.call("state_name")])
				_go(Stage.TAP_ON)
			return false

		Stage.TAP_ON:
			if _tap_jump():
				_go(Stage.EXPECT_GLIDE)
			return false
		Stage.EXPECT_GLIDE:
			if _state() == PlayerScript.State.GLIDE:
				print("[활공토글] ① 하강 중 한 번 눌러 활공 진입 (%d 프레임 만에)" % _stage_frames)
				_go(Stage.TAP_OFF)
			return false

		Stage.TAP_OFF:
			if _tap_jump():
				_go(Stage.EXPECT_AIR)
			return false
		Stage.EXPECT_AIR:
			if _state() == PlayerScript.State.GLIDE:
				return false
			if _armed():
				_bad("다시 눌렀는데 활공 스위치가 아직 켜져 있다")
			print("[활공토글] ② 다시 눌러 활공 해제 (상태=%s, %d 프레임 만에)"
				% [_player.call("state_name"), _stage_frames])
			# 상승 중 예약 시험: 위로 던져 올린다
			_player.velocity = Vector3(0, RISE_SPEED, 0)
			_go(Stage.RISE)
			return false

		Stage.RISE:
			if _player.velocity.y > RISE_SPEED * 0.5:
				_go(Stage.TAP_RISING)
			return false
		Stage.TAP_RISING:
			# 상승 중에 누른다. 이 시점에 활공에 들어가면 안 되고, 스위치만 켜져야 한다.
			if _player.velocity.y < 0.5:
				_bad("상승이 너무 빨리 끝나 '상승 중 입력' 을 시험하지 못했다")
				return _finish()
			if _tap_jump():
				if not _armed():
					_bad("상승 중에 눌렀는데 활공 스위치가 켜지지 않았다 — 입력이 씹혔다")
				_go(Stage.EXPECT_RESERVED)
			return false
		Stage.EXPECT_RESERVED:
			# 아직 상승 중인 동안에는 활공이 아니어야 한다
			if _player.velocity.y >= 0.5:
				if _state() == PlayerScript.State.GLIDE:
					_bad("상승 중(%.2f m/s)인데 벌써 활공 상태다" % _player.velocity.y)
					return _finish()
				_rising_checks += 1
				return false
			print("[활공토글] ③ 상승 중 입력 예약됨: %d 프레임 동안 스위치 켜짐 + 활공 아님" % _rising_checks)
			if _rising_checks < 3:
				_bad("상승 구간이 %d 프레임뿐이라 예약을 확인했다고 보기 어렵다" % _rising_checks)
			_go(Stage.EXPECT_LATE_GLIDE)
			return false
		Stage.EXPECT_LATE_GLIDE:
			if _state() != PlayerScript.State.GLIDE:
				if not _armed():
					_bad("하강으로 바뀌기 전에 활공 스위치가 꺼졌다 — 예약이 사라졌다")
					return _finish()
				return false
			print("[활공토글] ④ 하강으로 바뀌자 예약된 활공이 펴짐 (%d 프레임 뒤, 수직속도 %+.2f m/s)"
				% [_stage_frames, _player.velocity.y])
			print("[측정] 활공 토글: 진입/해제/상승중 예약 모두 동작 (상승 중 %d 프레임 대기 뒤 자동 진입)"
				% _rising_checks)
			return _finish()
		Stage.DONE:
			return true
	return false


# --- 발사 -------------------------------------------------------------------
func _launch() -> bool:
	_player = current_scene.get_node_or_null("Player") as CharacterBody3D
	var area := current_scene.get_node_or_null("Area")
	if _player == null or area == null:
		_bad("Player 또는 Area 노드가 없다")
		return _finish()

	var top_center := _tree_top_and_center(area)
	var top: float = top_center[0]
	var center: Vector3 = top_center[1]
	if top <= 0.0:
		_bad("나무 메시를 찾지 못했다 (이름 계약 '기둥_' / '가지_' 확인 필요)")
		return _finish()

	# 시작은 기둥에 붙어 있는 상태다. 떼어낸 뒤 숲 위로 올린다.
	_player.call("release_cling")
	var b: Basis = PlayerScript.basis_facing(Vector3.RIGHT, Vector3.UP)
	_player.set("_orientation", b)
	_player.basis = b
	_player.global_position = Vector3(center.x, top + START_CLEARANCE, center.z)
	_player.velocity = Vector3.ZERO

	print("[활공토글] 나무 꼭대기 y=%.2f -> 시작 y=%.2f (활공 진입 문턱: 하강 시작 + 지면까지 %.2f m 초과)"
		% [top, _player.global_position.y, float(_player.get("glide_min_height"))])
	_go(Stage.FALL)
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


func _finish() -> bool:
	_go(Stage.DONE)
	Input.action_release("jump")
	print("[활공토글] 판정=%s (실패 %d건)" % ["통과" if _fail == 0 else "실패", _fail])
	quit(0 if _fail == 0 else 1)
	return true
