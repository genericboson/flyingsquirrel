extends CanvasLayer
## 화면 UI — 좌하단 조작 안내와 게임오버 표시.
##
## 사용자가 「키보드 키 매핑이 직관적이지 않다」고 한 것에 대한 가장 직접적인 대응이다.
## 지금 무엇을 누를 수 있는지를 상태에 맞춰 그때그때 보여준다.
##   F1  안내 켜기·끄기 (기본 켜짐)
##
## 그래픽 에셋을 쓰지 않는다. 패널은 StyleBoxFlat, 글꼴은 OS 글꼴(SystemFont)이다.
## 이미지가 필요해지면 픽셀 아티스트에게 맡길 일이므로 여기서 만들지 않는다.
##
## ★ 글꼴 주의: Godot 내장 기본 글꼴에는 **한글 글리프가 없다.** 그대로 두면
##   안내문이 빈칸으로 나온다. 그래서 OS 에 설치된 한글 글꼴을 이름으로 찾아 쓴다.

const PlayerScript = preload("res://scripts/characters/player.gd")

## OS 글꼴 후보. 앞에서부터 있는 것을 쓴다 (윈도우/맥/리눅스 순).
## (PackedStringArray(...) 는 상수식이 아니라 const 에 못 넣는다. 쓸 때 변환한다.)
const FONT_NAMES := [
	"Malgun Gothic", "맑은 고딕", "NanumGothic", "Noto Sans CJK KR",
	"Noto Sans KR", "AppleSDGothicNeo", "Gulim", "sans-serif",
]

var _root: Control
var _help_panel: PanelContainer
var _help_label: Label
var _over_panel: PanelContainer
var _player: CharacterBody3D
var _help_visible := true
var _game_over := false


func _ready() -> void:
	layer = 10
	_build()


func bind_player(player: CharacterBody3D) -> void:
	_player = player


# --- 화면 구성 ---------------------------------------------------------------
func _build() -> void:
	var font := SystemFont.new()
	font.font_names = PackedStringArray(FONT_NAMES)

	var theme := Theme.new()
	theme.default_font = font
	theme.default_font_size = 16

	_root = Control.new()
	_root.name = "Root"
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.theme = theme
	add_child(_root)

	# --- 좌하단 조작 안내 ---
	_help_panel = _make_panel(Color(0.03, 0.06, 0.11, 0.55))
	_help_panel.name = "조작안내"
	# 좌하단에 붙이고 내용 크기만큼만 차지하게 한다 (글이 길어지면 위로 자란다)
	_help_panel.set_anchors_and_offsets_preset(
		Control.PRESET_BOTTOM_LEFT, Control.PRESET_MODE_MINSIZE, 16)
	_help_panel.grow_horizontal = Control.GROW_DIRECTION_END
	_help_panel.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_root.add_child(_help_panel)

	_help_label = Label.new()
	_help_label.name = "안내문"
	_help_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_help_label.add_theme_color_override("font_color", Color(0.93, 0.96, 1.0))
	_help_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8))
	_help_label.add_theme_constant_override("outline_size", 3)
	_help_panel.add_child(_help_label)

	# --- 가운데 게임오버 ---
	var center := CenterContainer.new()
	center.name = "게임오버층"
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(center)

	_over_panel = _make_panel(Color(0.05, 0.08, 0.14, 0.72))
	_over_panel.name = "게임오버"
	_over_panel.visible = false
	center.add_child(_over_panel)

	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	_over_panel.add_child(box)

	var title := Label.new()
	title.text = "눈에 파묻혔다"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 34)
	title.add_theme_color_override("font_color", Color(0.98, 0.99, 1.0))
	box.add_child(title)

	var sub := Label.new()
	sub.text = "R : 다시 시작"
	sub.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	sub.add_theme_font_size_override("font_size", 20)
	sub.add_theme_color_override("font_color", Color(0.78, 0.87, 0.98))
	box.add_child(sub)

	_refresh()


func _make_panel(bg: Color) -> PanelContainer:
	var sb := StyleBoxFlat.new()
	sb.bg_color = bg
	sb.set_corner_radius_all(8)
	sb.set_content_margin_all(14)
	sb.border_color = Color(1, 1, 1, 0.14)
	sb.set_border_width_all(1)
	var p := PanelContainer.new()
	p.add_theme_stylebox_override("panel", sb)
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return p


# --- 갱신 -------------------------------------------------------------------
func _process(_delta: float) -> void:
	_refresh()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_toggle_help"):
		_help_visible = not _help_visible
		_refresh()
		get_viewport().set_input_as_handled()


## 게임오버 표시를 켜고 끈다 (world.gd 가 부른다).
func set_game_over(on: bool) -> void:
	_game_over = on
	_refresh()


func _refresh() -> void:
	if _help_panel == null:
		return
	_help_panel.visible = _help_visible
	if _over_panel != null:
		_over_panel.visible = _game_over
	if _help_visible:
		_help_label.text = _hint_text()


## 지금 상태에서 쓸 수 있는 조작만 보여준다.
func _hint_text() -> String:
	var lines: Array[String] = []

	if _game_over:
		lines.append("R : 다시 시작")
	elif _player == null:
		lines.append("Space : 점프")
	else:
		var st: int = _player.get("state")
		match st:
			PlayerScript.State.CLING:
				lines.append("Space : 나무에서 뛰어내리기")
			PlayerScript.State.GLIDE:
				lines.append("Space : 활공 끄기")
				lines.append("WASD : 활공 방향 틀기")
			PlayerScript.State.BURIED:
				lines.append("눈에 파묻히는 중…")
			PlayerScript.State.GROUND:
				lines.append("Space : 점프")
				lines.append("WASD : 이동   Shift : 달리기")
			_:
				if bool(_player.call("glide_armed")):
					lines.append("Space : 활공 끄기   (하강하면 펼쳐진다)")
				else:
					lines.append("Space : 활공 켜기")

	lines.append("마우스 : 시점   C : 시점 리셋   F1 : 안내 끄기")
	return "\n".join(lines)
