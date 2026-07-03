"""管理后台 —— SQLAdmin。

在 /admin 提供数据库全表 CRUD 和活动统计仪表盘。
认证复用 User 表，仅 is_admin=1 的用户可登录。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import func, select

from .config import settings
from .database import async_session
from .models import ActivityLog, Course, CourseOffering, News, Review, User


# ============================================================
# 认证
# ============================================================


class AdminAuth(AuthenticationBackend):
    """管理后台认证 —— 复用 User 表，仅管理员可登录。"""

    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = form.get("username", "")
        password = form.get("password", "")

        async with async_session() as db:
            result = await db.execute(
                select(User).where(User.email == email, User.is_admin == 1)
            )
            user = result.scalar_one_or_none()
            if not user:
                return False

            from .auth import normalize_password, verify_password

            # 前端注册/登录用 SHA-256 哈希，管理后台是明文。
            # 统一 normalize 后再验证。
            if not verify_password(normalize_password(password), user.password):
                return False

        request.session.update({"admin_user_id": user.id, "admin_email": user.email})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return "admin_user_id" in request.session


# ============================================================
# ModelView 定义
# ============================================================


class UserAdmin(ModelView, model=User):
    """用户管理。密码字段使用明文输入，保存时自动 bcrypt 哈希。"""

    name = "用户"
    name_plural = "用户管理"
    icon = "fa-solid fa-users"
    column_list = [User.id, User.email, User.is_admin, User.created_at]
    column_searchable_list = [User.email]
    column_sortable_list = [User.id, User.email, User.is_admin, User.created_at]
    form_excluded_columns = [User.created_at]
    can_create = True
    can_edit = True
    can_delete = True

    async def insert_model(self, request: Request, data: dict) -> Any:
        """创建用户前规范化并哈希密码，自动生成 created_at（东八区时间）。"""
        from .auth import hash_password, normalize_password
        from datetime import datetime, timezone, timedelta
        if data.get("password"):
            normalized = normalize_password(data["password"])
            data = {**data, "password": hash_password(normalized)}
        # 使用东八区时间
        china_tz = timezone(timedelta(hours=8))
        data["created_at"] = datetime.now(china_tz).isoformat()
        return await super().insert_model(request, data)

    async def update_model(self, request: Request, pk: str, data: dict) -> Any:
        """修改用户前规范化并哈希密码。空密码或与现有哈希相同则保持原值。"""
        from .auth import hash_password, normalize_password, verify_password

        password = (data.get("password") or "").strip()
        if not password:
            # 无输入：跳过，保留数据库原值
            data = {k: v for k, v in data.items() if k != "password"}
        elif password.startswith("$2") and len(password) >= 50:
            # 表单预填了 bcrypt 哈希（用户未修改密码）→ 跳过
            data = {k: v for k, v in data.items() if k != "password"}
        else:
            # 新密码：SHA-256 + bcrypt
            data = {**data, "password": hash_password(normalize_password(password))}

        return await super().update_model(request, pk, data)


class CourseAdmin(ModelView, model=Course):
    """课程管理。"""

    name = "课程"
    name_plural = "课程管理"
    icon = "fa-solid fa-book"
    column_list = [Course.id, Course.code, Course.name, Course.teacher, Course.department, Course.credits, Course.created_at]
    column_searchable_list = [Course.code, Course.name, Course.teacher]
    column_sortable_list = [Course.id, Course.code, Course.name]
    form_excluded_columns = [Course.created_at]

    async def insert_model(self, request: Request, data: dict) -> Any:
        """创建课程时自动生成 created_at（东八区时间）。"""
        from datetime import datetime, timezone, timedelta
        china_tz = timezone(timedelta(hours=8))
        data["created_at"] = datetime.now(china_tz).isoformat()
        return await super().insert_model(request, data)


class CourseOfferingAdmin(ModelView, model=CourseOffering):
    """开课记录管理。"""

    name = "开课记录"
    name_plural = "开课记录"
    icon = "fa-solid fa-calendar"
    column_list = [CourseOffering.id, CourseOffering.course_id, CourseOffering.semester, CourseOffering.major, CourseOffering.created_at]
    column_searchable_list = [CourseOffering.semester, CourseOffering.major]
    form_excluded_columns = [CourseOffering.created_at]

    async def insert_model(self, request: Request, data: dict) -> Any:
        """创建开课记录时自动生成 created_at（东八区时间）。"""
        from datetime import datetime, timezone, timedelta
        china_tz = timezone(timedelta(hours=8))
        data["created_at"] = datetime.now(china_tz).isoformat()
        return await super().insert_model(request, data)


class ReviewAdmin(ModelView, model=Review):
    """评价管理。"""

    name = "评价"
    name_plural = "评价管理"
    icon = "fa-solid fa-star"
    column_list = [Review.id, Review.course_id, Review.user_id, Review.rating, Review.semester, Review.is_anonymous, Review.is_deleted, Review.source, Review.created_at]
    column_searchable_list = [Review.content]
    column_sortable_list = [Review.id, Review.rating, Review.created_at]
    form_excluded_columns = [Review.created_at]

    async def insert_model(self, request: Request, data: dict) -> Any:
        """创建评价时自动生成 created_at（东八区时间）。"""
        from datetime import datetime, timezone, timedelta
        china_tz = timezone(timedelta(hours=8))
        data["created_at"] = datetime.now(china_tz).isoformat()
        return await super().insert_model(request, data)


class ActivityLogAdmin(ModelView, model=ActivityLog):
    """活动日志（只读）。"""

    name = "活动日志"
    name_plural = "活动日志"
    icon = "fa-solid fa-clock-rotate-left"
    column_list = [ActivityLog.id, ActivityLog.user_id, ActivityLog.action, ActivityLog.target_type, ActivityLog.target_id, ActivityLog.ip_address, ActivityLog.created_at]
    column_searchable_list = [ActivityLog.action, ActivityLog.ip_address]
    column_sortable_list = [ActivityLog.id, ActivityLog.action, ActivityLog.created_at]
    can_create = False
    can_edit = False
    can_delete = True


class NewsAdmin(ModelView, model=News):
    """公告管理。"""

    name = "公告"
    name_plural = "公告管理"
    icon = "fa-solid fa-newspaper"
    column_list = [News.id, News.title, News.is_active, News.created_at]
    column_searchable_list = [News.title]
    column_sortable_list = [News.id, News.is_active, News.created_at]
    form_excluded_columns = [News.created_at]

    async def insert_model(self, request: Request, data: dict) -> Any:
        """创建公告时自动生成 created_at（东八区时间）。"""
        from datetime import datetime, timezone, timedelta
        china_tz = timezone(timedelta(hours=8))
        data["created_at"] = datetime.now(china_tz).isoformat()
        return await super().insert_model(request, data)


# ============================================================
# Admin 实例
# ============================================================


def create_admin(app, engine):
    """创建并挂载 SQLAdmin 实例。

    Args:
        app: FastAPI 应用实例。
        engine: SQLAlchemy 异步引擎（用于 Admin 的数据库会话）。
    """
    admin = Admin(
        app,
        engine,
        title="Nanping 管理后台",
        base_url="/admin",
        authentication_backend=AdminAuth(secret_key=settings.ADMIN_SECRET_KEY),
    )

    # 注册所有 ModelView
    for view in [
        UserAdmin,
        CourseAdmin,
        CourseOfferingAdmin,
        ReviewAdmin,
        ActivityLogAdmin,
        NewsAdmin,
    ]:
        admin.add_view(view)

    return admin
