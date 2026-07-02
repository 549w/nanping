#!/bin/bash
# ============================================================
# Nanping 服务器首次部署脚本
# 在 VPS 上以 root 或 sudo 用户运行
# ============================================================
set -e

APP_DIR="/opt/nanping"
GIT_REMOTE="${1:-git@github.com:549w/nanping.git}"

echo "============================================"
echo " Nanping 部署脚本"
echo "============================================"
echo ""

# ---- 1. 安装 Docker（如未安装）----
if ! command -v docker &> /dev/null; then
    echo "[1/8] 安装 Docker..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sudo sh /tmp/get-docker.sh
    sudo usermod -aG docker "$USER"
    echo "  Docker 已安装。如果这是首次安装，请重新登录以使 docker 组生效。"
else
    echo "[1/8] Docker 已安装: $(docker --version)"
fi

# ---- 2. 克隆项目 ----
if [ -d "$APP_DIR/.git" ]; then
    echo "[2/8] 项目目录已存在，执行 git pull..."
    cd "$APP_DIR"
    git pull origin main
else
    echo "[2/8] 克隆项目到 $APP_DIR..."
    sudo mkdir -p "$APP_DIR"
    sudo chown "$USER:$USER" "$APP_DIR"
    git clone "$GIT_REMOTE" "$APP_DIR"
fi

# ---- 3. 创建数据目录 ----
echo "[3/8] 准备数据目录..."
mkdir -p "$APP_DIR/data"
chmod 755 "$APP_DIR/data"

# ---- 4. 配置环境变量 ----
if [ ! -f "$APP_DIR/.env.production" ]; then
    echo "[4/8] 创建 .env.production（从模板复制）..."
    cp "$APP_DIR/.env.production.example" "$APP_DIR/.env.production"
    chmod 600 "$APP_DIR/.env.production"
    echo ""
    echo "  >>> 请现在编辑 $APP_DIR/.env.production <<<"
    echo "  >>> 至少需要修改 SECRET_KEY 和 SMTP 配置 <<<"
    echo ""
    read -rp "  编辑完成按回车继续..."
else
    echo "[4/8] .env.production 已存在，跳过."
fi

# ---- 5. 配置 Nginx ----
echo "[5/8] 配置 Nginx..."
if [ -f /etc/nginx/sites-available/nanping ]; then
    echo "  Nginx 配置已存在，跳过."
else
    sudo cp "$APP_DIR/nginx.conf" /etc/nginx/sites-available/nanping
    sudo ln -sf /etc/nginx/sites-available/nanping /etc/nginx/sites-enabled/nanping
    echo "  Nginx 配置已复制到 /etc/nginx/sites-available/nanping"
fi

# 测试 Nginx 配置
if sudo nginx -t 2>&1; then
    sudo systemctl reload nginx
    echo "  Nginx 配置测试通过，已重载。"
else
    echo "  >>> Nginx 配置测试失败！请检查 SSL 证书路径后手动修复 <<<"
    echo "  >>> 如果尚未获取证书，先运行: sudo certbot certonly --webroot -w /var/www/certbot -d nanping.eznju.com -d npapi.eznju.com <<<"
fi

# ---- 6. SSL 证书检查 ----
echo "[6/8] 检查 SSL 证书..."
for domain in nanping.eznju.com npapi.eznju.com; do
    if [ -d "/etc/letsencrypt/live/$domain" ]; then
        echo "  $domain: 证书已存在"
    else
        echo "  $domain: 证书不存在！部署后请运行:"
        echo "    sudo mkdir -p /var/www/certbot"
        echo "    sudo certbot certonly --webroot -w /var/www/certbot -d $domain"
    fi
done

# ---- 7. 构建并启动 Docker ----
echo "[7/8] 构建并启动 Docker 容器..."
cd "$APP_DIR"
docker compose up -d --build

# ---- 8. 验证 ----
echo "[8/8] 验证部署..."
sleep 3

# 容器状态
echo ""
echo "容器状态:"
docker compose ps

# API 健康检查
echo ""
echo "API 健康检查:"
curl -s http://127.0.0.1:8000/ 2>/dev/null || echo "  >>> 本地 API 检查失败，容器可能还在启动中 <<<"

echo ""
echo "============================================"
echo " 部署完成！"
echo ""
echo " 验证命令："
echo "   curl https://npapi.eznju.com/"
echo "   curl https://nanping.eznju.com/"
echo "   docker compose -f $APP_DIR/docker-compose.yml logs -f backend"
echo ""
echo " 后续更新命令："
echo "   $APP_DIR/scripts/update.sh"
echo "============================================"
