"""中间件：请求日志 & 全局异常处理。"""

import logging
import time
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("nanping.middleware")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求的 method、path、status、耗时、客户端 IP。"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000)

        client_ip = request.client.host if request.client else "unknown"
        logger.info(
            "%s %s %d %.0fms %s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_ip,
        )
        return response


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局异常处理器。

    捕获所有未处理的异常，记录完整 traceback 到日志，
    向客户端返回统一的 500 响应（不泄露实现细节）。
    """
    logger.error(
        "未处理异常 | %s %s | %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )
