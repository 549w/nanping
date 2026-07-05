"""公告路由。

GET /news — 获取当前有效的公告列表。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import News
from ..schemas import NewsItem

router = APIRouter(tags=["公告"])


async def _get_latest_news(db: AsyncSession, limit: int = 5) -> list[NewsItem]:
    """获取最新公告（供其他路由复用的内部函数）。"""
    result = await db.execute(
        select(News)
        .where(News.is_active == 1)
        .order_by(News.created_at.desc())
        .limit(limit)
    )
    return [NewsItem.model_validate(r) for r in result.scalars().all()]


@router.get("/news", response_model=list[NewsItem])
async def list_news(
    limit: int = Query(5, ge=1, le=20, description="返回条数"),
    db: AsyncSession = Depends(get_db),
) -> list[NewsItem]:
    """获取最新公告。

    返回 is_active=1 的公告，按发布时间倒序。
    插件和前端首页可调用此接口展示运营通知。
    """
    return await _get_latest_news(db, limit)
