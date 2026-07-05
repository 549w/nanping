"""插件统一路由。

POST /plugin — 一次性返回插件渲染所需的全部数据（匹配结果、公告、提示配置）。
"""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import log_activity
from ..database import get_db
from ..schemas import (
    BatchMatchRequest,
    MatchResult,
    PluginResponse,
    PluginToastConfig,
)
from .courses import _match_one
from .news import _get_latest_news

logger = logging.getLogger("nanping.plugin")
router = APIRouter(tags=["插件"])


@router.post("/plugin", response_model=PluginResponse)
async def plugin_endpoint(
    data: BatchMatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PluginResponse:
    """插件统一入口。

    一次请求完成课程匹配、公告查询和提示文案生成，
    所有内部逻辑复用 courses._match_one 和 news._get_latest_news。
    """
    # ---- 1. 课程匹配（复用 courses._match_one） ----
    results: list[MatchResult] = []
    matched_count = 0
    for idx, query in enumerate(data.queries):
        result = await _match_one(idx, query, db)
        if result.matched:
            matched_count += 1
        results.append(result)

    # ---- 2. 最新公告（复用 news._get_latest_news） ----
    news_items = await _get_latest_news(db, limit=3)

    # ---- 3. 构建 toast 配置 ----
    if matched_count > 0:
        success_msg = f"加载成功，匹配到 {matched_count} 条评价"
    else:
        success_msg = "加载完成，暂无匹配的评价"

    toast = PluginToastConfig(
        loading="「南评」正在加载评论...",
        success=success_msg,
        error="加载失败，请检查网络连接",
    )

    # ---- 4. 活动日志 ----
    detail: dict = {
        "query_count": len(data.queries),
        "matched_count": matched_count,
    }
    if data.username:
        detail["username"] = data.username
    if data.gender:
        detail["gender"] = data.gender
    await log_activity(db, request, "plugin_query", details=detail)

    logger.info(
        "插件统一请求: queries=%d matched=%d username=%s gender=%s",
        len(data.queries),
        matched_count,
        data.username or "未知",
        data.gender or "未知",
    )

    return PluginResponse(toast=toast, news=news_items, results=results)
