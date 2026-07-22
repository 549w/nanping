"""课程路由。

GET  /courses         — 搜索课程，支持按课程号 / 名称 / 教师搜索，分页返回。
GET  /courses/{id}    — 获取单个课程详情（含开课学期列表）。
POST /courses/match   — 批量匹配课程（浏览器插件用），按课程号→教师回退搜索。
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import log_activity
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

from .abbr import ABBR

logger = logging.getLogger("nanping.courses")
router = APIRouter(tags=["课程"])


def _escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符，防止用户通过 ``%`` / ``_`` 批量获取数据。

    SQLAlchemy 的 ``.like()`` 不会自动转义用户输入中的通配符，
    因此需要在拼接 pattern 前手动转义。

    Args:
        value: 用户输入的原始字符串。

    Returns:
        转义后的字符串，``%`` → ``\\%``，``_`` → ``\\_``。
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _shorten_semester(raw: str) -> str:
    """将教务系统长格式学期转为短格式。

    ``"2020-2021学年 第1学期"`` → ``"2020秋"``
    ``"2020-2021学年 第2学期"`` → ``"2021春"``
    ``"2025-2026学年 暑期"`` → ``"2026暑"``

    无法识别时原样返回。
    """
    # 暑期：取后一个年份 + "暑"
    m = re.match(r"(\d{4})-(\d{4})学年 暑期", raw)
    if m:
        return f"{m.group(2)}暑"

    m = re.match(r"(\d{4})-(\d{4})学年 第(\d)学期", raw)
    if not m:
        return raw
    y1, y2, term = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y1}秋" if term == 1 else f"{y2}春"


@router.get("/courses", response_model=CourseListResponse)
async def search_courses(
    request: Request,
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
        conditions.append(Course.code.like(f"{_escape_like(code)}%"))
    if name:
        if name in ABBR:
            conditions.append(Course.name.like(f"%{_escape_like(ABBR[name])}%"))
        else:
            conditions.append(Course.name.like(f"%{_escape_like(name)}%"))
    if teacher:
        conditions.append(Course.teacher.like(f"%{_escape_like(teacher)}%"))

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

    # 记录搜索活动日志
    search_detail: dict = {}
    if code: search_detail["code"] = code
    if name: search_detail["name"] = name
    if teacher: search_detail["teacher"] = teacher

    await log_activity(db, request, "search", details=search_detail)

    return CourseListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/courses/{course_id}", response_model=CourseDetail)
async def get_course_detail(
    course_id: int,
    request: Request,
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

    # 记录查看课程详情活动日志
    await log_activity(
        db, request, "course_view",
        target_type="course",
        target_id=course_id,
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


async def _search_courses(
    db: AsyncSession,
    code: str = "",
    teacher_str: str = "",
    name: str = "",
) -> list[tuple[Course, int, float | None]]:
    """通用课程搜索：按给定条件 AND 组合查询，附带评价统计。

    三个筛选条件均为可选，传入空字符串表示跳过该维度。
    - code: 精确匹配
    - teacher_str: 拆分后 OR 模糊匹配（最多前 5 位教师）
    - name: LIKE 模糊匹配

    Returns:
        [(Course, review_count, avg_rating), ...] 列表
    """
    conditions: list = []

    if code:
        conditions.append(Course.code == code.strip())

    if teacher_str:
        teachers = [t.strip() for t in teacher_str.split(",") if t.strip()][:5]
        if teachers:
            conditions.append(or_(*[Course.teacher.like(f"%{_escape_like(t)}%") for t in teachers]))

    if name:
        conditions.append(Course.name.like(f"%{_escape_like(name.strip())}%"))

    if not conditions:
        return []

    rc_subq, ar_subq = _make_review_stats_subqueries()
    query = select(Course, rc_subq, ar_subq).where(and_(*conditions))
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


# 匹配策略定义：(code, teacher, name) → match_level
# 按严格度从高到低排列，match_level 以 "+" 连接使用的字段名
_MATCH_STRATEGIES: list[tuple[str, str, str, str]] = [
    # (use_code, use_teacher, use_name, match_level)
    ("code", "teacher", "name", "code+teacher+name"),  # 1. 课程号 + 教师 + 课程名
    ("code", "teacher", "",     "code+teacher"),        # 2. 课程号 + 教师
    ("",     "teacher", "name", "name+teacher"),        # 3. 课程名 + 教师
    ("",     "teacher", "",     "teacher"),             # 4. 仅教师
    ("code", "",        "",     "code"),                # 5. 仅课程号
]


async def _find_exact_course(
    db: AsyncSession, code: str, name: str, teacher_str: str
) -> Course | None:
    """精确匹配页面课程对应的 Course 记录。

    选课平台上的课程必然来自官方教务系统，而我们的数据库导入了教务数据，
    因此每门页面课程都能在 Course 表中唯一找到（code + name + teacher 完全匹配）。

    匹配步骤：
    1. code 精确匹配
    2. 在候选中找 name 精确匹配
    3. 若多条命中，按 teacher 重叠度选最佳
    """
    if not code or not name:
        return None

    result = await db.execute(select(Course).where(Course.code == code))
    candidates = result.scalars().all()
    if not candidates:
        return None

    # 课程名完全匹配
    name_matches = [c for c in candidates if c.name.strip() == name]
    if not name_matches:
        return None

    if len(name_matches) == 1:
        return name_matches[0]

    # 多条同名课程：按教师重叠度选最佳
    if teacher_str:
        return max(name_matches, key=lambda c: _teacher_overlap(teacher_str, c.teacher))

    return name_matches[0]


async def _match_one(
    idx: int, query, db: AsyncSession
) -> MatchResult:
    """对单个 query 执行五级递进搜索，返回最佳匹配结果。

    搜索策略（从严格到宽松）：
    1. 课程号 + 教师 + 课程名
    2. 课程号 + 教师
    3. 课程名 + 教师
    4. 仅教师
    5. 仅课程号

    每级只取有评价（review_count > 0）的结果。
    命中后按教师重叠度 + 名称匹配度 + 评价数排序，取 top 3。

    此外，始终尝试精确匹配课程（用于写评价链接），即使该课程尚无评价。
    """
    code = query.code.strip()
    teacher_str = query.teacher.strip()
    name = query.name.strip()

    # 精确匹配课程 ID（供「写评价」链接使用，不依赖评价）
    exact_course = await _find_exact_course(db, code, name, teacher_str)
    exact_course_id = exact_course.id if exact_course else None

    for use_code, use_teacher, use_name, match_level in _MATCH_STRATEGIES:
        # 策略需要的字段若为空则跳过：空白不应被视为匹配
        if use_code and not code:
            continue
        if use_teacher and not teacher_str:
            continue
        if use_name and not name:
            continue

        search_code = code if use_code else ""
        search_teacher = teacher_str if use_teacher else ""
        search_name = name if use_name else ""

        results = await _search_courses(db, search_code, search_teacher, search_name)
        with_reviews = [(c, rc, ar) for c, rc, ar in results if rc > 0]

        if not with_reviews:
            continue

        # 命中：按教师重叠 + 名称匹配 + 评价数排序
        scored = [
            (
                c,
                rc,
                ar,
                _teacher_overlap(teacher_str, c.teacher),
                _name_match_score(name, c.name),
            )
            for c, rc, ar in with_reviews
        ]
        scored.sort(key=lambda x: (x[3], x[4], x[1]), reverse=True)

        matched: list[MatchCourseItem] = []
        for course, rc, ar, _, _ in scored[:3]:
            reviews = await _get_top_reviews(db, course.id)
            matched.append(
                MatchCourseItem(
                    course=_course_to_item(course, rc, ar),
                    top_reviews=reviews,
                    match_level=match_level,
                )
            )
        return MatchResult(query_index=idx, matched=matched, exact_course_id=exact_course_id)

    # 所有策略均无有评价的结果
    return MatchResult(query_index=idx, matched=[], exact_course_id=exact_course_id)


@router.post("/courses/match", response_model=BatchMatchResponse)
async def match_courses(
    data: BatchMatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> BatchMatchResponse:
    """批量匹配课程（浏览器插件用）。"""
    results: list[MatchResult] = []
    matched_count = 0
    for idx, query in enumerate(data.queries):
        result = await _match_one(idx, query, db)
        if result.matched:
            matched_count += 1
        results.append(result)

    # 记录插件查询活动日志
    detail = {
        "query_count": len(data.queries),
        "matched_count": matched_count,
    }
    if data.username:
        detail["username"] = data.username
    if data.gender:
        detail["gender"] = data.gender
    await log_activity(db, request, "plugin_query", details=detail)

    logger.info(
        "插件批量匹配: queries=%d matched=%d username=%s gender=%s",
        len(data.queries),
        matched_count,
        data.username or "未知",
        data.gender or "未知",
    )

    return BatchMatchResponse(results=results)
