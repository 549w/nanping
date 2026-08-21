# Nanping 项目规范（CLAUDE.md）

> 本文件是 AI 协作时的"单一信息源"。新增/修改路由、模型、命令时，**必须同步更新本文对应章节**。

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
| 数据库     | SQLite（dev）/ PostgreSQL（prod） | 配置切换 `DATABASE_URL`  |
| ORM        | SQLAlchemy 2.x（异步模式）        | 配合 FastAPI async        |
| 缓存       | 自研 `TTLCache` + `singleflight`  | 防止击穿，详见 §7        |
| 风控       | 自研 IP 级别追踪器                | 防止爬虫滥用插件端点      |
| 数据清洗   | Python（pandas / openpyxl）       | 处理 Excel 导入           |
| Python 版本 | 3.13.9                            | 跟随本地开发环境          |

## 3. 项目结构

```
nanping/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # 应用入口，注册路由/CORS/中间件
│   │   ├── config.py            # 配置（数据库、JWT、缓存 TTL、风控阈值等）
│   │   ├── database.py          # SQLite + SQLAlchemy 异步连接
│   │   ├── models.py            # ORM：User、Course、CourseOffering、Review、RawCourse、News、VerificationCode
│   │   ├── schemas.py           # Pydantic 请求/响应模型
│   │   ├── auth.py              # JWT 生成与解析、登录态依赖注入、密码哈希
│   │   ├── cache.py             # TTLCache 基础类
│   │   ├── plugin_cache.py      # 插件端点的缓存包装层（singleflight + TTL）
│   │   ├── activity.py          # 活动日志记录（用于风控/分析）
│   │   ├── risk.py              # IP 级别风控：限速、封禁、爬虫检测
│   │   ├── limiter.py           # slowapi 限流装饰器
│   │   ├── query_helpers.py     # 共享 SQL 表达式（布尔过滤常量 + 评价子查询）
│   │   └── routers/
│   │       ├── abbr.py          # 课程名简称表（如 "高数" → "高等数学"）
│   │       ├── auth.py          # /auth/send-code、/auth/register、/auth/login
│   │       ├── courses.py       # /courses、/courses/{id}、/courses/match
│   │       ├── events.py        # /events — 活动事件流
│   │       ├── news.py          # /news — 公告
│   │       ├── plugin.py        # /plugin v2 — 插件统一入口
│   │       └── review.py        # /review、/review/add、/review/delete、/review/me
│   ├── tests/
│   │   ├── conftest.py          # 共享 fixture（client、test_user、test_course 等）
│   │   ├── test_auth.py
│   │   ├── test_cache.py
│   │   ├── test_cache_invalidation.py   # 评价写操作必须让插件缓存失效
│   │   ├── test_config_wiring.py        # TTL/cooldown 必须从 settings 读取
│   │   ├── test_courses.py
│   │   ├── test_plugin.py
│   │   ├── test_review.py
│   │   └── test_risk.py
│   ├── scripts/
│   │   ├── scrape_courses.py    # 教务系统抓取 → page_*.json
│   │   ├── import_raw.py        # page_*.json → raw_course 表（一次性）
│   │   ├── extract_courses.py   # raw_course → course + course_offering（一次性）
│   │   └── import_reviews.py    # Excel 评价清洗 + 课程名匹配 → Review
│   ├── requirements.txt
│   └── .env.example
├── extension/                    # Chrome 浏览器插件
│   ├── manifest.json
│   └── content_dev.js           # content script（行注入评分 + 侧边面板）
├── frontend/                     # 独立评价浏览页面
│   ├── index.html / course.html / login.html / register.html / me.html / ...
│   ├── css/style.css
│   ├── js/
│   │   ├── api.js               # 封装 fetch 请求
│   │   ├── auth.js              # 登录态管理（TOKEN_KEY 等）
│   │   └── utils.js             # 通用工具（escapeHtml、formatDate、renderStars、showToast）
│   └── nanping-extension.zip    # 打包后的插件，供下载页分发
├── data/                         # 原始数据与清洗产物
├── docs/                         # 重要文档
│   └── field-mapping.md          # API 字段对照表
├── .github/workflows/
│   └── test.yml                  # CI：每个 push/PR 跑 pytest
├── .gitignore
├── CLAUDE.md
└── README.md
```

### 技术说明

- **前端**：原生 HTML + Pico.css（响应式）+ vanilla JS，多页面按功能拆分
- **插件**：单一 content script（`content_dev.js`），后端预渲染 HTML → 插件只做 innerHTML 注入
- **后端路由按模块拆分**：auth / courses / review / plugin / news / events
- **测试框架**：pytest + httpx（异步测试 FastAPI 接口）

## 4. 数据模型

**唯一标识**：用「课程号 + 老师」作为唯一评价对象。同一课程号不同老师授课，评价分开。

**数据层级**：教务系统返回的是教学班粒度（Level 3），包含具体上课时间、教室等。导入时分为三级存储：

```
Level 1: RawCourse（原始教学班，39 字段，一一对应 API 返回）
Level 2: Course（评价对象，按 code + teacher 聚类去重）
Level 3: CourseOffering（开课记录，按 course + semester + major 去重）
```

### 教师聚类规则

同一 KCH（课程号）下，将每条记录的 SKJS 按逗号拆分为教师集合。两张集合有**任意交集**即视为同一门课，取所有出现过的教师**并集**排序后存储。无交集的集合各自独立分课。

例：
```
KCH=00010 下共有三条记录的 SKJS：
  张三,李四
  李四,王五
  张三,李四,王五,赵六
→ 三者互相有交集 → 合并为 1 门课，teacher = "李四,王五,张三,赵六"
```

### 字段回退规则

| 目标字段 | 优先取 | 回退值 |
|----------|--------|--------|
| Course.name | KCM（不为空） | JXBMC |
| Course.teacher | SKJS（不为空） | "未知" |
| CourseOffering.major | SKBJ（不为空） | JXBMC |

### User

| 字段       | 类型    | 说明                     |
| ---------- | ------- | ------------------------ |
| id         | INTEGER | 主键                     |
| email      | TEXT    | 南大邮箱（唯一）         |
| password   | TEXT    | 密码哈希                 |
| created_at | TEXT    | 注册时间                 |

### Course

| 字段       | 类型    | 说明                          |
| ---------- | ------- | ----------------------------- |
| id         | INTEGER | 主键                          |
| code       | TEXT    | 课程编号（来自教务系统）      |
| name       | TEXT    | 标准课程名称（来自教务系统）  |
| teacher    | TEXT    | 授课教师（聚类合并后的排序集合，逗号分隔） |
| department | TEXT    | 开课院系                      |
| credits    | REAL    | 学分                          |
| created_at | TEXT    | 入库时间                      |

唯一约束：`(code, teacher)`

### CourseOffering

| 字段       | 类型    | 说明                       |
| ---------- | ------- | -------------------------- |
| id         | INTEGER | 主键                       |
| course_id  | INTEGER | 外键 → Course.id           |
| semester   | TEXT    | 学期，如 "2024秋"          |
| major      | TEXT    | 上课专业，如 "数学系大班"  |
| created_at | TEXT    | 入库时间                   |

唯一约束：`(course_id, semester, major)`

### Review

| 字段         | 类型    | 说明                              |
| ------------ | ------- | --------------------------------- |
| id           | INTEGER | 主键                              |
| course_id    | INTEGER | 外键 → Course.id（1 : 0..*）      |
| user_id      | INTEGER | 外键 → User.id                    |
| rating       | INTEGER | 评分（1-5），导入数据可为空       |
| content      | TEXT    | 评价正文                          |
| semester     | TEXT    | 学年学期，如 "2024秋"，可为空     |
| is_anonymous | INTEGER | 展示时是否匿名（0/1）             |
| is_deleted   | INTEGER | 软删除标记（0/1）                 |
| source       | TEXT    | 来源标识（导入数据用文件名，自有数据用 `native`） |
| ai_rated     | INTEGER | 是否由 AI 自动评分（0/1）         |
| created_at   | TEXT    | 提交时间                          |

> **注意**：SQLite 没有原生 BOOLEAN，所有布尔字段用 `INTEGER` 存 0/1。**统一使用 `query_helpers` 中的常量**（如 `REVIEW_NOT_DELETED`），不要在路由里写 `is_deleted == 0`。

### News（公告）

| 字段       | 类型    | 说明                       |
| ---------- | ------- | -------------------------- |
| id         | INTEGER | 主键                       |
| title      | TEXT    | 公告标题                   |
| content    | TEXT    | 公告正文                   |
| is_active  | INTEGER | 是否展示（0/1）             |
| created_at | TEXT    | 发布时间                   |

### 特殊处理

- **系统账号**：预置 `email=system@nanping` 的 User，所有导入评价挂其名下。前端检测到该账号时特殊渲染（如显示"历史导入评价"）。
- **实名制**：用户以南京大学邮箱注册，发评价时可选匿名展示（`is_anonymous`），但数据库始终记录真实 `user_id`。
- **老数据评分**：导入评价的 `rating` 先留空，后续可用 LLM 分析评价情绪自动补打分（`ai_rated=1`）。

## 5. API 设计

API 部署在独立子域名（如 `api.nanping.xxx`），路径中不含 `/api` 前缀。需登录的接口通过 `Authorization: Bearer <JWT>` 传递身份，后端从 token 解析 `user_id`，不信任请求体中传入的用户信息。

### 认证

| 方法 | 路径            | 说明                                   |
|------|-----------------|----------------------------------------|
| POST | /auth/send-code | 发送验证码到南大邮箱。同邮箱 N 秒（`AUTH_RESEND_COOLDOWN_SECONDS`，默认 60s）内不可重复发送，验证码有效期 M 分钟（`AUTH_CODE_EXPIRE_MINUTES`，默认 5）。开发阶段支持 mock 模式（验证码打印到控制台或设为固定值） |
| POST | /auth/register  | 注册。请求体：`email` + `code`（验证码）+ `password` |
| POST | /auth/login     | 登录。请求体：`email` + `password`。返回 JWT token |

### 课程

| 方法 | 路径             | 说明     |
|------|------------------|----------|
| GET  | /courses         | 搜索课程，分页。参数：`?code=`、`?name=`、`?teacher=`（至少填一个） |
| GET  | /courses/{id}    | 获取课程详情（含开课学期列表） |
| POST | /courses/match   | 批量匹配课程（插件用），按 5 级递进策略返回最佳匹配 |

### 评价

| 方法   | 路径            | 说明                                |
|--------|-----------------|-------------------------------------|
| GET    | /review         | 查看评价列表。参数：`?course_id=`，分页 |
| POST   | /review/add     | 提交新评价（需登录）。请求体：`course_id` + `rating` + `content` + `semester`（可选） + `is_anonymous`。`user_id` 由 token 解析 |
| DELETE | /review/delete  | 删除某条评价（需登录，只能删自己提交的）。请求体：`review_id`。软删除 |
| GET    | /review/me      | 查看当前用户提交的所有评价（需登录） |

### 公告 / 事件

| 方法 | 路径     | 说明     |
|------|----------|----------|
| GET  | /news    | 获取最新公告（`?limit=`，默认 5） |
| GET  | /events  | 活动事件流（管理员用） |

### 插件统一入口

| 方法 | 路径     | 说明     |
|------|----------|----------|
| POST | /plugin  | 插件 v2 入口。一次请求完成课程匹配 + 公告查询 + HTML 预渲染。返回 `badge_html` / `panel_html` / `news_html`，插件仅做 innerHTML 注入。详见 §7 |

### 设计原则

- 列表页只返回摘要，详细评价按需加载
- 不支持编辑评价（删了重发即可）
- 删除为软删除，`DELETE` 将 `is_deleted` 置为 `1`，评价列表默认过滤已删除记录
- **写评价后必须 `clear_all_caches()`**（详见 §7），否则插件会看到 30 秒旧数据

### 安全（MVP 基础防护）

- **JWT 认证**：需登录的接口从 `Authorization: Bearer` 头解析 `user_id`，不信任请求体中的用户信息
- **CORS 白名单**：仅允许自有前端和插件域名跨域请求
- **限流**：使用 `slowapi` 对写接口（POST/DELETE）做频率限制
- **风控**（§8）：IP 级别追踪 + 高频拦截 + 已登录用户折扣

## 6. 共享查询助手（query_helpers）

新增查询或修改现有查询时，**先看这里有没有可复用的**。

```python
from app.query_helpers import (
    REVIEW_NOT_DELETED,    # Review.is_deleted == 0
    REVIEW_IS_DELETED,     # Review.is_deleted == 1
    REVIEW_IS_ANONYMOUS,   # Review.is_anonymous == 1
    NEWS_IS_ACTIVE,        # News.is_active == 1
    make_review_count_subq,    # 某课程未删除评价数
    make_avg_rating_subq,      # 某课程未删除评价的平均分
    make_review_stats_subqueries,  # 同时返回 (count, avg)
    make_user_email_expr,      # 匿名 → None；否则 User.email
)
```

**禁止**在路由里写 `Review.is_deleted == 0` 之类的内联表达式，统一用上面的常量。

## 7. 缓存层（plugin_cache）

插件 `/plugin` 端点是热点（每次打开选课页都调一次），后端在以下查询前做了缓存：

| 缓存                  | Key 示例                          | TTL（默认）              | 配置项                       |
|-----------------------|-----------------------------------|--------------------------|------------------------------|
| `_exact_course_cache` | `exact:{code}:{name}:{teacher}`   | 5 分钟                   | `PLUGIN_CACHE_TTL_COURSE`    |
| `_search_cache`       | `search:{code}:{teacher}:{name}`  | 5 分钟                   | `PLUGIN_CACHE_TTL_COURSE`    |
| `_reviews_cache`      | `reviews:{course_id}:{limit}`     | **30 秒**（评价变化快）  | `PLUGIN_CACHE_TTL_REVIEWS`   |
| `_news_cache`         | `news:{limit}`                    | 2 分钟                   | `PLUGIN_CACHE_TTL_NEWS`      |

### Singleflight

并发 miss 时只让一个协程查 DB，其余 await 同一个 Future，防止缓存击穿（300 学生同时打开选课页 → 300 次查询 → DB 被打爆）。

### 失效策略

`/review/add` 和 `/review/delete` 写完后必须调用 `await clear_all_caches()`，否则新评价要等 30 秒才在插件里出现。**这是高频 bug 点**，已被 `test_cache_invalidation.py` 保护。

### 关闭缓存

生产排障时可设 `PLUGIN_CACHE_ENABLED=False`（不走缓存层，原函数直接执行）。

## 8. 风控（risk）

为防止插件端点被爬虫滥用，IP 级别追踪：

| 配置项                    | 默认值 | 说明                              |
|---------------------------|--------|-----------------------------------|
| `RISK_ENABLED`            | True   | 总开关                            |
| `RISK_RATE_THRESHOLD`     | 100    | 1 分钟请求速率阈值                |
| `RISK_COURSE_THRESHOLD`   | 200    | 10 分钟独立课程数阈值             |
| `RISK_AUTH_DISCOUNT`      | 0.5    | 已登录用户计分折扣                |
| `RISK_BLOCK_DURATION`     | 300    | 高风险封禁时长（秒）              |
| `RISK_SESSION_TTL`        | 3600   | 1 小时不活跃清理                  |
| `RISK_COOKIE_NAME`        | np_sid | 会话标识 cookie                   |

被风控拦截返回 429 + 详情，**不**在响应里暴露具体规则（避免对抗）。

## 9. 开发约定

### 代码风格

- **Python**：遵循 PEP 8，使用 ruff 进行格式化和 lint
- **注释**：每个函数和类必须写清晰的 docstring（Google 风格），说明功能、参数、返回值
- **命名**：函数/变量 `snake_case`，类 `PascalCase`
- **JS**：插件 `content_dev.js` 内的 `escapeHtml` / `formatDate` / `TOKEN_KEY` 是 `frontend/js/utils.js` 和 `frontend/js/auth.js` 的**手动镜像**（MV3 content script 不能 import ESM）。修改任一处时必须同步另一处，并在代码注释里写明来源。

### 插件选择器集中

NJU 教务系统 DOM 选择器集中在 `content_dev.js` 的 `SELECTORS` 常量。**禁止**在业务代码里写内联选择器（如 `tbody.course-body tr.course-tr`），NJU 改版时只需改这一处。

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
- 提交前确认代码可运行、测试通过

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

### 常用命令

```bash
# 跑全部测试
.venv/bin/python3 -m pytest backend/tests/ --tb=short -q

# 跑单个测试文件
.venv/bin/python3 -m pytest backend/tests/test_review.py -v

# 跑单个测试
.venv/bin/python3 -m pytest backend/tests/test_review.py::TestList::test_returns_reviews -v

# 语法检查 JS
node --check extension/content_dev.js
```

## 10. CI / 部署

### CI（GitHub Actions）

`.github/workflows/test.yml` 在每个 push / PR 时：

1. 启动 Python 3.13
2. `pip install -r backend/requirements.txt`
3. `pytest backend/tests/ --tb=short -q`

绿勾 = 通过。任何改动必须让 CI 保持绿。

### 插件分发

1. 改完 `extension/content_dev.js` 后重新打包：`cd extension && zip -r ../frontend/nanping-extension.zip . -x "*.DS_Store"`
2. `frontend/download.html` 的 `?v=` 查询参数需要 bump（如 `?v=20260807-1`），让浏览器知道有新版
3. **不要**手动编辑 `nanping-extension.zip` 里的文件（它是产物）

### 环境变量（.env）

复制 `backend/.env.example` 为 `backend/.env`，至少改：

- `SECRET_KEY`：JWT 签名密钥（必须改）
- `ADMIN_SECRET_KEY`：管理后台密钥
- `DATABASE_URL`：生产用 PostgreSQL

其他都有可用的开发默认值。
