# 排错手册：端侧部署踩过的坑

按"症状 → 原因 → 修复"组织。**如果你只想跑通端侧实验,先读完前两节**(那两个坑会静默产出无效数据)。

---

## 坑 1：装上 vLLM 后 GPU 消失

**症状**

```bash
$ python3 -c "import torch; print(torch.__version__, torch.version.hip, torch.cuda.is_available())"
2.13.0+cu130 None False
```

但 `rocm-smi` 正常,机器确实是 AMD ROCm 环境。

**原因**

PyPI 上的 vLLM wheel 是纯 CUDA 构建。`pip install vllm` 会把 `torch` 替换成 `2.13.0+cu130`,并拉入 `nvidia-cublas-cu13` 等一整套 CUDA 依赖。ROCm 版 torch 被 `~/.local` 下的 CUDA 版覆盖后,GPU 对所有 torch 计算不可用。

**修复**

不要修,直接撤掉遮罩。系统自带 `/usr/local` 下的 ROCm torch,删掉用户级包即可让它重新生效:

```bash
pip uninstall -y vllm triton torch torchvision torchaudio
python3 -c "import torch; print(torch.__file__, torch.version.hip, torch.cuda.is_available())"
# 期望：/usr/local/...  hip=7.13...  True
```

`triton` 必须一起卸载 —— 它同样被装成了 CUDA 版,会盖住系统的 ROCm 版。

**替代方案**:不要用 vLLM,改用本仓库的 `serve_qwen.py`(transformers 直接服务,接口仍是 OpenAI 兼容)。

---

## 坑 2：`所有嵌入模型都不可用`

**症状**

```text
❌ 李四 Agent创建失败: 所有嵌入模型都不可用，请安装依赖或检查配置
```

冒烟测试只花 7 ms,回复是「当前为模拟模式,请配置API_KEY以启用AI对话」。

**原因**

`hello_agents/memory/embedding.py` 第 272 行的默认值是 **`dashscope`**,不是 `local`:

```python
preferred = os.getenv("EMBED_MODEL_TYPE", "dashscope")
default_model = "text-embedding-v3" if preferred == "dashscope" else "sentence-transformers/all-MiniLM-L6-v2"
model_name = os.getenv("EMBED_MODEL_NAME", default_model)
return create_embedding_model_with_fallback(preferred_type=preferred, model_name=model_name, ...)
```

回退链把**同一个 `model_name` 喂给三个后端**:

| 顺序 | 后端 | 结果 |
|---|---|---|
| 1 | DashScope | `import dashscope` 未安装 → 失败 |
| 2 | local | 去加载名为 `text-embedding-v3` 的 ST 模型 → 不存在 → 失败 |
| 3 | tfidf | 构造函数只收 `max_features` → TypeError → 失败 |

三级全挂,抛"所有嵌入模型都不可用"。

**修复**

```bash
export EMBED_MODEL_TYPE=local
```

**为什么难查**:`try/except: continue` 吞掉了全部真实异常,报错信息与真实原因完全无关。本仓库的 `run_aup.sh` 已内置该检查(会真的加载一次 MiniLM 并编码,而不只是 `import`)。

---

## 坑 3：`qdrant-client未安装`(其实已经装了)

**症状**

```text
❌ 李四 Agent创建失败: qdrant-client未安装。请运行: pip install qdrant-client>=1.6.0
```

但 `python3 -c "import qdrant_client"` 明明成功。

**原因**

`hello_agents/memory/storage/qdrant_store.py` 第 17–20 行导入了一个**已被新版客户端删除**的符号:

```python
from qdrant_client.http.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, SearchRequest   # ← 1.10 起弃用，后续版本移除
)
```

`from ... import` 抛 `ImportError` → 整块 `try` 走 `except` → `QDRANT_AVAILABLE = False` → 报"未安装"。

而且 `SearchRequest` 在这份代码里**从未被使用**,纯属死导入,却让整个记忆系统瘫痪。第 398 行还有 `self.client.search(...)`,新版客户端同样已移除。

**修复**

降级客户端到两个 API 都还在的版本:

```bash
pip install "qdrant-client==1.9.2"
```

**验证**(必须验证真实符号,不能只验证能导入):

```bash
python3 -c "
from qdrant_client import QdrantClient
from qdrant_client.http.models import SearchRequest
print('导入 OK, client.search 存在:', hasattr(QdrantClient, 'search'))"
```

---

## 坑 4：Qdrant 不启动不影响对话,但记忆初始化会崩

**原因**

`qdrant_store.py` 在 `QDRANT_URL` 为空时**不会**跳过向量库,而是默认连 `localhost:6333`,连不上直接 `raise`:

```python
else:
    self.client = QdrantClient(host="localhost", port=6333, ...)
...
except Exception as e:
    logger.error(f"❌ Qdrant连接失败: {e}")
    raise
```

**更糟的是**:`agents.py` 把记忆管理器创建和 Agent 创建放在同一个 `try` 里,记忆失败会把 `self.agents[name] = None` —— 整个 NPC 连对话能力一起丢掉。

**修复**

必须真的起一个 Qdrant(不需要 docker,单文件二进制):

```bash
curl -sL -o qdrant.tar.gz \
  https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar -xzf qdrant.tar.gz
QDRANT__STORAGE__STORAGE_PATH=$HOME/qdrant_data ./qdrant
```

> 在 NFS 上会打印 `Filesystem check failed ... NFS may cause data corruption` 的 ERROR,但服务照常启动。单次实验够用;若重启失败,删掉 `qdrant_data/` 重来。

---

## 坑 5：记忆写进去了,但检索永远是 0 条

**症状**

```text
🧠 检索到0条相关记忆
💾 对话已保存到李四的记忆中     ← 写入是成功的
```

**原因**

工作记忆的检索用的是 `sklearn` TF-IDF(`hello_agents/memory/types/working.py`):

```python
vectorizer = TfidfVectorizer(stop_words=None, lowercase=True)
```

默认分词正则 `(?u)\b\w\w+\b` **依赖空格和词边界**。中文整句被标点切成几个大块:

| 文本 | 被切成 |
|---|---|
| 查询「你还记得我的名字,以及我正在做什么项目吗?」 | `你还记得我的名字`、`以及我正在做什么项目吗` |
| 记忆「玩家说: 你好,我叫小林…」 | `玩家说`、`你好`、`我叫小林`、`我正在做一个赛博小镇课程项目` |

两组 token **交集为空** → cosine = 0 → 关键词分 = 0 → 被 `if final_score > 0` 全丢弃 → 返回空。

**修复**

```bash
python3 patches/apply_working_memory_fix.py
```

补丁在分数全为 0 时退化为「按时间倒序返回最近 N 条」——这本来就是工作记忆应有的语义。**无记忆组不受影响**(不创建 `MemoryManager`),因此打补丁前后基线数据等价。

**只影响中文**。英文对话天然有空格,不会踩这个坑。

---

## 坑 6：`/npcs/{name}/memories` 恒返回空

**别把它当判据。**

`agents.py` 的 `get_npc_memories()` 用 `query=""` 去"检索所有记忆",但 `working.py` 里空查询使 `keyword_score = len("")/len(content) = 0`、向量分数也是 0,最终被 `final_score > 0` 全部过滤。

**正确的判据**:

```bash
# 服务端指标
cut -d, -f6,7 experiments/aup_qwen_memory_on_metrics.csv
# 或日志
grep -c "已保存到" backend/logs/dialogue_$(date +%F).log
```

---

## 坑 7：删了日志文件,新日志不再生成

后端运行时执行 `rm backend/logs/dialogue_*.log`,Python logging 的 handler 仍持有**已删文件的句柄**,后续写入进入"幽灵 inode",同名新文件不会出现。

**正确顺序**:先停后端 → 再删日志 → 再启动。

---

## 坑 8：JupyterHub 反向代理需要鉴权

原生 HTTP 客户端(PowerShell / Godot / curl)访问 `/user/<name>/proxy/8000` 会拿到 **JupyterHub 登录页 HTML**,而不是 JSON —— 因为代理路径挂了 cookie 认证。

**可行的替代**:在 JupyterLab 的浏览器控制台里用同源 `fetch` 发请求(浏览器自带 cookie)。本仓库的四组延迟数据就是用这种方式采集的,脚本思路见报告 §1。

---

## 坑 9：本地 embedding 被远程参数"污染"（报"所有嵌入模型都不可用"）

**现象**：`EMBED_MODEL_TYPE=local` 已设置、`sentence-transformers` 也装好了，但后端启动仍报
`所有嵌入模型都不可用，请安装依赖或检查配置`，Agent 全部降级。

**原因**：`hello_agents/memory/embedding.py` 的 `_build_embedder()` 把**所有**已配置的参数
一次性传给三个分支：

```python
kwargs["model_name"] = model_name
if api_key:  kwargs["api_key"] = api_key        # 来自 .env 的 DashScope 配置
if base_url: kwargs["base_url"] = base_url      # 同上
return create_embedding_model_with_fallback(preferred_type=preferred, **kwargs)
```

而 `LocalTransformerEmbedding.__init__(self, model_name=...)` **不接受** `api_key` / `base_url`
→ `TypeError` → 被 `except Exception: continue` 吞掉 → 三个分支全挂 → 报"都不可用"。

**最小复现**：

```python
LocalTransformerEmbedding(model_name='all-MiniLM-L6-v2', api_key='x', base_url='https://e.com')
# TypeError: __init__() got an unexpected keyword argument 'api_key'
```

**解法**：启动前把这两个变量**置空字符串**（不是不设）：

```powershell
$env:EMBED_MODEL_TYPE='local'
$env:EMBED_MODEL_NAME='sentence-transformers/all-MiniLM-L6-v2'
$env:EMBED_BASE_URL=''    # 关键
$env:EMBED_API_KEY=''     # 关键
```

## 坑 10：回退链复用 `EMBED_MODEL_NAME`，把 DashScope 的模型名塞给本地分支

即使绕过坑 9，只要 `.env` 里写着 `EMBED_MODEL_NAME=text-embedding-v3`（DashScope 的名字），
本地分支就会去加载一个叫 `text-embedding-v3` 的 sentence-transformers 模型 —— 加载不到。

`hello_agents` 的默认值逻辑是：

```python
default_model = "text-embedding-v3" if preferred == "dashscope" else "sentence-transformers/all-MiniLM-L6-v2"
model_name = os.getenv("EMBED_MODEL_NAME", default_model)
```

一旦 `.env` 显式设置了名字，按 provider 选默认值的逻辑就失效了。

**解法**：`EMBED_MODEL_NAME` 必须跟着当前 provider 走；本地就写
`sentence-transformers/all-MiniLM-L6-v2`。

> 两坑叠加的典型表现是"我明明装了 sentence-transformers，它还说不可用"。
> 排查顺序：`EMBED_MODEL_TYPE` → `EMBED_MODEL_NAME` → 两个远程变量是否为空。
> 诊断脚本：`python tools/diag_embedding.py`（逐分支打印 traceback）。

## 坑 11：一轮里连写两条记忆可能抛 TypeError（潜伏崩溃）

**现象**：TypeError: '<' not supported between instances of 'MemoryItem' and 'MemoryItem'，
抛出点在 hello_agents/memory/types/working.py 的
`heapq.heappush(self.memory_heap, (-priority, memory_item.timestamp, memory_item))`。

**原因**：堆里存的是三元组，比较到第三项（MemoryItem）才会出问题。只要两条记忆的
-priority 与 	imestamp 都相同，Python 就会去比较 MemoryItem —— 而它不可比较。
Windows 的 datetime.now() 分辨率约 1–15 ms，同一轮里连续写入"玩家说 / 我说"两条，
完全可能拿到同一个时间戳。

**影响**：这条路径在 _save_conversation_to_memory 里，是每轮对话都会走的。
实测在 benchmark 中稳定复现。

**临时规避**：两次写入之间加一个小间隔（	ools/bench_retrieve.py 里就是这么绕开的）。

**彻底修法**：给堆元组加一个单调递增的序号作为决胜项，例如

```python
# working.py
self._seq = itertools.count()
...
heapq.heappush(self.memory_heap, (-priority, memory_item.timestamp, next(self._seq), memory_item))
```

（memory_heap 的消费处也要相应调整取值下标。）本轮未实施，仅记录。

## 坑 12：`QDRANT_URL` 建议写 `127.0.0.1` 而不是 `localhost`

双栈机器上 `localhost` 会同时解析出 `::1` 与 `127.0.0.1`。若向量库只绑了 IPv4
（Docker 默认如此），每次请求会先连 `[::1]` 等超时再回退，实测每轮多约 2 秒。

改成 `http://127.0.0.1:6333` 后，同一次向量检索从 2051 ms 降到 6 ms。
排查工具：`python tools/bench_episodic.py`（把 `retrieve` 拆成 embed / vector_search /
doc_store 三段计时）。

## 一键自检

`run_aup.sh` 把这些检查都固化了:

```bash
bash run_aup.sh check     # torch/GPU、模型服务、后端
bash run_aup.sh on        # 记忆组：额外检查 embedding 实载、Qdrant 可达、Agent 未降级
```

它会在启动阶段直接拦截两种静默失败:回复含「模拟模式」、日志出现 `Agent创建失败`。

## 坑 13：metrics 的列是硬编码清单，加字段会被静默丢弃

`logger.log_metrics_csv` 里 `fields` 是一个写死的列表，
`writer.writerow({key: metrics.get(key, "") for key in fields})` ——
**dict 里多出来的键根本不会被写**。我在 `agents.py` 里加了 `ledger_context_chars`，
跑完发现 CSV 里没这一列，排查半天才发现问题不在 agents。

**改列必须同时做两件事**：改 `logger.py` 的 `fields`，并**轮换当天 CSV**
（旧文件列少，新行会多出几列，就是上面那个 schema 漂移的坑）。

## 坑 14：「修复后指标反而变小」——注意 limit 取的是尾部

`MemoryLedger.render_context(limit=5)` 取**最后 5 条**。
做 A/B 时如果用同一个 (NPC, 玩家)，历史记录会把你想观察的那条挤出尾部，
于是出现「把可信度抬高了，上下文却从 357 字符降到 339 字符」的假象。

**测这类对比必须每次换独立 player**（或用全新账本）。
