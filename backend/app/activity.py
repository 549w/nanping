"""活动日志写入辅助。

在路由中调用 ``log_activity()`` 即可记录用户行为到 activity_log 表。
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ActivityLog

logger = logging.getLogger("nanping.activity")


async def log_activity(
    db: AsyncSession,
    request: Request,
    action: str,
    *,
    user_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict | str | None = None,
) -> None:
    """写入一条活动日志。

    Args:
        db: 数据库会话。
        request: FastAPI Request 对象，用于提取 IP 和 User-Agent。
        action: 操作类型，如 ``"login"``、``"register"``、``"review_create"`` 等。
        user_id: 操作用户 ID（可为空）。
        target_type: 操作目标类型，如 ``"course"``、``"review"``。
        target_id: 操作目标 ID。
        details: 附加信息，dict 会自动转为 JSON 字符串。
    """
    if isinstance(details, dict):
        details = json.dumps(details, ensure_ascii=False)

    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("User-Agent", "")

    entry = ActivityLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=client_ip,
        user_agent=user_agent,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(entry)
    await db.commit()
