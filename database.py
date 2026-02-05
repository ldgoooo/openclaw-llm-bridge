# database.py - MongoDB 异步连接（motor）

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import get_mongodb_database, get_settings
from utils.logger import get_logger

logger = get_logger("database")

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncIOMotorClient(s.MONGODB_URI)
        logger.info("MongoDB client 已创建: %s", s.MONGODB_URI)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        _db = get_client()[get_mongodb_database()]
    return _db


# 集合名常量
COLL_USERS = "users"
COLL_AUDIT_LOGS = "audit_logs"
