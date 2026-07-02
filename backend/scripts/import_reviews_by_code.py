"""将有课程号的评价导入 Review 表，并将已匹配的行从 all_reviews.xlsx 中删除。

只做精确课程号匹配（含教师/课程名辅助消歧），不补零、不猜。
匹配一条删一条，未匹配的留在 xlsx 里供后续处理。

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/import_reviews_by_code.py
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import Column, Integer, Text, Float, ForeignKey
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select

# ---------- 配置 ----------

DB_PATH = "data/nanping.db"
REVIEWS_PATH = Path("data/reviews_normalized/all_reviews.xlsx")

# ---------- 独立模型 ----------


class Base(DeclarativeBase):
    pass


class Course(Base):
    __tablename__ = "course"
    id = Column(Integer, primary_key=True)
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    teacher = Column(Text, nullable=False)
    department = Column(Text)
    credits = Column(Float)
    created_at = Column(Text, nullable=False)


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(Text, nullable=False, unique=True)
    password = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)


class Review(Base):
    __tablename__ = "review"
    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    rating = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    semester = Column(Text, nullable=True)
    is_anonymous = Column(Integer, nullable=False, default=0)
    is_deleted = Column(Integer, nullable=False, default=0)
    source = Column(Text, nullable=False, default="native")
    created_at = Column(Text, nullable=False)


# ---------- 引擎 ----------

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_system_user(session: AsyncSession) -> int:
    result = await session.execute(
        select(User).where(User.email == "system@nanping")
    )
    user = result.scalar_one_or_none()
    if user:
        return user.id
    now = _now()
    sys_user = User(email="system@nanping", password="", created_at=now)
    session.add(sys_user)
    await session.flush()
    return sys_user.id


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def teacher_matches(review_teacher: str, course_teacher: str) -> bool:
    """review_teacher 是否为 course_teacher 中某个教师的子串或反之。"""
    if not review_teacher or not course_teacher:
        return False
    rt = review_teacher.strip()
    ct_names = [t.strip() for t in course_teacher.split(",") if t.strip()]
    for ct in ct_names:
        if rt in ct or ct in rt:
            return True
    return False


async def lookup_course(session: AsyncSession, code: str, teacher: str,
                         name: str) -> tuple[int | None, str]:
    """精确课程号匹配，教师名/课程名辅助消歧。"""
    code = code.strip()
    result = await session.execute(select(Course).where(Course.code == code))
    courses = result.scalars().all()

    if not courses:
        return None, "not_found"

    if len(courses) == 1:
        return courses[0].id, "exact"

    # 多门课同号 → 教师消歧
    if teacher:
        for c in courses:
            if teacher_matches(teacher.strip(), c.teacher):
                return c.id, "teacher"

    # 课程名消歧
    if name:
        for c in courses:
            if c.name == name.strip():
                return c.id, "name"

    teachers = ", ".join(c.teacher for c in courses[:5])
    return None, f"ambiguous_{len(courses)}"


# ---------- 主流程 ----------

async def main():
    await create_tables()

    async with async_session() as session:
        sys_user_id = await ensure_system_user(session)
        await session.commit()
    print(f"系统用户 ID = {sys_user_id}\n")

    # ---- 处理 all_reviews.xlsx ----
    df = pd.read_excel(REVIEWS_PATH)
    code_mask = (df["course_code"].notna() &
                 (df["course_code"].astype(str).str.strip() != "") &
                 (df["course_code"].astype(str).str.strip() != "nan") &
                 (df["course_code"].astype(str).str.strip() != "无") &
                 (df["course_code"].astype(str).str.strip() != "课程号") &
                 (df["course_code"].astype(str).str.strip() != "原编号"))

    total_with_code = code_mask.sum()
    print(f"all_reviews.xlsx: {len(df)} 行，其中 {total_with_code} 行有课程号")

    matched_indices = []
    stats_exact = 0
    stats_teacher = 0
    stats_name = 0
    stats_not_found = 0
    stats_ambiguous = 0
    not_found_codes: dict[str, int] = {}

    now = _now()

    async with async_session() as session:
        for idx in df[code_mask].index:
            row = df.loc[idx]
            code = str(row["course_code"]).strip()
            teacher = str(row["teacher"]).strip() if pd.notna(row["teacher"]) else ""
            name = str(row["course_name"]).strip() if pd.notna(row["course_name"]) else ""
            semester = str(row["semester"]).strip() if pd.notna(row["semester"]) else ""
            content = str(row["content"]).strip()
            source_file = str(row["source_file"]).strip() if pd.notna(row["source_file"]) else ""

            course_id, match_type = await lookup_course(session, code, teacher, name)

            if course_id is None:
                if match_type == "not_found":
                    stats_not_found += 1
                    not_found_codes[code] = not_found_codes.get(code, 0) + 1
                else:
                    stats_ambiguous += 1
                continue

            # 匹配成功 → 入库
            session.add(Review(
                course_id=course_id,
                user_id=sys_user_id,
                content=content,
                semester=semester if semester else None,
                source=source_file,
                created_at=now,
            ))
            matched_indices.append(idx)

            if match_type == "exact":
                stats_exact += 1
            elif match_type == "teacher":
                stats_teacher += 1
            else:
                stats_name += 1

        await session.commit()

    # 从 xlsx 删除已匹配行
    matched_count = len(matched_indices)
    if matched_indices:
        df = df.drop(matched_indices)
        df.to_excel(REVIEWS_PATH, index=False, engine="openpyxl")
        print(f"已从 all_reviews.xlsx 删除 {matched_count} 行")

    # ---- 报告 ----
    print(f"\n===== 本次导入 =====")
    print(f"精确匹配（唯一课程号）: {stats_exact} 条")
    print(f"教师消歧匹配:         {stats_teacher} 条")
    print(f"课程名消歧匹配:       {stats_name} 条")
    print(f"合计导入:             {matched_count} 条")
    print(f"\n未匹配（留在 xlsx 中）:")
    print(f"  DB中无此课程号: {stats_not_found} 条（涉及 {len(not_found_codes)} 个不同课程号）")
    print(f"  课程号存在但教师/课程名无法消歧: {stats_ambiguous} 条")
    print(f"\nall_reviews.xlsx 剩余: {len(df)} 行")

    if not_found_codes:
        print(f"\nDB中不存在的课程号（前 30 个）:")
        for code, cnt in sorted(not_found_codes.items(), key=lambda x: -x[1])[:30]:
            print(f"  {code}: {cnt} 条")


if __name__ == "__main__":
    asyncio.run(main())
