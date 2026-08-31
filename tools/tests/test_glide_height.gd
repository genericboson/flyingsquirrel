extends SceneTree
## 회귀 테스트 — 활공 진입 높이 판정이 나뭇가지에 걸리지 않는가.
##
##   godot --headless --path . --script res://tools/tests/test_glide_height.gd
##   종료 코드 0 = 통과, 1 = 실패
##
## 왜 이 테스트가 있는가 (scripts/physics_layers.gd 참조):
##   소나무 숲에서는 플레이어 바로 아래를 나뭇가지가 지나간다. "지면까지의 높이"를
##   재는 레이가 그 가지를 지면으로 착각하면 활공 진입 판정(glide_min_height)이
##   막혀 핵심 기능이 죽는다. 레이어 분리(지형 2 / 나무 3)가 그걸 막는 유일한 장치라,
##   레이어가 어긋나는 순간 조용히 게임이 망가진다. 그래서 기계로 지킨다.
##
## 인공 상자가 아니라 **실제 숲 씬(scenes/World.tscn)** 을 띄워서 검사한다.
## 표본 지점은 좌표를 박아 넣지 않고 실제 가지 메시의 AABB 에서 뽑아내므로
## 모델러가 숲 배치를 바꿔도 그대로 유효하다.

const Layers = preload("res://scripts/physics_layers.gd")
const PlayerScript = preload("res://scripts/characters/player.gd")

## 가지 윗면에서 이만큼 위에 서서 잰다 (가지가 바로 발밑에 있는 상황).
## 다람쥐 몸에 딸린 값이라 월드 축척을 곱하지 않는다.
const ABOVE_BRANCH := 0.5
## 대조용 레이의 길이. **검사 대상과 같은 사거리를 써야 한다.**
## 숫자를 따로 박아 두면 월드 축척이 바뀔 때 여기만 옛 값으로 남아, 게임은 멀쩡한데
## 테스트만 "지면이 없다" 고 하는 거짓 실패가 난다 (N=16 재축척 때 50 m 가 남아 5건 실패).
## 그래서 player.gd 의 상수를 그대로 읽는다 — 현재 967.4 m.
const RAY_LEN := PlayerScript.GROUND_PROBE_RANGE
## 지면까지의 거리와 가지까지의 거리가 최소 이만큼은 벌어져야 "가지를 무시했다"고 본다.
## 표본이 의미 있는지 보는 하한일 뿐이라 축척과 무관하다 (실제 간격은 지금 100 m 이상).
const MIN_SEPARATION := 1.0

var _frames := 0
var _fail := 0
var _checked := 0
var _min_ground := INF
var _max_ground := 0.0


func _initialize() -> void:
	change_scene_to_file("res://scenes/World.tscn")


func _process(_delta: float) -> bool:
	# 충돌체 생성과 물리 서버 반영에 몇 프레임 준다
	_frames += 1
	if current_scene == null or _frames < 6:
		return false

	_check_name_contract()
	_check_forest()

	if _checked > 0:
		print("[측정] 활공 높이 판정: 표본 %d개, 발밑 가지를 무시하고 지면까지 %.2f~%.2f m 로 읽음"
			% [_checked, _min_ground, _max_ground])
	print("[활공높이] 판정=%s (표본 %d개, 실패 %d건)"
		% ["통과" if _fail == 0 else "실패", _checked, _fail])
	quit(0 if _fail == 0 else 1)
	return true


func _bad(msg: String) -> void:
	_fail += 1
	print("[활공높이] X %s" % msg)


# --- 1) 모델러와의 명명 계약 -------------------------------------------------
## 이름 접두사 -> 레이어 매핑. 계약이 깨지면 숲 전체가 잘못된 층으로 간다.
func _check_name_contract() -> void:
	var cases := {
		"기둥_main": Layers.TREE,      # 단일 나무 파일
		"기둥_07": Layers.TREE,        # 숲 파일
		"가지_01": Layers.TREE,
		"가지_07_03": Layers.TREE,
		"지면_눈": Layers.TERRAIN,
	}
	for n in cases:
		var got := Layers.layer_for_name(n)
		var want: int = cases[n]
		if got != want:
			_bad("이름 '%s' -> 레이어 %d (기대 %d)" % [n, got, want])
	print("[활공높이] 이름 계약 %d건 확인" % cases.size())


# --- 2) 실제 숲에서의 높이 판정 ----------------------------------------------
func _check_forest() -> void:
	var area := current_scene.get_node_or_null("Area")
	if area == null:
		_bad("숲 노드 'Area' 가 없다 — 지역 에셋이 안 실렸다")
		return

	var player := current_scene.get_node_or_null("Player") as CharacterBody3D
	if player == null:
		_bad("Player 노드가 없다")
		return
	# 물리에 흘러가지 않도록 멈춘 뒤 표본 지점으로 순간이동시킨다
	player.set_physics_process(false)

	var branches := _lowest_branch_per_tree(area)
	if branches.is_empty():
		_bad("가지 메시를 하나도 찾지 못했다 (이름 계약 '가지_' 확인 필요)")
		return
	print("[활공높이] 나무 %d그루의 최하단 가지를 표본으로 쓴다" % branches.size())

	var min_h: float = player.get("glide_min_height")
	for tree_id in branches:
		var ab: AABB = branches[tree_id]
		var c := ab.get_center()
		_sample(player, Vector3(c.x, ab.end.y + ABOVE_BRANCH, c.z), tree_id, min_h)


## 나무 번호별로 가장 낮은 가지의 월드 AABB. (`가지_NN_MM` 에서 NN 을 뽑는다)
func _lowest_branch_per_tree(area: Node) -> Dictionary:
	var out := {}
	var stack: Array[Node] = [area]
	while not stack.is_empty():
		var n: Node = stack.pop_back()
		if n is MeshInstance3D and n.name.begins_with("가지_"):
			var m := n as MeshInstance3D
			var ab := m.global_transform * m.get_aabb()
			var parts := String(m.name).split("_")
			var key: String = parts[1] if parts.size() > 1 else "?"
			if not out.has(key) or ab.position.y < (out[key] as AABB).position.y:
				out[key] = ab
		for c in n.get_children():
			stack.append(c)
		# 사전순 출력이 되도록 정렬 키를 유지한다
	var sorted := {}
	var keys := out.keys()
	keys.sort()
	for k in keys:
		sorted[k] = out[k]
	return sorted


## 한 표본 지점에서 세 가지를 본다.
##   ① SOLID(지형+나무) 레이는 발밑 가지를 맞혀야 한다   — 표본이 실제로 가지 위인지 확인
##   ② _height_above_ground() 는 그보다 훨씬 멀어야 한다  — 가지를 무시했다는 증거
##   ③ 그 레이가 맞힌 것이 정말 '지면_눈' 이어야 한다     — 딴 걸 지면으로 착각하지 않았다
func _sample(player: CharacterBody3D, at: Vector3, tag: String, min_h: float) -> void:
	_checked += 1
	player.global_position = at

	var space := player.get_world_3d().direct_space_state

	var qs := PhysicsRayQueryParameters3D.create(at, at + Vector3.DOWN * RAY_LEN)
	qs.collision_mask = Layers.SOLID
	qs.exclude = [player.get_rid()]
	var hs := space.intersect_ray(qs)

	var qt := PhysicsRayQueryParameters3D.create(at, at + Vector3.DOWN * RAY_LEN)
	qt.collision_mask = Layers.TERRAIN
	qt.exclude = [player.get_rid()]
	var ht := space.intersect_ray(qt)

	var h: float = player.call("_height_above_ground")

	if hs.is_empty():
		_bad("나무%s (%.1f,%.1f,%.1f): 발밑에 아무 충돌체도 없다 — 표본이 가지 위가 아니다"
			% [tag, at.x, at.y, at.z])
		return
	var d_solid: float = at.distance_to(hs.position)
	var solid_name := String((hs.collider as Node).name)
	if not solid_name.begins_with("가지_"):
		_bad("나무%s: 발밑 첫 충돌체가 '%s' 다 (가지_ 로 시작해야 한다)" % [tag, solid_name])
		return

	if ht.is_empty():
		_bad("나무%s: 지형 레이가 아무것도 못 맞혔다 — 눈 지면이 발밑에 없다" % tag)
		return
	var ground_name := String((ht.collider as Node).name)
	if not ground_name.begins_with("지면"):
		_bad("나무%s: 지형 레이가 '%s' 를 맞혔다 (지면_ 로 시작해야 한다)" % [tag, ground_name])

	var d_ground: float = at.distance_to(ht.position)
	_min_ground = minf(_min_ground, d_ground)
	_max_ground = maxf(_max_ground, d_ground)

	# 본론: 활공 높이가 가지가 아니라 지면을 봤는가
	if absf(h - d_ground) > 0.01:
		_bad("나무%s: _height_above_ground()=%.2f 인데 지면까지는 %.2f 다" % [tag, h, d_ground])
	if d_ground - d_solid < MIN_SEPARATION:
		_bad("나무%s: 가지(%.2f)와 지면(%.2f)이 너무 가까워 표본이 의미 없다"
			% [tag, d_solid, d_ground])
	if h <= min_h:
		_bad("나무%s: 높이 %.2f 로는 활공 진입 불가 (필요 %.2f)" % [tag, h, min_h])

	print("[활공높이] 나무%s 표본(%.1f,%.1f,%.1f): 가지까지 %.2fm / 지면까지 %.2fm / 판정높이 %.2fm -> 활공 %s"
		% [tag, at.x, at.y, at.z, d_solid, d_ground, h, "가능" if h > min_h else "불가"])
