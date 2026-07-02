"""课程路由。

GET /courses — 搜索课程，支持按课程号 / 名称 / 教师搜索，分页返回。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Course, Review
from ..schemas import CourseItem, CourseListResponse

router = APIRouter(tags=["课程"])


@router.get("/courses", response_model=CourseListResponse)
async def search_courses(
    code: str | None = Query(None, description="课程编号（前缀匹配）"),
    name: str | None = Query(None, description="课程名称（模糊匹配）"),
    teacher: str | None = Query(None, description="授课教师（模糊匹配）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> CourseListResponse:
    """搜索课程。

    至少需要提供 code、name、teacher 三个参数之一。
    返回课程基本信息 + avg_rating（平均评分） + review_count（评价数）。
    """
    if not code and not name and not teacher:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要提供 code、name 或 teacher 参数之一",
        )

    # 构建 WHERE 条件
    conditions = []
    if code:
        conditions.append(Course.code.like(f"{code}%"))
    if name:
        conditions.append(Course.name.like(f"%{name}%"))
    if teacher:
        conditions.append(Course.teacher.like(f"%{teacher}%"))

    # 聚合子查询：评价数
    review_count_subq = (
        select(func.count(Review.id))
        .where(Review.course_id == Course.id, Review.is_deleted == 0)
        .correlate(Course)
        .scalar_subquery()
        .label("review_count")
    )

    # 聚合子查询：平均分
    avg_rating_subq = (
        select(func.avg(Review.rating))
        .where(
            Review.course_id == Course.id,
            Review.is_deleted == 0,
            Review.rating.isnot(None),
        )
        .correlate(Course)
        .scalar_subquery()
        .label("avg_rating")
    )

    # 查询总数
    count_query = select(func.count(Course.id)).where(or_(*conditions))
    total = (await db.execute(count_query)).scalar() or 0

    # 主查询
    offset = (page - 1) * page_size
    query = (
        select(Course, review_count_subq, avg_rating_subq)
        .where(or_(*conditions))
        .order_by(Course.id)
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()

    # 组装响应
    items: list[CourseItem] = []
    for course, review_count, avg_rating in rows:
        items.append(
            CourseItem(
                id=course.id,
                code=course.code,
                name=course.name,
                teacher=course.teacher,
                department=course.department,
                credits=course.credits,
                avg_rating=round(avg_rating, 1) if avg_rating is not None else None,
                review_count=review_count if review_count is not None else 0,
            )
        )

    return CourseListResponse(items=items, total=total, page=page, page_size=page_size)
