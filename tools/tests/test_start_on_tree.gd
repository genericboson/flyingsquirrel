extends SceneTree
## 회귀 테스트 — 게임 시작 시 소나무 기둥에 붙어 있는가 (요구사항 I4).
##
##   godot --headless --path . --script res://tools/tests/test_start_on_tree.gd
##   종료 코드 0 = 통과, 1 = 실패
##
## 기획서 원문: 「주인공 하늘다람쥐가 눈덮인 소나무 하나에 매달려있는 것을 …」
##
## ★ 기대값을 상수로 박지 않는다. 나무는 곧 훨씬 커진다(배율 미정).
##   높이는 「기둥 높이의 몇 %」, 표면까지의 거리는 「몸 반지름의 몇 배」로 따진다.
##   나무 크기가 바뀌어도 안 깨지고, 부착 기능이 죽을 때만 깨져야 한다.
##
## 보는 것 네 가지:
##   ① 시작 상태가 CLING 인가
##   ② 지면보다 충분히 높은가 — 씬에서 잰 기둥 높이의 50% 이상
##   ③ 기둥 표면에서 몸 반지름만큼 떨어져 있는가 (파묻히지도 떠 있지도 않다)
##   ④ 인트로가 끝나도 미끄러져 떨어지지 않는가

const PlayerScript = preload("res://scripts/characters/player.gd")
const Layers = preload("res://scripts/physics_layers.gd")

## 기둥 표면까지의 거리가 몸 반지름의 이 범위 안이어야 한다
const CLEAR_MIN_RATIO := 0.5
const CLEAR_MAX_RATIO := 2.0
## 부착 높이가 최소한 기둥 높이의 이 비율보다는 위여야 한다
const MIN_HEIGHT_RATIO := 0.5
## 인트로 동안 이만큼 넘게 움직였으면 미끄러진 것이다 (m)
const DRIFT_TOL := 0.01
## 자세 판정: 등/머리 방향의 내적이 이보다 커야 한다
const AXIS_DOT := 0.98

var _t := 0.0
var _frames := 0
var _fail := 0
var _stage := 0
var _wait_until := 0.0

var _player: CharacterBody3D
var _trunk: MeshInstance3D
var _trunk_ab := AABB()
var _start_pos := Vector3.ZERO


func _initialize() -> void:
	change_scene_to_file("res://scenes/World.tscn")


func _bad(msg: String) -> void:
	_fail += 1
	print("[시작부착] X %s" % msg)


func _process(delta: float) -> bool:
	_t += delta
	_frames += 1
	if current_scene == null or _frames < 8:
		return false

	match _stage:
		0:
			return _check_pose()
		1:
			if _t < _wait_until:
				return false
			return _check_still_attached()
	return true


# --- ①②③ 시작 자세 ----------------------------------------------------------
func _check_pose() -> bool:
	_player = current_scene.get_node_or_null("Player") as CharacterBody3D
	if _player == null:
		_bad("Player 노드가 없다")
		return _finish()

	_trunk = _find_trunk()
	if _trunk == null:
		_bad("기둥 메시를 찾지 못했다 (모델러와의 이름 계약 '기둥_' 확인 필요)")
		return _finish()
	_trunk_ab = _trunk.global_transform * _trunk.get_aabb()

	var st: int = _player.get("state")
	if st != PlayerScript.State.CLING:
		_bad("시작 상태가 CLING 이 아니다 (state=%d, %s)" % [st, _player.call("state_name")])

	# ② 높이 — 절대값이 아니라 씬에서 잰 기둥 높이의 비율로 본다
	var base_y := _trunk_ab.position.y
	var span := _trunk_ab.size.y
	var ratio := (_player.global_position.y - base_y) / maxf(span, 0.001)
	if ratio < MIN_HEIGHT_RATIO:
		_bad("부착 높이가 기둥 높이의 %.0f%% 밖에 안 된다 (최소 %.0f%%, 기둥 밑동 y=%.2f 높이 %.2f)"
			% [ratio * 100.0, MIN_HEIGHT_RATIO * 100.0, base_y, span])

	# 지면보다 실제로 높은지도 확인한다 (기둥이 지면에 묻혀 있는 경우 대비)
	var need := span * MIN_HEIGHT_RATIO
	var ground := _ground_below(_player.global_position)
	if ground == -INF:
		# 레이 사거리 안에 지면이 없었다. 사거리가 요구 높이보다 길었다면 "그보다 더 높다"는
		# 뜻이라 통과지만, 사거리 자체가 요구 높이에 못 미치면 아무것도 증명하지 못한다.
		# 여기를 조용히 넘기면 월드 축척이 바뀌어 레이가 짧아졌을 때 이 검사가 빈 껍데기가 된다.
		if PlayerScript.GROUND_PROBE_RANGE < need:
			_bad("지면 탐색 레이 사거리 %.1f m 가 요구 높이 %.1f m 에 못 미쳐 높이를 확인할 수 없다"
				% [PlayerScript.GROUND_PROBE_RANGE, need])
	elif _player.global_position.y - ground < need:
		_bad("지면(y=%.2f)에서 %.2f m 밖에 안 떨어졌다 (기둥 높이 %.2f 의 %.0f%% 이상이어야 한다)"
			% [ground, _player.global_position.y - ground, span, MIN_HEIGHT_RATIO * 100.0])

	# ③ 기둥 표면까지의 거리 — 몸 반지름 기준
	var radius: float = float(_player.call("body_radius"))
	var gap := _gap_to_trunk()
	if gap < 0.0:
		_bad("플레이어에서 기둥 축 쪽으로 쏜 레이가 기둥을 맞히지 못했다 — 기둥에 붙어 있지 않다")
	else:
		if gap < radius * CLEAR_MIN_RATIO:
			_bad("기둥에 %.3f m 까지 파고들었다 (몸 반지름 %.3f 의 %.0f%% 이상 떨어져야 한다)"
				% [gap, radius, CLEAR_MIN_RATIO * 100.0])
		if gap > radius * CLEAR_MAX_RATIO:
			_bad("기둥에서 %.3f m 나 떠 있다 (몸 반지름 %.3f 의 %.0f%% 이내여야 한다)"
				% [gap, radius, CLEAR_MAX_RATIO * 100.0])

	# 자세: 등(basis 의 +Y)이 기둥 바깥, 앞(+Z)이 월드 위쪽
	var n: Vector3 = _player.call("cling_normal")
	var back := _player.global_transform.basis.y
	var head := _player.global_transform.basis.z
	if n.length_squared() > 0.5 and back.dot(n) < AXIS_DOT:
		_bad("등(+Y)이 기둥 바깥쪽을 보지 않는다 (내적 %.3f) — 배가 기둥을 향하지 않는다" % back.dot(n))
	if head.dot(Vector3.UP) < AXIS_DOT:
		_bad("머리(+Z)가 위를 향하지 않는다 (내적 %.3f)" % head.dot(Vector3.UP))

	print("[시작부착] 기둥 %s 밑동 y=%.2f 높이 %.2f / 플레이어 y=%.2f (비율 %.2f) / 표면까지 %.3f m (몸 반지름 %.3f)"
		% [_trunk.name, base_y, span, _player.global_position.y, ratio, gap, radius])
	print("[측정] 시작 부착: 기둥 높이의 %.0f%% 지점, 표면에서 몸 반지름의 %.2f배 떨어짐, 상태=%s"
		% [ratio * 100.0, gap / maxf(radius, 0.001), _player.call("state_name")])

	# ④ 인트로가 끝나고도 붙어 있는지 본다
	_start_pos = _player.global_position
	var rig := current_scene.get_node_or_null("CameraRig")
	var intro: float = float(rig.get("intro_duration")) if rig != null else 4.0
	_wait_until = _t + intro + 0.6
	_stage = 1
	return false


# --- ④ 인트로가 지나도 붙어 있는가 -------------------------------------------
func _check_still_attached() -> bool:
	var st: int = _player.get("state")
	var drift := _player.global_position.distance_to(_start_pos)
	if st != PlayerScript.State.CLING:
		_bad("인트로(%.1f초)가 지나자 부착이 풀렸다 (상태=%s) — 중력을 받고 있다"
			% [_wait_until, _player.call("state_name")])
	if drift > DRIFT_TOL:
		_bad("붙어 있는 동안 %.3f m 움직였다 (허용 %.3f) — 미끄러지고 있다" % [drift, DRIFT_TOL])
	print("[시작부착] 인트로 뒤 t=%.2f: 상태=%s, 이동 %.4f m" % [_t, _player.call("state_name"), drift])
	return _finish()


# --- 도구 -------------------------------------------------------------------
## 시작 기둥 메시. world.gd 와 같은 규칙(H-계약)으로 찾는다.
func _find_trunk() -> MeshInstance3D:
	var area := current_scene.get_node_or_null("Area")
	if area == null:
		return null
	var want: String = String(current_scene.get("start_trunk_name"))
	var exact: MeshInstance3D = null
	var any: MeshInstance3D = null
	var stack: Array[Node] = [area]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		if node is MeshInstance3D:
			var n := String(node.name)
			if not want.is_empty() and n.begins_with(want):
				exact = node as MeshInstance3D
			elif n.begins_with("기둥_") and any == null:
				any = node as MeshInstance3D
		for c in node.get_children():
			stack.append(c)
	return exact if exact != null else any


## 플레이어에서 기둥 중심축 쪽으로 쏜 레이가 만나는 기둥 표면까지의 거리.
## 못 맞히면 -1.
func _gap_to_trunk() -> float:
	var space := _player.get_world_3d().direct_space_state
	var from := _player.global_position
	var axis := Vector3(_trunk_ab.get_center().x, from.y, _trunk_ab.get_center().z)
	if from.distance_squared_to(axis) < 0.000001:
		return -1.0
	var q := PhysicsRayQueryParameters3D.create(from, axis)
	q.collision_mask = Layers.TREE
	q.exclude = [_player.get_rid()]
	var hit := space.intersect_ray(q)
	if hit.is_empty():
		return -1.0
	if not String((hit.collider as Node).name).begins_with("기둥_"):
		return -1.0
	return from.distance_to(hit.position)


## 사거리는 player.gd 의 지면 탐색 레이와 같은 값을 쓴다 (현재 967.4 m).
## 여기 숫자를 따로 박으면 월드 축척이 바뀔 때 조용히 짧아진다 — 시작 지점에서
## 지면까지가 이미 213 m 라 옛 값 200 m 는 지면 기복(±29 m) 하나로 빗나갈 수 있었다.
func _ground_below(from: Vector3) -> float:
	var space := _player.get_world_3d().direct_space_state
	var q := PhysicsRayQueryParameters3D.create(
		from, from + Vector3.DOWN * PlayerScript.GROUND_PROBE_RANGE)
	q.collision_mask = Layers.TERRAIN
	q.exclude = [_player.get_rid()]
	var hit := space.intersect_ray(q)
	if hit.is_empty():
		return -INF
	var p: Vector3 = hit.position
	return p.y


func _finish() -> bool:
	print("[시작부착] 판정=%s (실패 %d건)" % ["통과" if _fail == 0 else "실패", _fail])
	quit(0 if _fail == 0 else 1)
	return true
