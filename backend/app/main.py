"""Nanping API 应用入口。

组装 FastAPI 应用，注册中间件、路由和生命周期事件。
"""

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .database import engine, Base
from .limiter import limiter
from .routers import auth, courses, review


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。

    startup: 创建数据库表（如不存在）
    shutdown: 关闭数据库连接池
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Nanping API",
    description="南京大学课程评价系统 API",
    version="0.1.0",
    lifespan=lifespan,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 限流 ----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---- 静态文件（插件热更新开发用） ----
_ext_dir = Path(__file__).resolve().parent.parent.parent / "extension"
if _ext_dir.exists():
    app.mount("/extension", StaticFiles(directory=str(_ext_dir), html=False), name="extension")

# ---- 路由注册 ----
app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(review.router)


@app.get("/", tags=["健康检查"])
async def root():
    """健康检查端点。"""
    return {"status": "ok", "version": "0.1.0"}
