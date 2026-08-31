extends RefCounted
## 조작 키 등록.
##
## 기획서에 조작 항목이 자체가 없어 여기서 정했다 (claudedocs/요구사항.md F1~F8).
##
## Space 의 의미는 상태에 따라 갈린다 (player.gd):
##   지상  점프 · 나무에 붙은 상태  뛰어내리기 · 공중  활공 켜기/끄기(토글)
## project.godot 에 직렬화된 InputEvent 를 손으로 써넣는 대신 코드로 등록한다.
## 키 배치가 한 곳에 모여 있어 읽기 쉽고, 파일 손상 위험이 없다.

const KEYS := {
	"move_forward": [KEY_W, KEY_UP],
	"move_back": [KEY_S, KEY_DOWN],
	"move_left": [KEY_A, KEY_LEFT],
	"move_right": [KEY_D, KEY_RIGHT],
	"jump": [KEY_SPACE],
	"sprint": [KEY_SHIFT],
	"camera_recenter": [KEY_C],
	"ui_release_mouse": [KEY_ESCAPE],
	## 눈에 파묻혀 게임오버가 된 뒤 시작 나무로 되돌아간다 (PD 결정, world.gd 참조)
	"restart": [KEY_R],
	## 좌하단 조작 안내 켜기·끄기
	"ui_toggle_help": [KEY_F1],
}

## 게임패드 (기획서 요구는 아니지만 3인칭 액션에는 사실상 필수)
const PAD_BUTTONS := {
	"jump": [JOY_BUTTON_A],
	"sprint": [JOY_BUTTON_LEFT_STICK],
	"camera_recenter": [JOY_BUTTON_RIGHT_STICK],
	"restart": [JOY_BUTTON_Y, JOY_BUTTON_START],
}

const PAD_AXES := {
	"move_forward": [JOY_AXIS_LEFT_Y, -1.0],
	"move_back": [JOY_AXIS_LEFT_Y, 1.0],
	"move_left": [JOY_AXIS_LEFT_X, -1.0],
	"move_right": [JOY_AXIS_LEFT_X, 1.0],
}


static func ensure() -> void:
	for action in KEYS:
		if not InputMap.has_action(action):
			InputMap.add_action(action, 0.2)
		else:
			InputMap.action_erase_events(action)   # 재실행 시 중복 등록 방지

		for key in KEYS[action]:
			var ev := InputEventKey.new()
			ev.physical_keycode = key
			InputMap.action_add_event(action, ev)

	for action in PAD_BUTTONS:
		for btn in PAD_BUTTONS[action]:
			var ev := InputEventJoypadButton.new()
			ev.button_index = btn
			InputMap.action_add_event(action, ev)

	for action in PAD_AXES:
		var axis: int = PAD_AXES[action][0]
		var value: float = PAD_AXES[action][1]
		var ev := InputEventJoypadMotion.new()
		ev.axis = axis
		ev.axis_value = value
		InputMap.action_add_event(action, ev)
