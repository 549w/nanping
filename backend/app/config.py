"""应用配置。

所有配置项通过环境变量读取，开发阶段使用默认值。
"""

import os


class Settings:
    """应用配置。"""

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///data/nanping.db",
    )


settings = Settings()
