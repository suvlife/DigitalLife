#!/bin/bash
# 数字人生 — 服务器部署脚本
# 用法：在服务器上执行 bash deploy.sh
# 前提：Ubuntu 22.04+ / Debian 12+，root 权限

set -e

# ===== 配置 =====
APP_NAME="digitallife"
APP_DIR="/opt/digitallife"
APP_PORT=8180
DOMAIN="dashi.guofeng.me"
PYTHON_VERSION="3.11"
NODE_VERSION="20"
REPO_URL="https://github.com/suvlife/DigitalLife.git"

echo "=========================================="
echo "  数字人生 — 服务器部署"
echo "  域名: $DOMAIN"
echo "  端口: $APP_PORT"
echo "=========================================="

# ===== 1. 系统更新 + 基础依赖 =====
echo "[1/10] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq \
    python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    git curl wget unzip sqlite3 \
    ufw fail2ban \
    htop jq 2>/dev/null

# ===== 2. 安装 Node.js（前端构建）=====
echo "[2/10] 安装 Node.js..."
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash -
    apt-get install -y -qq nodejs
fi
echo "  Node: $(node --version)"

# ===== 3. 克隆代码 =====
echo "[3/10] 克隆代码..."
if [ -d "$APP_DIR" ]; then
    echo "  目录已存在，拉取最新代码..."
    cd $APP_DIR
    git pull origin main
else
    git clone $REPO_URL $APP_DIR
    cd $APP_DIR
fi

# ===== 4. 安装后端依赖 =====
echo "[4/10] 安装后端依赖..."
python${PYTHON_VERSION} -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# ===== 5. 构建前端 =====
echo "[5/10] 构建前端..."
cd frontend
npm install --silent 2>/dev/null
npm run build 2>/dev/null
cd ..
mkdir -p assets/frontend
cp -r frontend/dist/* assets/frontend/
echo "  前端构建完成"

# ===== 6. 创建数据目录 =====
echo "[6/10] 创建数据目录..."
mkdir -p /opt/digitallife-data
# 如果已有 setting.json 保留，否则从模板复制
if [ ! -f /opt/digitallife-data/setting.json ]; then
    cp assets/config_template.json /opt/digitallife-data/setting.json
fi

# ===== 7. 创建 systemd 服务 =====
echo "[7/10] 创建 systemd 服务..."
cat > /etc/systemd/system/${APP_NAME}.service << EOF
[Unit]
Description=数字人生多智能体协作平台
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}/src
ExecStart=${APP_DIR}/.venv/bin/python backend_main.py --config-dir /opt/digitallife-data --port ${APP_PORT}
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=${APP_DIR}/src

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${APP_NAME}

# ===== 8. 配置 Nginx =====
echo "[8/10] 配置 Nginx..."
cat > /etc/nginx/sites-available/${APP_NAME} << 'NGINX'
server {
    listen 80;
    server_name dashi.guofeng.me;

    # 静态文件 + API 代理
    location / {
        proxy_pass http://127.0.0.1:8180;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:8180;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }

    client_max_body_size 20m;
}
NGINX

ln -sf /etc/nginx/sites-available/${APP_NAME} /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

# ===== 9. 启动应用 =====
echo "[9/10] 启动应用..."
systemctl restart ${APP_NAME}
sleep 3
systemctl status ${APP_NAME} --no-pager | head -10

# ===== 10. 配置 SSL 证书 =====
echo "[10/10] 配置 SSL 证书..."
certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos --register-unsafely-without-email --redirect
echo "  SSL 证书已配置，自动续期已启用"

# ===== 配置防火墙 =====
echo "[额外] 配置防火墙..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ===== 完成 =====
echo ""
echo "=========================================="
echo "  部署完成！"
echo "  访问地址: https://${DOMAIN}"
echo "  后端端口: ${APP_PORT}"
echo "  数据目录: /opt/digitallife-data"
echo "  代码目录: ${APP_DIR}"
echo ""
echo "  管理命令:"
echo "    systemctl status ${APP_NAME}"
echo "    systemctl restart ${APP_NAME}"
echo "    journalctl -u ${APP_NAME} -f"
echo "=========================================="
