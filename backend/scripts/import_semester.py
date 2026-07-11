"""学期课程增量导入脚本。

每学期抓取新数据后运行，将新教学班数据导入到 raw_course / course / course_offering 三张表中。

流程：
    1. 将 JSON 中的原始记录全量写入 raw_course 表
    2. 从目标学期的 raw_course 中按 (code, teacher_set) 去重，提取课程标识
    3. 对每个课程标识，在 course 表中查找 (code, name, teacher_set) 完全匹配的记录
       - 找到 → 复用已有 course
       - 找不到 → 新建 course
    4. 为该学期每条 raw_course 创建对应的 course_offering（以 SKBJ 为 major，回退 JXBMC）

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/import_semester.py 2026-2027-1
    # 也可以传 display 格式
    python backend/scripts/import_semester.py "2026-2027学年 第1学期"
"""

import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, Integer, Text, Float, ForeignKey, select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# ---------- 配置 ----------

DB_PATH = "data/nanping.db"


# ---------- 独立模型定义（不依赖 app/，只包含本脚本需要的表） ----------

class Base(DeclarativeBase):
    pass


class RawCourse(Base):
    """教务系统原始教学班记录。"""

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


class Course(Base):
    """课程（评价对象）。"""

    __tablename__ = "course"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(Text, nullable=False, comment="课程编号")
    name = Column(Text, nullable=False, comment="课程名称")
    teacher = Column(Text, nullable=False, comment="授课教师")
    department = Column(Text, comment="开课院系")
    credits = Column(Float, comment="学分")
    created_at = Column(Text, nullable=False, comment="入库时间")


class CourseOffering(Base):
    """开课记录。"""

    __tablename__ = "course_offering"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), nullable=False)
    semester = Column(Text, nullable=False, comment="学年学期")
    major = Column(Text, nullable=False, comment="上课专业")
    created_at = Column(Text, nullable=False, comment="入库时间")


# ---------- 引擎 ----------

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------- 工具函数 ----------

def normalize_teacher(teacher: str) -> str:
    """标准化教师集合：拆分、去空、排序、逗号连接。

    使不同顺序的同一组教师产生相同的字符串，
    例如 "李四,张三" 和 "张三,李四" 都变为 "张三,李四"。

    Args:
        teacher: 原始教师字符串（逗号分隔）

    Returns:
        标准化后的教师字符串
    """
    if not teacher:
        return ""
    parts = [t.strip() for t in teacher.split(",") if t.strip()]
    return ",".join(sorted(set(parts)))


def resolve_semester(arg: str) -> tuple[str, str]:
    """将命令行参数解析为 (XNXQDM 代码, XNXQDM_DISPLAY 显示名)。

    支持两种输入格式：
    - 代码格式："2026-2027-1"
    - 显示格式："2026-2027学年 第1学期"

    Args:
        arg: 用户传入的学期参数

    Returns:
        (semester_code, semester_display) 元组
    """
    if "学年" in arg:
        # 用户传的是 display 格式，需要反查 code
        # 常见映射规则：第1学期→-1, 第2学期→-2, 暑期→-3
        display = arg
        if "第1学期" in arg:
            code = arg.replace("学年 第1学期", "-1").replace("学年第1学期", "-1")
        elif "第2学期" in arg:
            code = arg.replace("学年 第2学期", "-2").replace("学年第2学期", "-2")
        elif "暑期" in arg:
            code = arg.replace("学年 暑期", "-3").replace("学年暑期", "-3")
        else:
            print(f"错误：无法从 display 格式推断 semester code：{arg}")
            sys.exit(1)
        return code, display
    else:
        # 用户传的是 code 格式，推断 display
        code = arg
        parts = code.rsplit("-", 1)
        if len(parts) != 2:
            print(f"错误：学期代码格式不正确：{code}（应为如 2026-2027-1）")
            sys.exit(1)
        year_range, term = parts
        term_map = {"1": "第1学期", "2": "第2学期", "3": "暑期"}
        term_display = term_map.get(term)
        if not term_display:
            print(f"错误：学期号 {term} 不在 1/2/3 范围内")
            sys.exit(1)
        display = f"{year_range}学年 {term_display}"
        return code, display


def find_json_dir(semester_code: str) -> Path:
    """查找学期 JSON 数据目录。

    按优先级查找：
    1. data/raw_courses_{semester_code}/
    2. data/raw_courses_*/ 下包含该学期数据的目录

    Args:
        semester_code: 学期代码，如 "2026-2027-1"

    Returns:
        JSON 文件所在目录

    Raises:
        SystemExit: 找不到数据目录
    """
    # 优先精确匹配
    target = Path(f"data/raw_courses_{semester_code}")
    if target.is_dir():
        return target

    # 回退：查找所有 raw_courses_* 目录
    candidates = sorted(Path("data").glob("raw_courses_*"))
    dirs = [d for d in candidates if d.is_dir()]
    if not dirs:
        print(f"错误：data/ 下没有找到 raw_courses_* 数据目录")
        sys.exit(1)

    print(f"未找到 data/raw_courses_{semester_code}/，可用目录：")
    for d in dirs:
        print(f"  {d}")
    print("请确认学期代码或手动指定目录。")
    sys.exit(1)


# ---------- 导入步骤 ----------

async def import_raw_courses(session: AsyncSession, json_dir: Path) -> int:
    """步骤 1：将 JSON 文件中的原始记录插入 raw_course 表。

    Args:
        session: 数据库会话
        json_dir: JSON 文件目录

    Returns:
        本次插入的记录数
    """
    files = sorted(json_dir.glob("page_*.json"))
    if not files:
        print(f"  警告：{json_dir} 下没有找到 page_*.json 文件")
        return 0

    total = 0
    int_columns = ("XKZRS", "XS", "KCSJXS", "KTJSXS", "SYXS", "SFTK", "SFXGXK")

    for fp in files:
        with open(fp, encoding="utf-8") as f:
            rows = json.load(f)

        # JSON 中的数值字段做类型转换
        for row in rows:
            for col in int_columns:
                if row.get(col) is not None:
                    try:
                        row[col] = int(row[col])
                    except (ValueError, TypeError):
                        row[col] = None

        session.add_all([RawCourse(**row) for row in rows])
        total += len(rows)
        print(f"  {fp.name} → {len(rows)} 条")

    await session.commit()
    return total


async def build_offerings(
    session: AsyncSession,
    semester_code: str,
    semester_display: str,
) -> None:
    """步骤 2-4：从 raw_course 提取 course_offering 并关联 course。

    流程：
    - 从目标学期的 raw_course 中按 (code, name, teacher_set) 去重
    - 对每个课程标识，在 course 表中查找匹配：找到则复用，否则新建
    - 为该学期每条 raw_course 创建一条 course_offering（跳过已存在的）

    Args:
        session: 数据库会话
        semester_code: 学期代码（用于查询 raw_course）
        semester_display: 学期显示名（存入 course_offering.semester）
    """
    now = datetime.now().isoformat()

    # ---- 1. 加载目标学期所有 raw_course ----
    result = await session.execute(
        select(RawCourse).where(RawCourse.XNXQDM == semester_code)
    )
    raw_courses = result.scalars().all()
    print(f"  目标学期 raw_course 共 {len(raw_courses)} 条")

    if not raw_courses:
        print("  没有找到该学期的原始记录，请先运行 import 步骤。")
        return

    # ---- 2. 按 (code, name, teacher_set) 去重，提取课程标识 ----
    course_groups: dict[tuple[str, str, str], list] = defaultdict(list)
    for rc in raw_courses:
        code = (rc.KCH or "").strip()
        name = (rc.KCM or "").strip() or (rc.JXBMC or "").strip()
        teacher = normalize_teacher(rc.SKJS or "")
        course_groups[(code, name, teacher)].append(rc)

    print(f"  去重后课程标识 {len(course_groups)} 个")

    # ---- 3. 加载已有 course，建立 (code, name, teacher_set) → Course 索引 ----
    result = await session.execute(select(Course))
    existing_courses = result.scalars().all()

    course_index: dict[tuple[str, str, str], Course] = {}
    for c in existing_courses:
        key = (
            (c.code or "").strip(),
            (c.name or "").strip(),
            normalize_teacher(c.teacher or ""),
        )
        course_index[key] = c

    print(f"  已有 course {len(existing_courses)} 条")

    # ---- 4. 对每个课程标识：匹配或新建 course ----
    course_map: dict[tuple[str, str, str], int] = {}  # (code, name, teacher) → course_id
    new_courses = 0
    reused_courses = 0

    for (code, name, teacher), _rcs in course_groups.items():
        key = (code, name, teacher)
        if key in course_index:
            course_map[key] = course_index[key].id
            reused_courses += 1
        else:
            # 取该组第一条 raw_course 的院系和学分作为 course 的 department / credits
            first_rc = _rcs[0]
            new_course = Course(
                code=code,
                name=name,
                teacher=teacher,
                department=first_rc.PKDWDM_DISPLAY,
                credits=first_rc.XF,
                created_at=now,
            )
            session.add(new_course)
            await session.flush()  # 获取自增 ID
            course_map[key] = new_course.id
            course_index[key] = new_course  # 防止同批次重复创建
            new_courses += 1

    print(f"  复用 course {reused_courses} 个，新建 course {new_courses} 个")

    # ---- 5. 为每条 raw_course 创建 course_offering ----
    # 先批量加载已有 offering 的 (course_id, semester, major) 用于去重
    result = await session.execute(
        select(CourseOffering.course_id, CourseOffering.semester, CourseOffering.major)
    )
    existing_offering_keys: set[tuple[int, str, str]] = set(result.all())

    new_offerings = 0
    skipped_offerings = 0

    for (code, name, teacher), rcs in course_groups.items():
        course_id = course_map[(code, name, teacher)]
        for rc in rcs:
            major = (rc.SKBJ or "").strip() or (rc.JXBMC or "").strip() or "未知"
            offering_key = (course_id, semester_display, major)

            if offering_key in existing_offering_keys:
                skipped_offerings += 1
                continue

            session.add(CourseOffering(
                course_id=course_id,
                semester=semester_display,
                major=major,
                created_at=now,
            ))
            existing_offering_keys.add(offering_key)
            new_offerings += 1

    await session.commit()
    print(f"  新建 offering {new_offerings} 条，跳过已存在 {skipped_offerings} 条")


async def main():
    """主流程：解析参数，执行导入。"""
    if len(sys.argv) < 2:
        print("用法：python backend/scripts/import_semester.py <学期>")
        print('  学期代码格式：2026-2027-1')
        print('  学期显示格式："2026-2027学年 第1学期"')
        sys.exit(1)

    semester_arg = sys.argv[1]
    semester_code, semester_display = resolve_semester(semester_arg)
    json_dir = find_json_dir(semester_code)

    print(f"=== 学期增量导入 ===")
    print(f"  学期代码：{semester_code}")
    print(f"  学期显示：{semester_display}")
    print(f"  数据目录：{json_dir}")
    print()

    # ---- 步骤 1：导入 raw_course ----
    print("[1/2] 导入 raw_course ...")
    async with async_session() as session:
        raw_count = await import_raw_courses(session, json_dir)
    print(f"  共导入 {raw_count} 条原始记录\n")

    # ---- 步骤 2-4：构建 course + course_offering ----
    print("[2/2] 构建 course + course_offering ...")
    async with async_session() as session:
        await build_offerings(session, semester_code, semester_display)

    # ---- 最终统计 ----
    async with async_session() as session:
        rc_count = (await session.execute(select(func.count(RawCourse.id)))).scalar()
        c_count = (await session.execute(select(func.count(Course.id)))).scalar()
        co_count = (await session.execute(select(func.count(CourseOffering.id)))).scalar()

    print(f"\n=== 完成 ===")
    print(f"  raw_course:     {rc_count:,} 条")
    print(f"  course:         {c_count:,} 条")
    print(f"  course_offering: {co_count:,} 条")


if __name__ == "__main__":
    asyncio.run(main())
