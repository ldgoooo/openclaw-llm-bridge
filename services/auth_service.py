# services/auth_service.py - Key 校验与用户信息获取

from typing import Optional

from database import COLL_USERS, get_db
from models import UserKeyInDB
from utils.logger import get_logger

logger = get_logger("auth_service")


async def get_user_by_api_key(api_key: str) -> Optional[UserKeyInDB]:
    """
    根据 api_key 查询用户；仅当 status=active 时视为有效。
    返回 None 表示 Key 无效或已冻结。
    """
    if not api_key or not api_key.strip():
        return None
    db = get_db()
    doc = await db[COLL_USERS].find_one(
        {"api_key": api_key.strip(), "status": "active"},
    )
    if not doc:
        return None
    doc.pop("_id", None)
    return UserKeyInDB(**doc)


async def require_admin_token(token: str) -> bool:
    """校验管理端 token，与环境变量 ADMIN_TOKEN 比对。"""
    from config import get_settings
    admin = get_settings().ADMIN_TOKEN
    return bool(admin and admin.strip() and token == admin.strip())
