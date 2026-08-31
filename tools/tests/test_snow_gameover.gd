extends SceneTree
## 회귀 테스트 — 눈밭에 떨어지면 게임오버, 나뭇가지 위는 게임오버가 아니다.
##
##   godot --headless --path . --script res://tools/tests/test_snow_gameover.gd
##   종료 코드 0 = 통과, 1 = 실패
##
## 사용자 요구: 「다람쥐가 눈밭인 땅에 떨어지면 눈에 파묻혀서 게임오버가 되게 해줘」
##
## 여기서 기계로 지킬 수 있는 것은 세 가지다:
##   ① 지면(레이어 2 TERRAIN)에 닿으면 파묻힘 → 게임오버
##   ② 나뭇가지(레이어 3 TREE) 위에 있으면 게임오버가 **아니다**
##      — 레이어 구분(scripts/physics_layers.gd)이 실제로 동작하는지 보는 것이 핵심이다.
##        이게 깨지면 나무에 앉는 순간 죽는 게임이 된다.
##   ③ R 재시작이 시작 부착 지점으로 정확히 되돌린다
##
## ★ 좌표를 박지 않는다. 낙하 지점도 가지 표본도 씬의 AABB 에서 뽑는다.

const PlayerScript = preload("res://scripts/characters/player.gd")
const Layers = preload("res://scripts/physics_layers.gd")

## 이 프레임 안에 각 단계가 끝나지 않으면 실패
const STAGE_FRAMES := 900
## 가지 위에서 이만큼(초) 버텨야 "게임오버가 아니다" 라고 인정한다
const BRANCH_HOLD := 1.5
## 재시작 복귀 오차 허용 (m)
const RESPAWN_TOL := 0.01
## 눈 지면을 찾는 레이를 가지 윗면보다 이만큼 위에서 시작한다 (가지 속에서 쏘지 않도록).
## 사거리는 player.gd 와 같은 값을 써서 월드 축척을 따라간다 (현재 967.4 m).
const PROBE_LIFT := 20.0
const PROBE_RANGE := PlayerScript.GROUND_PROBE_RANGE

enum Stage { WAIT, SKIP_INTRO, ARM, DROP, RESTART, BRANCH, DONE }

var _stage: Stage = Stage.WAIT
var _frames := 0
var _stage_frames := 0
var _t := 0.0
var _fail := 0

var _world: Node
var _player: CharacterBody3D
var _start_pos := Vector3.ZERO
var _saw_buried := false
var _branch_ab := AABB()
var _branch_name := ""
var _branch_t := 0.0
var _branch_contacts := 0
var _restart_pressed := 0
## _snow_spot() 이 실제로 눈 지면을 찾았는가. 못 찾으면 낙하 시험 자체가 성립하지 않는다.
var _snow_found := false


func _initialize() -> void:
	change_scene_to_file("res://scenes/World.tscn")


func _bad(msg: String) -> void:
	_fail += 1
	print("[눈매장] X %s" % msg)


func _go(next: Stage) -> void:
	_stage = next
	_stage_frames = 0


## 실패 메시지에 쓸 단계 이름
func _stage_name() -> String:
	match _stage:
		Stage.WAIT: return "씬 대기"
		Stage.SKIP_INTRO: return "인트로 스킵"
		Stage.ARM: return "지면 판정 켜지기 대기"
		Stage.DROP: return "눈밭 낙하 -> 게임오버"
		Stage.RESTART: return "R 재시작"
		Stage.BRANCH: return "가지 위 유지"
		Stage.DONE: return "끝"
	return "?"


func _process(delta: float) -> bool:
	_frames += 1
	_stage_frames += 1
	_t += delta
	if current_scene == null or _frames < 8:
		return false
	if _stage_frames > STAGE_FRAMES:
		_bad("단계 '%s' 가 %d 프레임 안에 끝나지 않았다 (플레이어 상태=%s, y=%.2f, 게임오버=%s)"
			% [_stage_name(), STAGE_FRAMES,
				"?" if _player == null else _player.call("state_name"),
				0.0 if _player == null else _player.global_position.y,
				false if _world == null else _world.call("is_game_over")])
		return _finish()

	match _stage:
		Stage.WAIT:
			return _setup()
		Stage.SKIP_INTRO:
			return _skip_intro()
		Stage.ARM:
			return _wait_armed()
		Stage.DROP:
			return _drop_on_snow(delta)
		Stage.RESTART:
			return _try_restart()
		Stage.BRANCH:
			return _stand_on_branch(delta)
		Stage.DONE:
			return true
	return false


# --- 준비 -------------------------------------------------------------------
func _setup() -> bool:
	_world = current_scene
	_player = _world.get_node_or_null("Player") as CharacterBody3D
	if _player == null:
		_bad("Player 노드가 없다")
		return _finish()
	if not _world.has_method("is_game_over"):
		_bad("World 에 is_game_over() 가 없다 — 게임오버 상태를 확인할 수 없다")
		return _finish()

	_start_pos = _player.global_position
	if not bool(_player.call("is_clinging")):
		_bad("시작 상태가 부착이 아니다 (%s) — 재시작 복귀 지점을 믿을 수 없다" % _player.call("state_name"))

	# 가지 표본: 시작 나무에서 가장 굵은 가지를 쓴다 (얇은 가지는 미끄러져 떨어질 수 있다)
	if not _pick_branch():
		_bad("가지 메시를 찾지 못했다 (이름 계약 '가지_' 확인 필요)")
		return _finish()

	_go(Stage.SKIP_INTRO)
	return false


## 인트로를 건너뛴다. 인트로 동안에는 파묻힘 판정을 하지 않게 되어 있으므로
## (안전장치) 먼저 인트로를 끝내야 지면 판정을 시험할 수 있다.
func _skip_intro() -> bool:
	var ev := InputEventKey.new()
	ev.physical_keycode = KEY_SPACE
	ev.pressed = true
	Input.parse_input_event(ev)
	_go(Stage.ARM)
	return false


func _wait_armed() -> bool:
	if not bool(_player.get("death_enabled")):
		return false
	print("[눈매장] 인트로 종료, 지면 판정 켜짐 (t=%.2f)" % _t)
	# 눈 지면 바로 위로 옮겨 떨어뜨린다. 지점은 시작 나무 밑동 근처 지면에서 구한다.
	var ground := _snow_spot()
	if not _snow_found:
		_bad("나무 밖 눈 지면을 찾지 못했다 — 낙하 지점을 정할 수 없다 "
			+ "(지면 탐색 레이 사거리 %.1f m 가 월드 축척에 못 미치는지 확인)" % PROBE_RANGE)
		return _finish()
	_player.call("release_cling")
	_player.global_position = ground + Vector3.UP * 2.0
	_player.velocity = Vector3.ZERO
	print("[눈매장] 눈 지면 위 %s 에서 낙하 시작" % [_player.global_position])
	_go(Stage.DROP)
	return false


# --- ① 눈밭 낙하 -> 게임오버 -------------------------------------------------
func _drop_on_snow(_delta: float) -> bool:
	var st: int = _player.get("state")
	if st == PlayerScript.State.BURIED:
		_saw_buried = true
	if not bool(_world.call("is_game_over")):
		return false

	if not _saw_buried:
		_bad("게임오버는 됐지만 파묻히는 상태(BURIED)를 거치지 않았다 — 연출이 빠졌다")
	print("[눈매장] 눈밭 착지 -> 게임오버 확인 (t=%.2f, 최종 y=%.2f)" % [_t, _player.global_position.y])
	print("[측정] 눈밭 착지: 파묻힘 연출 %s, 게임오버 %s"
		% ["있음" if _saw_buried else "없음", "발생"])
	_go(Stage.RESTART)
	return false


# --- ③ R 재시작 -> 시작 부착 지점 --------------------------------------------
func _try_restart() -> bool:
	# R 을 몇 프레임 눌러 준다 (SceneTree._process 는 노드 _process 보다 먼저 돈다)
	if _restart_pressed < 3:
		_restart_pressed += 1
		Input.action_press("restart")
		return false
	Input.action_release("restart")

	if bool(_world.call("is_game_over")):
		return false

	var back := _player.global_position.distance_to(_start_pos)
	if back > RESPAWN_TOL:
		_bad("재시작 위치가 시작 부착 지점에서 %.3f m 어긋났다 (허용 %.3f)" % [back, RESPAWN_TOL])
	if not bool(_player.call("is_clinging")):
		_bad("재시작했는데 부착 상태가 아니다 (%s)" % _player.call("state_name"))
	print("[눈매장] R 재시작 -> 시작 부착 지점 복귀 (오차 %.4f m, 상태=%s)"
		% [back, _player.call("state_name")])

	# 가지 시험 준비: 가지 윗면에 올려놓는다
	var c := _branch_ab.get_center()
	_player.call("release_cling")
	_player.global_position = Vector3(c.x, _branch_ab.end.y + _player.call("body_radius"), c.z)
	_player.velocity = Vector3.ZERO
	_branch_t = 0.0
	_branch_contacts = 0
	_go(Stage.BRANCH)
	return false


# --- ② 가지 위에서는 게임오버가 아니다 ---------------------------------------
func _stand_on_branch(delta: float) -> bool:
	_branch_t += delta
	_branch_contacts += _player.get_slide_collision_count()

	if bool(_world.call("is_game_over")):
		var st: int = _player.get("state")
		_bad("가지(%s) 위에 있는데 게임오버가 됐다 — 레이어 구분(TERRAIN/TREE)이 동작하지 않는다 (y=%.2f, 상태=%s)"
			% [_branch_name, _player.global_position.y, _player.call("state_name")])
		return _finish()

	if _branch_t < BRANCH_HOLD:
		return false

	# 가지에서 미끄러져 지면까지 떨어졌다면 위 판정이 의미가 없다. 구분해서 알린다.
	if _player.global_position.y < _branch_ab.position.y - 1.0:
		_bad("가지(%s) 위에서 %.2f m 아래로 미끄러져 떨어졌다 — 가지 착지 시험이 성립하지 않았다"
			% [_branch_name, _branch_ab.position.y - _player.global_position.y])
	elif _branch_contacts == 0:
		_bad("가지(%s) 위에서 %.1f초 동안 아무것도 접촉하지 않았다 — 공중에 떠 있다"
			% [_branch_name, BRANCH_HOLD])
	else:
		print("[눈매장] 가지 %s 위에서 %.1f초 유지, 접촉 %d회, 게임오버 없음 (y=%.2f)"
			% [_branch_name, BRANCH_HOLD, _branch_contacts, _player.global_position.y])
		print("[측정] 가지 위 대기 %.1f초: 접촉 %d회, 게임오버 없음 (레이어 구분 동작)"
			% [BRANCH_HOLD, _branch_contacts])
	return _finish()


# --- 도구 -------------------------------------------------------------------
## 시작 나무에서 가장 굵은 가지의 월드 AABB 를 고른다.
func _pick_branch() -> bool:
	var area := current_scene.get_node_or_null("Area")
	if area == null:
		return false
	var want: String = String(current_scene.get("start_trunk_name")).replace("기둥_", "가지_")
	var best := -1.0
	var stack: Array[Node] = [area]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		if node is MeshInstance3D and String(node.name).begins_with(want):
			var m := node as MeshInstance3D
			var ab := m.global_transform * m.get_aabb()
			var thick := minf(ab.size.y, minf(ab.size.x, ab.size.z))
			if thick > best:
				best = thick
				_branch_ab = ab
				_branch_name = String(m.name)
		for c in node.get_children():
			stack.append(c)
	return best > 0.0


## 나무에서 떨어진 눈 지면 위의 한 점. 지형(레이어 2)에만 걸리는 곳을 고른다.
func _snow_spot() -> Vector3:
	var space := _player.get_world_3d().direct_space_state
	var c := _branch_ab.get_center()
	# 가지 끝보다 더 바깥으로 나가 기둥·가지가 없는 곳을 찾는다
	var span := maxf(_branch_ab.size.x, _branch_ab.size.z)
	for step in range(1, 8):
		var at := Vector3(c.x + span * step, 0.0, c.z + span * step)
		var top := _branch_ab.end.y + PROBE_LIFT
		var q := PhysicsRayQueryParameters3D.create(
			Vector3(at.x, top, at.z), Vector3(at.x, top - PROBE_RANGE, at.z))
		q.collision_mask = Layers.SOLID
		q.exclude = [_player.get_rid()]
		var hit := space.intersect_ray(q)
		if hit.is_empty():
			continue
		if (hit.collider as Node).name.begins_with("지면"):
			var p: Vector3 = hit.position
			_snow_found = true
			return p
	# 못 찾았으면 좌표를 지어내지 않는다. 예전에는 y=0 을 예비값으로 썼는데, 그건
	# 옛 축척에서만 눈 위였고 지금은 지면과 무관한 숫자다. 호출부가 실패로 처리한다.
	return Vector3.ZERO


func _finish() -> bool:
	_go(Stage.DONE)
	Input.action_release("restart")
	print("[눈매장] 판정=%s (실패 %d건)" % ["통과" if _fail == 0 else "실패", _fail])
	quit(0 if _fail == 0 else 1)
	return true
