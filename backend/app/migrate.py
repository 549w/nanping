"""数据库迁移辅助。

SQLite 的 ``Base.metadata.create_all`` 只创建新表，不会修改已有表。
此模块在应用启动时执行必要的 ALTER TABLE，确保旧数据库兼容新代码。
"""

import logging

logger = logging.getLogger("nanping.migrate")


MIGRATIONS = [
    # (表名, 列名, 列定义)
    ("user", "is_admin", "INTEGER DEFAULT 0"),
]


async def run_migrations(conn) -> None:
    """检查并执行所有待执行的列迁移。

    用 PRAGMA table_info 检查列是否存在，不存在则 ALTER TABLE ADD COLUMN。
    """
    import sqlalchemy as sa

    for table, column, definition in MIGRATIONS:
        # 检查列是否存在
        result = await conn.execute(
            sa.text(f"PRAGMA table_info({table})")
        )
        columns = [row[1] for row in result.fetchall()]
        if column not in columns:
            logger.info("迁移: ALTER TABLE %s ADD COLUMN %s %s", table, column, definition)
            await conn.execute(
                sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            )
        else:
            logger.debug("列 %s.%s 已存在，跳过", table, column)
