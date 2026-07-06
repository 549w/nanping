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
    course_id = Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), nullable=False, comment="所属课程")
    semester = Column(Text, nullable=False, comment="学年学期")
    major = Column(Text, nullable=False, comment="上课专业")
    created_at = Column(Text, nullable=False, comment="入库时间")

    __table_args__ = (
        UniqueConstraint("course_id", "semester", "major", name="uq_offering"),
    )

    course = relationship("Course", back_populates="offerings")


class User(Base):
    """用户。

    以南京大学邮箱注册，登录后提交评价。
    系统账号 system@nanping 用于挂载导入的历史评价。
    """

    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(Text, nullable=False, unique=True, comment="南大邮箱")
    password = Column(Text, nullable=False, comment="密码哈希")
    is_admin = Column(Integer, nullable=False, default=0, comment="是否为管理员")
    created_at = Column(Text, nullable=False, comment="注册时间")


class ActivityLog(Base):
    """用户活动日志。

    记录关键用户行为（登录/注册/评价/插件查询等），
    供管理后台查询与审计。
    """

    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="操作用户，未登录可为空")
    action = Column(Text, nullable=False, comment="操作类型：login/register/review_create/review_delete/plugin_query 等")
    target_type = Column(Text, nullable=True, comment="操作目标类型：course/review")
    target_id = Column(Integer, nullable=True, comment="操作目标 ID")
    details = Column(Text, nullable=True, comment="附加信息 JSON")
    ip_address = Column(Text, nullable=True, comment="客户端 IP")
    user_agent = Column(Text, nullable=True, comment="客户端 User-Agent")
    created_at = Column(Text, nullable=False, comment="操作时间")


class News(Base):
    """系统公告/新闻。

    管理员通过数据库或管理后台发布，插件和前端在首页展示。
    """

    __tablename__ = "news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False, comment="标题")
    content = Column(Text, nullable=False, comment="正文")
    is_active = Column(Integer, nullable=False, default=1, comment="是否展示")
    created_at = Column(Text, nullable=False, comment="发布时间")


class Review(Base):
    """课程评价。

    每条评价属于一个 Course 和一个 User。
    导入的历史评价挂在 system@nanping 用户下。
    """

    __tablename__ = "review"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), nullable=False, comment="所属课程")
    user_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="提交用户，用户删除后保留评价")
    rating = Column(Integer, nullable=True, comment="评分 1-5，导入数据可为空")
    content = Column(Text, nullable=False, comment="评价正文")
    semester = Column(Text, nullable=True, comment="学年学期，如 2024秋，导入数据可为空")
    is_anonymous = Column(Integer, nullable=False, default=0, comment="展示时是否匿名")
    is_deleted = Column(Integer, nullable=False, default=0, comment="软删除标记")
    source = Column(Text, nullable=False, default="native", comment="来源：native 或导入文件名")
    ai_rated = Column(Integer, nullable=False, default=0, comment="是否由 AI 评分：0=否（用户自行评分），1=是（AI 评分）")
    created_at = Column(Text, nullable=False, comment="提交时间")

    # 关联
    course = relationship("Course", backref="reviews")


class VerificationCode(Base):
    """邮箱验证码。

    存储在数据库中而非进程内存，确保多 worker 部署时各进程共享。
    每条记录以 email 为唯一键，重复发送时覆盖旧记录。
    """

    __tablename__ = "verification_code"

    email = Column(Text, primary_key=True, comment="南大邮箱")
    code = Column(Text, nullable=False, comment="6 位验证码")
    expires_at = Column(Text, nullable=False, comment="过期时间 ISO 格式")
    last_sent_at = Column(Text, nullable=False, comment="上次发送时间 ISO 格式")
