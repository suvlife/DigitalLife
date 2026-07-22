#!/bin/bash
# 数字人生 — 安全更新脚本（保留数据）
# 用法：在服务器上执行 bash update.sh
# 不会删除 /opt/digitallife-data 中的任何数据（用户/团队/消息/配置）

set -e
# 管道左端命令失败时让整条管道返回非零，配合 set -e 在构建/安装失败时立即中止，
# 避免把构建失败的前端或残缺依赖照样 systemctl start 上线。
set -o pipefail

APP_DIR="/opt/digitallife"
DATA_DIR="/opt/digitallife-data"
APP_NAME="digitallife"

echo "=========================================="
echo "  数字人生 — 安全更新（保留数据）"
echo "=========================================="

# 1. 停止服务（先停再备份，避免运行中拷贝 WAL 数据库得到不一致备份）
echo "[1/6] 停止服务..."
systemctl stop ${APP_NAME} 2>/dev/null || true
echo "  服务已停止"

# 2. 备份数据库（优先使用仓库自带的安全备份脚本，基于 SQLite 在线备份 API，
#    含完整性校验；失败时回退为停服后的物理拷贝，此时服务已停、数据一致）
echo "[2/6] 备份数据库..."
BACKUP_FILE="${DATA_DIR}/data/data_backup_$(date +%Y%m%d_%H%M%S).db"
mkdir -p "${DATA_DIR}/data/backups"
if [ -f "${DATA_DIR}/data/data.db" ]; then
    if .venv/bin/python scripts/backup_and_migrate.py --config-dir "${DATA_DIR}" --backup-dir "${DATA_DIR}/data/backups"; then
        echo "  数据库已通过 backup_and_migrate.py 安全备份（含完整性校验）"
    else
        echo "  安全备份脚本失败，回退为停服后物理拷贝"
        cp "${DATA_DIR}/data/data.db" "$BACKUP_FILE"
        echo "  数据库已备份: $BACKUP_FILE"
    fi
else
    echo "  数据库文件不存在，跳过备份"
fi

# 3. 拉取最新代码
echo "[3/6] 拉取最新代码..."
cd $APP_DIR
git fetch origin main
git reset --hard origin/main
echo "  代码已更新到最新版本"

# 4. 安装新依赖 + 重建前端（含 V3）
echo "[4/6] 安装依赖 + 构建前端..."
.venv/bin/pip install -r requirements.txt -q 2>&1 | tail -3

cd frontend
npm install --silent 2>/dev/null
npm run build 2>&1 | tail -3
cd ..
cp -r frontend/dist/* assets/frontend/

cd frontend-v2
npm install --silent 2>/dev/null
npm run build 2>&1 | tail -3
cd ..
mkdir -p assets/frontend-v2
cp -r frontend-v2/dist/* assets/frontend-v2/

cd frontend-v3
npm install --silent 2>/dev/null
npm run build 2>&1 | tail -3
cd ..
mkdir -p assets/frontend-v3
cp -r frontend-v3/dist/* assets/frontend-v3/
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
