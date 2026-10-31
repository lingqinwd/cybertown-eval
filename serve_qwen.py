"""Minimal OpenAI-compatible server for Qwen2.5-1.5B-Instruct.

Replacement for `vllm.entrypoints.openai.api_server` when the image has no
usable vLLM wheel (e.g. AMD/ROCm, where the PyPI vllm wheel is CUDA-only).
It speaks just enough of the OpenAI protocol for HelloAgentsLLM:

    GET  /v1/models
    POST /v1/chat/completions
    GET  /health

Run (AUP terminal, after a FRESH restart so ROCm torch is intact):

    cd ~/cybertown-eval
    python3 serve_qwen.py

Then in the backend shell:

    export LLM_BASE_URL=http://127.0.0.1:8001/v1
"""

import os
import time
import uuid

import torch
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = os.getenv("SERVE_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
PORT = int(os.getenv("SERVE_PORT", "8001"))
MAX_NEW_DEFAULT = int(os.getenv("SERVE_MAX_NEW_TOKENS", "256"))


def pick_device() -> str:
    """SERVE_DEVICE=auto|cpu|cuda. auto = GPU if torch can really see one."""
    want = os.getenv("SERVE_DEVICE", "auto").strip().lower()
    if want == "cpu":
        return "cpu"
    if want in ("cuda", "gpu"):
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"


def pick_dtype(device: str):
    name = os.getenv("SERVE_DTYPE", "").strip().lower()
    if name == "float32":
        return torch.float32
    if name in ("bfloat16", "bf16"):
        return torch.bfloat16
    if name == "float16":
        return torch.float16
    # CPU: float32 is both correct and usually faster than emulated bf16.
    return torch.float32 if device == "cpu" else torch.bfloat16


def load_model():
    device = pick_device()
    dtype = pick_dtype(device)
    print(f"[serve] loading {MODEL_ID}  target={device}  dtype={dtype}", flush=True)
    if device == "cpu" and torch.cuda.is_available():
        print("[serve] NOTE: GPU visible but SERVE_DEVICE=cpu -> CPU mode", flush=True)
    if device == "cuda" and not torch.cuda.is_available():
        print("[serve] NOTE: cuda requested but torch cannot see a GPU; "
              "falling back to CPU", flush=True)
        device = "cpu"
        dtype = pick_dtype(device)

    tok = AutoTokenizer.from_pretrained(MODEL_ID)

    model = None
    last = None
    # transformers v5 uses dtype=, v4 used torch_dtype=; accept both.
    for kw in ("dtype", "torch_dtype"):
        try:
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID, device_map=device, **{kw: dtype}
            )
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"[serve] device_map={device} with {kw}= failed: {exc}", flush=True)

    if model is None:
        # Last resort: plain load, then move manually (no accelerate needed).
        print("[serve] falling back to plain load + manual .to()", flush=True)
        try:
            model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=dtype)
            model = model.to(device)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"[serve] cannot load model: {last} / {exc}")

    model.eval()
    dev = next(model.parameters()).device
    dt = next(model.parameters()).dtype
    print(f"[serve] ready  device={dev}  dtype={dt}", flush=True)
    return tok, model, dev


TOKENIZER, MODEL, DEVICE = load_model()
APP = FastAPI(title="qwen-openai-shim")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[Message]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False


@APP.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "model": MODEL_ID, "device": str(DEVICE)}


@APP.get("/v1/models")
def list_models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}],
    }


@APP.post("/v1/chat/completions")
def chat_completions(req: ChatRequest) -> Dict[str, Any]:
    t0 = time.perf_counter()

    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    prompt = TOKENIZER.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = TOKENIZER(prompt, return_tensors="pt").to(DEVICE)

    temperature = req.temperature if req.temperature is not None else 0.7
    max_new = req.max_tokens or MAX_NEW_DEFAULT

    gen_kwargs: Dict[str, Any] = {
        "max_new_tokens": max_new,
        "pad_token_id": TOKENIZER.eos_token_id,
    }
    if temperature > 0:
        gen_kwargs.update(do_sample=True, temperature=temperature, top_p=req.top_p)
    else:
        gen_kwargs.update(do_sample=False)

    with torch.no_grad():
        out = MODEL.generate(**inputs, **gen_kwargs)

    n_prompt = int(inputs["input_ids"].shape[1])
    text = TOKENIZER.decode(out[0][n_prompt:], skip_special_tokens=True)
    n_new = int(out.shape[1] - n_prompt)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": n_prompt,
            "completion_tokens": n_new,
            "total_tokens": n_prompt + n_new,
        },
        # extra field, harmless for OpenAI clients, handy for your latency table
        "latency_ms": latency_ms,
    }


if __name__ == "__main__":
    uvicorn.run(APP, host="0.0.0.0", port=PORT)
