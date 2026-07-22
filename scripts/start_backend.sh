#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$REPO_ROOT/.venv/bin:$PATH"

# 日志目录可能不存在（.gitignore 忽略 logs/），重定向前先创建，避免全新检出首次启动失败。
mkdir -p "$REPO_ROOT/logs"

cd "$REPO_ROOT/src"
nohup python backend_main.py "$@" >> "$REPO_ROOT/logs/backend_stdout.log" 2>&1 &
PID=$!
echo "后端已启动 (PID $PID)"

# 存活检查：等待进程监听端口，失败则报告并退出非零。
PORT="${DIGITALLIFE_PORT:-8180}"
for _ in $(seq 1 15); do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "❌ 后端进程已退出，最近日志："
        tail -20 "$REPO_ROOT/logs/backend_stdout.log" || true
        exit 1
    fi
    if curl -sf -o /dev/null --connect-timeout 2 "http://127.0.0.1:${PORT}/system/status.json" 2>/dev/null; then
        echo "✅ 后端健康检查通过 (http://127.0.0.1:${PORT}/)"
        exit 0
    fi
    sleep 1
done
echo "⚠️  后端已启动 (PID $PID) 但 ${PORT} 端口 15s 内未通过健康检查，请查看日志："
echo "    tail -f $REPO_ROOT/logs/backend_stdout.log"
