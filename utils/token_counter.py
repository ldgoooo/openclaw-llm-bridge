# utils/token_counter.py - 基于 tiktoken 的异步 Token 计数

import asyncio
from typing import Any

import tiktoken

from utils.logger import get_logger

logger = get_logger("token_counter")

# 默认编码，与 GPT 系列兼容
_DEFAULT_ENCODING = "cl100k_base"
_encoding: tiktoken.Encoding | None = None


def _get_encoding(encoding_name: str = _DEFAULT_ENCODING) -> tiktoken.Encoding:
    """懒加载 tiktoken 编码（同步）。"""
    global _encoding
    if _encoding is None:
        try:
            _encoding = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            logger.warning("tiktoken get_encoding %s 失败，回退 cl100k_base: %s", encoding_name, e)
            _encoding = tiktoken.get_encoding(_DEFAULT_ENCODING)
    return _encoding


def count_tokens_sync(messages: list[dict[str, Any]], encoding_name: str = _DEFAULT_ENCODING) -> int:
    """
    根据 OpenAI 规则估算 messages 的 token 数（同步）。
    用于请求体解析后的 input 估算。
    """
    enc = _get_encoding(encoding_name)
    # 与 OpenAI 的计数方式近似：每 message 有 3-4 个额外 token，再按内容计
    total = 0
    for msg in messages:
        total += 4  # 每条消息的开销
        for k, v in msg.items():
            if isinstance(v, str):
                total += len(enc.encode(v))
            else:
                total += len(enc.encode(str(v)))
    return total


async def count_tokens_async(
    messages: list[dict[str, Any]],
    encoding_name: str = _DEFAULT_ENCODING,
) -> int:
    """在线程池中执行计数，避免阻塞事件循环。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: count_tokens_sync(messages, encoding_name),
    )


async def count_tokens_text_async(text: str, encoding_name: str = _DEFAULT_ENCODING) -> int:
    """对单段文本计数的异步封装。"""
    def _count() -> int:
        return len(_get_encoding(encoding_name).encode(text))

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _count)
