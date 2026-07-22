#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/run/backend.pid"
[ -f "$PID_FILE" ] || { echo "后端未运行" >&2; exit 1; }
PID=$(cat "$PID_FILE")

# 校验 PID 对应进程确为后端进程，避免 PID 被系统复用后误杀无关进程。
PROC_CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
if [ -z "$PROC_CMD" ]; then
    echo "PID $PID 已不存在（可能已自行退出），清理 PID 文件"
    rm -f "$PID_FILE"
    exit 0
fi
if ! grep -q "backend_main.py" <<< "$PROC_CMD"; then
    echo "❌ 拒绝停止：PID $PID 不是后端进程（实际为: $PROC_CMD）" >&2
    echo "   PID 可能已被复用，请手动确认后删除 $PID_FILE" >&2
    exit 1
fi

kill "$PID" && echo "后端已停止 (PID $PID)"
