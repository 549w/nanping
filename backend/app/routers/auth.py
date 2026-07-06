"""认证路由。

POST /auth/send-code  — 发送邮箱验证码
POST /auth/register   — 注册新用户
POST /auth/login      — 登录获取 JWT
"""

import logging
import random
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import log_activity
from ..config import settings
from ..database import get_db
from ..limiter import limiter
from ..models import User, VerificationCode
from ..schemas import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    SendCodeRequest,
    TokenResponse,
)
from ..auth import create_access_token, hash_password, normalize_password, verify_password

logger = logging.getLogger("nanping.auth")
router = APIRouter(tags=["认证"])


# ============================================================
# 验证码辅助（数据库存储，支持多 worker 共享）
# ============================================================


async def _get_code_entry(db: AsyncSession, email: str) -> VerificationCode | None:
    """从数据库获取指定邮箱的验证码记录。"""
    result = await db.execute(
        select(VerificationCode).where(VerificationCode.email == email)
    )
    return result.scalar_one_or_none()


async def _purge_expired_codes(db: AsyncSession) -> None:
    """清理数据库中过期的验证码记录。"""
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.execute(
        delete(VerificationCode).where(VerificationCode.expires_at < now_iso)
    )
    await db.commit()


# ============================================================
# POST /auth/send-code
# ============================================================


@router.post("/auth/send-code", response_model=MessageResponse)
@limiter.limit("3/minute")
async def send_code(
    request: Request, data: SendCodeRequest, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """发送验证码到指定邮箱。

    开发阶段使用 Mock 模式：验证码打印到控制台，值为固定值。
    同邮箱 60 秒内不可重复发送，验证码有效期 5 分钟。
    验证码存储在数据库而非内存，确保多 worker 部署时各进程共享。
    """
    email = data.email
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # 清理过期验证码
    await _purge_expired_codes(db)

    # 检查邮箱是否已注册（提前拦截，避免用户白等验证码）
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已注册，请直接登录",
        )

    # 60 秒冷却期检查
    existing = await _get_code_entry(db, email)
    if existing:
        last_sent = datetime.fromisoformat(existing.last_sent_at)
        if (now - last_sent).total_seconds() < 60:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请在 60 秒后重新获取验证码",
            )

    # 生成验证码
    if settings.AUTH_MOCK_MODE:
        code = settings.MOCK_VERIFICATION_CODE
        logger.info("Mock 模式发送验证码: email=%s code=%s", email, code)
    else:
        code = str(random.randint(100000, 999999))
        from ..email import send_verification_code

        try:
            await send_verification_code(email, code)
            logger.info("验证码已发送: email=%s", email)
        except Exception as exc:
            logger.error("验证码发送失败: email=%s error=%s", email, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="验证码发送失败，请稍后重试",
            ) from exc

    expires_at = (now + timedelta(minutes=5)).isoformat()

    # UPSERT: 存在则更新，不存在则插入
    if existing:
        existing.code = code
        existing.expires_at = expires_at
        existing.last_sent_at = now_iso
    else:
        db.add(
            VerificationCode(
                email=email,
                code=code,
                expires_at=expires_at,
                last_sent_at=now_iso,
            )
        )
    await db.commit()

    return MessageResponse(message="验证码已发送")


# ============================================================
# POST /auth/register
# ============================================================


@router.post("/auth/register", response_model=MessageResponse, status_code=201)
async def register(
    request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """注册新用户。

    校验验证码 → 检查邮箱唯一性 → 创建用户。
    验证码存储在数据库，多 worker 共享。
    """
    now = datetime.now(timezone.utc)

    # 从数据库获取验证码记录
    entry = await _get_code_entry(db, data.email)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先获取验证码",
        )
    if entry.code != data.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误",
        )
    if entry.expires_at < now.isoformat():
        await db.delete(entry)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码已过期",
        )

    # 检查邮箱唯一性
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已注册",
        )

    # 创建用户（前端已 SHA-256，后端再 bcrypt）
    normalized_pwd = normalize_password(data.password)
    user = User(
        email=data.email,
        password=hash_password(normalized_pwd),
        created_at=now.isoformat(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # 记录活动日志
    await log_activity(db, request, "register", user_id=user.id)

    # 销毁已使用验证码
    await db.delete(entry)
    await db.commit()

    return MessageResponse(message="注册成功")


# ============================================================
# POST /auth/login
# ============================================================


@router.post("/auth/login", response_model=TokenResponse)
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """用户登录，返回 JWT 令牌。"""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    # 前端已 SHA-256，后端验证时用相同的规范化流程
    normalized_pwd = normalize_password(data.password)
    if not user or not verify_password(normalized_pwd, user.password):
        logger.warning("登录失败: email=%s", data.email)
        await log_activity(db, request, "login_failed", details={"email": data.email})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    token = create_access_token(user.id)
    logger.info("登录成功: user_id=%s", user.id)
    await log_activity(db, request, "login", user_id=user.id)
    return TokenResponse(access_token=token)
