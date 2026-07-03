"""Pydantic 请求/响应模型。

所有 API 的输入输出都通过这里的 schema 校验和序列化。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ============================================================
# 公告
# ============================================================


class NewsItem(BaseModel):
    """公告/新闻项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    created_at: str


# ============================================================
# 通用
# ============================================================


class MessageResponse(BaseModel):
    """通用成功消息。"""

    message: str


class TokenResponse(BaseModel):
    """JWT 令牌响应。"""

    access_token: str
    token_type: str = "bearer"


# ============================================================
# 认证请求
# ============================================================


class SendCodeRequest(BaseModel):
    """发送验证码请求。"""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_and_validate_nju_email(cls, v: str) -> str:
        """转小写并校验为南京大学邮箱。"""
        v = v.lower().strip()
        allowed = ("@nju.edu.cn", "@smail.nju.edu.cn")
        if not any(v.endswith(domain) for domain in allowed):
            raise ValueError("请使用南京大学邮箱注册")
        return v


class RegisterRequest(BaseModel):
    """注册请求。"""

    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=6)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_nju_email(cls, v: str) -> str:
        """转小写并校验为南京大学邮箱。"""
        v = v.lower().strip()
        allowed = ("@nju.edu.cn", "@smail.nju.edu.cn")
        if not any(v.endswith(domain) for domain in allowed):
            raise ValueError("请使用南京大学邮箱注册")
        return v


class LoginRequest(BaseModel):
    """登录请求。"""

    email: EmailStr
    password: str


# ============================================================
# 评价请求
# ============================================================


class ReviewCreate(BaseModel):
    """新增评价请求。"""

    course_id: int
    rating: int = Field(ge=1, le=5)
    content: str = Field(min_length=1, max_length=5000)
    semester: str
    is_anonymous: bool = False
    referrer: str | None = Field(default=None, description="来源标识，如 plugin_v0.1 / search / me")


class ReviewDelete(BaseModel):
    """删除评价请求。"""

    review_id: int


# ============================================================
# 课程响应
# ============================================================


class CourseItem(BaseModel):
    """课程搜索结果项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    teacher: str
    department: str | None = None
    credits: float | None = None
    avg_rating: float | None = None
    review_count: int = 0
    semesters: list[str] = []


class SemesterOffering(BaseModel):
    """单条开课记录。"""

    semester: str
    major: str


class CourseDetail(BaseModel):
    """课程详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    teacher: str
    department: str | None = None
    credits: float | None = None
    avg_rating: float | None = None
    review_count: int = 0
    semesters: list[SemesterOffering] = []


class CourseListResponse(BaseModel):
    """课程搜索分页响应。"""

    items: list[CourseItem]
    total: int
    page: int
    page_size: int


# ============================================================
# 评价响应
# ============================================================


class ReviewItem(BaseModel):
    """评价响应项。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    rating: int | None = None
    content: str
    semester: str | None = None
    is_anonymous: bool
    created_at: str
    # 匿名评价时为 null；由查询层使用 CASE 表达式控制
    user_email: str | None = None
    # /review/me 接口额外返回课程信息
    course_name: str | None = None
    course_code: str | None = None

    @field_validator("is_anonymous", mode="before")
    @classmethod
    def int_to_bool(cls, v: object) -> bool:
        """数据库 INTEGER 0/1 → Python bool。"""
        if isinstance(v, int):
            return bool(v)
        return v  # type: ignore[return-value]


class ReviewListResponse(BaseModel):
    """评价分页响应。"""

    items: list[ReviewItem]
    total: int
    page: int
    page_size: int


# ============================================================
# 批量课程匹配（浏览器插件用）
# ============================================================


class MatchQuery(BaseModel):
    """单条匹配查询 —— 来自选课页面的一个课程行。"""

    code: str = Field(min_length=1, description="课程号")
    teacher: str = Field(default="", description="授课教师，逗号分隔")
    name: str = Field(default="", description="课程名称")


class MatchCourseItem(BaseModel):
    """单条匹配结果：一个 Course + 其 top 评价。"""

    course: CourseItem
    top_reviews: list[ReviewItem] = []
    match_level: str = Field(description="匹配字段组合，如 code+teacher+name / teacher / code 等")


class MatchResult(BaseModel):
    """单个 query 的匹配结果集合。"""

    query_index: int = Field(description="对应请求中 queries 的索引")
    matched: list[MatchCourseItem] = []
    exact_course_id: int | None = Field(
        default=None,
        description="精确匹配到的课程 ID（code + name + teacher 完全匹配），仅用于写评价链接",
    )


class BatchMatchRequest(BaseModel):
    """批量匹配请求 —— 插件一次性发送页面上所有课程行。"""

    queries: list[MatchQuery] = Field(max_length=200, description="最多 200 条")
    username: str | None = Field(default=None, description="选课页面登录用户名，用于活动日志")


class BatchMatchResponse(BaseModel):
    """批量匹配响应。"""

    results: list[MatchResult]
