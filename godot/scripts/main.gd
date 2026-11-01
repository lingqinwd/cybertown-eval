# 主场景脚本
extends Node2D

# NPC节点引用
@onready var npc_zhang: Node2D = $NPCs/NPC_Zhang
@onready var npc_li: Node2D = $NPCs/NPC_Li
@onready var npc_wang: Node2D = $NPCs/NPC_Wang

# API客户端
var api_client: Node = null

# NPC状态更新计时器
var status_update_timer: float = 0.0

func _ready():
	print("[INFO] 主场景初始化")
	
	# 关系面板（右上角，按 R 显示/隐藏）。只读 /relations/graph，不影响对话逻辑
	# 必须挂在 CanvasLayer 下：Control 直接挂 Node2D 时锚点相对零尺寸父矩形，会被推出屏幕
	var ui_layer := CanvasLayer.new()
	ui_layer.name = "UILayer"
	ui_layer.layer = 10
	add_child(ui_layer)

	var panel_script: GDScript = load("res://scripts/relations_panel.gd")
	if panel_script:
		var panel: Control = panel_script.new()
		panel.name = "RelationsPanel"
		ui_layer.add_child(panel)
	else:
		print("[WARN] 关系面板脚本未找到")

	# 自动化截图（仅当设置了 CYBERTOWN_SHOT 时启用）：导出视口图像后退出
	if not OS.get_environment("CYBERTOWN_SHOT").is_empty():
		_auto_screenshot()

	# 获取API客户端
	api_client = get_node_or_null("/root/APIClient")
	if api_client:
		api_client.npc_status_received.connect(_on_npc_status_received)
		
		# 立即获取一次NPC状态
		api_client.get_npc_status()
	else:
		print("[ERROR] API客户端未找到")

func _process(delta: float):
	# 定时更新NPC状态
	status_update_timer += delta
	if status_update_timer >= Config.NPC_STATUS_UPDATE_INTERVAL:
		status_update_timer = 0.0
		if api_client:
			api_client.get_npc_status()

func _on_npc_status_received(dialogues: Dictionary):
	"""收到NPC状态更新"""
	print("[INFO] 更新NPC状态: ", dialogues)
	
	# 更新各个NPC的对话
	for npc_name in dialogues:
		var dialogue = dialogues[npc_name]
		update_npc_dialogue(npc_name, dialogue)

func update_npc_dialogue(npc_name: String, dialogue: String):
	"""更新指定NPC的对话"""
	var npc_node = get_npc_node(npc_name)
	if npc_node and npc_node.has_method("update_dialogue"):
		npc_node.update_dialogue(dialogue)

func get_npc_node(npc_name: String) -> Node2D:
	"""根据名字获取NPC节点"""
	match npc_name:
		"张三":
			return npc_zhang
		"李四":
			return npc_li
		"王五":
			return npc_wang
		_:
			return null


func _auto_screenshot() -> void:
	"""等 8 秒（让面板拉到数据 / 走完失败分支）后导出视口图像，然后退出。仅自动化验证用。"""
	await get_tree().create_timer(8.0).timeout
	var image: Image = get_viewport().get_texture().get_image()
	if image == null:
		print("[ERROR] 取不到视口图像")
		get_tree().quit(1)
		return
	var path: String = OS.get_environment("CYBERTOWN_SHOT")
	var err: int = image.save_png(path)
	print("[INFO] 自动截图 %s  err=%d  %dx%d"
		% [path, err, image.get_width(), image.get_height()])
	get_tree().quit(0)
