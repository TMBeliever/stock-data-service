#!/usr/bin/env bash

# 查找占用 8000 端口的进程并关闭
PID=$(lsof -ti:8000 || true)

if [ -n "$PID" ]; then
    kill -9 $PID 2>/dev/null || true
    echo "✓ 已成功停止股票数据服务 (PID: $PID)"
else
    echo "ℹ️ 当前没有正在运行的股票数据服务 (端口 8000 未被占用)"
fi
