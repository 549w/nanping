# ============================================================
# Nanping Backend Dockerfile
# 多阶段构建：编译依赖 → 精简运行时镜像
# ============================================================

# ---- Stage 1: 编译依赖 ----
FROM python:3.13-slim-bookworm AS builder

WORKDIR /build

# 安装编译 bcrypt 所需的工具链
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单并安装到独立 venv
COPY backend/requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: 运行时 ----
FROM python:3.13-slim-bookworm

# 创建非 root 用户
RUN groupadd -r nanping && useradd -r -g nanping -d /app nanping

# 从 builder 复制 venv
COPY --from=builder /opt/venv /opt/venv

# 设置工作目录，只复制后端代码
WORKDIR /app
COPY backend/ /app/

# 创建数据目录（SQLite 卷挂载点）
RUN mkdir -p /app/data && chown -R nanping:nanping /app

# 切换到非 root 用户
USER nanping

# 确保 venv 在 PATH 最前
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')" || exit 1

# 启动
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
