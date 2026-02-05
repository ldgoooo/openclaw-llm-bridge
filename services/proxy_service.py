# services/proxy_service.py - 通过 LiteLLM 调用后端并支持流式与计费

import json
import time
from typing import Any, AsyncIterator

import litellm
from litellm import acompletion

from config import get_settings
from utils.logger import get_logger
from utils.token_counter import count_tokens_async

logger = get_logger("proxy_service")


def _get_litellm_model() -> str:
    """返回 LiteLLM 使用的 Azure 模型名。"""
    s = get_settings()
    return f"azure/{s.LLM_MODEL}"


def _litellm_kwargs() -> dict[str, Any]:
    """从配置构建 litellm 调用的 api_base / api_key / api_version。"""
    s = get_settings()
    return {
        "api_base": s.LLM_ENDPOINT.rstrip("/"),
        "api_key": s.LLM_API_KEY,
        "api_version": s.LLM_API_VERSION,
    }


async def estimate_input_tokens(messages: list[dict[str, Any]]) -> int:
    """异步估算输入 token 数，用于预检余额。"""
    s = get_settings()
    return await count_tokens_async(messages, s.TIKTOKEN_ENCODING)


async def stream_completion(
    messages: list[dict[str, Any]],
    model: str | None = None,
    stream: bool = True,
    **kwargs: Any,
) -> AsyncIterator[dict]:
    """
    通过 LiteLLM 发起异步 completion，支持流式。
    返回 chunk 的异步迭代器（每个 chunk 为 OpenAI 兼容的 dict）。
    调用方需在消费流时收集 content 与最后一个 chunk 的 usage，用于计费。
    """
    litellm_model = _get_litellm_model()
    litellm_kw = _litellm_kwargs()
    all_kw: dict[str, Any] = {
        "model": litellm_model,
        "messages": messages,
        "stream": stream,
        **litellm_kw,
        **kwargs,
    }
    if stream:
        all_kw.setdefault("stream_options", {})["include_usage"] = True

    response = await acompletion(**all_kw)
    async for chunk in response:
        if hasattr(chunk, "model_dump"):
            c = chunk.model_dump()
        elif hasattr(chunk, "dict"):
            c = chunk.dict()
        else:
            c = dict(chunk) if chunk else {}
        yield c


def build_sse_line(data: dict) -> str:
    """将一条 JSON 转为 SSE 行：data: {...}\n\n"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
