# services/audit_service.py - 请求审计写入 MongoDB

from database import COLL_AUDIT_LOGS, get_db
from models import AuditLogDoc
from utils.logger import get_logger

logger = get_logger("audit_service")


async def write_audit_log(doc: AuditLogDoc) -> None:
    """将单次请求审计写入 audit_logs 集合（ fire-and-forget，不阻塞响应）。"""
    try:
        db = get_db()
        await db[COLL_AUDIT_LOGS].insert_one(doc.model_dump())
    except Exception as e:
        logger.exception("写入审计日志失败: %s", e)
