"""定位「所有嵌入模型都不可用」的真实原因：逐个分支试，打印 traceback。"""
import os
import traceback

os.environ["EMBED_MODEL_TYPE"] = "local"
os.environ["EMBED_MODEL_NAME"] = "all-MiniLM-L6-v2"

print("python:", os.sys.executable)
print("EMBED_MODEL_TYPE:", os.getenv("EMBED_MODEL_TYPE"))
print("EMBED_MODEL_NAME:", os.getenv("EMBED_MODEL_NAME"))

print("\n--- 1) 直接 import sentence_transformers ---")
try:
    import sentence_transformers  # noqa: F401
    print("ok", sentence_transformers.__version__)
except Exception:
    traceback.print_exc()

print("\n--- 2) 直接构造 LocalTransformerEmbedding ---")
try:
    from hello_agents.memory.embedding import LocalTransformerEmbedding

    emb = LocalTransformerEmbedding(model_name="all-MiniLM-L6-v2")
    vec = emb.encode(["测试文本"])
    print("ok, dim =", len(vec[0]))
except Exception:
    traceback.print_exc()

print("\n--- 3) 走工厂函数（hello_agents 实际调用路径）---")
try:
    from hello_agents.memory.embedding import create_embedding_model_with_fallback

    model = create_embedding_model_with_fallback(
        preferred_type="local", model_name="all-MiniLM-L6-v2"
    )
    print("ok:", type(model).__name__)
except Exception:
    traceback.print_exc()
