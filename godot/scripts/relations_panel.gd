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
var _url: String = ""

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
	# 直接按视口尺寸定位：锚点在 CanvasLayer/首帧下解析不确定，显式算更稳
	_apply_layout()
	get_viewport().size_changed.connect(_apply_layout)

	_http = HTTPRequest.new()
	_http.timeout = 5.0
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)

	print("[INFO] 关系面板已就绪（按 R 显示/隐藏）")
	if Config.DEBUG_MODE:
		print("[INFO] 关系面板 rect: ", get_global_rect(), " visible=", visible)
	_refresh()


func _apply_layout() -> void:
	"""把面板钉在右上角：位置由视口尺寸算出来，不依赖锚点解析时机。"""
	var vp: Vector2 = get_viewport_rect().size
	if vp.x <= 0.0 or vp.y <= 0.0:
		vp = Vector2(1280, 720)      # headless / 首帧兜底
	size = PANEL_SIZE
	position = Vector2(vp.x - PANEL_SIZE.x - 14.0, 14.0)


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
	_url = base_url
	var err := _http.request(base_url)
	if err != OK:
		_set_status("请求发起失败 err=%d" % err)


func _host_only() -> String:
	"""把 http://host:port/relations/graph 缩短成 host:port，标题和报错里显示。"""
	var u: String = _url
	u = u.replace("http://", "").replace("https://", "")
	var slash: int = u.find("/")
	if slash > 0:
		u = u.substr(0, slash)
	return u


func _set_status(text: String) -> void:
	_status = text
	if typeof(Config) != TYPE_NIL and Config.DEBUG_MODE:
		print("[WARN] 关系面板: ", text)
	queue_redraw()


func _on_request_completed(result: int, response_code: int,
		_headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		# 后端没启动时最常见就是这个分支：连接被拒 / 超时
		_set_status("连不上 %s（后端没启动？）" % _host_only())
		return
	if response_code != 200:
		_set_status("后端返回 %d（路径或参数不对）" % response_code)
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		_set_status("数据格式异常")
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
	var title: String = "NPC 关系图 · %s（按 R 隐藏）" % _host_only()
	draw_string(font, Vector2(12, 22), title,
		HORIZONTAL_ALIGNMENT_LEFT, -1, 13, COLOR_TITLE)
	draw_string(font, Vector2(12, PANEL_SIZE.y - 10), _status,
		HORIZONTAL_ALIGNMENT_LEFT, -1, 12, COLOR_TEXT)

	var count: int = _nodes.size()
	if count == 0 or _edges.is_empty():
		draw_string(font, Vector2(12, 52), "暂无关系数据（后端未启动或未施加事件）",
			HORIZONTAL_ALIGNMENT_LEFT, -1, 12, COLOR_TEXT)
		return

	var ids: Array = []
	for i in count:
		ids.append(_nodes[i].get("id", str(i)))
	var positions: Dictionary = layout_positions(ids, PANEL_SIZE)

	# 先画边
	for edge in _edges:
		var a: String = str(edge.get("a", ""))
		var b: String = str(edge.get("b", ""))
		if not (positions.has(a) and positions.has(b)):
			continue
		var rel_type: String = str(edge.get("type", "neutral"))
		var strength: float = float(edge.get("strength", 0.0))
		var color: Color = TYPE_COLORS.get(rel_type, TYPE_COLORS["neutral"])
		var is_neutral: bool = rel_type == "neutral"
		# 中立边淡化：细、半透明，避免三条灰线抢戏
		if is_neutral:
			color.a = 0.45
		var width: float = 1.2 if is_neutral else 1.5 + 3.0 * abs(strength)
		draw_line(positions[a], positions[b], color, width, true)

		var mid: Vector2 = (positions[a] + positions[b]) * 0.5
		var label: String = TYPE_LABELS.get(rel_type, rel_type)
		var text: String = label if is_neutral else "%s %+.2f" % [label, strength]
		var label_x: float = -14.0 if is_neutral else -26.0
		draw_string(font, mid + Vector2(label_x, -4), text,
			HORIZONTAL_ALIGNMENT_LEFT, -1, 12, color)

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


# ==================== 版式（纯函数，便于 headless 校验）====================
const NODE_RADIUS: float = 16.0


func layout_positions(ids: Array, box: Vector2) -> Dictionary:
	"""环形布局：给定节点 id 与面板尺寸，返回 id -> 坐标。

	抽成纯函数是为了能脱离绘制流程做几何断言（见 godot/tests/panel_layout_check.gd）。
	"""
	var positions: Dictionary = {}
	var count: int = ids.size()
	if count == 0:
		return positions
	var center := Vector2(box.x * 0.5, box.y * 0.48)
	var radius: float = min(box.x, box.y) * 0.30
	for i in count:
		var angle: float = -PI * 0.5 + TAU * float(i) / float(count)
		positions[str(ids[i])] = center + Vector2(cos(angle), sin(angle)) * radius
	return positions
