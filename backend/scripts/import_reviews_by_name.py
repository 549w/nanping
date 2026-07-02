"""用课程名（+ 教师消歧）匹配导入评价。

适用场景：all_reviews.xlsx 中无课程号（或课程号匹配不上），但有课程名的记录。

匹配逻辑（两级、四层）：
  1. 精确匹配 → 唯一 course → 直接导入
  2. 精确匹配 → 多条 course → 教师名子串消歧 → 导入
  3. 规范化匹配（小写 + 全半角统一 + 去标点空格，只保留中英文数字）→ 唯一 → 导入
  4. 规范化匹配 → 多条 course → 教师消歧 → 导入
  5. 均失败 → 跳过，留在 xlsx 中

匹配一条从 xlsx 删一条。统计报告输出到 docs/。

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/import_reviews_by_name.py
"""

import asyncio
import re
from collections import defaultdict
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
REPORT_PATH = Path("docs/import_by_name_report_ambi.md")

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


# ---------- 规范化 ----------

def normalize(s: str) -> str:
    """规范化课程名：小写 + 全半角统一 + 去标点空格（只保留中英文+数字）。"""
    s = s.strip().lower()
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("　", " ")
    s = re.sub(r"\s+", " ", s)
    # 只保留：小写字母、数字、中文字符、罗马数字
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\u2160-\u2188]", "", s)
    return s


# ---------- 教师消歧 ----------

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


# ---------- 课程名索引（内存） ----------

# exact_index: 精确课程名 → [(course_id, teacher)]
# norm_index:  规范化课程名 → [(course_id, teacher)]
exact_index: dict[str, list[tuple[int, str]]] = defaultdict(list)
norm_index: dict[str, list[tuple[int, str]]] = defaultdict(list)


async def build_index(session: AsyncSession):
    """一次性加载全部课程到内存，构建两级索引。"""
    result = await session.execute(select(Course.id, Course.name, Course.teacher))
    for cid, name, teacher in result:
        name = name.strip() if name else ""
        teacher = teacher.strip() if teacher else ""
        exact_index[name].append((cid, teacher))
        norm_index[normalize(name)].append((cid, teacher))


def lookup_by_name(name: str, teacher: str) -> tuple[int | None, str]:
    """两级课程名匹配。

    Returns:
        (course_id, match_type) 或 (None, reason)
        match_type 取值：exact, exact_teacher, normalized, normalized_teacher
    """
    name = name.strip()
    teacher = teacher.strip() if teacher else ""

    # ---- 第一级：精确匹配 ----
    exact_candidates = exact_index.get(name, [])

    if len(exact_candidates) == 1:
        return exact_candidates[0][0], "exact"

    if len(exact_candidates) > 1 and teacher:
        for cid, ct in exact_candidates:
            if teacher_matches(teacher, ct):
                return cid, "exact_teacher"

    # ---- 第二级：规范化匹配 ----
    norm_name = normalize(name)
    norm_candidates = norm_index.get(norm_name, [])

    if len(norm_candidates) == 1:
        return norm_candidates[0][0], "normalized"

    if len(norm_candidates) > 1 and teacher:
        for cid, ct in norm_candidates:
            if teacher_matches(teacher, ct):
                return cid, "normalized_teacher"

    # ---- 全部失败 ----
    if exact_candidates:
        return None, f"ambiguous_{len(exact_candidates)}"
    if norm_candidates:
        return None, f"ambiguous_norm_{len(norm_candidates)}"

    return None, "not_found"


# ---------- 主流程 ----------

async def main():
    await create_tables()

    async with async_session() as session:
        sys_user_id = await ensure_system_user(session)
        await build_index(session)
        await session.commit()

    print(f"系统用户 ID = {sys_user_id}")
    print(f"课程索引：{len(exact_index)} 个精确名，{len(norm_index)} 个规范化名\n")

    # ---- 读取 all_reviews.xlsx ----
    df = pd.read_excel(REVIEWS_PATH)
    print(f"all_reviews.xlsx: {len(df)} 行")

    name_mask = (df["course_name"].notna() &
                 (df["course_name"].astype(str).str.strip() != "") &
                 (df["course_name"].astype(str).str.strip() != "nan"))
    total_with_name = name_mask.sum()
    print(f"其中有课程名: {total_with_name} 行\n")

    # 统计（按匹配层级分开）
    stats: dict[str, int] = {
        "exact": 0, "exact_teacher": 0,
        "normalized": 0, "normalized_teacher": 0,
        "not_found": 0, "ambiguous": 0,
    }
    matched_indices = []
    not_found_names: dict[str, int] = {}
    ambiguous_names: dict[str, int] = {}
    source_stats: dict[str, dict] = {}

    now = _now()

    async with async_session() as session:
        for idx in df[name_mask].index:
            row = df.loc[idx]
            name = str(row["course_name"]).strip()
            teacher = str(row["teacher"]).strip() if pd.notna(row["teacher"]) else ""
            semester = str(row["semester"]).strip() if pd.notna(row["semester"]) else ""
            content = str(row["content"]).strip()
            source_file = str(row["source_file"]).strip() if pd.notna(row["source_file"]) else ""

            course_id, match_type = lookup_by_name(name, teacher)

            if course_id is None:
                if match_type == "not_found":
                    stats["not_found"] += 1
                    not_found_names[name] = not_found_names.get(name, 0) + 1
                else:
                    stats["ambiguous"] += 1
                    ambiguous_names[name] = ambiguous_names.get(name, 0) + 1
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
            print(f"匹配入库 - course_id: {course_id} - content: {content}")
            matched_indices.append(idx)
            stats[match_type] += 1

            if source_file not in source_stats:
                source_stats[source_file] = {}
            source_stats[source_file][semester] = \
                source_stats[source_file].get(semester, 0) + 1

        await session.commit()

    matched_count = len(matched_indices)
    print(f"匹配成功: {matched_count} 条")
    print(f"  精确-唯一:        {stats['exact']}")
    print(f"  精确-教师消歧:    {stats['exact_teacher']}")
    print(f"  规范化-唯一:      {stats['normalized']}")
    print(f"  规范化-教师消歧:  {stats['normalized_teacher']}")
    print(f"未匹配: {stats['not_found'] + stats['ambiguous']} 条")
    print(f"  课程名不在 DB:   {stats['not_found']}（{len(not_found_names)} 个不同名）")
    print(f"  消歧失败:        {stats['ambiguous']}（{len(ambiguous_names)} 个不同名）")

    # 从 xlsx 删除已匹配行
    if matched_indices:
        df = df.drop(matched_indices)
        df.to_excel(REVIEWS_PATH, index=False, engine="openpyxl")
        print(f"\n已从 all_reviews.xlsx 删除 {matched_count} 行，剩余 {len(df)} 行")

    # ---- 生成 Markdown 报告 ----
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# 课程名匹配导入报告\n")
    lines.append(f"**执行时间**：{_now()}\n")
    lines.append(f"**脚本**：`backend/scripts/import_reviews_by_name.py`\n")
    lines.append("---\n")

    lines.append("## 总体统计\n")
    lines.append(f"| 指标 | 数量 |")
    lines.append(f"|------|------|")
    lines.append(f"| 导入前 xlsx 总行数 | {len(df) + matched_count} |")
    lines.append(f"| 有课程名的行数 | {total_with_name} |")
    lines.append(f"| **匹配成功导入** | **{matched_count}** |")
    lines.append(f"| ├ 精确-唯一 | {stats['exact']} |")
    lines.append(f"| ├ 精确-教师消歧 | {stats['exact_teacher']} |")
    lines.append(f"| ├ 规范化-唯一 | {stats['normalized']} |")
    lines.append(f"| └ 规范化-教师消歧 | {stats['normalized_teacher']} |")
    lines.append(f"| **未匹配（留在 xlsx）** | **{stats['not_found'] + stats['ambiguous']}** |")
    lines.append(f"| 导入后 xlsx 剩余 | {len(df)} |")
    lines.append("")

    if source_stats:
        lines.append("## 按来源 / 学期分布\n")
        lines.append("| 来源文件 | 学期 | 导入条数 |")
        lines.append("|----------|------|----------|")
        for src in sorted(source_stats.keys()):
            for sem in sorted(source_stats[src].keys()):
                cnt = source_stats[src][sem]
                lines.append(f"| {src} | {sem or '(空)'} | {cnt} |")
        lines.append("")

    if not_found_names:
        lines.append("## 未匹配：课程名不在 DB 中\n")
        lines.append(f"共 {stats['not_found']} 条，涉及 {len(not_found_names)} 个不同课程名。\n")
        lines.append("| 课程名 | 条数 |")
        lines.append("|--------|------|")
        for nm, cnt in sorted(not_found_names.items(), key=lambda x: (-x[1], x[0]))[:50]:
            lines.append(f"| {nm} | {cnt} |")
        if len(not_found_names) > 50:
            lines.append(f"| ... | （共 {len(not_found_names)} 个，仅列前 50） |")
        lines.append("")

    if ambiguous_names:
        lines.append("## 未匹配：课程名存在但消歧失败\n")
        lines.append(f"共 {stats['ambiguous']} 条，涉及 {len(ambiguous_names)} 个不同课程名。\n")
        lines.append("| 课程名 | 条数 |")
        lines.append("|--------|------|")
        for nm, cnt in sorted(ambiguous_names.items(), key=lambda x: (-x[1], x[0]))[:50]:
            lines.append(f"| {nm} | {cnt} |")
        if len(ambiguous_names) > 50:
            lines.append(f"| ... | （共 {len(ambiguous_names)} 个，仅列前 50） |")
        lines.append("")

    #report = "\n".join(lines) + "\n"
    #REPORT_PATH.write_text(report, encoding="utf-8")
    #print(f"\n报告已保存: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
