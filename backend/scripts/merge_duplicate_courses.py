"""合并 Course 表中教师集合相同但顺序不同的重复记录。

合并规则：同一 (code, 教师集合) 的 course 视为同一门课。
保留策略：有评价的优先 → ID 最小的。
被合并 course 的 Review 和 CourseOffering 重新映射到保留的 ID。

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/merge_duplicate_courses.py
"""

import asyncio
from collections import defaultdict
from pathlib import Path

from sqlalchemy import Column, Integer, Text, Float, ForeignKey, select, delete, update, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DB_PATH = "data/nanping.db"


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
    major = Column(Text, nullable=False)


class Review(Base):
    __tablename__ = "review"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False)
    content = Column(Text, nullable=False)


engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def teacher_key(teacher: str) -> str:
    """标准化教师：拆分、去空格、排序、逗号连接。"""
    ts = sorted(t.strip() for t in teacher.split(",") if t.strip())
    return ",".join(ts)


async def main():
    async with async_session() as session:
        # 1. 加载所有 course
        result = await session.execute(select(Course.id, Course.code, Course.name, Course.teacher))
        all_courses = [(cid, code.strip() if code else "", name, teacher)
                       for cid, code, name, teacher in result]

        # 2. 按 (code, teacher_key) 分组
        groups = defaultdict(list)
        for cid, code, name, teacher in all_courses:
            groups[(code, teacher_key(teacher))].append((cid, name, teacher))

        # 3. 找出重复组
        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
        print(f"重复组: {len(dup_groups)} 组, 涉及 {sum(len(v) for v in dup_groups.values())} 条 course")

        # 4. 查看每组中有多少 review
        merge_map = {}   # old_course_id → keep_course_id
        total_merged = 0
        review_remapped = 0
        offering_remapped = 0

        for (code, tkey), courses in dup_groups.items():
            # 统计每条 course 的评价数
            cids = [c[0] for c in courses]
            review_counts = {}
            for cid in cids:
                r = await session.execute(select(Review.id).where(Review.course_id == cid).limit(1))
                review_counts[cid] = 1 if r.first() else 0

            # 保留：有评价优先，其次 ID 最小
            courses_sorted = sorted(courses, key=lambda c: (-review_counts.get(c[0], 0), c[0]))
            keep_id = courses_sorted[0][0]

            for cid, name, teacher in courses_sorted[1:]:
                merge_map[cid] = keep_id
                total_merged += 1

                # Re-map reviews
                await session.execute(
                    update(Review).where(Review.course_id == cid).values(course_id=keep_id)
                )
                r_cnt = await session.execute(
                    select(Review.id).where(Review.course_id == keep_id)
                )
                review_remapped += len(r_cnt.fetchall())

                # Re-map offerings（跳过会和保留 course 已有的 offering 冲突的）
                keep_offerings = await session.execute(
                    select(CourseOffering.semester, CourseOffering.major)
                    .where(CourseOffering.course_id == keep_id)
                )
                keep_off_keys = set(keep_offerings.fetchall())

                merged_offerings = await session.execute(
                    select(CourseOffering.id, CourseOffering.semester, CourseOffering.major)
                    .where(CourseOffering.course_id == cid)
                )
                for oid, sem, maj in merged_offerings.fetchall():
                    if (sem, maj) in keep_off_keys:
                        # 冲突 → 删除
                        await session.execute(delete(CourseOffering).where(CourseOffering.id == oid))
                    else:
                        await session.execute(
                            update(CourseOffering).where(CourseOffering.id == oid)
                            .values(course_id=keep_id)
                        )
                        keep_off_keys.add((sem, maj))

                # Delete merged course
                await session.execute(delete(Course).where(Course.id == cid))

            # 更新保留 course 的 teacher 为标准顺序
            await session.execute(
                update(Course).where(Course.id == keep_id).values(teacher=tkey)
            )

        await session.commit()

    print(f"合并了 {total_merged} 条 course")
    print(f"重新映射 {review_remapped} 条 review")
    print(f"重新映射 {offering_remapped} 条 offering")

    # 5. 最终统计
    async with async_session() as session:
        r = await session.execute(select(Course.id))
        final_course_count = len(r.fetchall())
    print(f"\n合并后 course 数: {final_course_count}")


if __name__ == "__main__":
    asyncio.run(main())
