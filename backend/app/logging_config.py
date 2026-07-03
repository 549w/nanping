"""日志配置。

使用 Python 内置 logging 模块，输出 JSON 结构化日志到 stdout，
Docker 容器自动捕获。开发环境用人类可读格式。
"""

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class JsonFormatter(logging.Formatter):
    """JSON 结构化日志格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """初始化全局日志配置。

    开发环境（AUTH_MOCK_MODE=true）：人类可读的彩色终端输出
    生产环境：JSON 结构化输出到 stdout

    Args:
        level: 日志级别，默认 INFO。
    """
    from .config import settings

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler（避免重复添加）
    root.handlers.clear()

    if settings.AUTH_MOCK_MODE:
        # 开发环境：人类可读
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    else:
        # 生产环境：JSON
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())

    root.addHandler(handler)

    # 降低第三方库日志噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。

    Args:
        name: 模块名，通常传 ``__name__``。

    Returns:
        对应模块的 Logger 实例。
    """
    return logging.getLogger(name)
