# Nanping 项目规范（CLAUDE.md）

## 1. 项目定位

Nanping 是一个面向南京大学选课系统的课程信息增强工具。

核心能力：

- 浏览器插件在官方选课页面中增强课程信息展示
- 后端提供课程评价查询与存储服务
- 使用结构化数据库管理课程与评价数据

目标：构建一个可扩展的校园课程评价基础系统（MVP 优先）。

背景信息：

- 现有多个来源的课程评价数据，大多以网页表格的形式存在（可导出为 Excel），预估上千条记录。
- 除了开发项目，我们还需要将现有评价信息进行清洗和规范化，纳入我们的数据库。
- MVP 核心功能：用户能提交新评价。

## 2. 技术选型

| 模块       | 技术                              | 说明                     |
| ---------- | --------------------------------- | ------------------------ |
| 浏览器插件 | Chrome Extension Manifest V3（原生） | 内容脚本注入、弹出窗口   |
| 后端 API   | Python FastAPI                    | 异步支持、自动生成 OpenAPI |
| 数据库     | SQLite                            | 轻量起步，后续可迁移至 PG |
| ORM        | SQLAlchemy（异步模式）            | 配合 FastAPI async        |
| 数据清洗   | Python（pandas / openpyxl）       | 处理 Excel 导入           |
| Python 版本 | 3.13.9                            | 跟随本地开发环境          |

## 3. 项目结构

```
nanping/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # 应用入口，注册路由/CORS/中间件
│   │   ├── config.py            # 配置（数据库路径、JWT 密钥、SMTP 等）
│   │   ├── database.py          # SQLite + SQLAlchemy 异步连接
│   │   ├── models.py            # ORM：User、Course、CourseOffering、Review
│   │   ├── schemas.py           # Pydantic 请求/响应模型
│   │   ├── auth.py              # JWT 生成与解析、登录态依赖注入
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── auth.py          # /auth/send-code、/auth/register、/auth/login
│   │       ├── courses.py       # /courses（搜索）
│   │       └── review.py        # /review、/review/add、/review/delete、/review/me
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_auth.py
│   │   ├── test_courses.py
│   │   └── test_review.py
│   ├── scripts/
│   │   ├── scrape_courses.py    # 教务系统抓取 → Course + CourseOffering
│   │   └── import_reviews.py    # Excel 评价清洗 + 课程名匹配 → Review
│   ├── requirements.txt
│   └── .env.example
├── extension/                    # Chrome 浏览器插件
│   ├── manifest.json
│   └── content.js               # 课程行注入评分 + hover/点击查看详情
├── frontend/                     # 独立评价浏览页面
│   ├── index.html               # 首页（课程搜索）
│   ├── course.html              # 课程详情 + 评价列表
│   ├── login.html               # 登录
│   ├── register.html            # 注册
│   ├── me.html                  # 我的评价
│   ├── css/
│   │   └── style.css            # 少量自定义样式（Pico.css 为主）
│   └── js/
│       ├── api.js               # 封装 fetch 请求
│       ├── auth.js              # 登录态管理（token 存储、过期处理）
│       └── utils.js             # 通用工具函数
├── data/                         # 原始数据与清洗产物
│   └── README.md
├── .gitignore
├── CLAUDE.md
└── README.md
```

### 技术说明

- 前端：原生 HTML + Pico.css（响应式）+ vanilla JS，多页面按功能拆分
- 插件交互：课程行旁边显示评分，悬停/点击弹出详细评价
- 后端路由按模块拆分：auth（认证）、courses（课程搜索）、review（评价 CRUD）
- 测试框架：pytest + httpx（异步测试 FastAPI 接口）

## 4. 数据模型

**唯一标识**：用「课程号 + 老师」作为唯一评价对象。同一课程号不同老师授课，评价分开。

**抓取数据去重**：教务系统返回的是教学班粒度（Level 3），比评价对象多出学期/分班维度。抓取时先按 `(code, teacher)` 聚拢到 Course 表（靠唯一约束去重），再将学期/专业信息写入 CourseOffering。

### User（用户）

| 字段       | 类型    | 说明                     |
| ---------- | ------- | ------------------------ |
| id         | INTEGER | 主键                     |
| email      | TEXT    | 南大邮箱（唯一）         |
| password   | TEXT    | 密码哈希                 |
| created_at | TEXT    | 注册时间                 |

### Course（课程）

| 字段       | 类型    | 说明                          |
| ---------- | ------- | ----------------------------- |
| id         | INTEGER | 主键                          |
| code       | TEXT    | 课程编号（来自教务系统）      |
| name       | TEXT    | 标准课程名称（来自教务系统）  |
| teacher    | TEXT    | 授课教师                      |
| department | TEXT    | 开课院系                      |
| credits    | REAL    | 学分                          |
| created_at | TEXT    | 入库时间                      |

唯一约束：`(code, teacher)`

### CourseOffering（开课记录）

| 字段       | 类型    | 说明                       |
| ---------- | ------- | -------------------------- |
| id         | INTEGER | 主键                       |
| course_id  | INTEGER | 外键 → Course.id           |
| semester   | TEXT    | 学期，如 "2024秋"          |
| major      | TEXT    | 上课专业，如 "数学系大班"  |
| created_at | TEXT    | 入库时间                   |

唯一约束：`(course_id, semester, major)`

### Review（评价）

| 字段         | 类型    | 说明                              |
| ------------ | ------- | --------------------------------- |
| id           | INTEGER | 主键                              |
| course_id    | INTEGER | 外键 → Course.id（1 : 0..*）      |
| user_id      | INTEGER | 外键 → User.id                    |
| rating       | INTEGER | 评分（1-5），导入数据可为空       |
| content      | TEXT    | 评价正文                          |
| is_anonymous | BOOL    | 展示时是否匿名                    |
| is_deleted   | BOOL    | 软删除标记，默认 false            |
| source       | TEXT    | 来源标识（导入数据用文件名，自有数据用 `native`） |
| created_at   | TEXT    | 提交时间                          |

### 特殊处理

- **系统账号**：预置 `email=system@nanping` 的 User，所有导入评价挂其名下。前端检测到该账号时特殊渲染（如显示"历史导入评价"）。
- **实名制**：用户以南京大学邮箱注册，发评价时可选匿名展示（`is_anonymous`），但数据库始终记录真实 `user_id`。
- **老数据评分**：导入评价的 `rating` 先留空，后续可用 LLM 分析评价情绪自动补打分。

## 5. API 设计

API 部署在独立子域名（如 `api.nanping.xxx`），路径中不含 `/api` 前缀。需登录的接口通过 `Authorization: Bearer <JWT>` 传递身份，后端从 token 解析 `user_id`，不信任请求体中传入的用户信息。

### 认证

| 方法 | 路径            | 说明                                   |
|------|-----------------|----------------------------------------|
| POST | /auth/send-code | 发送验证码到南大邮箱。同邮箱 60s 内不可重复发送，验证码有效期 5 分钟。开发阶段支持 mock 模式（验证码打印到控制台或设为固定值） |
| POST | /auth/register  | 注册。请求体：`email` + `code`（验证码）+ `password` |
| POST | /auth/login     | 登录。请求体：`email` + `password`。返回 JWT token |

### 课程

| 方法 | 路径     | 说明     |
|------|----------|----------|
| GET  | /courses | 搜索课程，分页。参数：`?code=`、`?name=`、`?teacher=`（至少填一个） |

返回数据含课程基本信息和两个摘要字段：`avg_rating`（平均分）、`review_count`（评价数）。

### 评价

| 方法   | 路径            | 说明                                |
|--------|-----------------|-------------------------------------|
| GET    | /review         | 查看评价列表。参数：`?course_id=`，分页 |
| POST   | /review/add     | 提交新评价（需登录）。请求体：`course_id` + `rating` + `content` + `is_anonymous`。`user_id` 由 token 解析 |
| DELETE | /review/delete  | 删除某条评价（需登录，只能删自己提交的）。请求体：`review_id`。软删除 |
| GET    | /review/me      | 查看当前用户提交的所有评价（需登录） |

### 设计原则

- 列表页只返回摘要，详细评价按需加载
- 不支持编辑评价（删了重发即可）
- 删除为软删除，`DELETE` 将 `is_deleted` 置为 `true`，评价列表默认过滤已删除记录

### 安全（MVP 基础防护）

- **JWT 认证**：需登录的接口从 `Authorization: Bearer` 头解析 `user_id`，不信任请求体中的用户信息
- **CORS 白名单**：仅允许自有前端和插件域名跨域请求
- **限流**：使用 `slowapi` 对写接口（POST/DELETE）做频率限制

## 6. 开发约定

### 代码风格

- **Python**：遵循 PEP 8，使用 ruff 进行格式化和 lint
- **注释**：每个函数和类必须写清晰的 docstring（Google 风格），说明功能、参数、返回值
- **命名**：函数/变量 `snake_case`，类 `PascalCase`

### Git 规范

- 分支：`main` 为稳定版本，功能开发拉 `feature/<功能>` 分支
- Commit message：遵循 Conventional Commits 格式，前缀 + 中文描述
  - `feat:` 新功能
  - `fix:` 修复 bug
  - `docs:` 文档变更
  - `refactor:` 重构
  - `test:` 测试
  - `chore:` 构建/工具等杂项
  - 例：`feat: 新增课程搜索接口`
- 提交前确认代码可运行

### 虚拟环境

- 项目使用 `.venv/` 目录存放虚拟环境
- `.venv/` 已在 `.gitignore` 中
- 创建方式：`python3 -m venv .venv`
- 激活后 `pip install -r backend/requirements.txt`

### 包管理

- pip + requirements.txt（轻量起步，后续可迁 poetry）
- `requirements.txt` 放在 `backend/` 下

### 测试

- 框架：pytest + httpx（异步测试 FastAPI 接口）
- 测试文件放在 `backend/tests/`，按模块命名 `test_<模块>.py`
- 每个接口至少覆盖正常路径和常见异常路径
- 提交前跑一遍测试确认通过
