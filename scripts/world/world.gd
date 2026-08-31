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
const Layers = preload("res://scripts/physics_layers.gd")

const AREA_PATH := "res://models/area_forest.glb"

## 스폰 지점의 수평 위치. 높이(y)는 지형 레이캐스트로 매번 다시 구하므로
## 여기 적힌 y 는 레이가 아무것도 못 맞혔을 때만 쓰이는 예비값이다.
@export var spawn_point := Vector3(0, 3, 0)

## 지면을 찾을 때 레이를 쏘기 시작하는 높이 (지역 에셋의 최고점보다 위)
const SPAWN_PROBE_TOP := 60.0
## 지면 위로 몸을 띄워 놓을 여유. 캡슐 반지름(0.38)보다 커야 첫 프레임에 파묻히지 않는다.
const SPAWN_CLEARANCE := 0.6

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
const FOG_DENSITY := 0.010

## 지면(`지면_눈`)은 130 m x 130 m 라 그 바깥은 허공이다. 카메라가 지역 한가운데
## 있을 때 경계까지는 최대 65 m, 인트로 카메라처럼 가장자리로 물러나면 100 m 를 넘는다.
## 지수 안개의 가려짐 = 1 - exp(-density * 거리) 이므로
##   0.010 에서 65 m -> 48%,  100 m -> 63%,  130 m -> 73%
## 이다. 경계가 하늘색에 충분히 녹아 눈에 띄지 않는 지점이 이 근처다.
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
	_player.position = _resolve_spawn(spawn_point)
	add_child(_player)


## 스폰 지점의 착지 높이를 지형(레이어 2)으로 쏜 아래 방향 레이로 구한다.
## 블렌더 지면에 기복이 생긴 뒤로 y 를 손으로 박아 두면 공중에 뜨거나 땅에 묻힌다.
##
## 지면은 `지면_눈` 하나뿐이므로 대상은 TERRAIN 레이어로 한정한다. 나무(레이어 3)를
## 맞히면 가지 위에서 시작하게 되는데, 시작 상태는 눈 지면이어야 한다(기획서 I4 의
## 나무 매달리기는 H2 가 들어온 뒤의 일이다).
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
