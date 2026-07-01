"""数据库连接与会话管理。

使用 SQLAlchemy 异步模式 + aiosqlite，配合 FastAPI 的 async/await。
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# 异步引擎 —— 负责与 SQLite 文件通信
# echo=False 表示不打印 SQL 日志，调试时可改为 True
engine = create_async_engine(settings.DATABASE_URL, echo=False)

# 会话工厂 —— 每次请求从这里领一个 AsyncSession 实例
# expire_on_commit=False 防止提交后对象属性被清空
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。

    models.py 里的每个类都继承它，
    调用 Base.metadata.create_all() 时会自动建表。
    """
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：为每个请求提供独立的数据库会话。

    用法（在 router 里）：
        @router.get("/xxx")
        async def handler(db: AsyncSession = Depends(get_db)):
            result = await db.execute(...)
            return result

    请求开始时创建会话，返回响应后自动关闭，
    不用手动 .open() / .close()。

    Yields:
        AsyncSession: 异步数据库会话
    """
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
