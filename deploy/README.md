# 数字人生 — 服务器部署指南

## 一键部署（在服务器上执行）

```bash
# 1. 下载部署脚本
wget https://raw.githubusercontent.com/suvlife/DigitalLife/main/deploy/deploy.sh -O deploy.sh
chmod +x deploy.sh

# 2. 执行部署（自动安装所有依赖、构建前端、配置 Nginx + SSL）
bash deploy.sh
```

## 部署完成后

### 访问地址
- HTTPS: https://dashi.guofeng.me
- 首次访问需注册账号（首个用户自动成为管理员）

### 管理命令
```bash
# 查看服务状态
systemctl status digitallife

# 重启服务
systemctl restart digitallife

# 查看实时日志
journalctl -u digitallife -f

# 查看应用日志
tail -f /opt/digitallife-data/logs/backend/backend.log
```

### Watchdog 监控（自动配置）
```bash
# 配置 crontab（每 2 分钟检查）
crontab -e
# 添加：
*/2 * * * * /opt/digitallife/deploy/watchdog.sh

# 查看监控日志
tail -f /var/log/digitallife-watchdog.log
```

### 自动更新（可选）
```bash
# 配置 crontab（每天凌晨 4 点自动更新）
crontab -e
# 添加：
0 4 * * * /opt/digitallife/deploy/auto-update.sh
```

## 手动部署步骤（如需分步执行）

### 1. 安装系统依赖
```bash
apt-get update
apt-get install -y python3.11 python3.11-venv nginx certbot python3-certbot-nginx git curl
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
```

### 2. 克隆代码
```bash
git clone https://github.com/suvlife/DigitalLife.git /opt/digitallife
cd /opt/digitallife
```

### 3. 安装后端依赖
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 4. 构建前端
```bash
cd frontend && npm install && npm run build && cd ..
cp -r frontend/dist/* assets/frontend/
```

### 5. 创建数据目录
```bash
mkdir -p /opt/digitallife-data
cp assets/config_template.json /opt/digitallife-data/setting.json
```

### 6. 配置 systemd 服务
```bash
cat > /etc/systemd/system/digitallife.service << 'EOF'
[Unit]
Description=数字人生
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/digitallife/src
ExecStart=/opt/digitallife/.venv/bin/python backend_main.py --config-dir /opt/digitallife-data --port 8180
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/opt/digitallife/src

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable digitallife
systemctl start digitallife
```

### 7. 配置 Nginx
```bash
cat > /etc/nginx/sites-available/digitallife << 'EOF'
server {
    listen 80;
    server_name dashi.guofeng.me;

    location / {
        proxy_pass http://127.0.0.1:8180;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8180;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }

    client_max_body_size 20m;
}
EOF

ln -sf /etc/nginx/sites-available/digitallife /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
```

### 8. 配置 SSL
```bash
certbot --nginx -d dashi.guofeng.me --non-interactive --agree-tos --register-unsafely-without-email --redirect
```

### 9. 配置防火墙
```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

### 10. 配置 Watchdog
```bash
chmod +x /opt/digitallife/deploy/watchdog.sh
(crontab -l 2>/dev/null; echo "*/2 * * * * /opt/digitallife/deploy/watchdog.sh") | crontab -
```

## 目录结构
```
/opt/digitallife/          # 代码目录
/opt/digitallife-data/     # 数据目录（setting.json + 数据库 + 日志）
/etc/nginx/sites-available/digitallife  # Nginx 配置
/etc/systemd/system/digitallife.service # systemd 服务
```

## 注意事项
- 后端监听 127.0.0.1:8180（仅本机），Nginx 代理 80/443
- SSL 证书自动续期（certbot 定时任务）
- Watchdog 每 2 分钟检查，异常自动重启（最多 5 次）
- 首个注册用户自动成为 ADMIN
- 内置 API Key 开箱即用（GLM + Tavily + Brave + Ghost CMS）
