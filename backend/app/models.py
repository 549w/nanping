"""ORM 模型定义。"""

from sqlalchemy import Column, Integer, Text, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from .database import Base


class RawCourse(Base):
    """教务系统 API 返回的原始教学班记录，字段一一对应 JSON 键名。

    39 个字段，保留全部原始信息，用于数据归档。
    后续从中按 (KCH, SKJS) 去重抽取 Course 和 CourseOffering。
    """

    __tablename__ = "raw_course"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 课程标识
    KCH = Column(Text, nullable=False, comment="课程号")
    KCM = Column(Text, comment="课程名")
    KXH = Column(Text, comment="课序号")
    JXBID = Column(Text, comment="教学班 ID")
    JXBMC = Column(Text, comment="教学班名称")
    WID = Column(Text, comment="系统唯一标识")

    # 教师与单位
    SKJS = Column(Text, comment="授课教师")
    PKDWDM = Column(Text, comment="排课单位代码")
    PKDWDM_DISPLAY = Column(Text, comment="排课单位名称")

    # 时间地点
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

    # 班级与学生
    SKBJ = Column(Text, comment="上课专业/学生群体")
    XKZRS = Column(Integer, comment="选课总人数")

    # 学分学时
    XF = Column(Float, comment="学分")
    XS = Column(Integer, comment="学时")
    KCSJXS = Column(Integer, comment="课程实践学时")
    KTJSXS = Column(Integer, comment="课堂讲授学时")
    SYXS = Column(Integer, comment="实验学时")

    # 课程分类
    KCFL1 = Column(Text, comment="课程分类 1 代码")
    KCFL1_DISPLAY = Column(Text, comment="课程分类 1 显示")
    TXKCLB = Column(Text, comment="通识课程类别代码")
    TXKCLB_DISPLAY = Column(Text, comment="通识课程类别显示")
    XGXKLBDM = Column(Text, comment="新工学科课类别代码")
    XGXKLBDM_DISPLAY = Column(Text, comment="新工学科课类别显示")

    # 状态标记
    PKZTDM = Column(Text, comment="排课状态代码")
    SFTK = Column(Integer, comment="是否停开")
    SFTK_DISPLAY = Column(Text, comment="是否停开显示")
    SFXGXK = Column(Integer, comment="是否新工学科课")
    SFXGXK_DISPLAY = Column(Text, comment="是否新工学科课显示")
    TKJG = Column(Text, comment="停开结果")


class Course(Base):
    """课程。

    用 (code, teacher) 唯一标识一个评价对象。
    同一课程号不同老师授课视为不同课程。
    数据来源：从 RawCourse 按 (KCH, SKJS) 去重抽取。
    """

    __tablename__ = "course"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(Text, nullable=False, comment="课程编号")
    name = Column(Text, nullable=False, comment="课程名称")
    teacher = Column(Text, nullable=False, comment="授课教师")
    department = Column(Text, comment="开课院系")
    credits = Column(Float, comment="学分")
    created_at = Column(Text, nullable=False, comment="入库时间")

    __table_args__ = (
        UniqueConstraint("code", "teacher", name="uq_course_code_teacher"),
    )

    offerings = relationship("CourseOffering", back_populates="course")


class CourseOffering(Base):
    """开课记录。

    记录某门课程在哪个学期、面向什么专业开设。
    从 RawCourse 按 (KCH, SKJS, XNXQDM_DISPLAY, SKBJ/JXBMC) 去重抽取。
    """

    __tablename__ = "course_offering"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("course.id"), nullable=False, comment="所属课程")
    semester = Column(Text, nullable=False, comment="学年学期")
    major = Column(Text, nullable=False, comment="上课专业")
    created_at = Column(Text, nullable=False, comment="入库时间")

    __table_args__ = (
        UniqueConstraint("course_id", "semester", "major", name="uq_offering"),
    )

    course = relationship("Course", back_populates="offerings")
