extends Node2D

## Minimal Godot 4 client for CyberTown-Eval.
## The FastAPI service remains authoritative for world state and dialogue.

@export var base_url := "http://127.0.0.1:8000/"
@export var cell_size := 52.0

var world: Dictionary = {}
var selected_npc: Dictionary = {}
var state_request: HTTPRequest
var action_request: HTTPRequest
var title_label: Label
var status_label: Label
var dialogue_label: Label
var dialogue_input: LineEdit
var npc_label: Label

func _ready() -> void:
	_ready_base_url()
	state_request = HTTPRequest.new()
	action_request = HTTPRequest.new()
	add_child(state_request)
	add_child(action_request)
	state_request.request_completed.connect(_on_state_response)
	action_request.request_completed.connect(_on_action_response)
	_build_ui()
	refresh_state()
	queue_redraw()

func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var panel := PanelContainer.new()
	panel.position = Vector2(900, 32)
	panel.size = Vector2(340, 650)
	layer.add_child(panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 12)
	box.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT, Control.PRESET_MODE_MINSIZE, 18)
	panel.add_child(box)
	title_label = Label.new()
	title_label.text = "晨雾镇 · Godot 2D"
	title_label.add_theme_font_size_override("font_size", 26)
	box.add_child(title_label)
	status_label = Label.new()
	status_label.text = "正在连接 CyberTown 后端…"
	box.add_child(status_label)
	npc_label = Label.new()
	npc_label.name = "NpcLabel"
	npc_label.text = "选择一个居民"
	npc_label.add_theme_font_size_override("font_size", 20)
	box.add_child(npc_label)
	dialogue_input = LineEdit.new()
	dialogue_input.placeholder_text = "和附近的 NPC 说点什么…"
	box.add_child(dialogue_input)
	var talk_button := Button.new()
	talk_button.text = "开始对话"
	talk_button.pressed.connect(_talk)
	box.add_child(talk_button)
	dialogue_label = Label.new()
	dialogue_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	dialogue_label.text = ""
	box.add_child(dialogue_label)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		_select_npc_at(get_global_mouse_position())
		return
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	var key := event as InputEventKey
	var dx := 0
	var dy := 0
	if key.keycode in [KEY_W, KEY_UP]: dy = -1
	if key.keycode in [KEY_S, KEY_DOWN]: dy = 1
	if key.keycode in [KEY_A, KEY_LEFT]: dx = -1
	if key.keycode in [KEY_D, KEY_RIGHT]: dx = 1
	if dx != 0 or dy != 0:
		_move(dx, dy)

func _select_npc_at(point: Vector2) -> void:
	for npc in world.get("npcs", []):
		var npc_position := Vector2(32, 32) + Vector2(npc.get("x", 0), npc.get("y", 0)) * cell_size + Vector2(cell_size / 2, cell_size / 2)
		if npc_position.distance_to(point) <= 24.0:
			selected_npc = npc
			npc_label.text = "%s\n%s · 好感度 %s\n%s" % [npc.get("name", "居民"), npc.get("role", "居民"), npc.get("affinity", 0), "；".join(_task_titles(npc.get("tasks", [])))]
			queue_redraw()
			return

func _task_titles(tasks: Array) -> Array[String]:
	var titles: Array[String] = []
	for task in tasks:
		titles.append(("✓ " if task.get("done", false) else "○ ") + str(task.get("title", "任务")))
	return titles

func refresh_state() -> void:
	var error := state_request.request(_url("api/state"))
	if error != OK:
		status_label.text = "连接失败：%s" % error

func _move(dx: int, dy: int) -> void:
	var body := JSON.stringify({"dx": dx, "dy": dy})
	action_request.request(_url("api/move"), ["Content-Type: application/json"], HTTPClient.METHOD_POST, body)

func _talk() -> void:
	if selected_npc.is_empty():
		dialogue_label.text = "请先点击一个 NPC。"
		return
	var message := dialogue_input.text.strip_edges()
	if message.is_empty():
		message = "你好"
	var body := JSON.stringify({"npc_id": selected_npc.get("npc_id", ""), "message": message})
	action_request.request(_url("api/talk"), ["Content-Type: application/json"], HTTPClient.METHOD_POST, body)

func _on_state_response(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code >= 400:
		status_label.text = "后端状态请求失败"
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) == TYPE_DICTIONARY:
		world = parsed.get("state", parsed)
		status_label.text = "memory backend · %s · dialogue · %s" % [parsed.get("memory_backend", {}).get("device", "unknown"), parsed.get("llm_provider", "fallback")]
		queue_redraw()

func _on_action_response(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		dialogue_label.text = "网络请求失败"
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if response_code >= 400:
		dialogue_label.text = str(parsed.get("detail", "请求失败"))
		return
	if typeof(parsed) == TYPE_DICTIONARY:
		if parsed.has("reply"):
			dialogue_label.text = parsed["reply"]
		world = parsed.get("state", world)
		queue_redraw()

func _url(path: String) -> String:
	return base_url.trim_suffix("/") + "/" + path.trim_prefix("/")

func _draw() -> void:
	var width := int(world.get("width", 15))
	var height := int(world.get("height", 10))
	var origin := Vector2(32, 32)
	for y in height:
		for x in width:
			var rect := Rect2(origin + Vector2(x, y) * cell_size, Vector2(cell_size - 2, cell_size - 2))
			draw_rect(rect, Color("#d9f2e4") if (x + y) % 2 == 0 else Color("#cce6f2"), true)
	for building in [[1, 1, "档案馆", Color("#8b7cf6")], [7, 1, "广场", Color("#ffb454")], [11, 6, "咖啡馆", Color("#ef6f9a")], [2, 7, "诊所", Color("#35b6aa")]]:
		var position := origin + Vector2(building[0], building[1]) * cell_size + Vector2(6, 6)
		draw_rect(Rect2(position, Vector2(cell_size * 2 - 12, cell_size * 1.3)), building[3], true)
		draw_string(ThemeDB.fallback_font, position + Vector2(10, 28), building[2], HORIZONTAL_ALIGNMENT_LEFT, -1, 13, Color.WHITE)
	var player: Dictionary = world.get("player", {})
	_draw_actor(player, true)
	for npc in world.get("npcs", []):
		_draw_actor(npc, false)

func _draw_actor(actor: Dictionary, is_player: bool) -> void:
	if actor.is_empty():
		return
	var position := Vector2(32, 32) + Vector2(actor.get("x", 0), actor.get("y", 0)) * cell_size + Vector2(cell_size / 2, cell_size / 2)
	draw_circle(position, 18.0 if is_player else 16.0, Color("#101828") if is_player else Color(actor.get("color", "#155eef")))
	draw_circle(position, 18.0 if is_player else 16.0, Color.WHITE, false, 3.0)
	if not is_player and actor.get("npc_id", "") == selected_npc.get("npc_id", ""):
		draw_circle(position, 23.0, Color("#facc15"), false, 4.0)
	draw_string(ThemeDB.fallback_font, position - Vector2(8, -5), "你" if is_player else str(actor.get("name", "?")).left(1), HORIZONTAL_ALIGNMENT_CENTER, 16, 15, Color.WHITE)

func _ready_base_url() -> void:
	if not OS.has_feature("web"):
		return
	var href := str(JavaScriptBridge.eval("window.location.href"))
	var godot_marker := href.find("/godot/")
	if godot_marker >= 0:
		base_url = href.substr(0, godot_marker)
