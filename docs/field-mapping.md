# 教务系统 API 字段对照表

数据来源：`ehallapp.nju.edu.cn` 课程查询接口

## 全部字段（共 39 个）

| 字段名 | 含义 | 非空率（抽样） | 映射目标 | 备注 |
|--------|------|:-----------:|----------|------|
| JXBID | | ~100% | ? | 教学班 ID，较新的结构为 `学年（8 位） + 学期（1 位） + 课程号（8 位）+ 班级号（2 位）`，如 `2025202612500070003` |
| JXBMC | | 100% | ? | 教学班名称，如 `C语言程序设计基础03班` |
| JXLDM | | ~80% | ? | 教学楼代码 |
| JXLDM_DISPLAY | | ~80% | ? | 教学楼名称 |
| KCFL1 | | ~68% | ? | 课程分类 1（代码） |
| KCFL1_DISPLAY | | ~68% | ? | 课程分类 1（显示），如 `理论+实践课程` |
| KCH | | 100% | Course.code | 课程号 |
| KCM | | ~100% | Course.name | 课程名（老数据偶有缺失） |
| KCSJXS | | ~100% | ? | 课程实践学时 |
| KTJSXS | | ~100% | ? | 课堂讲授学时 |
| KXH | | 100% | ? | 课序号，推测为班级序号 |
| PKDWDM | | 100% | ? | 排课单位代码 |
| PKDWDM_DISPLAY | | 100% | Course.department | 排课单位名称 |
| PKZTDM | | 100% | ? | 排课状态代码 |
| SFTK | | 100% | ? | 是否停开（0/1） |
| SFTK_DISPLAY | | 100% | ? | 是否停开（显示） |
| SFXGXK | | 100% | ? | 是否新工学科课（0/1） |
| SFXGXK_DISPLAY | | 100% | ? | 是否新工学科课（显示） |
| SKBJ | | ~60-97% | CourseOffering.major | 上课「班级」实际上为专业（新数据缺失严重） |
| SKJAS | | ~95% | ? | 上课教室 |
| SKJC | | ~95% | ? | 上课节次 |
| SKJS | | ~96% | Course.teacher | 授课教师（为空时填"未知"） |
| SKXQ | | ~95% | ? | 上课星期，如 `周三,周五` |
| SKZC | | ~94% | ? | 上课周次 |
| SYXS | | ~68% | ? | 实验学时 |
| TKJG | | | ? | 停开结果 |
| TXKCLB | | ~100% | ? | 通识课程类别（代码） |
| TXKCLB_DISPLAY | | ~100% | ? | 通识课程类别（显示） |
| WID | | 100% | ? | 推测为系统内唯一标识，较新的结构为 `学年（8 位） + 学期（1 位） + 课程号（8 位）+ 班级号（2 位）`，如 `2025202612500070003`|
| XF | | ~100% | Course.credits | 学分 |
| XGXKLBDM | | | ? | 新工学科课类别代码 |
| XGXKLBDM_DISPLAY | | | ? | 新工学科课类别（显示） |
| XKZRS | | 100% | ? | 选课总人数 |
| XNXQDM | | 100% | ? | 学年学期代码，如 `2008-2009-2` |
| XNXQDM_DISPLAY | | 100% | CourseOffering.semester | 学年学期显示，如 `2008-2009学年 第2学期` |
| XS | | ~100% | ? | 学时 |
| XXXQDM | | ~100% | ? | 校区代码 |
| XXXQDM_DISPLAY | | ~100% | ? | 校区名称，如 `鼓楼校区` |
| YPSJDD | | ~95% | ? | 上课时间地点汇总 |

## 已确定映射

| API 字段 | 模型字段 | 处理规则 |
|----------|----------|----------|
| KCH | Course.code | 直接映射 |
| KCM | Course.name | 为空时用 JXBMC 回退 |
| SKJS | Course.teacher | 为空时填 `未知` |
| PKDWDM_DISPLAY | Course.department | 直接映射 |
| XF | Course.credits | 直接映射 |
| XNXQDM_DISPLAY | CourseOffering.semester | 直接映射 |
| SKBJ | CourseOffering.major | 为空时用 JXBMC 回退 |

## 唯一约束

- Course: `(KCH, SKJS)` → `(code, teacher)`
- CourseOffering: `(course_id, XNXQDM_DISPLAY, SKBJ)` → `(course_id, semester, major)`
