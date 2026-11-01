# 关系面板的版式几何检查（headless 可跑，不需要显示器、不需要后端）
#
# 运行：
#   Godot_v4.5.2-stable_win64_console.exe --headless ^
#       --path <godot 项目目录> --script res://tests/panel_layout_check.gd
#
# 检查的是"能不能看清"的客观前提，而不是审美：
#   1. 面板整块在视口内
#   2. 面板不与底部对话框重叠
#   3. 三个节点都在面板内且留出边距
#   4. 两两节点不重叠（间距 >= 2R + 余量）
extends SceneTree

const PANEL_SIZE := Vector2(380, 320)
const PANEL_MARGIN := 14.0
const NODE_RADIUS := 16.0
const DIALOGUE_HEIGHT := 218.0     # dialogue_ui.tscn: anchor_bottom=1, offset_top=-218

var _failures: int = 0


func _check(label: String, ok: bool, detail: String = "") -> void:
	if ok:
		print("  [PASS] ", label, "" if detail.is_empty() else "  " + detail)
	else:
		_failures += 1
		print("  [FAIL] ", label, "" if detail.is_empty() else "  " + detail)


func _initialize() -> void:
	print("\n=== 关系面板版式检查 ===")
	var viewport_w: float = float(ProjectSettings.get_setting("display/window/size/viewport_width", 1280))
	var viewport_h: float = float(ProjectSettings.get_setting("display/window/size/viewport_height", 720))
	print("视口: %dx%d   面板: %dx%d   节点半径: %d\n"
		% [int(viewport_w), int(viewport_h), int(PANEL_SIZE.x), int(PANEL_SIZE.y), int(NODE_RADIUS)])

	# 面板矩形（右上角，与 _ready() 里的定位一致）
	var panel_left: float = viewport_w - PANEL_SIZE.x - PANEL_MARGIN
	var panel_top: float = PANEL_MARGIN
	var panel_rect := Rect2(Vector2(panel_left, panel_top), PANEL_SIZE)

	_check("面板完整落在视口内",
		panel_rect.position.x >= 0.0 and panel_rect.position.y >= 0.0 \
		and panel_rect.end.x <= viewport_w and panel_rect.end.y <= viewport_h,
		"rect=%s" % str(panel_rect))

	var dialogue_top: float = viewport_h - DIALOGUE_HEIGHT
	_check("不与底部对话框重叠",
		panel_rect.end.y <= dialogue_top,
		"面板底 %.0f / 对话框顶 %.0f" % [panel_rect.end.y, dialogue_top])

	# 实例化脚本，调用纯函数布局
	var panel_script: GDScript = load("res://scripts/relations_panel.gd")
	if panel_script == null:
		_check("脚本可加载", false, "load 失败")
		quit(1)
		return
	var panel: Control = panel_script.new()
	var ids: Array = ["张三", "李四", "王五"]
	var positions: Dictionary = panel.layout_positions(ids, PANEL_SIZE)
	_check("布局返回 3 个坐标", positions.size() == 3, "size=%d" % positions.size())

	# 节点必须落在面板内并留边距
	var margin_ok := true
	var worst := 0.0
	for id in positions:
		var pos: Vector2 = positions[id]
		var dx: float = min(pos.x - NODE_RADIUS, PANEL_SIZE.x - pos.x - NODE_RADIUS)
		var dy: float = min(pos.y - NODE_RADIUS, PANEL_SIZE.y - pos.y - NODE_RADIUS)
		var m: float = min(dx, dy)
		if m < 8.0:
			margin_ok = false
		worst = m if worst == 0.0 else min(worst, m)
	_check("节点在面板内且留 >=8px 边距", margin_ok, "最小边距 %.1f px" % worst)

	# 两两不重叠（同半径圆，间距 >= 2R + 6）
	var min_gap := 1e9
	for i in ids.size():
		for j in range(i + 1, ids.size()):
			var d: float = positions[ids[i]].distance_to(positions[ids[j]])
			min_gap = min(min_gap, d)
	_check("节点两两不重叠", min_gap >= 2.0 * NODE_RADIUS + 6.0,
		"最小间距 %.1f px（需 >= %.0f）" % [min_gap, 2.0 * NODE_RADIUS + 6.0])

	panel.free()

	print()
	if _failures == 0:
		print("[PASS] 版式几何检查全部通过")
		quit(0)
	else:
		print("[FAIL] %d 项未通过" % _failures)
		quit(1)
