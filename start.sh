#!/bin/bash
# AI Interview Assistant - 启动脚本
# 在 Git Bash 中运行:  bash start.sh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "  AI Interview Assistant"
echo "========================================"
echo ""
echo "  终端 1 — 启动后端:"
echo "    cd \"$PROJECT_DIR/backend\""
echo "    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "  终端 2 — 启动前端:"
echo "    cd \"$PROJECT_DIR/frontend\""
echo "    npm run dev"
echo ""
echo "  后端: http://localhost:8000/docs"
echo "  前端: http://localhost:5173"
echo "========================================"
