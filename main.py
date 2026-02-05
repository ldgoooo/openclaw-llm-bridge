# main.py - openclaw-llm-bridge 路由入口：OpenAI 兼容 /v1/chat/completions + 管理端

import json
import time
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import get_settings
from database import get_db
from models import AuditLogDoc, UserKeyCreate, UserKeyUpdate
from services import audit_service, auth_service, billing_service, proxy_service
from utils.logger import get_logger, setup_logging
from utils.token_counter import count_tokens_text_async

# 启动时配置日志：控制台 + app.log
setup_logging()
logger = get_logger("main")

app = FastAPI(
    title="OpenClaw LLM Bridge",
    description="OpenAI 协议兼容网关，Token 计费与审计",
    version="1.0.0",
)

# ---------- 依赖 ----------


def _get_bearer_key(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[7:].strip()


def _openai_error(code: str, message: str, status: int = 400) -> dict:
    """符合 OpenAI 规范的错误体。"""
    return {
        "error": {
            "type": code,
            "code": code,
            "message": message,
        }
    }


# ---------- /v1/chat/completions（代理 + 计费 + 审计） ----------


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(None),
):
    """
    模拟 OpenAI /v1/chat/completions，支持流式 SSE。
    校验 api_key、预检余额、调用 LiteLLM、原子扣费、写审计日志。
    """
    start = time.perf_counter()
    api_key = _get_bearer_key(authorization)
    if not api_key:
        raise HTTPException(status_code=401, detail=_openai_error("invalid_request_error", "Missing or invalid Authorization header"))

    user = await auth_service.get_user_by_api_key(api_key)
    if not user:
        raise HTTPException(
            status_code=401,
            detail=_openai_error("invalid_api_key", "Invalid API key or key is frozen"),
        )

    try:
        body = await request.json()
    except Exception as e:
        logger.warning("chat_completions 解析 body 失败: %s", e)
        raise HTTPException(status_code=400, detail=_openai_error("invalid_request_error", "Invalid JSON body"))

    messages = body.get("messages") or []
    if not messages:
        raise HTTPException(status_code=400, detail=_openai_error("invalid_request_error", "messages is required"))
    stream = body.get("stream", False)
    model = body.get("model") or get_settings().LLM_MODEL

    # 输入 token 估算与余额预检（预留一定 output 空间，避免流中途欠费）
    try:
        input_tokens_est = await proxy_service.estimate_input_tokens(messages)
    except Exception as e:
        logger.exception("estimate_input_tokens 失败: %s", e)
        input_tokens_est = 0
    reserve = max(256, input_tokens_est)  # 至少预留 256 作为 output
    if not await billing_service.check_balance(api_key, reserve):
        raise HTTPException(
            status_code=402,
            detail=_openai_error("insufficient_quota", "Insufficient balance. Please recharge your account."),
        )

    # 调用 LiteLLM
    try:
        chunk_iter = proxy_service.stream_completion(
            messages=messages,
            model=model,
            stream=True,
            **{k: v for k, v in body.items() if k not in ("messages", "model", "stream")},
        )
    except Exception as e:
        logger.exception("LiteLLM stream_completion 失败: %s", e)
        raise HTTPException(status_code=502, detail=_openai_error("api_error", str(e)))

    collected_content: list[str] = []
    usage_from_chunk: dict[str, int] = {}

    async def _consume_stream():
        nonlocal usage_from_chunk
        async for chunk in chunk_iter:
            choices = chunk.get("choices") or []
            if choices and isinstance(choices[0], dict):
                delta = (choices[0] or {}).get("delta") or {}
                if isinstance(delta, dict) and delta.get("content"):
                    collected_content.append(delta["content"])
                # 流式末尾可能带 usage
                u = (choices[0] or {}).get("usage") or chunk.get("usage")
                if u and isinstance(u, dict):
                    usage_from_chunk["input_tokens"] = u.get("input_tokens") or u.get("prompt_tokens") or 0
                    usage_from_chunk["output_tokens"] = u.get("output_tokens") or u.get("completion_tokens") or 0
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    if stream:
        async def _stream_with_billing():
            gen = _consume_stream()
            try:
                async for part in gen:
                    yield part
            finally:
                # 流结束后执行扣费与审计（在生成器 finally 中执行）
                await _after_stream_billing_and_audit(
                    api_key=api_key,
                    user_name=user.user_name,
                    model=model,
                    messages=messages,
                    collected_content=collected_content,
                    usage_from_chunk=usage_from_chunk,
                    start=start,
                    status_code=200,
                )
        return StreamingResponse(
            _stream_with_billing(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # 非流式：消费同一迭代器并收集 content / usage
    full_chunks: list[dict] = []
    async for c in chunk_iter:
        full_chunks.append(c)
        choices = c.get("choices") or []
        if choices and isinstance(choices[0], dict):
            delta = (choices[0] or {}).get("delta") or {}
            if isinstance(delta, dict) and delta.get("content"):
                collected_content.append(delta["content"])
            u = (choices[0] or {}).get("usage") or c.get("usage")
            if u and isinstance(u, dict):
                usage_from_chunk["input_tokens"] = u.get("input_tokens") or u.get("prompt_tokens") or 0
                usage_from_chunk["output_tokens"] = u.get("output_tokens") or u.get("completion_tokens") or 0
    # 合并为单条 OpenAI 格式响应（取最后一条的 id/model，choices 合并 content）
    input_tokens_final = usage_from_chunk.get("input_tokens")
    output_tokens_final = usage_from_chunk.get("output_tokens")
    if input_tokens_final is None:
        input_tokens_final = input_tokens_est
    if output_tokens_final is None:
        output_tokens_final = await count_tokens_text_async("".join(collected_content))
    total = input_tokens_final + output_tokens_final
    ok = await billing_service.deduct_tokens(api_key, total)
    if not ok:
        logger.warning("扣费失败 api_key=%s total=%s", api_key[:8] + "***", total)
        raise HTTPException(status_code=402, detail=_openai_error("insufficient_quota", "Insufficient balance after completion."))
    duration_ms = (time.perf_counter() - start) * 1000
    await audit_service.write_audit_log(
        AuditLogDoc(
            api_key=api_key[:8] + "***",
            user_id=user.user_name,
            model=model,
            input_tokens=input_tokens_final,
            output_tokens=output_tokens_final,
            total_tokens=total,
            duration_ms=duration_ms,
            status_code=200,
        )
    )
    # 非流式时构造一条完整响应返回
    last = full_chunks[-1] if full_chunks else {}
    merged = {
        "id": last.get("id", "chatcmpl-bridge"),
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(collected_content)},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens_final,
            "completion_tokens": output_tokens_final,
            "total_tokens": total,
        },
    }
    return merged


async def _after_stream_billing_and_audit(
    api_key: str,
    user_name: str,
    model: str,
    messages: list,
    collected_content: list[str],
    usage_from_chunk: dict,
    start: float,
    status_code: int,
):
    """流式结束后：计算 token、扣费、写审计。"""
    input_tokens_est = await proxy_service.estimate_input_tokens(messages)
    input_tokens_final = usage_from_chunk.get("input_tokens")
    output_tokens_final = usage_from_chunk.get("output_tokens")
    if input_tokens_final is None:
        input_tokens_final = input_tokens_est
    if output_tokens_final is None:
        output_tokens_final = await count_tokens_text_async("".join(collected_content))
    total = input_tokens_final + output_tokens_final
    await billing_service.deduct_tokens(api_key, total)
    duration_ms = (time.perf_counter() - start) * 1000
    await audit_service.write_audit_log(
        AuditLogDoc(
            api_key=api_key[:8] + "***",
            user_id=user_name,
            model=model,
            input_tokens=input_tokens_final,
            output_tokens=output_tokens_final,
            total_tokens=total,
            duration_ms=duration_ms,
            status_code=status_code,
        )
    )


# ---------- 管理端：Key 管理（需 ADMIN_TOKEN） ----------


async def require_admin(authorization: str | None = Header(None)) -> None:
    """管理端接口：校验 Authorization: Bearer <ADMIN_TOKEN>。"""
    token = _get_bearer_key(authorization)
    if not await auth_service.require_admin_token(token):
        raise HTTPException(status_code=403, detail={"detail": "Invalid or missing admin token"})


@app.post("/admin/keys")
async def admin_create_key(
    payload: UserKeyCreate,
    authorization: str | None = Header(None),
):
    """创建新 Key。"""
    await require_admin(authorization)
    db = get_db()
    from database import COLL_USERS
    existing = await db[COLL_USERS].find_one({"api_key": payload.api_key})
    if existing:
        raise HTTPException(status_code=400, detail="api_key already exists")
    doc = {
        "api_key": payload.api_key,
        "user_name": payload.user_name,
        "balance_tokens": payload.balance_tokens,
        "status": payload.status,
        "created_at": datetime.utcnow(),
    }
    await db[COLL_USERS].insert_one(doc)
    return {"ok": True, "api_key": payload.api_key, "user_name": payload.user_name, "balance_tokens": payload.balance_tokens, "status": payload.status}


@app.get("/admin/keys")
async def admin_list_keys(
    authorization: str | None = Header(None),
):
    """查看所有 Key 及余额。"""
    await require_admin(authorization)
    db = get_db()
    from database import COLL_USERS
    cursor = db[COLL_USERS].find({}, {"_id": 0, "api_key": 1, "user_name": 1, "balance_tokens": 1, "status": 1, "created_at": 1})
    keys = []
    async for doc in cursor:
        keys.append(doc)
    return {"keys": keys}


@app.patch("/admin/keys/{api_key:path}")
async def admin_update_key(
    api_key: str,
    payload: UserKeyUpdate,
    authorization: str | None = Header(None),
):
    """充值或冻结 Key。"""
    await require_admin(authorization)
    db = get_db()
    from database import COLL_USERS
    update: dict = {}
    if payload.balance_tokens is not None:
        update["$inc"] = {"balance_tokens": payload.balance_tokens}
    if payload.status is not None:
        update["$set"] = update.get("$set", {})
        update["$set"]["status"] = payload.status
    if not update:
        return {"ok": True, "message": "no changes"}
    # 合并 $inc 与 $set 到同一次 update
    result = await db[COLL_USERS].update_one({"api_key": api_key}, update)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="api_key not found")
    return {"ok": True, "matched": result.matched_count, "modified": result.modified_count}


# ---------- 访问日志中间件 ----------


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """将请求方法与路径、状态码写入日志（控制台 + app.log）。"""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "access | %s %s | %s | %.2f ms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
