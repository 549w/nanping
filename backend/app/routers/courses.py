"""课程路由。

GET  /courses         — 搜索课程，支持按课程号 / 名称 / 教师搜索，分页返回。
GET  /courses/{id}    — 获取单个课程详情（含开课学期列表）。
POST /courses/match   — 批量匹配课程（浏览器插件用），按课程号→教师回退搜索。
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Course, CourseOffering, Review, User
from ..schemas import (
    BatchMatchRequest,
    BatchMatchResponse,
    CourseDetail,
    CourseItem,
    CourseListResponse,
    MatchCourseItem,
    MatchResult,
    ReviewItem,
    SemesterOffering,
)

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


# ============================================================
# POST /courses/match — 批量课程匹配（浏览器插件用）
# ============================================================


def _teacher_overlap(query_teacher: str, course_teacher: str) -> float:
    """计算两个教师集合的 Jaccard 相似度。

    页面上的教师和数据库中 Course.teacher 都是逗号分隔的字符串，
    拆分后计算交集 / 并集。

    Args:
        query_teacher: 页面上的教师字符串，如 ``"戚海峰,葛中芹"``
        course_teacher: 数据库中的教师字符串，如 ``"葛中芹,戚海峰"``

    Returns:
        0.0 ~ 1.0 的相似度，空字符串返回 0。
    """
    if not query_teacher or not course_teacher:
        return 0.0
    q_set = {t.strip() for t in query_teacher.split(",") if t.strip()}
    c_set = {t.strip() for t in course_teacher.split(",") if t.strip()}
    if not q_set or not c_set:
        return 0.0
    intersection = q_set & c_set
    union = q_set | c_set
    return len(intersection) / len(union)


def _name_match_score(query_name: str, course_name: str) -> float:
    """计算课程名称匹配度。

    1.0 = 完全相同，0.5 = 包含关系，0 = 不匹配。

    Args:
        query_name: 页面上的课程名
        course_name: 数据库中的课程名

    Returns:
        匹配分数。
    """
    if not query_name or not course_name:
        return 0.0
    q = query_name.strip()
    c = course_name.strip()
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.5
    return 0.0


def _make_review_stats_subqueries():
    """创建 review_count 和 avg_rating 的标量子查询。

    供 _get_courses_by_code 和 _get_courses_by_teacher 复用，
    避免重复写相同的子查询定义。
    """
    review_count_subq = (
        select(func.count(Review.id))
        .where(Review.course_id == Course.id, Review.is_deleted == 0)
        .correlate(Course)
        .scalar_subquery()
        .label("review_count")
    )
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
    return review_count_subq, avg_rating_subq


async def _get_courses_by_code(
    db: AsyncSession, code: str
) -> list[tuple[Course, int, float | None]]:
    """按课程号精确查找课程，附带评价统计。

    Returns:
        [(Course, review_count, avg_rating), ...] 列表
    """
    rc_subq, ar_subq = _make_review_stats_subqueries()
    query = select(Course, rc_subq, ar_subq).where(Course.code == code)
    result = await db.execute(query)
    return [(row[0], row[1] or 0, row[2]) for row in result.all()]


async def _get_courses_by_teacher(
    db: AsyncSession, teacher_str: str
) -> list[tuple[Course, int, float | None]]:
    """按教师名模糊查找课程，附带评价统计。

    将页面上的教师字符串拆分，用 OR 连接多个 LIKE 条件。
    最多取前 5 位教师，防止超长教师列表导致 SQL 膨胀。

    Returns:
        [(Course, review_count, avg_rating), ...] 列表
    """
    teachers = [t.strip() for t in teacher_str.split(",") if t.strip()][:5]
    if not teachers:
        return []

    rc_subq, ar_subq = _make_review_stats_subqueries()
    conditions = [Course.teacher.like(f"%{t}%") for t in teachers]
    query = select(Course, rc_subq, ar_subq).where(or_(*conditions))
    result = await db.execute(query)
    return [(row[0], row[1] or 0, row[2]) for row in result.all()]


async def _get_top_reviews(
    db: AsyncSession, course_id: int, limit: int = 5
) -> list[ReviewItem]:
    """获取某课程的最新几条评价。

    匿名评价的 user_email 返回 null。
    """
    user_email_expr = case(
        (Review.is_anonymous == 1, None),
        else_=User.email,
    ).label("user_email")

    query = (
        select(Review, user_email_expr)
        .join(User, Review.user_id == User.id)
        .where(Review.course_id == course_id, Review.is_deleted == 0)
        .order_by(Review.created_at.desc())
        .limit(limit)
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
    return items


def _course_to_item(course: Course, review_count: int, avg_rating: float | None) -> CourseItem:
    """将 ORM Course + 统计数据 转为 CourseItem 响应对象。"""
    return CourseItem(
        id=course.id,
        code=course.code,
        name=course.name,
        teacher=course.teacher,
        department=course.department,
        credits=course.credits,
        avg_rating=round(avg_rating, 1) if avg_rating is not None else None,
        review_count=review_count,
        semesters=[],
    )


async def _match_one(
    idx: int, query, db: AsyncSession
) -> MatchResult:
    """对单个 query 执行三级回退搜索，返回最佳匹配结果。

    搜索策略：
    1. 课程号精确匹配 → 按教师重叠度排序，取 top 3
    2. 教师模糊匹配 → 按教师重叠 + 名称匹配排序，取 top 3
    3. 都没有 → 返回空列表（插件端渲染「暂无评价」）
    """
    code = query.code.strip()
    teacher_str = query.teacher.strip()
    name = query.name.strip()

    # ---- Step 1: 课程号精确匹配 ----
    code_courses = await _get_courses_by_code(db, code)
    code_with_reviews = [(c, rc, ar) for c, rc, ar in code_courses if rc > 0]

    if code_with_reviews:
        # 按教师重叠度 + 评价数排序
        scored = [
            (c, rc, ar, _teacher_overlap(teacher_str, c.teacher))
            for c, rc, ar in code_with_reviews
        ]
        # 存在有教师重叠的结果时，过滤掉重叠度为 0 的
        with_overlap = [(c, rc, ar, o) for c, rc, ar, o in scored if o > 0]
        candidates = with_overlap if with_overlap else scored
        candidates.sort(key=lambda x: (x[3], x[1]), reverse=True)

        matched: list[MatchCourseItem] = []
        for course, rc, ar, _ in candidates[:3]:
            reviews = await _get_top_reviews(db, course.id)
            matched.append(
                MatchCourseItem(
                    course=_course_to_item(course, rc, ar),
                    top_reviews=reviews,
                    match_level="code",
                )
            )
        return MatchResult(query_index=idx, matched=matched)

    # ---- Step 2: 教师模糊匹配 ----
    if teacher_str:
        teacher_courses = await _get_courses_by_teacher(db, teacher_str)
        teacher_with_reviews = [(c, rc, ar) for c, rc, ar in teacher_courses if rc > 0]

        if teacher_with_reviews:
            scored = [
                (
                    c,
                    rc,
                    ar,
                    _teacher_overlap(teacher_str, c.teacher),
                    _name_match_score(name, c.name),
                )
                for c, rc, ar in teacher_with_reviews
            ]
            scored.sort(key=lambda x: (x[3], x[4], x[1]), reverse=True)

            matched = []
            for course, rc, ar, _, _ in scored[:3]:
                reviews = await _get_top_reviews(db, course.id)
                matched.append(
                    MatchCourseItem(
                        course=_course_to_item(course, rc, ar),
                        top_reviews=reviews,
                        match_level="teacher",
                    )
                )
            return MatchResult(query_index=idx, matched=matched)

    # ---- Step 3: 无匹配 ----
    return MatchResult(query_index=idx, matched=[])


@router.post("/courses/match", response_model=BatchMatchResponse)
async def match_courses(
    data: BatchMatchRequest,
    db: AsyncSession = Depends(get_db),
) -> BatchMatchResponse:
    """批量匹配课程（浏览器插件用）。

    插件从选课页面提取所有课程行，一次性发送到此端点进行匹配。
    对每条 query 按「课程号 → 教师」三级回退搜索，
    返回最佳匹配课程及其最新评价。

    Args:
        data: 包含最多 200 条 MatchQuery 的批量请求

    Returns:
        每条 query 的匹配结果，按 query_index 对应
    """
    results: list[MatchResult] = []
    for idx, query in enumerate(data.queries):
        result = await _match_one(idx, query, db)
        results.append(result)
    return BatchMatchResponse(results=results)
