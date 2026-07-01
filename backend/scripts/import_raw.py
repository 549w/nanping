"""将 page_*.json 原始数据导入 SQLite 的 raw_course 表。

一次性的运营脚本，不依赖 FastAPI 项目配置，自建引擎和模型。

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/import_raw.py
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import Column, Integer, Text, Float
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# ---------- 独立配置（不依赖 app/） ----------

DB_PATH = "data/nanping.db"               # 数据库文件
PAGES_DIR = Path("data/raw_courses")       # JSON 源文件目录


# ---------- 独立模型定义（只包含本脚本需要的表） ----------

class Base(DeclarativeBase):
    pass


class RawCourse(Base):
    """教务系统原始教学班记录，39 字段。"""

    __tablename__ = "raw_course"

    id = Column(Integer, primary_key=True, autoincrement=True)

    KCH = Column(Text, nullable=False, comment="课程号")
    KCM = Column(Text, comment="课程名")
    KXH = Column(Text, comment="课序号")
    JXBID = Column(Text, comment="教学班 ID")
    JXBMC = Column(Text, comment="教学班名称")
    WID = Column(Text, comment="系统唯一标识")
    SKJS = Column(Text, comment="授课教师")
    PKDWDM = Column(Text, comment="排课单位代码")
    PKDWDM_DISPLAY = Column(Text, comment="排课单位名称")
    XNXQDM = Column(Text, comment="学年学期代码")
    XNXQDM_DISPLAY = Column(Text, comment="学年学期显示")
    SKXQ = Column(Text, comment="上课星期")
    SKJC = Column(Text, comment="上课节次")
    SKZC = Column(Text, comment="上课周次")
    SKJAS = Column(Text, comment="上课教室")
    JXLDM = Column(Text, comment="教学楼代码")
    JXLDM_DISPLAY = Column(Text, comment="教学楼名称")
    XXXQDM = Column(Text, comment="校区代码")
    XXXQDM_DISPLAY = Column(Text, comment="校区名称")
    YPSJDD = Column(Text, comment="上课时间地点汇总")
    SKBJ = Column(Text, comment="上课专业/学生群体")
    XKZRS = Column(Integer, comment="选课总人数")
    XF = Column(Float, comment="学分")
    XS = Column(Integer, comment="学时")
    KCSJXS = Column(Integer, comment="课程实践学时")
    KTJSXS = Column(Integer, comment="课堂讲授学时")
    SYXS = Column(Integer, comment="实验学时")
    KCFL1 = Column(Text, comment="课程分类 1 代码")
    KCFL1_DISPLAY = Column(Text, comment="课程分类 1 显示")
    TXKCLB = Column(Text, comment="通识课程类别代码")
    TXKCLB_DISPLAY = Column(Text, comment="通识课程类别显示")
    XGXKLBDM = Column(Text, comment="新工学科课类别代码")
    XGXKLBDM_DISPLAY = Column(Text, comment="新工学科课类别显示")
    PKZTDM = Column(Text, comment="排课状态代码")
    SFTK = Column(Integer, comment="是否停开")
    SFTK_DISPLAY = Column(Text, comment="是否停开显示")
    SFXGXK = Column(Integer, comment="是否新工学科课")
    SFXGXK_DISPLAY = Column(Text, comment="是否新工学科课显示")
    TKJG = Column(Text, comment="停开结果")


# ---------- 引擎 ----------

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables():
    """建表（不存在则自动创建）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("表 raw_course 已就绪。\n")


async def import_page(session: AsyncSession, filepath: Path) -> int:
    """导入单个 page_*.json 文件。

    Args:
        session: 数据库会话
        filepath: JSON 文件路径

    Returns:
        成功插入的记录数
    """
    with open(filepath, encoding="utf-8") as f:
        rows = json.load(f)

    # 数值字段做类型转换（JSON 里可能是字符串）
    int_columns = ("XKZRS", "XS", "KCSJXS", "KTJSXS", "SYXS", "SFTK", "SFXGXK")
    for row in rows:
        for col in int_columns:
            if row.get(col) is not None:
                try:
                    row[col] = int(row[col])
                except (ValueError, TypeError):
                    row[col] = None

    session.add_all([RawCourse(**row) for row in rows])
    await session.commit()
    return len(rows)


async def main():
    await create_tables()

    files = sorted(PAGES_DIR.glob("page_*.json"))
    if not files:
        print(f"错误：{PAGES_DIR} 下没有找到 page_*.json 文件")
        return

    total = 0
    for fp in files:
        async with async_session() as session:
            count = await import_page(session, fp)
        total += count
        print(f"  {fp.name} → {count} 条")

    print(f"\n完成！共 {total} 条记录，数据库 {DB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
