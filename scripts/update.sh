#!/bin/bash
# ============================================================
# Nanping 更新脚本
# 拉取最新代码 → 重建镜像 → 重启容器
# ============================================================
set -e

APP_DIR="/opt/nanping"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始更新 Nanping..."

cd "$APP_DIR"

echo "  拉取最新代码..."
git pull origin main

echo "  重新构建 Docker 镜像..."
docker compose build --no-cache backend

echo "  重启容器..."
docker compose up -d backend

echo "  清理旧镜像..."
docker image prune -f

echo ""
echo "更新完成！容器状态:"
docker compose ps

echo ""
echo "查看日志: docker compose logs -f backend"
