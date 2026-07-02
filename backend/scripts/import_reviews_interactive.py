"""交互式确认导入：按课程号精确匹配，人工 y/n 决定是否入库。

流程：
  1. 将 xlsx 按课程号分组
  2. 每组用课程号在 DB 中查找所有对应 course
  3. 展示候选项，人工 y/n/编号确认
  4. y → 该组全部评价入表；n → 跳过；s → 跳过剩余全部
  5. 匹配一条删一条，最后输出报告到 docs/

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/import_reviews_interactive.py
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
REPORT_PATH = Path("docs/import_interactive_report.md")

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

        # 课程 → code_index
        result = await session.execute(select(Course.id, Course.code, Course.name, Course.teacher))
        code_index: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
        for cid, code, name, teacher in result:
            code = code.strip() if code else ""
            name = name.strip() if name else ""
            teacher = teacher.strip() if teacher else ""
            code_index[code].append((cid, code, name, teacher))

        # 学期（展示用）
        result = await session.execute(select(CourseOffering.course_id, CourseOffering.semester))
        sem_short: dict[int, str] = {}
        raw = defaultdict(list)
        for cid, sem in result:
            raw[cid].append(sem)
        for cid, sems in raw.items():
            short = []
            for s in sems:
                m = re.match(r'(\d{4})-(\d{4})学年 第(\d)学期', s)
                if m:
                    y1, y2, t = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    short.append(f"{y1}秋" if t == 1 else f"{y2}春")
            sem_short[cid] = ", ".join(sorted(set(short)))

        await session.commit()

    print(f"课程号索引：{len(code_index)} 个\n")

    # ---- 读 xlsx ----
    df = pd.read_excel(REVIEWS_PATH)
    print(f"all_reviews.xlsx: {len(df)} 行")

    # 筛选有课程号的行
    df["_code"] = df.apply(
        lambda r: str(r["course_code"]).strip() if pd.notna(r["course_code"]) else "", axis=1
    )
    code_mask = (df["_code"] != "") & (df["_code"] != "nan") & (df["_code"] != "无")
    df_code = df[code_mask]
    df_nocode = df[~code_mask]

    print(f"有课程号: {len(df_code)} 行（{df_code['_code'].nunique()} 个不同号）")
    print(f"无课程号: {len(df_nocode)} 行（自动跳过）\n")

    # 按课程号分组
    groups = dict(list(df_code.groupby("_code")))

    # 预计算匹配
    group_candidates = {}
    for code, gdf in groups.items():
        candidates = code_index.get(code, [])
        group_candidates[code] = candidates

    matchable = sum(1 for c in group_candidates.values() if c)
    no_match = sum(1 for c in group_candidates.values() if not c)
    print(f"分组: {len(groups)} 组")
    print(f"  DB有匹配: {matchable} 组")
    print(f"  DB无此号: {no_match} 组（自动跳过）\n")

    # ---- 交互确认 ----
    approved: dict[str, int] = {}   # code -> course_id
    rejected: list[str] = []
    skip_all = False

    for code, gdf in sorted(groups.items(), key=lambda x: len(group_candidates.get(x[0], []))):
        candidates = group_candidates[code]
        name0 = str(gdf.iloc[0]["course_name"])[:60]
        teacher0 = str(gdf.iloc[0]["teacher"]) if pd.notna(gdf.iloc[0]["teacher"]) else ""
        semester0 = str(gdf.iloc[0]["semester"]) if pd.notna(gdf.iloc[0]["semester"]) else ""
        sample = str(gdf.iloc[0]["content"])[:80]
        n_rows = len(gdf)

        if not candidates:
            continue
        if skip_all:
            rejected.append(code)
            continue

        show_limit = min(len(candidates), 20) if len(candidates) <= 30 else 15
        print(f"\n{'─'*60}")
        print(f"XLSX 课程号: {code}")
        print(f"XLSX 课程名: {name0}")
        print(f"XLSX 教师:   {teacher0 or '(空)'}")
        print(f"XLSX 学期:   {semester0 or '(空)'}")
        print(f"评价数:      {n_rows} 条")
        print(f"样例内容:    {sample}...")
        print(f"\nDB 匹配 ({len(candidates)} 个 course):")
        for i, (cid, ccode, cname, cteacher) in enumerate(candidates[:show_limit], 1):
            sems = sem_short.get(cid, "-")
            print(f"  [{i}] {ccode} {cname}  —  {cteacher}")
            print(f"      学期: {sems}")

        if len(candidates) > show_limit:
            remaining = len(candidates) - show_limit
            show_all = input(f"\n  ... 还有 {remaining} 个，全部展示? [y/回车]: ").strip().lower()
            if show_all == 'y':
                for i, (cid, ccode, cname, cteacher) in enumerate(candidates[show_limit:], show_limit + 1):
                    sems = sem_short.get(cid, "-")
                    print(f"  [{i}] {ccode} {cname}  —  {cteacher}")
                    print(f"      学期: {sems}")

        while True:
            prompt = f"\n导入? [y=第1个 / n=跳过 / 1~{len(candidates)}编号 / s=跳过剩余]: "
            choice = input(prompt).strip().lower()
            if choice == 'y':
                approved[code] = candidates[0][0]
                break
            elif choice == 'n':
                rejected.append(code)
                break
            elif choice == 's':
                rejected.append(code)
                skip_all = True
                print("已跳过剩余全部。")
                break
            elif choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(candidates):
                    approved[code] = candidates[idx - 1][0]
                    break
            print("无效输入。")

    # ---- 执行导入 ----
    print(f"\n{'='*60}")
    print(f"导入: {len(approved)} 组确认, {len(rejected)} 组跳过...")

    imported = 0
    now = _now()
    approved_detail: list[tuple[str, str, int, str, str]] = []

    async with async_session() as session:
        for code, course_id in approved.items():
            gdf = groups[code]
            name0 = str(gdf.iloc[0]["course_name"])[:60]
            db_code, db_name, db_teacher = "", "", ""
            for cid, ccode, cname, cteacher in code_index.get(code, []):
                if cid == course_id:
                    db_code, db_name, db_teacher = ccode, cname, cteacher
                    break
            approved_detail.append((code, name0, course_id, db_name, db_teacher))

            for _, row in gdf.iterrows():
                semester = str(row["semester"]).strip() if pd.notna(row["semester"]) else ""
                content = str(row["content"]).strip()
                source_file = str(row["source_file"]).strip() if pd.notna(row["source_file"]) else ""
                session.add(Review(
                    course_id=course_id,
                    user_id=sys_user_id,
                    content=content,
                    semester=semester if semester else None,
                    source=source_file,
                    created_at=now,
                ))
                imported += 1

        # 删除 xlsx 已导入行
        if approved:
            drop_indices = []
            for code in approved:
                drop_indices.extend(groups[code].index.tolist())
            df = df.drop(drop_indices)
            df = df.drop(columns=["_code"])
            df.to_excel(REVIEWS_PATH, index=False, engine="openpyxl")

        await session.commit()

    print(f"导入: {imported} 条, {len(approved)} 组")
    print(f"跳过: {len(rejected)} 组")
    print(f"xlsx 剩余: {len(df)} 行")

    # ---- 报告 ----
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 交互式导入报告（课程号匹配）\n",
        f"**执行时间**：{_now()}\n",
        "---\n",
        "## 总体统计\n",
        f"| 指标 | 数量 |",
        f"|------|------|",
        f"| 导入组数 | {len(approved)} |",
        f"| 导入条数 | {imported} |",
        f"| 跳过组数 | {len(rejected)} |",
        f"| xlsx 剩余 | {len(df)} |\n",
    ]
    if approved_detail:
        lines.append("## 已确认的匹配\n")
        lines.append("| xlsx 课程号 | xlsx 课程名 | → DB 课程名 | DB 教师 |")
        lines.append("|------------|------------|------------|--------|")
        for code, xname, cid, db_name, db_teacher in approved_detail:
            lines.append(f"| {code} | {xname} | {db_name} | {db_teacher} |")
        lines.append("")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
