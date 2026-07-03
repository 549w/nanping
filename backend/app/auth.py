"""认证基础设施。

- 密码哈希：passlib + bcrypt
- 密码规范化：SHA-256（兼容前端已哈希和未哈希的情况）
- JWT 令牌：PyJWT + HS256
- 登录态依赖注入：从 Authorization: Bearer 头解析 user_id
"""

from datetime import datetime, timezone, timedelta
import hashlib

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db
from .models import User

# ---- 密码哈希 ----

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def normalize_password(password: str) -> str:
    """对密码进行 SHA-256 规范化（兼容前端已哈希和未哈希的情况）。

    如果密码已经是 64 位十六进制（SHA-256 输出），直接返回。
    否则进行 SHA-256 哈希。

    Args:
        password: 用户输入的密码（可能是明文或 SHA-256 哈希）

    Returns:
        SHA-256 哈希后的密码
    """
    # 如果已经是 64 位十六进制（SHA-256 输出），直接返回
    if len(password) == 64 and all(c in '0123456789abcdef' for c in password.lower()):
        return password
    # 否则进行 SHA-256 哈希
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希。

    Args:
        password: 明文密码

    Returns:
        哈希后的密码字符串
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配。

    Args:
        plain_password: 用户输入的明文密码
        hashed_password: 数据库中存储的哈希

    Returns:
        是否匹配
    """
    return pwd_context.verify(plain_password, hashed_password)


# ---- JWT ----

def create_access_token(user_id: int) -> str:
    """为用户生成 JWT 访问令牌。

    Args:
        user_id: 用户主键

    Returns:
        JWT 字符串
    """
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# ---- FastAPI 依赖 ----

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Authorization: Bearer <token> 头解析当前登录用户。

    用法（在 router 里）：
        @router.get("/xxx")
        async def handler(current_user: User = Depends(get_current_user)):
            ...

    Args:
        credentials: HTTP Bearer 凭证（由 HTTPBearer 自动提取）
        db: 数据库会话

    Returns:
        当前登录的 User ORM 对象

    Raises:
        HTTPException 401: token 无效/过期/用户不存在
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
        )

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    return user
