# NPC 关系面板
#
# 独立的一层 UI：从 /relations/graph 拉数据，在右上角画关系网络。
# 不触碰现有对话/移动逻辑 —— 只读，不写。
#
# 操作：R 键显示/隐藏；每 5 秒自动刷新一次。
extends Control

const REFRESH_SECONDS: float = 5.0
const PANEL_SIZE := Vector2(380, 320)

const COLOR_BG := Color(0.06, 0.08, 0.12, 0.78)
const COLOR_TITLE := Color(0.92, 0.94, 0.98)
const COLOR_TEXT := Color(0.78, 0.82, 0.88)
const COLOR_NODE := Color(0.30, 0.55, 0.95)

var _http: HTTPRequest
var _elapsed: float = 0.0
var _nodes: Array = []
var _edges: Array = []
var _status: String = "等待后端…"

const TYPE_COLORS := {
	"friend": Color(0.36, 0.86, 0.46),
	"coop": Color(0.56, 0.84, 0.56),
	"neutral": Color(0.60, 0.64, 0.70),
	"rival": Color(0.95, 0.66, 0.26),
	"conflict": Color(0.93, 0.35, 0.35),
}

const TYPE_LABELS := {
	"friend": "朋友",
	"coop": "协作",
	"neutral": "中立",
	"rival": "竞争",
	"conflict": "冲突",
}


func _ready() -> void:
	name = "RelationsPanel"
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_preset(Control.PRESET_TOP_RIGHT)
	size = PANEL_SIZE
	position = Vector2(-PANEL_SIZE.x - 14.0, 14.0)

	_http = HTTPRequest.new()
	_http.timeout = 5.0
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)

	print("[INFO] 关系面板已就绪（按 R 显示/隐藏）")
	_refresh()


func _process(delta: float) -> void:
	_elapsed += delta
	if _elapsed >= REFRESH_SECONDS:
		_elapsed = 0.0
		_refresh()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_R:
			visible = not visible
			if visible:
				_refresh()


func _refresh() -> void:
	if _http == null:
		return
	var base_url: String = "/relations/graph"
	if typeof(Config) != TYPE_NIL:
		base_url = Config.API_BASE_URL + "/relations/graph"
	var err := _http.request(base_url)
	if err != OK:
		_status = "请求失败（" + str(err) + "）"
		queue_redraw()


func _on_request_completed(_result: int, response_code: int,
		_headers: PackedStringArray, body: PackedByteArray) -> void:
	if response_code != 200:
		_status = "后端返回 " + str(response_code)
		queue_redraw()
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		_status = "数据格式异常"
		queue_redraw()
		return
	var data: Dictionary = parsed
	_nodes = data.get("nodes", [])
	_edges = data.get("edges", [])
	_status = "节点 %d · 边 %d" % [_nodes.size(), _edges.size()]
	if Config.DEBUG_MODE:
		print("[INFO] 关系面板刷新: ", _status)
	queue_redraw()


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, PANEL_SIZE), COLOR_BG, true)
	draw_rect(Rect2(Vector2.ZERO, PANEL_SIZE), Color(0.25, 0.35, 0.55, 0.9), false, 1.0)

	var font := ThemeDB.fallback_font
	draw_string(font, Vector2(12, 22), "NPC 关系图（R 隐藏）",
		HORIZONTAL_ALIGNMENT_LEFT, -1, 14, COLOR_TITLE)
	draw_string(font, Vector2(12, PANEL_SIZE.y - 10), _status,
		HORIZONTAL_ALIGNMENT_LEFT, -1, 12, COLOR_TEXT)

	var count: int = _nodes.size()
	if count == 0 or _edges.is_empty():
		draw_string(font, Vector2(12, 52), "暂无关系数据（后端未启动或未施加事件）",
			HORIZONTAL_ALIGNMENT_LEFT, -1, 12, COLOR_TEXT)
		return

	# 环形布局
	var center := Vector2(PANEL_SIZE.x * 0.5, PANEL_SIZE.y * 0.48)
	var radius: float = min(PANEL_SIZE.x, PANEL_SIZE.y) * 0.30
	var positions := {}
	for i in count:
		var angle: float = -PI * 0.5 + TAU * float(i) / float(count)
		var id: String = _nodes[i].get("id", str(i))
		positions[id] = center + Vector2(cos(angle), sin(angle)) * radius

	# 先画边
	for edge in _edges:
		var a: String = str(edge.get("a", ""))
		var b: String = str(edge.get("b", ""))
		if not (positions.has(a) and positions.has(b)):
			continue
		var rel_type: String = str(edge.get("type", "neutral"))
		var strength: float = float(edge.get("strength", 0.0))
		var color: Color = TYPE_COLORS.get(rel_type, TYPE_COLORS["neutral"])
		var width: float = 1.5 + 3.0 * abs(strength)
		draw_line(positions[a], positions[b], color, width, true)

		var mid: Vector2 = (positions[a] + positions[b]) * 0.5
		var label: String = TYPE_LABELS.get(rel_type, rel_type)
		var text: String = "%s %+.2f" % [label, strength]
		draw_string(font, mid + Vector2(-24, -4), text,
			HORIZONTAL_ALIGNMENT_LEFT, -1, 11, color)

	# 再画节点，避免被线压住
	for i in count:
		var id: String = _nodes[i].get("id", str(i))
		if not positions.has(id):
			continue
		var pos: Vector2 = positions[id]
		draw_circle(pos, 16.0, COLOR_NODE)
		draw_circle(pos, 16.0, COLOR_TITLE, false, 1.0)
		draw_string(font, pos + Vector2(-14, 34), id,
			HORIZONTAL_ALIGNMENT_LEFT, -1, 12, COLOR_TEXT)
