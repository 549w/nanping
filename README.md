<div align="center">
  <div style="font-family: 'Source Han Serif SC', 'Noto Serif CJK SC', '思源宋体', SimSun, serif; font-size: 72px; font-weight: 700; color: #7B2D8E; line-height: 1.2; letter-spacing: 8px;">
    南评
  </div>
  <p><strong>南京大学选课系统课程信息增强工具</strong></p>
  <p>
    <a href="#功能">功能</a> ·
    <a href="#快速开始">快速开始</a> ·
    <a href="#项目结构">项目结构</a> ·
    <a href="#部署">部署</a> ·
    <a href="#API">API</a>
  </p>
</div>

---

<div align="center">

# 🧩 240+ &nbsp;&nbsp;&nbsp; 📚 34,000+ &nbsp;&nbsp;&nbsp; 💬 11,300+

**插件用户** &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; **收录课程** &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; **评价总数**

<sub>数据截至 2026 年 7 月 14 日</sub>

</div>

Nanping 是一个面向 [南京大学选课系统](https://xk.nju.edu.cn) 的课程信息增强工具。它通过浏览器插件在选课页面中注入课程评分数据，并配合后端 API 提供评价查询与存储服务，帮助同学们更明智地选课。

## 立即体验

[南评官网](https://nanping.eznju.com) 
[南评插件](https://nanping.eznju.com/download)

## 功能

- **浏览器插件** — 在选课页面课程行旁直接显示评分，点击查看详细评价
- **课程搜索** — 按课程号、名称、教师搜索课程，获取平均评分和评价数
- **评价系统** — 提交、查看、管理课程评价，支持匿名展示
- **数据清洗** — 从教务系统 API 抓取教学班数据，聚类去重后建立标准课程库
- **评分洞察** — 利用 LLM 对历史评价进行情绪分析，自动补全评分

## 技术栈

| 模块       | 技术                           | 说明                     |
| ---------- | ------------------------------ | ------------------------ |
| 浏览器插件 | Chrome Extension Manifest V3   | 内容脚本注入 + 弹出窗口  |
| 后端 API   | Python FastAPI                 | 异步支持、自动 OpenAPI   |
| 数据库     | SQLite / PostgreSQL            | 轻量起步，可迁移         |
| ORM        | SQLAlchemy (异步)              | 配合 FastAPI async       |
| 前端       | 原生 HTML + Pico.css + Vanilla JS | 响应式多页面应用      |
| 数据清洗   | Python (pandas / openpyxl)     | Excel / JSON 导入        |
| 部署       | Docker / Nginx / Uvicorn       | 容器化部署               |
| LLM        | OpenAI 兼容 API                | 评价情绪分析 + 自动评分  |

## 快速开始

### 环境要求

- Python 3.13+
- Node.js (仅插件开发)

### 后端

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r backend/requirements.txt

# 配置环境变量
cp backend/.env.example .env

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

访问 `http://localhost:8000` 查看 API 健康状态，`http://localhost:8000/docs` 查看自动生成的 API 文档。

### 前端

前端为纯静态页面，无需构建步骤。直接用浏览器打开 `frontend/index.html` 即可，或通过任意静态服务器 serve：

```bash
python3 -m http.server 3000 -d frontend
```

### 浏览器插件

1. 打开 Chrome 扩展管理页面 `chrome://extensions/`
2. 开启「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择 `extension/` 目录

插件会在 `https://xk.nju.edu.cn/xsxkapp/` 选课页面中自动注入评分信息。

### 数据导入

项目提供了一套数据清洗 pipeline：

```bash
# 1. 从教务系统抓取教学班数据
python backend/scripts/scrape_courses.py

# 2. 导入原始数据
python backend/scripts/import_raw.py

# 3. 提取并聚类为标准课程 + 开课记录
python backend/scripts/extract_courses.py

# 4. 导入历史评价（Excel 格式）
python backend/scripts/import_reviews.py
```

## 项目结构

```
nanping/
├── backend/
│   ├── app/
│   │   ├── main.py             # 应用入口
│   │   ├── config.py           # 配置
│   │   ├── database.py         # 数据库连接
│   │   ├── models.py           # ORM 模型
│   │   ├── schemas.py          # Pydantic 模型
│   │   ├── auth.py             # JWT 认证
│   │   └── routers/
│   │       ├── auth.py         # 认证路由
│   │       ├── courses.py      # 课程搜索路由
│   │       └── review.py       # 评价 CRUD 路由
│   ├── tests/
│   ├── scripts/                # 数据抓取与清洗脚本
│   └── requirements.txt
├── extension/                  # Chrome 浏览器插件
│   ├── manifest.json
│   └── content.js
├── frontend/                   # 前端页面
│   ├── index.html              # 首页（课程搜索）
│   ├── course.html             # 课程详情
│   ├── login.html / register.html / me.html
│   ├── css/style.css
│   └── js/
│       ├── api.js              # API 请求封装
│       ├── auth.js             # 登录态管理
│       └── utils.js
├── data/                       # 原始数据与清洗产物
├── docs/                       # 文档
├── Dockerfile                  # 后端容器化
├── docker-compose.yml          # 后端 + PostgreSQL
└── nginx.conf                  # Nginx 部署配置
```

## API

API 路径不含前缀，认证使用 `Authorization: Bearer <JWT>`。

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/send-code` | 发送验证码到南大邮箱 |
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录，返回 JWT |

### 课程

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/courses` | 搜索课程（`?code=` / `?name=` / `?teacher=`） |

### 评价

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/review` | 查看评价列表 |
| POST | `/review/add` | 提交评价（需登录） |
| DELETE | `/review/delete` | 删除评价（需登录，仅自己的） |
| GET | `/review/me` | 查看自己提交的评价 |

## 部署

### Docker Compose（生产）

```bash
# 1. 复制并编辑环境变量
cp .env.production.example .env.production

# 2. 启动
docker compose up -d

# 3. 配置 Nginx（参考 nginx.conf）
# 4. 申请 SSL 证书
certbot --nginx -d nanping.eznju.com -d npapi.eznju.com
```

### 数据模型

- **Course** — 评价对象，按 `课程号 + 教师` 唯一标识，教师经过**聚类合并**处理
- **CourseOffering** — 开课记录，`course + 学期 + 专业` 唯一
- **Review** — 评价，挂载到 Course，支持软删除和匿名展示
- **User** — 用户，南大邮箱注册

## 许可

[MIT](LICENSE) © 549w
