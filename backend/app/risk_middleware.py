"""API 风控中间件。

集成 risk.py 的核心逻辑，处理 HTTP 层面的：
- 匿名 session Cookie 分配
- 请求行为追踪
- 风险评分与分级响应
- 响应头注入
"""

import logging
import random
import re
import time

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .risk import (
    IPTracker,
    RiskLevel,
    RiskResult,
    SessionState,
    SessionStore,
    compute_risk_score,
    extract_course_id_from_path,
    format_risk_log,
    generate_session_id,
)
from .utils import get_client_ip

logger = logging.getLogger("nanping.risk")


# ============================================================
# 全局会话存储和 IP 追踪器（单例）
# ============================================================

_session_store = SessionStore()
_ip_tracker = IPTracker()


def get_session_store() -> SessionStore:
    """获取全局会话存储（测试可替换）。"""
    return _session_store


def set_session_store(store: SessionStore) -> None:
    """替换全局会话存储（测试用）。"""
    global _session_store
    _session_store = store


def get_ip_tracker() -> IPTracker:
    """获取全局 IP 追踪器（测试可替换）。"""
    return _ip_tracker


def set_ip_tracker(tracker: IPTracker) -> None:
    """替换全局 IP 追踪器（测试用）。"""
    global _ip_tracker
    _ip_tracker = tracker


# ============================================================
# 路径白名单
# ============================================================

# 跳过风控的路径（正则）
_SKIP_PATHS = [
    r"^/$",  # 健康检查
    r"^/openapi\.json$",
    r"^/docs",
    r"^/redoc",
    r"^/auth/",  # 登录注册
    r"^/news",
    r"^/events",
    r"^/admin",
    r"^/css/",
    r"^/js/",
    r"^/fonts/",
    r"^/screenshots/",
    r"\.(css|js|png|jpg|jpeg|gif|ico|woff2|woff|ttf)$",  # 静态资源
]

_SKIP_PATTERNS = [re.compile(p) for p in _SKIP_PATHS]


def should_skip_path(path: str) -> bool:
    """判断路径是否跳过风控。"""
    return any(pattern.match(path) for pattern in _SKIP_PATTERNS)


# ============================================================
# Cookie 辅助
# ============================================================


def get_session_cookie(request: Request) -> str | None:
    """从请求中获取 session Cookie。"""
    cookie_name = settings.RISK_COOKIE_NAME
    return request.cookies.get(cookie_name)


def set_session_cookie(response: Response, session_id: str, is_new: bool) -> None:
    """设置 session Cookie。

    仅在首次分配或 Cookie 缺失时设置，避免每次请求都发送 Set-Cookie。
    """
    if not is_new:
        return

    response.set_cookie(
        key=settings.RISK_COOKIE_NAME,
        value=session_id,
        max_age=settings.RISK_COOKIE_MAX_AGE,
        httponly=True,
        samesite="none",  # 跨域需要 none
        secure=True,      # 必须 HTTPS
        path="/",
    )


# ============================================================
# 认证检测
# ============================================================


def detect_authenticated_user(request: Request) -> bool:
    """非阻断检测用户是否已登录。

    只解析 JWT 验证有效性，不查数据库。

    Args:
        request: HTTP 请求

    Returns:
        True 表示有有效 JWT
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header[7:]
    try:
        jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return True
    except Exception:
        return False


# ============================================================
# 行为追踪
# ============================================================


def track_request(
    session: SessionState,
    request: Request,
    now: float,
) -> None:
    """记录请求行为到会话状态。

    Args:
        session: 会话状态
        request: HTTP 请求
        now: 当前时间
    """
    # 更新时间戳
    session.last_seen = now
    session.request_timestamps.append(now)
    session.total_requests += 1

    # 追踪 IP
    ip = get_client_ip(request)
    session.ip_addresses.add(ip)

    # 检测认证
    session.is_authenticated = detect_authenticated_user(request)

    # 追踪 course_id（带时间戳，用于时间窗口清理）
    course_id = extract_course_id_from_path(request.url.path)
    if course_id is not None:
        session.course_id_sequence.append(course_id)  # deque 自动限制 50 个
        session.course_id_history.append((course_id, now))

    # 追踪搜索关键词（带时间戳）
    if request.url.path == "/courses":
        for param in ("code", "name", "teacher"):
            value = request.query_params.get(param)
            if value:
                session.search_keywords.append((value, now))

    # 追踪 /plugin 请求
    if request.url.path == "/plugin":
        session.plugin_request_count += 1


# ============================================================
# 中间件
# ============================================================


class RiskControlMiddleware(BaseHTTPMiddleware):
    """API 风控中间件。"""

    async def dispatch(self, request: Request, call_next):
        """处理请求。"""
        # 跳过风控检查
        if not settings.RISK_ENABLED or should_skip_path(request.url.path):
            return await call_next(request)

        now = time.monotonic()
        store = get_session_store()

        # 概率性清理过期会话（1% 概率）
        if random.random() < 0.01:
            await store.cleanup(settings.RISK_SESSION_TTL)

        # 获取或创建 session
        session_id = get_session_cookie(request)
        is_new_session = session_id is None
        if is_new_session:
            session_id = generate_session_id()

        session = await store.get_or_create(session_id)

        # 检查封禁状态
        if session.blocked_until and now < session.blocked_until:
            return self._create_blocked_response(session, now)

        # 封禁已过期，重置
        if session.blocked_until and now >= session.blocked_until:
            session.blocked_until = None

        # 追踪请求
        track_request(session, request, now)

        # 提取 course_id（用于 IP 追踪）
        course_id = extract_course_id_from_path(request.url.path)

        # IP 级别追踪
        ip = get_client_ip(request)
        await _ip_tracker.track_request(ip, session_id, course_id, now)

        # 计算 session 级别风险分数
        result = compute_risk_score(
            session,
            now,
            rate_threshold=settings.RISK_RATE_THRESHOLD,
            course_threshold=settings.RISK_COURSE_THRESHOLD,
            auth_discount=settings.RISK_AUTH_DISCOUNT,
        )

        # 计算 IP 级别风险分数
        ip_score, ip_reasons = await _ip_tracker.compute_ip_risk(ip, now)

        # 合并风险：取较高等级
        if ip_score > result.score:
            # IP 风险更高，使用 IP 风险
            if ip_score >= 70:
                result = RiskResult(
                    score=ip_score,
                    level=RiskLevel.HIGH,
                    components={"ip_risk": ip_score},
                    reasons=ip_reasons,
                )
            elif ip_score >= 30:
                result = RiskResult(
                    score=ip_score,
                    level=RiskLevel.MEDIUM,
                    components={"ip_risk": ip_score},
                    reasons=ip_reasons,
                )

        # 高风险处理
        if result.level == RiskLevel.HIGH:
            session.blocked_until = now + settings.RISK_BLOCK_DURATION
            logger.error(format_risk_log(session, result, "block", now))
            return self._create_high_risk_response(session, result)

        # 中风险警告
        if result.level == RiskLevel.MEDIUM:
            logger.warning(format_risk_log(session, result, "warn", now))

        # 正常处理
        response = await call_next(request)

        # 添加响应头
        self._add_risk_headers(response, session, result)

        # 设置 Cookie（仅首次）
        set_session_cookie(response, session_id, is_new_session)

        return response

    def _add_risk_headers(
        self,
        response: Response,
        session: SessionState,
        result: RiskResult,
    ) -> None:
        """添加风控相关响应头。"""
        response.headers["X-Risk-Score"] = f"{result.score:.0f}"
        response.headers["X-Risk-Level"] = result.level.value
        response.headers["X-Risk-Session"] = session.session_id[:8]

    def _create_blocked_response(
        self,
        session: SessionState,
        now: float,
    ) -> JSONResponse:
        """封禁期间的响应。"""
        remaining = int(session.blocked_until - now)
        return JSONResponse(
            status_code=429,
            content={
                "detail": f"访问过于频繁，请 {remaining} 秒后重试",
                "retry_after": remaining,
            },
            headers={"Retry-After": str(remaining)},
        )

    def _create_high_risk_response(
        self,
        session: SessionState,
        result: RiskResult,
    ) -> JSONResponse:
        """高风险响应。"""
        return JSONResponse(
            status_code=429,
            content={
                "detail": "访问频率异常，请登录后继续使用",
                "risk_score": result.score,
                "risk_level": result.level.value,
                "session_id": session.session_id[:8],
            },
            headers={"Retry-After": str(settings.RISK_BLOCK_DURATION)},
        )
