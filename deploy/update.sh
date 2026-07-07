#!/bin/bash
# 数字人生 — 安全更新脚本（保留数据）
# 用法：在服务器上执行 bash update.sh
# 不会删除 /opt/digitallife-data 中的任何数据（用户/团队/消息/配置）

set -e

APP_DIR="/opt/digitallife"
DATA_DIR="/opt/digitallife-data"
APP_NAME="digitallife"

echo "=========================================="
echo "  数字人生 — 安全更新（保留数据）"
echo "=========================================="

# 1. 备份数据库
echo "[1/6] 备份数据库..."
BACKUP_FILE="${DATA_DIR}/data/data_backup_$(date +%Y%m%d_%H%M%S).db"
if [ -f "${DATA_DIR}/data/data.db" ]; then
    cp "${DATA_DIR}/data/data.db" "$BACKUP_FILE"
    echo "  数据库已备份: $BACKUP_FILE"
else
    echo "  数据库文件不存在，跳过备份"
fi

# 2. 停止服务
echo "[2/6] 停止服务..."
systemctl stop ${APP_NAME} 2>/dev/null || true
echo "  服务已停止"

# 3. 拉取最新代码
echo "[3/6] 拉取最新代码..."
cd $APP_DIR
git fetch origin main
git reset --hard origin/main
echo "  代码已更新到最新版本"

# 4. 安装新依赖 + 重建前端
echo "[4/6] 安装依赖 + 构建前端..."
.venv/bin/pip install -r requirements.txt -q 2>&1 | tail -3

cd frontend
npm install --silent 2>/dev/null
npm run build 2>&1 | tail -3
cd ..
cp -r frontend/dist/* assets/frontend/
echo "  依赖安装 + 前端构建完成"

# 5. 重启服务
echo "[5/6] 重启服务..."
systemctl start ${APP_NAME}
sleep 5

# 6. 健康检查
echo "[6/6] 健康检查..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 http://127.0.0.1:8180/system/status.json 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✅ 服务启动成功 (HTTP 200)"
else
    echo "  ❌ 健康检查失败 (HTTP $HTTP_CODE)，查看日志："
    echo "  journalctl -u ${APP_NAME} -f"
    exit 1
fi

# 验证数据完好
USER_COUNT=$(sqlite3 "${DATA_DIR}/data/data.db" "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "?")
TEAM_COUNT=$(sqlite3 "${DATA_DIR}/data/data.db" "SELECT COUNT(*) FROM teams WHERE deleted=0;" 2>/dev/null || echo "?")
echo ""
echo "=========================================="
echo "  更新完成！"
echo "  用户数据: $USER_COUNT 个用户"
echo "  团队数据: $TEAM_COUNT 个团队"
echo "  访问地址: https://dashi.guofeng.me"
echo ""
echo "  数据库备份: $BACKUP_FILE"
echo "=========================================="
