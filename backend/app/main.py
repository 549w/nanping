"""Nanping API 应用入口。

组装 FastAPI 应用，注册中间件、路由和生命周期事件。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from .admin import create_admin
from .config import settings
from .database import engine, Base
from .limiter import limiter
from .logging_config import setup_logging
from .middleware import RequestLoggingMiddleware, global_exception_handler
from .migrate import run_migrations
from .risk_middleware import RiskControlMiddleware
from .routers import auth, courses, events, news, plugin, review


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。

    startup: 初始化日志系统，创建数据库表（如不存在）
    shutdown: 关闭数据库连接池
    """
    setup_logging(settings.LOG_LEVEL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 执行列迁移（旧数据库兼容新代码）
        await run_migrations(conn)
    yield
    await engine.dispose()


app = FastAPI(
    title="Nanping API",
    description="南京大学课程评价系统 API",
    version="0.1.0",
    lifespan=lifespan,
)

# ---- 强制 HTTPS scheme（nginx 代理后 Fix） ----
class ForceHttpsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("X-Forwarded-Proto") == "https":
            request.scope["scheme"] = "https"
        response = await call_next(request)
        return response

app.add_middleware(ForceHttpsMiddleware)

# ---- Session（SQLAdmin 认证需要） ----
app.add_middleware(SessionMiddleware, secret_key=settings.ADMIN_SECRET_KEY)

# ---- 风控中间件（在请求日志之前，以便记录拦截的请求） ----
app.add_middleware(RiskControlMiddleware)

# ---- 请求日志中间件 ----
app.add_middleware(RequestLoggingMiddleware)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Risk-Score", "X-Risk-Level", "X-Risk-Session"],
)

# ---- 限流 ----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---- 全局异常处理 ----
app.add_exception_handler(Exception, global_exception_handler)

# ---- 管理后台 ----
create_admin(app, engine)

# ---- 路由注册 ----
app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(news.router)
app.include_router(review.router)
app.include_router(plugin.router)
app.include_router(events.router)


@app.get("/", tags=["健康检查"])
async def root():
    """健康检查端点。"""
    return {"status": "ok", "version": "0.1.0"}
