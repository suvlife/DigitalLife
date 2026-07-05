#!/bin/bash
# 数字人生 — Watchdog 监控脚本
# 每 2 分钟检查服务状态，异常时自动重启 + 告警
# 用法：crontab -e → */2 * * * * /opt/digitallife/deploy/watchdog.sh

APP_NAME="digitallife"
APP_PORT=8180
HEALTH_URL="http://127.0.0.1:${APP_PORT}/system/status.json"
LOG_FILE="/var/log/digitallife-watchdog.log"
MAX_RESTARTS=5
RESTART_FILE="/tmp/digitallife-restart-count"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> $LOG_FILE
}

# 检查服务是否运行
if ! systemctl is-active --quiet ${APP_NAME}; then
    log "ERROR: 服务未运行，尝试重启..."
    systemctl restart ${APP_NAME}
    sleep 5
    if systemctl is-active --quiet ${APP_NAME}; then
        log "OK: 服务已重启成功"
    else
        log "CRITICAL: 服务重启失败！"
    fi
    exit 1
fi

# 检查 HTTP 健康端点
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 $HEALTH_URL 2>/dev/null)
if [ "$HTTP_CODE" != "200" ]; then
    log "ERROR: 健康检查失败 (HTTP $HTTP_CODE)，尝试重启..."

    # 重启计数
    COUNT=0
    if [ -f "$RESTART_FILE" ]; then
        COUNT=$(cat $RESTART_FILE)
    fi
    COUNT=$((COUNT + 1))
    echo $COUNT > $RESTART_FILE

    if [ $COUNT -le $MAX_RESTARTS ]; then
        systemctl restart ${APP_NAME}
        sleep 5
        log "WARNING: 第 $COUNT 次重启服务"
    else
        log "CRITICAL: 重启次数超限 ($COUNT/$MAX_RESTARTS)，停止自动重启"
    fi
    exit 1
else
    # 健康检查通过，重置计数
    if [ -f "$RESTART_FILE" ]; then
        rm -f $RESTART_FILE
    fi
fi

# 检查磁盘空间
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
if [ $DISK_USAGE -gt 90 ]; then
    log "WARNING: 磁盘空间不足 ${DISK_USAGE}%"
    # 清理旧日志
    find /opt/digitallife-data/logs -name "*.log" -mtime +7 -delete 2>/dev/null
    journalctl --vacuum-time=3d 2>/dev/null
fi

# 检查内存
MEM_USAGE=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100}')
if [ $MEM_USAGE -gt 90 ]; then
    log "WARNING: 内存使用率 ${MEM_USAGE}%"
fi

exit 0
