"""数据库查询助手。

集中以下跨路由复用的查询片段，避免散落各处造成不一致：
- 布尔过滤常量（SQLite 用 Integer 0/1 表示布尔）
- 评价统计子查询（评价数、平均分）
- 课程匿名 email 表达式

新增/修改查询时若发现散落多个文件的相同模式，请考虑加入这里。
"""

from sqlalchemy import case, func, select

from .models import Course, News, Review, User


# ============================================================
# 布尔过滤常量
# ============================================================
# SQLite 没有原生 BOOLEAN，用 Integer 0/1 表示。
# 这些常量是 SQL 表达式（不是 Python 布尔），直接用在 where() / case() 里。

REVIEW_NOT_DELETED = Review.is_deleted == 0  # 评价未删除
REVIEW_IS_DELETED = Review.is_deleted == 1  # 评价已软删除
REVIEW_IS_ANONYMOUS = Review.is_anonymous == 1  # 评价匿名
NEWS_IS_ACTIVE = News.is_active == 1  # 公告已发布


# ============================================================
# 评价统计子查询
# ============================================================


def make_review_count_subq():
    """生成「某课程未删除评价数」的标量子查询。

    用于 ``/courses`` 搜索结果中的 ``review_count`` 字段，
    以及插件的课程匹配中判断「是否有评价」。

    Returns:
        标量子查询，结果是整数。
    """
    return (
        select(func.count(Review.id))
        .where(Review.course_id == Course.id, REVIEW_NOT_DELETED)
        .correlate(Course)
        .scalar_subquery()
        .label("review_count")
    )


def make_avg_rating_subq():
    """生成「某课程未删除评价的平均分」的标量子查询。

    只统计 ``rating`` 不为空的评价（导入数据可能没有打分）。

    Returns:
        标量子查询，结果是 float 或 None。
    """
    return (
        select(func.avg(Review.rating))
        .where(
            Review.course_id == Course.id,
            REVIEW_NOT_DELETED,
            Review.rating.isnot(None),
        )
        .correlate(Course)
        .scalar_subquery()
        .label("avg_rating")
    )


def make_review_stats_subqueries():
    """同时返回 ``review_count`` 和 ``avg_rating`` 两个子查询。

    供搜索/列表/详情接口复用，避免每次重写相同的 where 条件。
    顺序固定为 (count, avg)。

    Returns:
        ``(review_count_subq, avg_rating_subq)``
    """
    return make_review_count_subq(), make_avg_rating_subq()


# ============================================================
# 匿名 email 表达式
# ============================================================


def make_user_email_expr():
    """生成「匿名时返回 null，否则返回 User.email」的表达式。

    用于评价列表 / 详情中：匿名评价不暴露用户邮箱。

    Returns:
        ``case`` 表达式，结果是 email 字符串或 None。
    """
    return case(
        (REVIEW_IS_ANONYMOUS, None),
        else_=User.email,
    ).label("user_email")
