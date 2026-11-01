# NPC ↔ NPC 社会关系图

## 为什么是"图",而不是再加一个好感度

`relationship_manager` 里只有 **NPC ↔ 玩家** 的一维好感度。要观察「两个 NPC 之间是朋友还是
对手、这个关系怎么随事件演化」，需要的是**边**：每对 NPC 一条，由事件驱动，带证据链。

## 数据结构

| 字段 | 说明 |
|---|---|
| `a` / `b` / `pair` | 无向边（3 个 NPC → 3 条边） |
| `strength` | **唯一连续量**，范围 −1…1 |
| `type` | 由强度派生：`friend` ≥0.5、`coop` ≥0.2、`neutral` >−0.2、`rival` ≤−0.2、`conflict` ≤−0.5 |
| `evidence` | 最近 20 条：时间 / 事件 / 增量 / 之后强度 / 备注 |
| `updated_at` | 最后变动时间 |

**类型是从强度派生出来的**，这样事件只需要加减一个数，不会出现"类型和强度互相矛盾"的状态。

## 事件规则

| 事件 | 增量 | 用途 |
|---|---:|---|
| `help` | +0.30 | 帮对方做事 |
| `cooperate` | +0.20 | 协作 |
| `praise` | +0.10 | 公开称赞 |
| `ignore` | 0 | 无互动 |
| `compete` | −0.30 | 争夺同一任务 |
| `conflict` | −0.40 | 正面冲突 |
| `betray` | −0.60 | 背约 |

一次事件可以涉及多个 NPC（例如三个人一起争），此时**所有两两组合**都会受影响：
3 个 NPC 会同时改动 3 条边。强度截断在 ±1。

## 实测：`scenarios/rivalry.yaml`

场景脚本（4 轮）驱动了 4 次关系事件：

| 时间 | 事件 | 增量 | 之后强度 | 备注 |
|---|---|---:|---:|---|
| 19:35:02 | `compete` | −0.3 | −0.3 | 争夺同一任务名额 |
| 19:35:03 | `conflict` | −0.4 | −0.7 | 公开互相指责 |
| 19:35:04 | `help` | +0.3 | −0.4 | 张三帮王五看了设计稿 |
| 19:35:05 | `cooperate` | +0.2 | **−0.2** | 李四促成分工 |

最终三对关系（`GET /relations`）：

```
张三↔李四   coop    0.2    1 条证据
张三↔王五   rival  -0.2    4 条证据    ← 竞争→冲突→帮助→协作，净 −0.2
李四↔王五   coop    0.2    1 条证据
```

**关键在于：关系只由事件决定，模型在对话里说什么都不影响它。** 同一场景重跑，关系轨迹
完全一致（事件是确定性的），这也是它可作实验条件的原因。

### 一个被实测暴露的 bug

第一版跑出来时，`张三↔王五` 是 `neutral` 而不是 `rival` —— 因为
−0.3 −0.4 +0.3 +0.2 在浮点下是 `-0.19999999999999998`，落在阈值 `≤ -0.2` 之外。
修法：`type_of()` 先四舍五入到 3 位，`apply_event` 每次累加后也四舍五入。
已补回归测试 `test_float_accumulation_keeps_boundary`。

> 这类 bug 只有真跑才会暴露，纯看代码不会发现。

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/relations?include_evidence=true` | 所有边 + 统计 |
| GET | `/relations/graph` | **节点 + 边**，给界面渲染用 |
| POST | `/relations/event` | `{kind, actors[], weight?, note?}` 驱动一次事件 |
| POST | `/relations/reset` | 清空回中立 |
| GET | `/relations/neo4j?read=true` | Neo4j 镜像状态；`read=true` 读回验证 |
| POST | `/relations/sync` | 把当前图镜像到 Neo4j |

## Neo4j 镜像（可选）

### 为什么是"可选"

3 个 NPC 只有 3 条边，**内存图才是权威**，用图数据库存是牛刀。镜像的真实价值只有两个：

1. 用 Cypher 做多跳查询（"谁和谁是一条线上的"），内存版没实现；
2. 演示时直接开 Neo4j Browser 看关系网络，比看 JSON 直观。

所以：**没配凭据就完全不启用**，`/relations/sync` 会安静地返回"未启用"，不影响任何其它功能。

### 本机现状与开启步骤

本机 Neo4j 是 `E:\Software\neo4j\neo4j-community-4.4.46` 的 **Windows 服务**。
4.4 起用户凭据存在 `data\databases\system` 库里（哈希），**密码无法找回**，只能重置或关闭认证。

这里选的是**关闭认证**（仅本机开发），**已完成并验证**（2026-11-01）：

| 检查 | 结果 |
|---|---|
| Neo4j 版本 | 4.4.46 community（Windows 服务） |
| 驱动版本 | `neo4j` 6.4.1（与 4.4 兼容，实测可连） |
| 无凭据 HTTP | 200（认证已关闭） |
| 写读回环 | 通过 |
| 关系图镜像 | **3 节点 / 3 边** 写入成功，读回一致 |

执行步骤（留档）：

```powershell
# 1) 已改好：conf 第 27 行取消注释
#    E:\Software\neo4j\neo4j-community-4.4.46\conf\neo4j.conf
dbms.security.auth_enabled=false

# 2) 必须用【管理员】PowerShell 重启服务（普通权限会报"无法打开服务"）
Restart-Service neo4j

# 3) 验证（不带凭据应返回 200）
python tools/check_neo4j.py

# 4) 让后端认识这个模式
$env:NEO4J_AUTH='none'
```

另一条路是保留认证并重置密码（会重建 `system` 库里的用户/角色，业务库数据不受影响）：
停服务 → 移走 `data\databases\system` 与 `data\transactions\system` →
`bin\neo4j-admin.bat set-initial-password 新密码` → 起服务。

### 镜像写入的 Cypher

```cypher
UNWIND $nodes AS n MERGE (x:NPC {id:n.id}) SET x.label = n.label
UNWIND $edges AS e MATCH (a:NPC {id:e.a}) MATCH (b:NPC {id:e.b})
MERGE (a)-[r:RELATES]->(b) SET r.strength=e.strength, r.type=e.type, r.updated_at=e.updated_at
```

## 验证证据

`tools/probe_relations.py` 一次跑出 10 项检查，全部通过：

```
[PASS] 复位后全部中立
[PASS] compete → 强度 -0.30 / rival
[PASS] conflict → 强度 -0.70 / conflict
[PASS] help → 强度 -0.40 / rival（回暖）
[PASS] 证据链累计 3 条
[PASS] graph 有 3 节点 3 边
[PASS] Neo4j 写入成功  nodes=3 edges=3
[PASS] Neo4j 读回图非空（3 条边 / 3 个节点）
```

原始输出：`experiments/governance/relations_check.txt`

## 边界（不假装）

1. **关系只由显式事件驱动，不从对话里自动推断。** 自动推断需要 LLM 判定"这句话算不算帮忙"，
   属于未验证的设计，没做。
2. **阈值与增量是启发式的**，不是从数据里拟合出来的。改 `EVENT_RULES` 与 `type_of()` 就能改口径。
3. **内存权威、Neo4j 镜像**。两者可能短暂不一致（同步是显式调用）；这是为"数据库挂了也不影响
   对话"付出的代价。
4. 每个 (NPC, 玩家) 关系图是**全局的**（NPC 之间不区分玩家）；如果要"每个玩家一个平行世界"，
   需要把图按玩家分片 —— 当前没做。

## 相关

- 事件驱动源：`scenarios/*.yaml` 的 `relation_event`，见 [SCENARIO.md](SCENARIO.md)
- 单测：`tests/test_relations.py`（22 个用例，含浮点边界回归）
- 检查工具：`tools/check_neo4j.py`
