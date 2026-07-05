#!/bin/bash
# 数字人生 — 自动更新脚本
# 拉取最新代码、重建前端、重启服务
# 用法：crontab -e → 0 4 * * * /opt/digitallife/deploy/auto-update.sh

set -e
APP_DIR="/opt/digitallife"
LOG_FILE="/var/log/digitallife-update.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> $LOG_FILE
}

log "=== 开始自动更新 ==="

cd $APP_DIR

# 拉取最新代码
git fetch origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    log "无新代码，跳过更新"
    exit 0
fi

log "发现新代码，开始更新..."
git pull origin main

# 安装新依赖
.venv/bin/pip install -r requirements.txt -q 2>> $LOG_FILE

# 重建前端（仅当 frontend/src 有变化时）
if git diff --name-only $LOCAL..$REMOTE | grep -q "^frontend/"; then
    log "前端代码有变化，重建前端..."
    cd frontend
    npm install --silent 2>> $LOG_FILE
    npm run build 2>> $LOG_FILE
    cd ..
    cp -r frontend/dist/* assets/frontend/
    log "前端重建完成"
fi

# 重启服务
systemctl restart digitallife
sleep 3

# 健康检查
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://127.0.0.1:8180/system/status.json 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    log "更新成功，服务正常运行"
else
    log "CRITICAL: 更新后健康检查失败 (HTTP $HTTP_CODE)"
fi

log "=== 更新完成 ==="
