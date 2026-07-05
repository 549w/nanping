"""插件统一路由 v2。

POST /plugin — 后端全控渲染。
所有 UI 由后端生成 HTML 片段，插件仅做机械 innerHTML 注入。
"""

import html as html_mod
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import log_activity
from ..database import get_db
from ..schemas import (
    PluginCourseResult,
    PluginQuery,
    PluginRequest,
    PluginResponse,
    PluginToastConfig,
    PluginWidget,
)
from .courses import _match_one
from .news import _get_latest_news

logger = logging.getLogger("nanping.plugin")
router = APIRouter(tags=["插件"])


# ============================================================
# HTML 模板函数 —— CSS class 与插件 INLINE_STYLES/Shadow DOM 一致
# ============================================================


def _esc(text: str) -> str:
    """HTML 转义。"""
    if not text:
        return ""
    return html_mod.escape(str(text), quote=True)


def _render_stars(rating: float | None) -> str:
    """渲染星级 HTML（★☆☆☆☆）。"""
    if rating is None:
        return ""
    r = min(max(rating, 0), 5)
    full = int(r)
    half = 1 if r - full >= 0.5 else 0
    empty = 5 - full - half
    parts = []
    parts.extend('<span class="np-star-full">★</span>' for _ in range(full))
    if half:
        parts.append('<span class="np-star-half">★</span>')
    parts.extend('<span class="np-star-empty">☆</span>' for _ in range(empty))
    return f'<span class="np-stars">{"".join(parts)}</span>'


def _render_match_tags(match_level: str) -> str:
    """渲染匹配字段标签。"""
    FIELD_MAP = {
        "code": ("课程号", "code"),
        "teacher": ("教师", "teacher"),
        "name": ("课程名", "name"),
    }
    if not match_level:
        return ""
    parts = []
    for f in match_level.split("+"):
        if f in FIELD_MAP:
            label, cls = FIELD_MAP[f]
            parts.append(f'<span class="np-badge-tag np-tag-{cls}">匹配{label}</span>')
    return "".join(parts)


def _render_badge_html(result, exact_course_id: int | None) -> str:
    """渲染课程行内评分徽章 HTML。

    无匹配时显示"暂无评价"，有匹配时显示星级 + 标签 + 按钮。
    """
    matched = result.matched if result else []
    if not matched:
        html = '<span class="np-badge-none">暂无评价</span>'
        if exact_course_id:
            html += (
                ' <a class="np-badge-write"'
                f' href="https://nanping.eznju.com/course.html?from=plugin_v0.2.0_inline&id={exact_course_id}"'
                ' target="_blank">写评价</a>'
            )
        return html

    best = matched[0]
    c = best.course
    match_level = getattr(best, "match_level", "")

    parts = []
    # 匹配标签
    tags = _render_match_tags(match_level)
    if tags:
        parts.append(tags)

    # 评分
    if c.avg_rating is not None:
        parts.append(_render_stars(c.avg_rating))
        parts.append(f'<span class="np-badge-rating">{c.avg_rating:.1f}</span>')

    # 评价数
    parts.append(f'<span class="np-badge-count">{c.review_count}条评价</span>')

    # 查看按钮
    parts.append('<button class="np-badge-btn">查看评价</button>')

    # 写评价链接
    if exact_course_id:
        parts.append(
            f' <a class="np-badge-write"'
            f' href="https://nanping.eznju.com/course.html?from=plugin_v0.2.0_inline&id={exact_course_id}"'
            f' target="_blank">写评价</a>'
        )

    return "".join(parts)


def _render_review_item(r) -> str:
    """渲染单条评价 HTML。"""
    author = "匿名用户" if r.is_anonymous else (getattr(r, "user_email", None) or "未知用户")
    time_str = ""
    if r.created_at:
        try:
            dt = datetime.fromisoformat(str(r.created_at).replace("Z", "+00:00"))
            time_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            time_str = str(r.created_at)[:10]

    rating_html = f'<span class="np-review-rating">⭐ {r.rating}</span>' if r.rating else ""
    semester = _esc(getattr(r, "semester", None) or "")

    return (
        f'<div class="np-review-item" data-review-id="{r.id}">'
        f'  <div class="np-review-header">'
        f'    <span class="np-review-author">{_esc(author)}</span>'
        f"    {rating_html}"
        f"  </div>"
        f'  <div class="np-review-content">{_esc(r.content)}</div>'
        f'  <div class="np-review-meta">'
        f'    <span class="np-review-semester">{semester}</span>'
        f'    <span class="np-review-time">{time_str}</span>'
        f"  </div>"
        f"</div>"
    )


def _render_panel_html(one_result) -> str:
    """渲染侧边面板内容（所有匹配课程 + 最新评价）。"""
    matched = one_result.matched if one_result else []
    if not matched:
        return ""

    parts = []
    for item in matched:
        c = item.course
        field_tags = _render_match_tags(getattr(item, "match_level", "") or "")
        reviews = getattr(item, "top_reviews", []) or []

        parts.append(
            f'<div class="np-course-card" data-course-id="{c.id}">'
            f'  <div class="np-course-header-row">'
            f'    <div>'
            f'      <div class="np-course-code">{_esc(c.code)}</div>'
            f'      <div class="np-course-name">{_esc(c.name)}</div>'
            f'      <div class="np-course-teacher">{_esc(c.teacher)}</div>'
            f"    </div>"
            f'    <div style="display:flex;flex-direction:column;gap:4px;align-items:flex-end;">{field_tags}</div>'
            f"  </div>"
            f'  <div class="np-course-stats">'
        )

        if c.avg_rating is not None:
            parts.append(f'<span class="np-rating">⭐ {c.avg_rating:.1f}</span>')
        else:
            parts.append('<span class="np-rating-none">暂无评分</span>')

        parts.append(
            f'    <span class="np-review-count">{c.review_count} 条评价</span>'
            f'    <a class="np-write-review-btn"'
            f' href="https://nanping.eznju.com/course.html?from=plugin_v0.2.0_panel&id={c.id}"'
            f' target="_blank">写评价</a>'
            f"  </div>"
            f'  <div class="np-section-title">最新评价</div>'
        )

        parts.extend(_render_review_item(r) for r in reviews)

        if c.review_count > len(reviews):
            parts.append(
                f'<button class="np-load-more" data-course-id="{c.id}" data-page="0">'
                f"加载更多评价 ▼</button>"
            )

        parts.append("</div>")

    return "".join(parts)


def _render_news_html(news_items) -> str:
    """渲染面板顶部公告卡片 HTML。"""
    if not news_items:
        return ""
    news = news_items[0]
    if not news.title:
        return ""

    preview = news.content or ""
    if len(preview) > 80:
        preview = preview[:80] + "..."

    return (
        '<div class="np-news-card">'
        '  <div class="np-news-card-header">'
        '    <span class="np-news-card-icon">&#x1F4E2;</span>'
        '    <span class="np-news-card-label">最新公告</span>'
        "  </div>"
        f'  <div class="np-news-card-title">{_esc(news.title)}</div>'
        + (f'  <div class="np-news-card-preview">{_esc(preview)}</div>' if preview else "")
        + '  <a class="np-news-card-link" href="https://nanping.eznju.com" target="_blank">查看详情 →</a>'
        + "</div>"
    )


# ============================================================
# POST /plugin - 统一入口
# ============================================================


@router.post("/plugin", response_model=PluginResponse)
async def plugin_endpoint(
    data: PluginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PluginResponse:
    """插件统一入口 v2。

    一次请求完成课程匹配、公告查询、HTML 预渲染。
    返回的 badge_html / panel_html / news_html 由插件直接 innerHTML 注入。
    """
    # ---- 1. 课程匹配（复用 courses._match_one） ----
    course_results: list[PluginCourseResult] = []
    matched_count = 0

    for idx, pq in enumerate(data.queries):
        # 构造 MatchQuery 兼容对象
        q = type("_MQ", (), {
            "code": pq.code,
            "teacher": pq.teacher,
            "name": pq.name,
        })()

        result = await _match_one(idx, q, db)
        if result.matched:
            matched_count += 1

        exact_id = result.exact_course_id
        badge_html = _render_badge_html(result, exact_id)
        panel_html = _render_panel_html(result)

        course_results.append(
            PluginCourseResult(
                badge_html=badge_html,
                panel_html=panel_html,
                exact_course_id=exact_id,
                load_more_endpoint=f"/review?course_id={exact_id}&page=1" if exact_id else None,
            )
        )

    # ---- 2. 最新公告 ----
    news_items = await _get_latest_news(db, limit=1)
    news_html = _render_news_html(news_items)

    # ---- 3. Toast 文案 ----
    if matched_count > 0:
        success_msg = f"加载成功，匹配到 {matched_count} 条评价"
    else:
        success_msg = "加载完成，暂无匹配的评价"

    toast = PluginToastConfig(
        loading="「南评」正在加载评论...",
        success=success_msg,
        error="加载失败，请检查网络连接",
    )

    # ---- 4. Widgets（v2 预留给增值服务的插槽） ----
    widgets: list[PluginWidget] = []

    # ---- 5. 活动日志 ----
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
        "插件 v2 请求: queries=%d matched=%d username=%s gender=%s",
        len(data.queries),
        matched_count,
        data.username or "未知",
        data.gender or "未知",
    )

    return PluginResponse(
        toast=toast,
        news_html=news_html,
        courses=course_results,
        widgets=widgets,
    )
