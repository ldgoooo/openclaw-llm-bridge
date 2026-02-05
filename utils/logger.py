# utils/logger.py - 系统与访问日志：控制台 + app.log

import logging
import sys
from pathlib import Path

# 统一格式
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_file: str = "app.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """
    配置根 logger：同时输出到控制台和 app.log。
    返回 app 使用的 logger 实例。
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 避免重复添加 handler（例如 reload 时）
    if root.handlers:
        return logging.getLogger("openclaw_llm_bridge")

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件 app.log
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    app_logger = logging.getLogger("openclaw_llm_bridge")
    app_logger.setLevel(level)
    return app_logger


def get_logger(name: str) -> logging.Logger:
    """获取带命名空间的 logger，便于区分模块。"""
    return logging.getLogger(f"openclaw_llm_bridge.{name}")
