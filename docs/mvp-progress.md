# Nanping MVP 开发进度报告

**Date:** 2026-07-02

---

## 1. 总体评估

项目目前大约 **30% 完成**。数据基础非常扎实——已完成教务系统爬取、课程聚类去重、以及 9 个学期共 11,814 条评价的清洗导入。但**整个运行时应用层完全是空的**：FastAPI 入口、8 个 API 端点、Pydantic schemas、JWT 鉴权、前端 5 个页面 + 3 个 JS 文件、浏览器插件、以及全部测试，都是 0 字节空文件。MVP 的核心目标（"用户可以提交新评价"）尚未实现。

---

## 2. 已完成 ✓

| 模块 | 状态 | 详情 |
|------|------|------|
| ORM 模型 | ✅ 完成 | 5 个模型（RawCourse, User, Course, CourseOffering, Review）全部定义，约束和索引正确 |
| 数据库连接层 | ✅ 完成 | `database.py`：异步 SQLAlchemy + aiosqlite，`get_db()` 依赖注入 |
| 教务系统爬取 | ✅ 完成 | `scrape_courses.py`：102 页 API 数据已爬取 |
| 原始数据导入 | ✅ 完成 | `import_raw.py`：101,845 条原始记录入库 |
| 评价格式转换 | ✅ 完成 | `convert_reviews.py`：9 份格式各异的 Excel 统一为标准格式 |
| 评价导入流水线 | ✅ 完成 | 四阶段匹配（code → name → semester → interactive），11,814 条评价导入 |
| 课程去重 | ✅ 完成 | `merge_duplicate_courses.py`：处理教师排序不同导致的重复课程 |
| 字段对照文档 | ✅ 完成 | `docs/field-mapping.md`：39 个 API 字段的含义和映射关系完整 |

---

## 3. 数据库现状

| 表 | 行数 |
|---|------|
| `raw_course` | 101,845 |
| `course` | 34,163（15,682 个不重复课程号） |
| `course_offering` | 98,444 |
| `user` | 1（`system@nanping`） |
| `review` | **11,814** |

评价来源分布：

| 来源文件 | 学期 | 数量 |
|---------|------|------|
| 2023级红黑榜.xlsx | 2023 | 2,884 |
| 红黑榜_2021.xlsx | 2021 | 2,484 |
| 红黑榜_2022.xlsx | 2022 | 1,715 |
| 红黑榜_2024春.xlsx | 2024春 | 1,582 |
| 红黑榜_2025春.xlsx | 2025春 | 1,218 |
| 红黑榜_2024冬.xlsx | 2024冬 | 1,165 |
| 红黑榜_2020.xlsx | 2020 | 748 |
| 红黑榜-fork25_2025秋.xlsx | 2025秋 | 17 |
| 红黑榜-fork25_2026春.xlsx | 2026春 | 1 |

有评价的课程占 4.9%（1,679/34,163）。还有约 149 条未匹配评价留在 `all_reviews.xlsx` 中。导入评价的 `rating` 全部为 NULL（按规范留空，后续用 LLM 分析情绪补打分）。

---

## 4. 未完成 ✗

### 4A. 完全空文件——整个运行时应用栈（22 个文件）

**后端（7 个）：**

| 文件 | 应包含内容 |
|------|-----------|
| `backend/app/main.py` | FastAPI app、CORS 白名单、slowapi 限流、路由注册、启动事件 |
| `backend/app/schemas.py` | 全部 Pydantic 请求/响应模型 |
| `backend/app/auth.py` | JWT 生成/验证、密码哈希、`get_current_user` 依赖 |
| `backend/app/routers/auth.py` | 3 个认证端点（send-code, register, login） |
| `backend/app/routers/courses.py` | 课程搜索端点（分页 + avg_rating + review_count） |
| `backend/app/routers/review.py` | 4 个评价端点（列表/新增/删除/我的） |
| `backend/tests/conftest.py` | 不存在——测试 fixtures 完全没有 |

**前端（11 个，全部 0 字节）：**

| 文件 | 应包含内容 |
|------|-----------|
| `frontend/index.html` | 课程搜索首页 |
| `frontend/course.html` | 课程详情 + 评价列表 + 提交评价表单 |
| `frontend/login.html` | 登录页 |
| `frontend/register.html` | 注册页 |
| `frontend/me.html` | 当前用户的所有评价 |
| `frontend/js/api.js` | 封装 fetch 请求 |
| `frontend/js/auth.js` | JWT token 存储、过期处理、登录态管理 |
| `frontend/js/utils.js` | 通用工具函数 |
| `frontend/css/style.css` | Pico.css 之上的自定义样式 |

**插件（2 个，全部 0 字节）：**

| 文件 | 应包含内容 |
|------|-----------|
| `extension/manifest.json` | Manifest V3 声明、权限、content_scripts 注册 |
| `extension/content.js` | 课程行注入评分 + hover/点击查看详情 |

**测试（4 个，全部 0 字节）：**

| 文件 | 应包含内容 |
|------|-----------|
| `backend/tests/__init__.py` | 测试包初始化 |
| `backend/tests/test_auth.py` | 认证端点测试 |
| `backend/tests/test_courses.py` | 课程搜索端点测试 |
| `backend/tests/test_review.py` | 评价 CRUD 端点测试 |

### 4B. 部分完成需补充

| 文件 | 缺失内容 |
|------|---------|
| `backend/app/config.py` | 缺 JWT_SECRET、JWT_ALGORITHM、JWT_EXPIRE_MINUTES、SMTP_HOST、SMTP_PORT、SMTP_USER、SMTP_PASSWORD、CORS_ORIGINS、AUTH_MOCK_MODE |
| `backend/.env.example` | 仅有 OFFICIAL_COOKIES，缺上述全部 |
| `backend/requirements.txt` | 缺 passlib[bcrypt]、pandas、openpyxl、email-validator、python-multipart |
| `CLAUDE.md` | 过时：仍然引用不存在的 `extract_courses.py` 和单一 `import_reviews.py`，未提及实际 5 个导入脚本和 `merge_duplicate_courses.py` |
| `data/README.md` | 0 字节空文件 |

### 4C. 关键文件丢失

**`backend/scripts/extract_courses.py` 不存在。** 这是 CLAUDE.md 明确记录的核心 ETL 步骤（raw_course → course + course_offering），包含教师聚类算法和字段回退规则。虽然 `course` 和 `course_offering` 表已有数据，但转换逻辑已不可复现——这是最大的风险点。

---

## 5. 建议开发顺序

### 第一优先——让 API 跑起来（后端核心）

1. 补全 `backend/app/config.py`（JWT/SMTP/CORS/Mock 配置）
2. 实现 `backend/app/schemas.py`（Pydantic 模型）
3. 实现 `backend/app/auth.py`（JWT + 密码哈希 + get_current_user）
4. 实现 `backend/app/routers/auth.py`（send-code / register / login）
5. 实现 `backend/app/routers/courses.py`（课程搜索 + avg_rating + review_count）
6. 实现 `backend/app/routers/review.py`（评价 CRUD + 软删除）
7. 实现 `backend/app/main.py`（组装 app、CORS、限流、路由注册、启动事件）
8. 更新 `backend/requirements.txt` 和 `backend/.env.example`

### 第二优先——测试

9. 创建 `backend/tests/conftest.py`（异步 test client + 内存 SQLite + fixtures）
10. 实现 `test_auth.py`、`test_courses.py`、`test_review.py`（覆盖正常路径和常见异常路径）

### 第三优先——前端

11. 实现 `frontend/js/api.js`（fetch 封装）和 `frontend/js/auth.js`（token 管理）
12. 构建 `frontend/login.html` 和 `frontend/register.html`
13. 构建 `frontend/index.html`（课程搜索）
14. 构建 `frontend/course.html`（课程详情 + 评价列表 + 提交表单）
15. 构建 `frontend/me.html`（我的评价）
16. 添加 `frontend/css/style.css`

### 第四优先——浏览器插件

17. 实现 `extension/manifest.json`（Manifest V3）
18. 实现 `extension/content.js`（DOM 注入评分 + 弹出详情）

### 第五优先——文档修缮

19. 重建 `extract_courses.py` 或至少记录其算法逻辑（教师聚类 + 字段回退）
20. 更新 `CLAUDE.md` 反映实际的 5 个导入脚本和 `merge_duplicate_courses.py`
21. 写 `data/README.md` 记录数据目录结构和流水线顺序

---

## 6. 后续计划（非 MVP 紧急）

- **LLM 评分回填**：用 LLM 分析 11,814 条导入评价的情绪，自动推断 1-5 评分
- **剩余 149 条评价**：手动或模糊匹配解决 `all_reviews.xlsx` 中未匹配的行
- **数据库迁移**：SQLite → PostgreSQL（SQLAlchemy 已抽象，主要是改连接串）
- **邮箱验证**：Mock 模式外的真实 SMTP 集成
- **管理工具**：评价审核、垃圾内容处理
- **学期筛选**：前端按学期浏览评价
- **数据看板**：课程评分分布、评价量趋势等聚合统计
- **导入脚本整合**：将 5 个导入脚本统一为一个或增加编排脚本
- **CI/CD**：自动化测试和 lint 检查
