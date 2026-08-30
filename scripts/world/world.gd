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

const AREA_PATH := "res://models/area_forest.glb"

@export var spawn_point := Vector3(0, 3, 0)

var _player: CharacterBody3D
var _camera: Node3D


func _enter_tree() -> void:
	InputActions.ensure()


func _ready() -> void:
	_build_environment()
	_load_area()
	_spawn_player()
	_spawn_camera()
	_maybe_auto_shot()


# --- 환경 -------------------------------------------------------------------
func _build_environment() -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.29, 0.47, 0.78)
	sky_mat.sky_horizon_color = Color(0.72, 0.82, 0.90)
	sky_mat.ground_bottom_color = Color(0.18, 0.20, 0.18)
	sky_mat.ground_horizon_color = Color(0.62, 0.68, 0.66)
	sky_mat.sun_angle_max = 12.0

	var sky := Sky.new()
	sky.sky_material = sky_mat

	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_sky_contribution = 0.85
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.ssao_enabled = true
	env.fog_enabled = true
	env.fog_light_color = Color(0.72, 0.80, 0.88)
	env.fog_density = 0.006
	env.fog_sky_affect = 0.3

	var we := WorldEnvironment.new()
	we.name = "WorldEnvironment"
	we.environment = env
	add_child(we)

	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	sun.rotation = Vector3(deg_to_rad(-48), deg_to_rad(-42), 0)
	sun.light_energy = 1.15
	sun.light_color = Color(1.0, 0.96, 0.88)
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 120.0
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
	var shape := CollisionShape3D.new()
	shape.shape = WorldBoundaryShape3D.new()
	body.add_child(shape)
	add_child(body)


## 불러온 지역 메시에 충돌을 붙인다.
## 블렌더에서 이름이 "노충돌" 로 시작하는 오브젝트는 건너뛴다.
func _generate_collision(node: Node) -> void:
	if node is MeshInstance3D and not node.name.begins_with("노충돌"):
		node.create_trimesh_collision()
	for child in node.get_children():
		_generate_collision(child)


# --- 배치 -------------------------------------------------------------------
func _spawn_player() -> void:
	_player = CharacterBody3D.new()
	_player.name = "Player"
	_player.set_script(PlayerScript)
	_player.position = spawn_point
	add_child(_player)


func _spawn_camera() -> void:
	_camera = Node3D.new()
	_camera.name = "CameraRig"
	_camera.set_script(ThirdPersonCamera)
	add_child(_camera)
	_camera.set("target_path", _camera.get_path_to(_player))


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
