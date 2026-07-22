"""插件请求缓存层。

为插件端点的高频数据库查询提供缓存包装：
- `_find_exact_course` → `cached_find_exact_course`
- `_search_courses` → `cached_search_courses`
- `_get_top_reviews` → `cached_get_top_reviews`
- `_get_latest_news` → `cached_get_latest_news`

设计原则：
- 缓存层是包装，原函数保持不变
- 缓存键基于函数参数生成
- 命中时跳过数据库查询
- 支持通过配置禁用缓存
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .cache import TTLCache
from .config import settings

logger = logging.getLogger("nanping.cache")


# ============================================================
# 缓存实例（按功能分类）
# ============================================================

# 课程精确匹配缓存：cache_key = "exact:{code}"
_exact_course_cache = TTLCache(maxsize=500, default_ttl=300)

# 课程搜索缓存：cache_key = "search:{code}:{teacher}:{name}"
_search_cache = TTLCache(maxsize=1000, default_ttl=300)

# 评价缓存：cache_key = "reviews:{course_id}:{limit}"
_reviews_cache = TTLCache(maxsize=500, default_ttl=30)

# 公告缓存：cache_key = "news:{limit}"
_news_cache = TTLCache(maxsize=10, default_ttl=120)


def get_all_caches() -> dict[str, TTLCache]:
    """获取所有缓存实例（调试/监控用）。"""
    return {
        "exact_course": _exact_course_cache,
        "search": _search_cache,
        "reviews": _reviews_cache,
        "news": _news_cache,
    }


def get_all_stats() -> dict:
    """获取所有缓存的统计信息。"""
    return {name: cache.stats() for name, cache in get_all_caches().items()}


async def clear_all_caches() -> int:
    """清空所有缓存，返回清理总数。"""
    total = 0
    for cache in get_all_caches().values():
        total += await cache.clear()
    return total


# ============================================================
# 缓存包装函数
# ============================================================


async def cached_find_exact_course(
    db: AsyncSession,
    code: str,
    name: str,
    teacher_str: str,
    original_func,
) -> Any:
    """缓存版 _find_exact_course。

    缓存键：(code, name, teacher_str)（函数按这三个字段过滤）

    Args:
        db: 数据库会话
        code: 课程号
        name: 课程名
        teacher_str: 教师
        original_func: 原始函数（延迟导入避免循环依赖）

    Returns:
        Course 对象或 None
    """
    if not settings.PLUGIN_CACHE_ENABLED:
        return await original_func(db, code, name, teacher_str)

    cache_key = f"exact:{code}:{name}:{teacher_str}"
    cached = await _exact_course_cache.get(cache_key)

    if cached is not None:
        logger.debug("缓存命中: %s", cache_key)
        return cached

    result = await original_func(db, code, name, teacher_str)
    await _exact_course_cache.set(cache_key, result)
    logger.debug("缓存写入: %s", cache_key)
    return result


async def cached_search_courses(
    db: AsyncSession,
    code: str,
    teacher_str: str,
    name: str,
    original_func,
) -> list:
    """缓存版 _search_courses。

    缓存键：(code, teacher_str, name)

    Args:
        db: 数据库会话
        code: 课程号筛选
        teacher_str: 教师筛选
        name: 课程名筛选
        original_func: 原始函数

    Returns:
        [(Course, review_count, avg_rating), ...] 列表
    """
    if not settings.PLUGIN_CACHE_ENABLED:
        return await original_func(db, code, teacher_str, name)

    cache_key = f"search:{code}:{teacher_str}:{name}"
    cached = await _search_cache.get(cache_key)

    if cached is not None:
        logger.debug("缓存命中: %s", cache_key)
        return cached

    result = await original_func(db, code, teacher_str, name)
    await _search_cache.set(cache_key, result)
    logger.debug("缓存写入: %s", cache_key)
    return result


async def cached_get_top_reviews(
    db: AsyncSession,
    course_id: int,
    limit: int,
    original_func,
) -> list:
    """缓存版 _get_top_reviews。

    缓存键：(course_id, limit)

    Args:
        db: 数据库会话
        course_id: 课程 ID
        limit: 返回数量
        original_func: 原始函数

    Returns:
        [ReviewItem, ...] 列表
    """
    if not settings.PLUGIN_CACHE_ENABLED:
        return await original_func(db, course_id, limit)

    cache_key = f"reviews:{course_id}:{limit}"
    cached = await _reviews_cache.get(cache_key)

    if cached is not None:
        logger.debug("缓存命中: %s", cache_key)
        return cached

    result = await original_func(db, course_id, limit)
    await _reviews_cache.set(cache_key, result)
    logger.debug("缓存写入: %s", cache_key)
    return result


async def cached_get_latest_news(
    db: AsyncSession,
    limit: int,
    original_func,
) -> list:
    """缓存版 _get_latest_news。

    缓存键：limit

    Args:
        db: 数据库会话
        limit: 返回数量
        original_func: 原始函数

    Returns:
        [NewsItem, ...] 列表
    """
    if not settings.PLUGIN_CACHE_ENABLED:
        return await original_func(db, limit)

    cache_key = f"news:{limit}"
    cached = await _news_cache.get(cache_key)

    if cached is not None:
        logger.debug("缓存命中: %s", cache_key)
        return cached

    result = await original_func(db, limit)
    await _news_cache.set(cache_key, result)
    logger.debug("缓存写入: %s", cache_key)
    return result
