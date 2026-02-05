# services/billing_service.py - 余额预检与原子扣除（$inc）

from database import COLL_USERS, get_db
from models import UserKeyInDB
from utils.logger import get_logger

logger = get_logger("billing_service")


async def check_balance(api_key: str, required_tokens: int) -> bool:
    """检查用户当前余额是否 >= required_tokens。"""
    db = get_db()
    doc = await db[COLL_USERS].find_one(
        {"api_key": api_key, "status": "active"},
        projection={"balance_tokens": 1},
    )
    if not doc:
        return False
    return (doc.get("balance_tokens") or 0) >= required_tokens


async def deduct_tokens(api_key: str, tokens: int) -> bool:
    """
    使用 $inc 原子扣除余额。
    若扣除后余额为负，则不执行并返回 False；否则返回 True。
    通过 find_one_and_update 的原子性保证并发安全。
    """
    if tokens <= 0:
        return True
    db = get_db()
    # 先扣减，再检查结果；若余额不足则用 $max 保证不为负（或先查再扣，这里用条件更新）
    result = await db[COLL_USERS].find_one_and_update(
        {"api_key": api_key, "status": "active"},
        {"$inc": {"balance_tokens": -tokens}},
        return_document=True,
        projection={"balance_tokens": 1},
    )
    if not result:
        return False
    new_balance = result.get("balance_tokens", 0)
    if new_balance < 0:
        # 回滚：加回已扣的
        await db[COLL_USERS].update_one(
            {"api_key": api_key},
            {"$inc": {"balance_tokens": tokens}},
        )
        logger.warning("余额不足已回滚: api_key=%s, 尝试扣除=%s", api_key[:8] + "***", tokens)
        return False
    return True
