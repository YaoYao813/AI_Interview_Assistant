#!/usr/bin/env bash
# AI Interview Assistant - 一键启动（Git Bash / macOS / Linux）
# 用法: bash start.sh
# 停止: Ctrl+C（一并停止后端与前端；Redis 容器保留）

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -t 1 ]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; NC=$'\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; NC=''
fi

say()  { printf '%s\n' "$*"; }
info() { printf '        %s\n' "$*"; }
ok()   { printf '%s[ok]%s %s\n' "$GREEN" "$NC" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$YELLOW" "$NC" "$*"; }
die()  { printf '%s[error]%s %s\n' "$RED" "$NC" "$*" >&2; exit 1; }

say "========================================"
say "  AI Interview Assistant - 一键启动"
say "========================================"
say ""

# ---------- 0. 前置检查 ----------
command -v docker >/dev/null 2>&1 || die "未找到 docker。请安装 Docker Desktop，并确保在 PATH 中。"
docker info >/dev/null 2>&1 || die "Docker 已安装但没有运行。请先启动 Docker Desktop。"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  die "找不到 docker compose / docker-compose。"
fi

[ -f backend/requirements.txt ] || die "当前目录不像仓库根目录（缺少 backend/requirements.txt）。"
[ -f backend/.env ] || die "缺少 backend/.env。先执行：cp backend/.env.example backend/.env，再填入 API Key。"
if ! command -v npm >/dev/null 2>&1 \
  && ! { command -v node >/dev/null 2>&1 && [ -f "$ROOT/frontend/node_modules/vite/bin/vite.js" ]; }; then
  die "未找到 npm/node。请安装 Node 18+ 并加入 PATH；或先在 frontend 目录运行 npm install。"
fi

pick_python() {
  local cand
  for cand in \
    "$ROOT/backend/.venv/Scripts/python.exe" "$ROOT/backend/.venv/bin/python" \
    "$ROOT/venv/Scripts/python.exe" "$ROOT/venv/bin/python" \
    python python3; do
    if [ "$cand" = "python" ] || [ "$cand" = "python3" ]; then
      command -v "$cand" >/dev/null 2>&1 || continue
      if "$cand" -c 'import uvicorn, fastapi' >/dev/null 2>&1; then
        printf '%s' "$cand"; return 0
      fi
    else
      [ -x "$cand" ] || continue
      if "$cand" -c 'import uvicorn, fastapi' >/dev/null 2>&1; then
        printf '%s' "$cand"; return 0
      fi
    fi
  done
  return 1
}

PY="$(pick_python)" || die "找不到可用的 Python（需要 uvicorn + fastapi）。在 backend 目录执行：
        python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"

port_busy() {
  "$PY" - "$1" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

port_busy 8000 && die "端口 8000 已被占用，后端无法启动。查看占用：netstat -ano | grep :8000"
port_busy 5173 && die "端口 5173 已被占用，前端无法启动。查看占用：netstat -ano | grep :5173"

# ---------- 1. Redis ----------
say "[1/4] 启动 Redis ..."
"${COMPOSE[@]}" up -d || die "Redis 启动失败，请检查上方 docker compose 的输出。"

for _ in $(seq 1 30); do
  docker exec ai-interview-redis redis-cli ping >/dev/null 2>&1 && break
  sleep 1
done
docker exec ai-interview-redis redis-cli ping >/dev/null 2>&1 \
  || die "Redis 30 秒内未就绪。查看日志：docker logs ai-interview-redis"
ok "Redis 就绪"

# ---------- 2. 后端 ----------
LOG_DIR="${TMPDIR:-/tmp}"
BACK_LOG="$LOG_DIR/ai-interview-backend.log"
FRONT_LOG="$LOG_DIR/ai-interview-frontend.log"

say "[2/4] 启动后端 ..."
( cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload ) \
  >"$BACK_LOG" 2>&1 &
BACK_PID=$!

wait_http() {
  local url=$1 tries=${2:-120} i
  for ((i = 0; i < tries; i++)); do
    if command -v curl >/dev/null 2>&1; then
      curl -fsS --max-time 2 "$url" >/dev/null 2>&1 && return 0
    else
      "$PY" - "$url" >/dev/null 2>&1 <<'PY' && return 0
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=2).read()
PY
    fi
    sleep 0.5
  done
  return 1
}

if ! wait_http "http://127.0.0.1:8000/health" 120; then
  kill "$BACK_PID" 2>/dev/null || true
  die "后端 60 秒内未通过健康检查。日志：$BACK_LOG"
fi
ok "后端就绪 http://127.0.0.1:8000"

# ---------- 3. 前端 ----------
say "[3/4] 启动前端 ..."
if command -v node >/dev/null 2>&1 && [ -f "$ROOT/frontend/node_modules/vite/bin/vite.js" ]; then
  ( cd "$ROOT/frontend" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 ) >"$FRONT_LOG" 2>&1 &
else
  ( cd "$ROOT/frontend" && exec npm run dev -- --host 127.0.0.1 ) >"$FRONT_LOG" 2>&1 &
fi
FRONT_PID=$!

if ! wait_http "http://127.0.0.1:5173" 120; then
  kill "$FRONT_PID" 2>/dev/null || true
  die "前端 60 秒内未就绪。日志：$FRONT_LOG"
fi
ok "前端就绪 http://127.0.0.1:5173"

# ---------- 4. 收尾 ----------
open_browser() {
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*) cmd.exe /c start "" "$1" >/dev/null 2>&1 || true ;;
    Darwin*) open "$1" >/dev/null 2>&1 || true ;;
    *) xdg-open "$1" >/dev/null 2>&1 || true ;;
  esac
}
say "[4/4] 打开浏览器"
open_browser "http://127.0.0.1:5173"

# 后端带 --reload 时 uvicorn 会派生多进程 worker，只 kill 父进程会留下占着端口的孤儿；
# Windows 上按 winpid 整棵树杀。
kill_tree() {
  local pid=$1 wpid=""
  [ -n "$pid" ] || return 0
  if [ -r "/proc/$pid/winpid" ]; then
    wpid="$(cat "/proc/$pid/winpid" 2>/dev/null || true)"
  fi
  case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*)
      [ -n "$wpid" ] && taskkill //PID "$wpid" //T //F >/dev/null 2>&1 || true
      ;;
  esac
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  trap - INT TERM EXIT
  say ""
  say "停止后端与前端 ..."
  kill_tree "${FRONT_PID:-}"
  kill_tree "${BACK_PID:-}"
  wait 2>/dev/null || true
  say "已停止。Redis 容器仍在运行（停止它：docker compose stop）。"
}
trap cleanup INT TERM EXIT

say ""
say "========================================"
say "  全部就绪"
say "----------------------------------------"
say "  前端   http://127.0.0.1:5173"
say "  后端   http://127.0.0.1:8000/docs"
say "  健康   http://127.0.0.1:8000/health"
say "----------------------------------------"
info "后端日志 $BACK_LOG"
info "前端日志 $FRONT_LOG"
say "========================================"
say ""
say "按 Ctrl+C 停止后端与前端。"

wait
