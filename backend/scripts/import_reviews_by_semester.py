"""课程名 + 教师 + 学期三重匹配导入。

匹配逻辑：
  1. 课程名模糊匹配（精确 → 规范化精确 → 规范化包含）
  2. 教师消歧（子串匹配）
  3. 学期消歧：xlsx 学期展开后，与 DB course_offering 的学期取交集
     年份学期 "2020" → 展开为 2019秋 + 2020春
     明确学期 "2024春" → 直接匹配 2024春
  4. 三层过滤后唯一确定 → 自动入库；否则跳过

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/import_reviews_by_semester.py
"""

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import Column, Integer, Text, Float, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# ---------- 配置 ----------

DB_PATH = "data/nanping.db"
REVIEWS_PATH = Path("data/reviews_normalized/all_reviews.xlsx")
REPORT_PATH = Path("docs/import_by_semester_report.md")

# ---------- 模型 ----------

class Base(DeclarativeBase):
    pass

class Course(Base):
    __tablename__ = "course"
    id = Column(Integer, primary_key=True)
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    teacher = Column(Text, nullable=False)

class CourseOffering(Base):
    __tablename__ = "course_offering"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False)
    semester = Column(Text, nullable=False)

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

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------- 规范化 ----------

def normalize(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("　", " ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\u2160-\u2188]", "", s)
    return s

# ---------- 学期 ----------

def parse_db_semester(s: str) -> tuple[int, str] | None:
    """解析 DB 学期格式 '2020-2021学年 第1学期' → (2020, '秋') 或 (2021, '春')。"""
    m = re.match(r'(\d{4})-(\d{4})学年 第(\d)学期', s)
    if not m:
        return None
    y1, y2, term = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if term == 1:
        return (y1, "秋")
    elif term == 2:
        return (y2, "春")
    return None


def expand_xlsx_semester(s: str) -> set[tuple[int, str]]:
    """展开 xlsx 学期为 (year, season) 集合。

    "2020"    → {(2019, '秋'), (2020, '春')}
    "2024春"  → {(2024, '春')}
    "2025秋"  → {(2025, '秋')}
    空/无     → 空集合（不过滤）
    """
    s = s.strip()
    if not s or s.lower() in ("nan", "无", ""):
        return set()

    # 带季节：如 "2024春", "2025秋", "2024春/秋" 等
    m = re.match(r'(\d{4})(春|秋|夏|冬)', s)
    if m:
        return {(int(m.group(1)), m.group(2))}

    # 纯年份：如 "2020", "2021"
    m = re.match(r'^(\d{4})$', s)
    if m:
        y = int(m.group(1))
        return {(y - 1, "秋"), (y, "春")}

    return set()


def semester_match(xlsx_sem: str, db_sems: set[tuple[int, str]]) -> bool:
    """xlsx 学期展开后是否与 DB 学期有交集。xlsx 为空时视为匹配。"""
    expanded = expand_xlsx_semester(xlsx_sem)
    if not expanded:
        return True  # xlsx 无学期，不参与过滤
    return bool(expanded & db_sems)


# ---------- 匹配 ----------

def teacher_matches(review_teacher: str, course_teacher: str) -> bool:
    if not review_teacher or not course_teacher:
        return False
    rt = review_teacher.strip()
    ct_names = [t.strip() for t in course_teacher.split(",") if t.strip()]
    for ct in ct_names:
        if rt in ct or ct in rt:
            return True
    return False


def find_candidate_courses(xlsx_name: str, xlsx_teacher: str, xlsx_semester: str,
                           exact_index: dict, norm_index: dict,
                           course_semesters: dict[int, set]) -> list[tuple[int, str, str, str, str]]:
    """返回 [(course_id, code, name, teacher, match_level), ...]，已按学期过滤。

    match_level: exact | normalized | contains
    """
    name = xlsx_name.strip()
    nname = normalize(name)
    xlsx_t = xlsx_teacher.strip() if xlsx_teacher else ""

    raw: list[tuple[int, str, str, str, str]] = []

    # 1. 精确
    if name in exact_index:
        raw = [(cid, code, cname, ct, "exact")
               for cid, code, cname, ct in exact_index[name]]
    # 2. 规范化精确
    elif nname in norm_index:
        raw = [(cid, code, cname, ct, "normalized")
               for cid, code, cname, ct in norm_index[nname]]
    # 3. 规范化包含
    else:
        for db_norm, courses in norm_index.items():
            if not nname or not db_norm:
                continue
            if nname in db_norm or db_norm in nname:
                for cid, code, cname, ct in courses:
                    raw.append((cid, code, cname, ct, "contains"))

    results = []
    for cid, code, cname, ct, level in raw:
        # 教师过滤
        if xlsx_t and not teacher_matches(xlsx_t, ct):
            continue
        # 学期过滤
        if not semester_match(xlsx_semester, course_semesters.get(cid, set())):
            continue
        results.append((cid, code, cname, ct, level))

    return results


# ---------- 主流程 ----------

async def main():
    async with async_session() as session:
        # 系统用户
        result = await session.execute(select(User).where(User.email == "system@nanping"))
        sys_user = result.scalar_one_or_none()
        if not sys_user:
            sys_user = User(email="system@nanping", password="", created_at=_now())
            session.add(sys_user)
            await session.flush()
        sys_user_id = sys_user.id

        # 加载课程
        result = await session.execute(select(Course.id, Course.code, Course.name, Course.teacher))
        exact_index: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
        norm_index: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
        for cid, code, name, teacher in result:
            code = code.strip() if code else ""
            name = name.strip() if name else ""
            teacher = teacher.strip() if teacher else ""
            exact_index[name].append((cid, code, name, teacher))
            norm_index[normalize(name)].append((cid, code, name, teacher))

        # 加载学期
        result = await session.execute(select(CourseOffering.course_id, CourseOffering.semester))
        course_semesters: dict[int, set[tuple[int, str]]] = defaultdict(set)
        for cid, sem in result:
            parsed = parse_db_semester(sem)
            if parsed:
                course_semesters[cid].add(parsed)

        await session.commit()

    print(f"课程索引：{len(exact_index)} 精确名, {len(norm_index)} 规范化名")
    print(f"有学期信息的课程：{len(course_semesters)} 门\n")

    # ---- 读 xlsx ----
    df = pd.read_excel(REVIEWS_PATH)
    print(f"all_reviews.xlsx: {len(df)} 行")

    name_mask = (df["course_name"].notna() &
                 (df["course_name"].astype(str).str.strip() != "") &
                 (df["course_name"].astype(str).str.strip() != "nan"))
    print(f"有课程名: {name_mask.sum()} 行\n")

    # 统计
    stats = {"exact": 0, "normalized": 0, "contains": 0,
             "not_found": 0, "ambiguous": 0}
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

            candidates = find_candidate_courses(
                name, teacher, semester,
                exact_index, norm_index, course_semesters
            )

            if not candidates:
                # 判断是课程名/教师找不到，还是学期过滤掉了
                candidates_no_sem = find_candidate_courses(
                    name, teacher, "",
                    exact_index, norm_index, course_semesters
                )
                if not candidates_no_sem:
                    stats["not_found"] += 1
                    not_found_names[name] = not_found_names.get(name, 0) + 1
                else:
                    stats["ambiguous"] += 1
                    ambiguous_names[name] = ambiguous_names.get(name, 0) + 1
                continue

            if len(candidates) > 1:
                stats["ambiguous"] += 1
                ambiguous_names[name] = ambiguous_names.get(name, 0) + 1
                continue

            # 唯一匹配 → 入库
            cid, code, cname, ct, level = candidates[0]
            session.add(Review(
                course_id=cid,
                user_id=sys_user_id,
                content=content,
                semester=semester if semester else None,
                source=source_file,
                created_at=now,
            ))
            matched_indices.append(idx)
            stats[level] += 1

            if source_file not in source_stats:
                source_stats[source_file] = {}
            source_stats[source_file][semester or "(空)"] = \
                source_stats[source_file].get(semester or "(空)", 0) + 1

        await session.commit()

    matched_count = len(matched_indices)
    print(f"匹配成功: {matched_count} 条")
    print(f"  精确:       {stats['exact']}")
    print(f"  规范化:     {stats['normalized']}")
    print(f"  包含:       {stats['contains']}")
    print(f"未匹配: {stats['not_found'] + stats['ambiguous']} 条")
    print(f"  名称/教师无匹配: {stats['not_found']}")
    print(f"  多条/学期无法消歧: {stats['ambiguous']}")

    if matched_indices:
        df = df.drop(matched_indices)
        df.to_excel(REVIEWS_PATH, index=False, engine="openpyxl")
        print(f"\n已从 xlsx 删除 {matched_count} 行，剩余 {len(df)} 行")

    # ---- 报告 ----
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 学期匹配导入报告\n",
        f"**执行时间**：{_now()}\n",
        "---\n",
        "## 总体统计\n",
        f"| 指标 | 数量 |",
        f"|------|------|",
        f"| 匹配成功 | **{matched_count}** |",
        f"| ├ 精确 | {stats['exact']} |",
        f"| ├ 规范化 | {stats['normalized']} |",
        f"| └ 包含 | {stats['contains']} |",
        f"| 未匹配 | {stats['not_found'] + stats['ambiguous']} |",
        f"| ├ 名称/教师无匹配 | {stats['not_found']} |",
        f"| └ 多条/学期消歧失败 | {stats['ambiguous']} |",
        f"| xlsx 剩余 | {len(df)} |\n",
    ]
    if source_stats:
        lines.append("## 按来源 / 学期\n")
        lines.append("| 来源 | 学期 | 条数 |")
        lines.append("|------|------|------|")
        for src in sorted(source_stats):
            for sem in sorted(source_stats[src]):
                lines.append(f"| {src} | {sem} | {source_stats[src][sem]} |")
        lines.append("")
    if not_found_names:
        lines.append("## 未匹配：名称/教师无匹配\n")
        lines.append("| 课程名 | 条数 |")
        lines.append("|--------|------|")
        for nm, cnt in sorted(not_found_names.items(), key=lambda x: (-x[1], x[0]))[:50]:
            lines.append(f"| {nm} | {cnt} |")
        lines.append("")
    if ambiguous_names:
        lines.append("## 未匹配：学期消歧失败\n")
        lines.append("| 课程名 | 条数 |")
        lines.append("|--------|------|")
        for nm, cnt in sorted(ambiguous_names.items(), key=lambda x: (-x[1], x[0]))[:50]:
            lines.append(f"| {nm} | {cnt} |")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
