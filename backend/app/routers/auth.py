"""认证路由。

POST /auth/send-code  — 发送邮箱验证码
POST /auth/register   — 注册新用户
POST /auth/login      — 登录获取 JWT
"""

import random
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..limiter import limiter
from ..models import User
from ..schemas import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    SendCodeRequest,
    TokenResponse,
)
from ..auth import create_access_token, hash_password, verify_password

router = APIRouter(tags=["认证"])


# ============================================================
# 内存验证码存储
# ============================================================


@dataclass
class CodeEntry:
    """一条验证码记录。"""

    code: str
    expires_at: datetime
    last_sent_at: datetime


# {email: CodeEntry}
_verification_codes: dict[str, CodeEntry] = {}


def _purge_expired() -> None:
    """清理过期的验证码记录，防止内存无限增长。"""
    now = datetime.now(timezone.utc)
    expired = [email for email, entry in _verification_codes.items() if entry.expires_at < now]
    for email in expired:
        del _verification_codes[email]


# ============================================================
# POST /auth/send-code
# ============================================================


@router.post("/auth/send-code", response_model=MessageResponse)
@limiter.limit("3/minute")
async def send_code(request: Request, data: SendCodeRequest) -> MessageResponse:
    """发送验证码到指定邮箱。

    开发阶段使用 Mock 模式：验证码打印到控制台，值为固定值。
    同邮箱 60 秒内不可重复发送，验证码有效期 5 分钟。
    """
    _purge_expired()
    email = data.email
    now = datetime.now(timezone.utc)

    # 60 秒冷却期检查
    existing = _verification_codes.get(email)
    if existing and (now - existing.last_sent_at).total_seconds() < 60:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请在 60 秒后重新获取验证码",
        )

    # 生成验证码
    if settings.AUTH_MOCK_MODE:
        code = settings.MOCK_VERIFICATION_CODE
        print(f"[MOCK] 验证码 for {email}: {code}")
    else:
        code = str(random.randint(100000, 999999))
        # TODO: 通过 SMTP 发送邮件
        # await send_email(email, f"您的 Nanping 验证码为：{code}")

    _verification_codes[email] = CodeEntry(
        code=code,
        expires_at=now + timedelta(minutes=5),
        last_sent_at=now,
    )
    return MessageResponse(message="验证码已发送")


# ============================================================
# POST /auth/register
# ============================================================


@router.post("/auth/register", response_model=MessageResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)) -> MessageResponse:
    """注册新用户。

    校验验证码 → 检查邮箱唯一性 → 创建用户。
    """
    # 校验验证码（先检查再清理，确保 "已过期" 分支可达）
    entry = _verification_codes.get(data.email)
    if not entry or entry.code != data.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        )
    if entry.expires_at < datetime.now(timezone.utc):
        del _verification_codes[data.email]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码已过期",
        )

    # 清理其他过期条目
    _purge_expired()

    # 检查邮箱唯一性
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已注册",
        )

    # 创建用户
    user = User(
        email=data.email,
        password=hash_password(data.password),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(user)
    await db.commit()

    # 销毁已使用验证码
    del _verification_codes[data.email]

    return MessageResponse(message="注册成功")


# ============================================================
# POST /auth/login
# ============================================================


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """用户登录，返回 JWT 令牌。"""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)
