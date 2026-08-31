extends SceneTree
## 게임오버 연출 스크린샷 도구 (파묻히는 중 / 게임오버 화면).
##
##   godot --path . --resolution 1280x720 --script res://tools/_shotgo.gd
##
## ★ 낙하 지점을 좌표로 박지 않는다. 옛 축척에서 잰 (-38.15, 2.6, 42.36) 이 그대로
##   남아 있었는데, N=16 재축척 뒤 그 자리는 지면에서 수십 m 어긋난 허공이었다.
##   지금은 씬의 눈 지면 메시에서 실측해 고른다.
const Layers = preload("res://scripts/physics_layers.gd")
const PlayerScript = preload("res://scripts/characters/player.gd")

## 지면 위 이만큼에서 떨어뜨린다 (다람쥐 몸에 딸린 값 — 축척과 무관)
const DROP_HEIGHT := 2.0
## 나무를 피해 지면 중심에서 바깥으로 훑어 볼 비율 (지면 반폭 기준)
const SPOT_RATIOS: Array[float] = [0.15, 0.28, 0.41, 0.54, 0.67, 0.80]
const SPOT_ANGLES: Array[float] = [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]

var _f := 0
var _stage := 0
var _world: Node
var _p: CharacterBody3D
var _busy := false

func _initialize() -> void:
	change_scene_to_file("res://scenes/World.tscn")

func _process(_d: float) -> bool:
	_f += 1
	if current_scene == null or _f < 10 or _busy:
		return false
	_world = current_scene
	_p = _world.get_node_or_null("Player") as CharacterBody3D
	match _stage:
		0:
			var ev := InputEventKey.new()
			ev.physical_keycode = KEY_SPACE
			ev.pressed = true
			Input.parse_input_event(ev)
			_stage = 1
		1:
			if not bool(_p.get("death_enabled")):
				return false
			_p.call("release_cling")
			_p.global_position = _snow_spot() + Vector3.UP * DROP_HEIGHT
			_p.velocity = Vector3.ZERO
			print("[진단] 낙하 시작 %s" % _p.global_position)
			_stage = 2
		2:
			if _p.call("state_name") != "파묻힘":
				return false
			_grab("tools/_shots/go_burying.png")
			_stage = 3
		3:
			if not bool(_world.call("is_game_over")):
				return false
			_grab("tools/_shots/go_over.png")
			_stage = 4
		4:
			quit(0)
			return true
	return false


## 나무가 없는 눈 지면 위의 한 점. 지면 메시의 AABB 에서 후보를 뽑아
## 위에서 아래로 쏜 레이의 첫 충돌이 '지면_' 인 곳을 고른다.
func _snow_spot() -> Vector3:
	var ground := _find_ground()
	if ground == null:
		push_warning("[촬영] 지면 메시를 찾지 못해 원점 아래를 쓴다")
		return Vector3.ZERO
	var ab := ground.global_transform * ground.get_aabb()
	var c := ab.get_center()
	var half := minf(ab.size.x, ab.size.z) * 0.5
	var top := ab.end.y + PlayerScript.GROUND_PROBE_RANGE * 0.5
	var space := _p.get_world_3d().direct_space_state
	for r in SPOT_RATIOS:
		for deg in SPOT_ANGLES:
			var rad := deg_to_rad(deg)
			var at := Vector3(c.x + sin(rad) * half * r, top, c.z + cos(rad) * half * r)
			var q := PhysicsRayQueryParameters3D.create(
				at, at + Vector3.DOWN * PlayerScript.GROUND_PROBE_RANGE)
			q.collision_mask = Layers.SOLID
			q.exclude = [_p.get_rid()]
			var hit := space.intersect_ray(q)
			if hit.is_empty():
				continue
			if not String((hit.collider as Node).name).begins_with("지면"):
				continue   # 나무 위다. 다른 지점을 본다
			var p: Vector3 = hit.position
			return p
	push_warning("[촬영] 나무를 피한 눈 지면을 못 찾아 지면 중심을 쓴다")
	return Vector3(c.x, ab.get_center().y, c.z)


func _find_ground() -> MeshInstance3D:
	var area := current_scene.get_node_or_null("Area")
	if area == null:
		return null
	var stack: Array[Node] = [area]
	while not stack.is_empty():
		var n: Node = stack.pop_back()
		if n is MeshInstance3D and String(n.name).begins_with("지면"):
			return n as MeshInstance3D
		for c in n.get_children():
			stack.append(c)
	return null


func _grab(path: String) -> void:
	_busy = true
	await RenderingServer.frame_post_draw
	var img := get_root().get_texture().get_image()
	img.save_png(path)
	print("[진단] 저장 %s" % path)
	_busy = false
