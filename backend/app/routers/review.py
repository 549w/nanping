"""评价路由。

GET    /review         — 查看某课程的评价列表
POST   /review/add     — 提交新评价（需登录）
DELETE /review/delete  — 软删除评价（需登录，仅限自己的）
GET    /review/me      — 查看当前用户的全部评价（需登录）
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..limiter import limiter
from ..models import Course, Review, User
from ..schemas import (
    MessageResponse,
    ReviewCreate,
    ReviewDelete,
    ReviewItem,
    ReviewListResponse,
)

router = APIRouter(tags=["评价"])


# ============================================================
# GET /review — 查看评价列表
# ============================================================


@router.get("/review", response_model=ReviewListResponse)
async def list_reviews(
    course_id: int = Query(..., description="课程 ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> ReviewListResponse:
    """查看某课程的评价列表。

    排除已删除评价，匿名评价不返回用户邮箱。
    按创建时间倒序排列。
    """
    # 确认课程存在
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="课程不存在",
        )

    # user_email：匿名时返回 null
    user_email_expr = case(
        (Review.is_anonymous == 1, None),
        else_=User.email,
    ).label("user_email")

    # 计数
    count_query = select(func.count(Review.id)).where(
        Review.course_id == course_id,
        Review.is_deleted == 0,
    )
    total = (await db.execute(count_query)).scalar() or 0

    # 主查询
    offset = (page - 1) * page_size
    query = (
        select(Review, user_email_expr)
        .join(User, Review.user_id == User.id)
        .where(Review.course_id == course_id, Review.is_deleted == 0)
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()

    items: list[ReviewItem] = []
    for review, user_email in rows:
        items.append(
            ReviewItem(
                id=review.id,
                course_id=review.course_id,
                rating=review.rating,
                content=review.content,
                semester=review.semester,
                is_anonymous=review.is_anonymous,
                created_at=review.created_at,
                user_email=user_email,
            )
        )

    return ReviewListResponse(items=items, total=total, page=page, page_size=page_size)


# ============================================================
# POST /review/add — 提交新评价
# ============================================================


@router.post("/review/add", response_model=ReviewItem, status_code=201)
@limiter.limit("5/minute")
async def create_review(
    request: Request,
    data: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewItem:
    """提交新评价（需登录）。

    user_id 由 JWT 令牌解析，不受请求体控制。
    """
    # 确认课程存在
    course = await db.get(Course, data.course_id)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="课程不存在",
        )

    review = Review(
        course_id=data.course_id,
        user_id=current_user.id,
        rating=data.rating,
        content=data.content,
        semester=data.semester,
        is_anonymous=1 if data.is_anonymous else 0,
        is_deleted=0,
        source="native",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    return ReviewItem(
        id=review.id,
        course_id=review.course_id,
        rating=review.rating,
        content=review.content,
        semester=review.semester,
        is_anonymous=review.is_anonymous,
        created_at=review.created_at,
        user_email=None if data.is_anonymous else current_user.email,
    )


# ============================================================
# DELETE /review/delete — 删除评价
# ============================================================


@router.delete("/review/delete", response_model=MessageResponse)
@limiter.limit("5/minute")
async def delete_review(
    request: Request,
    data: ReviewDelete,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """软删除评价（需登录）。

    只能删除自己提交的评价。
    """
    review = await db.get(Review, data.review_id)
    if not review or review.is_deleted == 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="评价不存在",
        )
    if review.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能删除自己的评价",
        )

    review.is_deleted = 1
    await db.commit()

    return MessageResponse(message="删除成功")


# ============================================================
# GET /review/me — 我的评价
# ============================================================


@router.get("/review/me", response_model=ReviewListResponse)
async def list_my_reviews(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewListResponse:
    """查看当前用户的全部评价（需登录）。

    返回评价内容及其所属课程名称和编号。
    """
    # 计数
    count_query = select(func.count(Review.id)).where(
        Review.user_id == current_user.id,
        Review.is_deleted == 0,
    )
    total = (await db.execute(count_query)).scalar() or 0

    # 主查询（JOIN Course 获取课程名和编号）
    offset = (page - 1) * page_size
    query = (
        select(Review, Course.name.label("course_name"), Course.code.label("course_code"))
        .join(Course, Review.course_id == Course.id)
        .where(Review.user_id == current_user.id, Review.is_deleted == 0)
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()

    items: list[ReviewItem] = []
    for review, course_name, course_code in rows:
        items.append(
            ReviewItem(
                id=review.id,
                course_id=review.course_id,
                rating=review.rating,
                content=review.content,
                semester=review.semester,
                is_anonymous=review.is_anonymous,
                created_at=review.created_at,
                user_email=current_user.email,
                course_name=course_name,
                course_code=course_code,
            )
        )

    return ReviewListResponse(items=items, total=total, page=page, page_size=page_size)
