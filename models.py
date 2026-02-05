# models.py - Pydantic 与 MongoDB 集合 Schema 定义

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 用户 / Key 管理 ----------


class UserKeyCreate(BaseModel):
    """创建 Key 的请求体。"""

    api_key: str = Field(..., min_length=1, description="API Key 字符串")
    user_name: str = Field(..., min_length=1, description="用户/Key 名称")
    balance_tokens: int = Field(default=0, ge=0, description="初始余额（Token 数）")
    status: str = Field(default="active", description="状态：active / frozen")


class UserKeyUpdate(BaseModel):
    """更新 Key：充值或冻结。"""

    balance_tokens: Optional[int] = Field(None, ge=0, description="充值数量（累加），不传则不改")
    status: Optional[str] = Field(None, description="状态：active / frozen")


class UserKeyInDB(BaseModel):
    """MongoDB 用户集合文档结构（与 DB 一致）。"""

    api_key: str
    user_name: str
    balance_tokens: int = 0
    status: str = "active"  # active | frozen
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


# ---------- OpenAI 协议相关（请求/响应占位，实际由 FastAPI 透传） ----------


class OpenAIErrorBody(BaseModel):
    """OpenAI 规范错误体，用于 insufficient_quota 等。"""

    error: dict  # {"type": "insufficient_quota", "code": "insufficient_quota", "message": "..."}


# ---------- 审计日志 ----------


class AuditLogDoc(BaseModel):
    """单次请求的审计日志文档，写入 audit_logs 集合。"""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None  # 可存 user_name 或 api_key 脱敏
    api_key: str  # 可脱敏：仅后几位
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0
    status_code: int = 200

    class Config:
        from_attributes = True
