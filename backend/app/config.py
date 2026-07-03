"""应用配置。

所有配置项通过环境变量读取，开发阶段使用默认值。
使用 pydantic-settings 自动加载 .env 文件并进行类型校验。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。

    所有敏感值都有开发阶段的安全默认值，
    生产环境必须通过 .env 文件或环境变量覆盖。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 数据库 ----
    DATABASE_URL: str = "sqlite+aiosqlite:///data/nanping.db"

    # ---- JWT ----
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 小时

    # ---- CORS ----
    CORS_ORIGINS: list[str] = ["*"]

    # ---- 认证 Mock 模式 ----
    # 开发阶段跳过真实邮件发送，使用固定验证码
    AUTH_MOCK_MODE: bool = True
    MOCK_VERIFICATION_CODE: str = "123456"

    # ---- 管理后台 ----
    ADMIN_SECRET_KEY: str = "change-me-admin-secret"

    # ---- 日志 ----
    LOG_LEVEL: str = "INFO"

    # ---- Resend 邮件服务（仅 AUTH_MOCK_MODE=False 时需要） ----
    # 注册地址：https://resend.com
    # API Key 在 https://resend.com/api-keys 创建
    RESEND_API_KEY: str = ""
    # 发件人地址，需先在 Resend 中验证域名并添加 DNS 记录
    SENDER_EMAIL: str = "noreply@eznju.com"


settings = Settings()
