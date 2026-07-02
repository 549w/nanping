"""Pydantic 请求/响应模型。

所有 API 的输入输出都通过这里的 schema 校验和序列化。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    semester: str | None = None
    is_anonymous: bool = False


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
