# 可追溯记忆（memory ledger）

## 为什么单开一层

底层 `hello_agents` 的 `MemoryManager` 只存「内容 + 类型 + 重要性」，**没有来源、没有可信度，
也不能合并 / 纠正 / 软删除**。而这三件事恰好决定"一条记忆能不能信"。

所以本层是**与底层并行的账本**：`agents.py` 每轮把对话按来源写进来，对外提供
"列举 / 纠正 / 遗忘 / 合并 / 调可信度 / 按可信度过滤"。

| | 底层 MemoryManager | 本层 MemoryLedger |
|---|---|---|
| 存什么 | 内容、类型、importance | 内容、**source**、**credibility**、status、seq、审计链 |
| 能否纠正 | ❌ | ✅ 旧记录转 `corrected`，另写替代记录 |
| 能否遗忘 | 只能整体清空 | ✅ 软删除，仍可查 |
| 能否合并 | ❌ | ✅ 标记 `merged` + 继承最高重要性/可信度 |
| 能否过滤 | 按 importance | ✅ **按可信度阈值过滤出 prompt** |

## 数据结构

| 字段 | 说明 |
|---|---|
| `record_id` | UUID |
| `npc` / `player` | 归属，与 `(NPC, 玩家)` 隔离一致 |
| `content` | 原文 |
| `source` | `event.world` / `dialogue.player` / `dialogue.npc` / `injected` / `manual` |
| `importance` | 0–1 |
| `credibility` | 0–1，默认取来源先验 |
| `created_at` | ISO 时间戳 |
| `status` | `active` / `corrected` / `forgotten` / `merged` |
| `corrected_from` / `merged_into` | 溯源指针 |
| `seq` | 单调序号，保证同一秒内写入排序稳定 |

## 来源 → 先验可信度

| 来源 | 先验 | 理由 |
|---|---:|---|
| `event.world` | 0.95 | 来自权威状态 / 审计事件 |
| `dialogue.player` | 0.60 | 玩家自述，可能记错也可能撒谎 |
| `dialogue.npc` | 0.50 | 模型生成，已知会编造 |
| `injected` | 0.20 | 场景注入 / 外部供给，未经证实 |
| `manual` | 0.60 | 调用方显式写入 |

## 四个操作的效果

```
add              → status=active，credibility=来源先验
correct(旧→新)   → 旧: status=corrected；新: status=active, corrected_from=旧, 可信度 ≥0.6
forget           → status=forgotten（不物理删除，审计链完整）
merge(多条→保留) → 其余: status=merged, merged_into=保留项；保留项继承最高分
set_credibility  → 任意改；flag_disputed 直接压到 0.05
```

## 可信度必须影响行为——否则只是标签

`render_context(limit, min_credibility)` 会**按阈值过滤**后再注入 prompt。
开关 `MEMORY_LEDGER=on` 时，`chat()` 会把这部分拼进消息：

```
【可追溯记忆】
- [2026-11-01T18:02:11] (dialogue.player, 可信度 0.60) 我叫小林，在做赛博小镇课程项目
```

而来源为 `injected` 的记录（先验 0.20）在默认阈值 0.5 下**根本不会出现**。
这是"可追溯"的真正价值：不是记录得更细，而是**能据此决定信不信**。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/memory/records?npc&player&status` | 列出记录（可按状态过滤） |
| POST | `/memory/records` | 写入，`source` 决定先验可信度 |
| POST | `/memory/correct` | 纠正（旧转 corrected，另写替代） |
| POST | `/memory/forget` | 软删除 |
| POST | `/memory/merge` | 合并多条到 `keep_id` |
| POST | `/memory/credibility` | 校正可信度；`disputed=true` 压到 0.05 |
| GET | `/memory/stats?npc&player` | 总数 / 按状态 / 按来源 / 平均可信度 |
| GET | `/memory/context?npc&player&min_credibility&limit` | 渲染将注入的片段 |

## 实测（`tools/probe_memory_ledger.py`，对照式 11 项检查，全部通过）

原始输出：`experiments/governance/memory_ledger_check.txt`

| 检查 | 结果 |
|---|---|
| 注入来源先验 = 0.20 | PASS |
| 玩家自述先验 = 0.60 | PASS |
| 默认阈值 0.5 下包含可信记忆 | PASS |
| **默认阈值 0.5 下排除伪造记忆** | PASS |
| 阈值降到 0.1 后伪造记忆出现 | PASS |
| 一轮对话后账本新增 2 条 | PASS（2 → 4） |
| 原记录被标记 corrected | PASS |
| 纠正后可信度 ≥ 0.60 | PASS（0.6） |
| 新记录带 `corrected_from` | PASS |
| 遗忘是软删除 | PASS |
| 遗忘后仍可查到 | PASS |

统计输出示例：`共 5 条，活跃 3 条，平均可信度 0.567；按状态 {active:3, corrected:1, forgotten:1}`

## 边界（不假装）

1. **没有自动事实抽取**。可信度是「来源先验 + 显式校正」，系统不会自己去比对
   "这条记忆和世界状态是否矛盾"。与状态比对目前要靠场景判据或人工调用
   `/memory/credibility?disputed=true`。
2. **存储是每 (NPC, 玩家) 一个 JSON 文件**。到万级需要换存储；当前是课程项目量级。
3. **与底层并行，不是替换**。检索仍走 `hello_agents` 的 working memory；
   账本负责溯源与过滤。两者不共享存储，因此可能出现"底层召回了一条、账本里没有"的情况
   —— 这是有意的取舍：不改第三方库。
4. **默认关闭**（`MEMORY_LEDGER=off`）。归档四组实验的 prompt 与行为完全不受影响。

## 用法

```powershell
cd backend
$env:MEMORY_LEDGER='on'
$env:MEMORY_MIN_CREDIBILITY='0.5'
python -m uvicorn main:app --port 8000

# 另开窗口
python tools/probe_memory_ledger.py
```
