"""测试基础设施。

为所有测试模块提供异步 HTTP 客户端、内存数据库和常用 fixtures。
"""

import os

# 在任何应用模块导入之前设置测试环境变量
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["AUTH_MOCK_MODE"] = "true"
os.environ["MOCK_VERIFICATION_CODE"] = "123456"
os.environ["CORS_ORIGINS"] = "[]"

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import Course, CourseOffering, Review, User
from backend.app.auth import hash_password
from backend.app.limiter import limiter


# ============================================================
# 数据库 fixtures
# ============================================================


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """为每个测试创建独立的内存 SQLite 数据库。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """提供一个事务级数据库会话，供工厂 fixtures 使用。"""
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


# ============================================================
# HTTP 客户端 fixture
# ============================================================


@pytest_asyncio.fixture(scope="function")
async def client(test_engine):
    """异步 HTTP 测试客户端，数据库依赖已替换为内存 SQLite。

    测试期间禁用限流器，避免触发速率限制。
    """
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # 禁用限流器（必须操作实际 limiter 实例，因为 @limiter.limit 装饰器持有其引用）
    limiter.enabled = False
    app.state.limiter = limiter

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ============================================================
# 工厂 fixtures
# ============================================================


@pytest_asyncio.fixture
async def test_user(db_session):
    """创建一个标准测试用户。"""
    user = User(
        email="test@nju.edu.cn",
        password=hash_password("password123"),
        created_at="2025-01-01T00:00:00",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user2(db_session):
    """创建第二个测试用户（用于测试跨用户操作）。"""
    user = User(
        email="other@nju.edu.cn",
        password=hash_password("password456"),
        created_at="2025-01-01T00:00:00",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_course(db_session):
    """创建一个标准测试课程。"""
    course = Course(
        code="00010",
        name="测试课程",
        teacher="张三",
        department="计算机系",
        credits=3.0,
        created_at="2025-01-01T00:00:00",
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


@pytest_asyncio.fixture
async def test_course2(db_session):
    """创建第二个测试课程（无评价）。"""
    course = Course(
        code="00020",
        name="另一门课",
        teacher="李四",
        department="数学系",
        credits=2.0,
        created_at="2025-01-01T00:00:00",
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


@pytest_asyncio.fixture
async def test_offering(db_session, test_course):
    """为 test_course 创建两条开课记录。"""
    o1 = CourseOffering(
        course_id=test_course.id,
        semester="2024-2025学年 第1学期",
        major="计算机科学与技术",
        created_at="2025-01-01T00:00:00",
    )
    o2 = CourseOffering(
        course_id=test_course.id,
        semester="2024-2025学年 第2学期",
        major="软件工程",
        created_at="2025-01-01T00:00:00",
    )
    db_session.add_all([o1, o2])
    await db_session.commit()
    await db_session.refresh(o1)
    await db_session.refresh(o2)
    return [o1, o2]


@pytest_asyncio.fixture
async def test_review(db_session, test_course, test_user):
    """创建一个标准测试评价。"""
    review = Review(
        course_id=test_course.id,
        user_id=test_user.id,
        rating=4,
        content="很好的课程",
        semester="2025春",
        is_anonymous=0,
        is_deleted=0,
        source="native",
        created_at="2025-06-01T00:00:00",
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)
    return review


@pytest_asyncio.fixture
async def test_review_anonymous(db_session, test_course, test_user):
    """创建一个匿名测试评价。"""
    review = Review(
        course_id=test_course.id,
        user_id=test_user.id,
        rating=5,
        content="匿名好评",
        semester="2025春",
        is_anonymous=1,
        is_deleted=0,
        source="native",
        created_at="2025-06-02T00:00:00",
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)
    return review


@pytest_asyncio.fixture
async def test_review_deleted(db_session, test_course, test_user):
    """创建一个已删除的测试评价。"""
    review = Review(
        course_id=test_course.id,
        user_id=test_user.id,
        rating=1,
        content="已删除的评价",
        semester="2025春",
        is_anonymous=0,
        is_deleted=1,
        source="native",
        created_at="2025-06-03T00:00:00",
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)
    return review


# ============================================================
# 认证 fixtures
# ============================================================


@pytest_asyncio.fixture
async def auth_token(client, test_user):
    """为 test_user 获取 JWT 令牌。"""
    response = await client.post(
        "/auth/login",
        json={"email": "test@nju.edu.cn", "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest_asyncio.fixture
async def auth_headers(auth_token):
    """包含 Bearer token 的 Authorization 头字典。"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest_asyncio.fixture
async def auth_headers_user2(client, test_user2):
    """为 test_user2 获取 Authorization 头字典。"""
    response = await client.post(
        "/auth/login",
        json={"email": "other@nju.edu.cn", "password": "password456"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
