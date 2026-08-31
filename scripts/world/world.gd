extends Node3D
## 월드 루트. 환경을 세우고, 블렌더에서 만든 지역 에셋을 불러오고,
## 플레이어와 카메라를 배치한다.
##
## 3D 형상은 전부 블렌더 산출물(.glb)에서 온다. 이 스크립트는 조명·안개·
## 배치·충돌 생성만 담당한다.
##
## 검증용 자동 스크린샷:
##   godot --path . -- --shot 결과.png --after 2.0

const InputActions = preload("res://scripts/input_actions.gd")
const ThirdPersonCamera = preload("res://scripts/camera/third_person_camera.gd")
const PlayerScript = preload("res://scripts/characters/player.gd")
const HudScript = preload("res://scripts/ui/hud.gd")
const Layers = preload("res://scripts/physics_layers.gd")
const WorldScale = preload("res://scripts/world_scale.gd")

const AREA_PATH := "res://models/area_forest.glb"

## 스폰 지점의 수평 위치. 시작 나무를 찾지 못했을 때만 쓰이는 예비값이다.
@export var spawn_point := Vector3(0, 3, 0)

## 지면을 찾을 때 레이를 쏘기 시작하는 높이 (지역 에셋의 최고점보다 위여야 한다).
## **월드를 훑는 거리라 축척을 곱한다** — 18 m 나무 시절의 60 m 기준 = 1160.8 m.
## 나무 꼭대기(348 m)와 지면 기복(±29 m)을 다 넘어선다.
const SPAWN_PROBE_TOP := 60.0 * WorldScale.FACTOR
## 지면 위로 몸을 띄워 놓을 여유. 캡슐 반지름(0.38)보다 커야 첫 프레임에 파묻히지 않는다.
## **다람쥐 몸에 딸린 값이라 축척을 곱하지 않는다.**
const SPAWN_CLEARANCE := 0.6

@export_group("시작 나무 부착")
## 기획서 I4: 「주인공 하늘다람쥐가 눈덮인 소나무 하나에 매달려있는 것을 …」
##
## ★ 나무 크기에 의존하는 숫자를 여기 적지 않는다. 나무는 곧 훨씬 커진다.
##   붙는 지점은 전부 시작 기둥 메시의 global AABB 에서 **비율**로 계산하고,
##   기둥 표면은 런타임 레이캐스트로 찾는다. 배율이 몇 배가 되든 코드는 그대로다.
##
## 시작 나무를 찾는 이름 (모델러와의 H-계약: 숲은 `기둥_NN`, 단일 나무는 `기둥_main`)
@export var start_trunk_name := "기둥_01"
## 붙는 높이 = 기둥 밑동에서 기둥 전체 높이의 이 비율만큼 위
@export var cling_height_ratio := 0.60
## 붙는 방위(도). 0 = 월드 +Z 쪽 면. 평소 3인칭 카메라가 대상의 +Z 쪽에 서므로
## 이 면에 붙으면 카메라가 다람쥐의 등을 보게 된다.
@export var cling_azimuth_deg := 0.0

## 기둥 표면을 찾을 때 밖에서 안쪽으로 쏘는 레이의 시작 거리 = 기둥 AABB 폭 × 이 배수.
## 절대 거리가 아니라 배수라서 나무가 커져도 그대로 통한다.
const TRUNK_PROBE_SPAN := 2.0
## 기둥을 못 찾았을 때 시도해 볼 높이 비율과 방위(도). 가지가 레이를 가로막는 경우 대비.
const CLING_RATIO_FALLBACK: Array[float] = [0.60, 0.55, 0.65, 0.50, 0.70, 0.45, 0.75]
const CLING_AZIMUTH_FALLBACK: Array[float] = [0.0, 30.0, -30.0, 60.0, -60.0, 120.0, 180.0]

var _player: CharacterBody3D
var _camera: Node3D
var _hud: CanvasLayer

## 시작 부착 지점 {"point": Vector3, "normal": Vector3}. 재시작이 여기로 되돌린다.
var _start_cling := {}
var _game_over := false
## 오프닝 인트로가 도는 동안에는 지면 접촉 판정을 하지 않는다 (안전장치)
var _death_armed := false


func _enter_tree() -> void:
	InputActions.ensure()


func _ready() -> void:
	_build_environment()
	_load_area()
	_spawn_player()
	_spawn_camera()
	_spawn_hud()
	_maybe_auto_shot()


# --- 환경 -------------------------------------------------------------------
## 겨울 설원 환경값 (요구사항 I3 / I9).
##
## 색은 전부 아티스트 팔레트 `assets/palettes/winter_snowfield.png` 의 Godot 수치를
## 그대로 옮긴 것이다. 눈대중으로 바꾸지 말고 팔레트를 고친 뒤 여기로 옮긴다.
## (팔레트 생성기: tools/make_winter_palette.py)
##
## 겨울 설원의 특징 세 가지를 값으로 옮긴 것:
##   1. 눈이 되쏘는 반사광 때문에 하늘의 '아래쪽' 이 어둡지 않고 밝고 푸르다.
##      → ground_bottom/horizon 을 밝은 청회색으로. 이게 그림자를 푸르게 만든다.
##   2. 겨울 해는 낮게 걸리고 색이 차다. → 고도 22도, 빛 색 (0.902,0.941,1.0).
##   3. 안개가 먼 나무를 지우고 **지면 끝(경계)을 가려 준다.**
##      → 아래 FOG_DENSITY 주석 참조.
## 안개 밀도의 단위는 1/m 다. **거리에 반비례하므로 축척으로 곱하지 않고 나눈다.**
## (거리를 S 배 늘리면서 같은 가려짐을 유지하려면 density 를 S 로 나눠야 한다)
const FOG_DENSITY := 0.010 / WorldScale.FACTOR

## 지면(`지면_눈`)은 130 m x 130 m 였고 지금은 그 19.35배인 2515 m 사방이다.
## 그 바깥은 허공이라 경계선이 보이면 안 된다. 카메라가 지역 한가운데 있을 때
## 경계까지는 최대 지면 절반, 인트로 카메라처럼 물러나면 그보다 멀다.
## 지수 안개의 가려짐 = 1 - exp(-density * 거리) 이므로 원래 축척에서
##   0.010 에서 65 m -> 48%,  100 m -> 63%,  130 m -> 73%
## 이었고, density 를 S 로 나눈 지금은 65 m x S = 1258 m 에서 똑같이 48% 다.
## 즉 **화면에 보이는 안개의 짙기는 재축척 전후로 같다.**
## (원래 값 0.006 은 100 m 에서 45% 라 지면 끝이 선으로 보였다 — 스크린샷으로 확인)
func _build_environment() -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.169, 0.361, 0.659)        ## 하늘 위쪽 #2B5CA8
	sky_mat.sky_horizon_color = Color(0.800, 0.859, 0.902)    ## 하늘 지평선 #CCDBE6
	sky_mat.ground_horizon_color = Color(0.859, 0.890, 0.922) ## 설원 반사 #DBE3EB
	sky_mat.ground_bottom_color = Color(0.659, 0.722, 0.820)  ## 눈이 되쏘는 푸른 반사광 #A8B8D1
	sky_mat.sun_angle_max = 12.0

	var sky := Sky.new()
	sky.sky_material = sky_mat

	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_sky_contribution = 0.75
	# 하늘 기여분(0.75) 이 아닌 나머지 0.25 에 쓰이는 색. 그늘을 푸른 쪽으로 끌어 준다.
	env.ambient_light_color = Color(0.580, 0.678, 0.859)      ## 주변광 #94ADDB
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.ssao_enabled = true
	env.fog_enabled = true
	env.fog_light_color = Color(0.780, 0.839, 0.902)          ## 안개 #C7D6E6
	env.fog_density = FOG_DENSITY
	env.fog_sky_affect = 0.25

	var we := WorldEnvironment.new()
	we.name = "WorldEnvironment"
	we.environment = env
	add_child(we)

	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	# 겨울 해는 낮게 뜬다. 고도 22도(원래 48도)라 그림자가 길게 눕고 눈 표면이
	# 스치는 빛을 받아 기복이 드러난다.
	sun.rotation = Vector3(deg_to_rad(-22), deg_to_rad(-42), 0)
	sun.light_energy = 1.05
	sun.light_color = Color(0.902, 0.941, 1.000)              ## 낮은 겨울 해, 차갑게 #E6F0FF
	sun.shadow_enabled = true
	# **월드를 훑는 거리라 축척을 곱한다** — 18 m 나무 시절의 120 m 기준 = 2321.7 m.
	# 곱하지 않으면 120 m 밖(= 348 m 나무의 몸통 대부분과 옆 나무 전부)이 그림자를
	# 잃고 평평하게 보인다. 대신 같은 그림자 아틀라스로 19배 넓은 범위를 덮으므로
	# 가까운 그림자의 해상도는 그만큼 떨어진다 (품질 조정은 아트 판단 영역).
	sun.directional_shadow_max_distance = 120.0 * WorldScale.FACTOR
	add_child(sun)


# --- 지역 에셋 ---------------------------------------------------------------
func _load_area() -> void:
	if not ResourceLoader.exists(AREA_PATH):
		push_warning("[월드] 지역 에셋이 없습니다: %s — 임시 바닥으로 대체합니다." % AREA_PATH)
		_add_placeholder_ground()
		return

	var packed: PackedScene = load(AREA_PATH)
	var area := packed.instantiate()
	area.name = "Area"
	add_child(area)
	_generate_collision(area)


## 임시 바닥. 형상이 없는 무한 평면 충돌체라 '모델'이 아니며,
## 블렌더 지형이 들어오면 이 분기는 타지 않는다.
func _add_placeholder_ground() -> void:
	var body := StaticBody3D.new()
	body.name = "임시바닥"
	body.collision_layer = Layers.TERRAIN
	body.collision_mask = 0
	var shape := CollisionShape3D.new()
	shape.shape = WorldBoundaryShape3D.new()
	body.add_child(shape)
	add_child(body)


## 불러온 지역 메시에 충돌을 붙인다.
## 블렌더에서 이름이 "노충돌" 로 시작하는 오브젝트는 건너뛴다.
##
## 만들어진 충돌체는 이름 규약에 따라 레이어를 나눈다 (scripts/physics_layers.gd):
##   "기둥_*" / "가지_NN"  -> 레이어 3 (나무)   밟히지만 '지면' 이 아니다
##   그 밖의 메시          -> 레이어 2 (지형)   활공 높이 판정의 대상
func _generate_collision(node: Node) -> void:
	if node is MeshInstance3D and not node.name.begins_with("노충돌"):
		node.create_trimesh_collision()
		_apply_layer(node, Layers.layer_for_name(node.name))
	for child in node.get_children():
		_generate_collision(child)


## create_trimesh_collision() 이 메시 밑에 붙여 준 StaticBody3D 에 레이어를 지정한다.
func _apply_layer(mesh: Node, layer: int) -> void:
	for child in mesh.get_children():
		if child is StaticBody3D:
			child.collision_layer = layer
			child.collision_mask = 0


# --- 배치 -------------------------------------------------------------------
func _spawn_player() -> void:
	_player = CharacterBody3D.new()
	_player.name = "Player"
	_player.set_script(PlayerScript)
	add_child(_player)
	_player.connect("bury_started", _on_bury_started)
	_player.connect("bury_finished", _on_bury_finished)

	_start_cling = _resolve_cling()
	if _start_cling.is_empty():
		# 시작 나무를 못 찾으면(단일 나무 씬 등) 예전처럼 눈 지면 위에 세운다.
		push_warning("[월드] 시작 기둥('%s')을 찾지 못해 지면에서 시작합니다." % start_trunk_name)
		_player.global_position = _resolve_spawn(spawn_point)
	else:
		_apply_start_cling()


## 시작 부착 지점으로 플레이어를 붙인다 (최초 배치와 재시작이 공유).
func _apply_start_cling() -> void:
	var point: Vector3 = _start_cling["point"]
	var normal: Vector3 = _start_cling["normal"]
	_player.call("cling_to", point, normal)


# --- 시작 나무 부착 지점 계산 ------------------------------------------------
## 시작 기둥 메시. 이름이 `start_trunk_name` 으로 시작하는 것을 먼저 찾고,
## 없으면 아무 `기둥_` 이나 쓴다 (단일 나무 파일은 `기둥_main`).
func _find_start_trunk() -> MeshInstance3D:
	var area := get_node_or_null("Area")
	if area == null:
		return null
	var exact: MeshInstance3D = null
	var any: MeshInstance3D = null
	var stack: Array[Node] = [area]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		if node is MeshInstance3D:
			var n := String(node.name)
			if n.begins_with(start_trunk_name):
				exact = node as MeshInstance3D
			elif n.begins_with("기둥_") and any == null:
				any = node as MeshInstance3D
		for c in node.get_children():
			stack.append(c)
	return exact if exact != null else any


## 기둥 표면의 부착 지점과 바깥쪽 법선을 런타임에 구한다.
##
## 좌표·높이·굵기를 상수로 박지 않는다. 전부 기둥 메시의 global AABB 에서 나온다:
##   중심축   = AABB 중심의 xz
##   밑동/높이 = AABB 의 y 범위
##   부착 높이 = 밑동 + 높이 × cling_height_ratio   (비율)
##   표면     = 축 바깥에서 축을 향해 쏜 레이가 기둥을 맞힌 지점 (실측)
## 나무가 몇 배로 커지든 이 함수는 그대로 맞는다.
func _resolve_cling() -> Dictionary:
	var trunk := _find_start_trunk()
	if trunk == null:
		return {}
	var space := get_world_3d().direct_space_state
	if space == null:
		return {}

	var ab := trunk.global_transform * trunk.get_aabb()
	var axis_xz := ab.get_center()
	var base_y := ab.position.y
	var span := ab.size.y
	var reach := maxf(ab.size.x, ab.size.z) * TRUNK_PROBE_SPAN

	# 요청 비율/방위를 맨 앞에 두고, 가지에 가로막히면 예비 후보로 넘어간다
	var ratios: Array[float] = [cling_height_ratio]
	for r in CLING_RATIO_FALLBACK:
		if not ratios.has(r):
			ratios.append(r)
	var azimuths: Array[float] = [cling_azimuth_deg]
	for a in CLING_AZIMUTH_FALLBACK:
		if not azimuths.has(a):
			azimuths.append(a)

	var clearance: float = float(_player.call("body_radius")) * 1.05

	for ratio in ratios:
		var y := base_y + span * ratio
		var axis := Vector3(axis_xz.x, y, axis_xz.z)
		for deg in azimuths:
			var rad := deg_to_rad(deg)
			var outward := Vector3(sin(rad), 0.0, cos(rad))
			var from := axis + outward * reach
			var q := PhysicsRayQueryParameters3D.create(from, axis)
			q.collision_mask = Layers.TREE
			q.exclude = [_player.get_rid()]
			var hit := space.intersect_ray(q)
			if hit.is_empty():
				continue
			var hit_name := String((hit.collider as Node).name)
			if not hit_name.begins_with("기둥_"):
				continue   # 가지를 맞혔다. 다른 각도/높이로 다시 본다
			var surface: Vector3 = hit.position
			var normal := Vector3(outward.x, 0.0, outward.z).normalized()
			print("[진단] 시작 부착: %s 밑동 y=%.2f 높이 %.2f -> 비율 %.2f (y=%.2f), 방위 %.0f도, 표면까지 %.2f m"
				% [hit_name, base_y, span, ratio, y, deg, axis.distance_to(surface)])
			return {"point": surface + normal * clearance, "normal": normal}

	push_warning("[월드] 기둥 표면을 찾지 못했습니다 (후보 %d개 전부 실패)" % [ratios.size() * azimuths.size()])
	return {}


## 스폰 지점의 착지 높이를 지형(레이어 2)으로 쏜 아래 방향 레이로 구한다.
## 블렌더 지면에 기복이 생긴 뒤로 y 를 손으로 박아 두면 공중에 뜨거나 땅에 묻힌다.
##
## 지금은 **예비 경로**다. 기본 시작 위치는 시작 나무의 기둥 표면이고(기획서 I4,
## _resolve_cling 참조), 이 함수는 시작 기둥을 찾지 못했을 때만 쓰인다.
## 지면은 `지면_눈` 하나뿐이므로 대상은 TERRAIN 레이어로 한정한다.
##
## 레이가 아무것도 못 맞히면(지역 에셋이 없거나 지면 밖) 넘겨받은 값을 그대로 쓴다.
func _resolve_spawn(want: Vector3) -> Vector3:
	var space := get_world_3d().direct_space_state
	if space == null:
		return want
	var from := Vector3(want.x, SPAWN_PROBE_TOP, want.z)
	var to := Vector3(want.x, -SPAWN_PROBE_TOP, want.z)
	var q := PhysicsRayQueryParameters3D.create(from, to)
	q.collision_mask = Layers.TERRAIN
	var hit := space.intersect_ray(q)
	if hit.is_empty():
		push_warning("[월드] 스폰 지점 %s 아래에서 지형을 찾지 못했습니다. 지정값을 그대로 씁니다." % want)
		return want
	var ground: Vector3 = hit.position
	print("[진단] 스폰: 지면 y=%.3f -> 시작 y=%.3f" % [ground.y, ground.y + SPAWN_CLEARANCE])
	return Vector3(want.x, ground.y + SPAWN_CLEARANCE, want.z)


func _spawn_camera() -> void:
	_camera = Node3D.new()
	_camera.name = "CameraRig"
	_camera.set_script(ThirdPersonCamera)
	# 대상은 트리에 넣기 **전에** 지정한다. add_child 가 카메라의 _ready 를 돌리는데
	# 그 시점에 target_path 가 비어 있으면 대상이 영영 null 로 남는다(추적·인트로 둘 다 죽는다).
	# 플레이어는 이미 트리에 있으므로 절대 경로를 쓸 수 있다.
	_camera.set("target_path", _player.get_path())
	add_child(_camera)


func _spawn_hud() -> void:
	_hud = CanvasLayer.new()
	_hud.name = "Hud"
	_hud.set_script(HudScript)
	add_child(_hud)
	_hud.call("bind_player", _player)


# --- 눈에 파묻힘 / 게임오버 / 재시작 -----------------------------------------
## 오프닝 인트로가 도는 동안에는 지면 접촉을 게임오버로 치지 않는다.
## 인트로를 스킵해도 곧바로 풀리도록 시간이 아니라 카메라의 인트로 진행 여부를 본다.
func _intro_running() -> bool:
	if _camera == null:
		return false
	return bool(_camera.get("_intro_active"))


func _process(_delta: float) -> void:
	if _player == null:
		return

	if not _death_armed and not _intro_running():
		_death_armed = true
		_player.set("death_enabled", true)

	if _game_over and Input.is_action_just_pressed("restart"):
		restart()


func _on_bury_started() -> void:
	print("[진단] 눈에 파묻힘 시작: %s" % _player.global_position)


func _on_bury_finished() -> void:
	_game_over = true
	if _hud != null:
		_hud.call("set_game_over", true)
	print("[진단] 게임오버 (눈에 파묻힘)")


## 게임오버 상태인가 (검증용)
func is_game_over() -> bool:
	return _game_over


## 다시 시작. 시작 나무의 부착 지점으로 되돌리고 게임오버를 푼다.
##
## ★ PD 결정 — 재시작할 때 오프닝 인트로(4초)는 **다시 돌리지 않는다.**
##   기획서에는 재시작 자체가 없어 PD 가 정한 규칙이다. 매번 4초를 기다리면
##   반복 플레이가 답답해지고, 인트로는 「게임 시작」의 연출이지 리트라이 연출이 아니다.
func restart() -> void:
	_game_over = false
	if _hud != null:
		_hud.call("set_game_over", false)

	if _start_cling.is_empty():
		_player.call("reset_for_respawn")
		_player.global_position = _resolve_spawn(spawn_point)
	else:
		_apply_start_cling()

	_player.set("death_enabled", _death_armed)
	if _camera != null:
		_camera.call("snap_to_target")
	print("[진단] 재시작: %s" % _player.global_position)


# --- 검증용 자동 스크린샷 ---------------------------------------------------
func _maybe_auto_shot() -> void:
	var args := OS.get_cmdline_user_args()
	var path := ""
	var after := 1.5
	for i in args.size():
		if args[i] == "--shot" and i + 1 < args.size():
			path = args[i + 1]
		elif args[i] == "--after" and i + 1 < args.size():
			after = float(args[i + 1])
	if path.is_empty():
		return

	# 자동 촬영 중에는 마우스를 잡지 않는다
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	await get_tree().create_timer(after).timeout
	await RenderingServer.frame_post_draw

	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(path)
	if err == OK:
		print("[진단] 스크린샷 저장: %s (%dx%d)" % [path, img.get_width(), img.get_height()])
		print("[진단] 플레이어 상태=%s 위치=%s" % [_player.call("state_name"), _player.global_position])
		print("[진단] 애니메이션 클립=%s" % [_player.call("animation_names")])
	else:
		printerr("[진단] 스크린샷 실패, 코드 ", err)
	get_tree().quit()
