# 赛博小镇 - 全局配置
extends Node

# ==================== API配置 ====================
# 默认连接本机 FastAPI；演示 AUP 后端时可设置环境变量
# CYBERTOWN_API_BASE_URL，而不需要修改项目代码。
var API_BASE_URL: String = "http://127.0.0.1:8000"
var API_CHAT: String = ""
var API_NPCS: String = ""
var API_NPC_STATUS: String = ""

# ==================== NPC配置 ====================
const NPC_NAMES = ["张三", "李四", "王五"]
const NPC_TITLES = {
	"张三": "Python工程师",
	"李四": "产品经理",
	"王五": "UI设计师"
}

# ==================== 游戏配置 ====================
const PLAYER_SPEED = 200.0  # 玩家移动速度
const INTERACTION_DISTANCE = 80.0  # 交互距离
const NPC_STATUS_UPDATE_INTERVAL = 30.0  # NPC状态更新间隔(秒)

# ==================== UI配置 ====================
const DIALOGUE_FADE_TIME = 0.3  # 对话框淡入淡出时间
const NPC_LABEL_OFFSET = Vector2(0, -60)  # NPC名字标签偏移

# ==================== 调试配置 ====================
const DEBUG_MODE = true  # 调试模式
const SHOW_INTERACTION_RANGE = true  # 显示交互范围

func _ready() -> void:
	var override_url := OS.get_environment("CYBERTOWN_API_BASE_URL").strip_edges()
	if not override_url.is_empty():
		API_BASE_URL = override_url.trim_suffix("/")
	API_CHAT = API_BASE_URL + "/chat"
	API_NPCS = API_BASE_URL + "/npcs"
	API_NPC_STATUS = API_BASE_URL + "/npcs/status"
	log_info("API地址: " + API_BASE_URL)

# ==================== 工具函数 ====================
func log_info(message: String) -> void:
	if DEBUG_MODE:
		print("[INFO] ", message)

func log_error(message: String) -> void:
	print("[ERROR] ", message)

func log_api(endpoint: String, data: Dictionary) -> void:
	if DEBUG_MODE:
		print("[API] ", endpoint, " -> ", JSON.stringify(data))
