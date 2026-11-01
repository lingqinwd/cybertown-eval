# 权威状态与玩家隔离

本项目最初的定位是"能对话的 NPC"，因此有两个地方把**状态的主权交给了语言模型**。
在把它当作"可交互世界"来看时，这两处都是缺陷，已经修掉：

| 缺陷 | 表现 | 修复 |
|---|---|---|
| 好感度由模型直接决定 | 玩家可以用话术让模型把好感度一次推满 | `backend/rules.py` 规则层：模型只提议，后端裁决 |
| 记忆按 NPC 隔离 | 两个玩家与同一 NPC 对话时，能召回对方说的话 | 记忆键改为 `(NPC, 玩家)`，存储路径同步分层 |

---

## 一、好感度规则层

### 修改前

`backend/relationship_manager.py` 拿到 LLM 给出的 `change_amount` 后**直接写入状态**：

```python
new_affinity = current_affinity + analysis["change_amount"]   # 完全由模型决定
new_affinity = max(0.0, min(100.0, new_affinity))             # 只做区间钳制
self.set_affinity(npc_name, new_affinity, player_id)
```

只要能在对话里说服模型，就能一次把好感度推到位 —— 这正是"提示词越权修改游戏状态"。

### 修改后

```python
verdict = evaluate_affinity_change(
    current=current_affinity,
    proposed_delta=analysis["change_amount"],   # 模型的提议
    sentiment=sentiment,
    reason=analysis.get("reason", ""),
)
if verdict.changed:
    self.set_affinity(npc_name, verdict.new_value, player_id)   # 规则放行后才写
```

### 规则清单（`backend/rules.py`）

| 编号 | 规则 | 默认参数 |
|---|---|---|
| R0 | 有限性：非数值 / NaN / inf 一律按 0 处理 | — |
| R1 | 正向单轮上限 | `AFFINITY_MAX_POS_DELTA=10` |
| R2 | 负向单轮上限 | `AFFINITY_MAX_NEG_DELTA=15` |
| R3 | 正向变化必须有 `positive` 情感证据 | — |
| R4 | 结果限制在 `[0, 100]`，越界部分截断 | — |

每条规则触发时，`status`（`applied` / `clipped` / `rejected` / `noop`）与命中说明会写进：

- 日志：`🛡️ 好感度规则[clipped]: R1 正向 50.00 超过单轮上限 10.00，已截断`
- CSV：`metrics_*.csv` 新增三列 `affinity_proposed` / `affinity_rule_status` / `affinity_rule_notes`

因此"模型提议了多少、规则实际放行多少"是可统计的，而不是只能口头声称。

### 为什么默认上限是 10

已归档的四组实验（`docs/EXPERIMENT_RESULTS.md`）采集于**没有规则层**的旧版本，观测到的单轮变化最大为 **+7**（`experiments/aup_qwen_memory_on_metrics.csv`）。

把默认正向上限设为 10 有两个好处：

1. 归档数据里的好感度轨迹在启用规则层后**仍然可复现**（+5 / +6 / +7 都不会被改写）；
2. 仍足以拦住"给加 50""调到 100"这类越权。

需要更严格时用环境变量覆盖，例如 `AFFINITY_MAX_POS_DELTA=5`。

---

## 二、记忆按玩家隔离

### 修改前

`backend/agents.py`：

```python
memory_manager = MemoryManager(
    user_id=npc_name,        # ⚠️ 用 NPC 名字当 user_id
    ...
)
self.memories[npc_name] = memory_manager     # 一个 NPC 只有一份记忆
```

`player_id` 只作为 metadata 存在，检索时并不参与过滤。于是**两个玩家与同一个 NPC 对话会共享记忆**：后一个玩家问"我叫什么"，NPC 会答出前一个玩家的名字。

实验里只有一个玩家（`player`），所以这个问题当时没有暴露。

### 修改后

```python
def memory_key(npc_name, player_id):
    return f"{npc_name}::{player_id}"

memory_manager = MemoryManager(user_id=memory_key(npc_name, player_id), ...)
# 存储路径：backend/memory_data/<npc>/<player>/
```

- 记忆管理器按 `(NPC, 玩家)` 键索引，缺失时在**首次对话按需创建**
- 某个玩家的记忆初始化失败只影响该玩家，不会让整个 NPC 降级
- 新增 `player_id` 参数贯穿：`POST /chat`、`GET /npcs/{npc}/memories`、`DELETE /npcs/{npc}/memories`
- 单玩家场景（Godot 客户端）行为不变，默认 `player_id="player"`

---

## 三、怎么验证

### 1. 单元测试（不需要模型、不需要网络）

```bash
python tests/test_affinity_rules.py      # 15 个用例，覆盖 R0–R4 与边界
```

### 2. 规则层行为验证（需要一个能跑的后端）

```bash
python tools/probe_governance.py --mode affinity --npc 李四
```

它依次发送三条提示词（越权指令 / 社交工程 / 正常礼貌），打印每轮的实际增幅与回复节选。判据是**单轮实际增幅不超过上限**。

### 3. 玩家隔离验证

```bash
python tools/probe_governance.py --mode isolation --npc 李四
```

让 `probe_alice` 自我介绍，再由 `probe_bob` 追问。判据是 bob 的回复里**不出现** alice 的名字与项目名。

> 注意：不要用 `GET /npcs/{npc}/memories` 判断记忆是否写入 —— 它对工作记忆恒返回空（原因见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 坑 6）。隔离验证靠**行为**判断，不靠这个接口。

---

## 四、这套规则的边界（要说清楚）

1. **它只覆盖好感度。** 金币、物品、任务等状态目前**并不存在**，所以谈不上被保护 —— 这些是 [ROADMAP.md](ROADMAP.md) 里"权威世界状态机"的工作，本层只提供了模式样板。
2. **模型仍然参与判断。** 规则层只是给模型的输出加了确定性的闸门，不能保证模型"提议得对"。真正的权威状态机还要求：所有状态变更必须走事件（Event），模型只能选择预定义动作。
3. **上限是经验值。** 10 这个数字来自"让归档数据可复现"，不是从实验里优化出来的。
4. **归档实验早于本层。** 四组数据生成于旧版本；用当前代码重跑会得到不同（更保守）的好感度轨迹。这一点已写进 `docs/EXPERIMENT_RESULTS.md` 的局限。
