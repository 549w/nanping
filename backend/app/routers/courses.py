"""课程路由。

GET /courses         — 搜索课程，支持按课程号 / 名称 / 教师搜索，分页返回。
GET /courses/{id}    — 获取单个课程详情（含开课学期列表）。
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Course, CourseOffering, Review
from ..schemas import CourseDetail, CourseItem, CourseListResponse, SemesterOffering

router = APIRouter(tags=["课程"])


def _shorten_semester(raw: str) -> str:
    """将教务系统长格式学期转为短格式。

    ``"2020-2021学年 第1学期"`` → ``"2020秋"``
    ``"2020-2021学年 第2学期"`` → ``"2021春"``

    无法识别时原样返回。
    """
    m = re.match(r"(\d{4})-(\d{4})学年 第(\d)学期", raw)
    if not m:
        return raw
    y1, y2, term = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y1}秋" if term == 1 else f"{y2}春"


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

    # 聚合子查询：最近开课学期（用于排序）
    latest_semester_subq = (
        select(func.max(CourseOffering.semester))
        .where(CourseOffering.course_id == Course.id)
        .correlate(Course)
        .scalar_subquery()
    )

    # 查询总数
    count_query = select(func.count(Course.id)).where(and_(*conditions))
    total = (await db.execute(count_query)).scalar() or 0

    # 主查询：按评价数降序、最近学期从新到旧排序
    offset = (page - 1) * page_size
    query = (
        select(Course, review_count_subq, avg_rating_subq)
        .where(and_(*conditions))
        .order_by(review_count_subq.desc(), latest_semester_subq.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()

    # 查询这些课程的开课学期
    course_ids = [course.id for course, _, _ in rows]
    semesters_map: dict[int, list[str]] = {}
    if course_ids:
        semester_query = (
            select(CourseOffering.course_id, CourseOffering.semester)
            .where(CourseOffering.course_id.in_(course_ids))
            .distinct()
        )
        semester_result = await db.execute(semester_query)
        for cid, sem in semester_result.all():
            short = _shorten_semester(sem)
            semesters_map.setdefault(cid, []).append(short)
        # 按短格式降序排列（"2024秋" > "2024春" > "2023秋"）
        for cid in semesters_map:
            semesters_map[cid].sort(reverse=True)

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
                semesters=semesters_map.get(course.id, []),
            )
        )

    return CourseListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/courses/{course_id}", response_model=CourseDetail)
async def get_course_detail(
    course_id: int,
    db: AsyncSession = Depends(get_db),
) -> CourseDetail:
    """获取课程详情。

    返回课程基本信息、平均评分、评价数量以及完整的开课学期列表（含专业）。
    """
    # 查询课程
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="课程不存在",
        )

    # 评价数
    review_count = (
        await db.execute(
            select(func.count(Review.id)).where(
                Review.course_id == course_id,
                Review.is_deleted == 0,
            )
        )
    ).scalar() or 0

    # 平均分
    avg_rating = (
        await db.execute(
            select(func.avg(Review.rating)).where(
                Review.course_id == course_id,
                Review.is_deleted == 0,
                Review.rating.isnot(None),
            )
        )
    ).scalar()

    # 开课学期列表
    offering_rows = (
        await db.execute(
            select(CourseOffering.semester, CourseOffering.major)
            .where(CourseOffering.course_id == course_id)
            .distinct()
            .order_by(CourseOffering.semester.desc())
        )
    ).all()

    semesters = [
        SemesterOffering(semester=_shorten_semester(sem), major=major)
        for sem, major in offering_rows
    ]

    return CourseDetail(
        id=course.id,
        code=course.code,
        name=course.name,
        teacher=course.teacher,
        department=course.department,
        credits=course.credits,
        avg_rating=round(avg_rating, 1) if avg_rating is not None else None,
        review_count=review_count,
        semesters=semesters,
    )
