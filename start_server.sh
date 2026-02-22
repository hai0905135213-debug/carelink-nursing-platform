#!/usr/bin/env bash
set -euo pipefail

# Small helper to start the Flask app safely.
# Usage:
#   ./start_server.sh                 # 自动创建 venv（若缺失），初始化 DB，启动 app
#   FORCE_KILL=1 ./start_server.sh    # 会尝试杀掉占用端口的进程

# 如果没有虚拟环境，自动创建并安装依赖
if [ ! -d venv ]; then
  echo "创建 Python 虚拟环境 venv 并安装依赖..."
  python3 -m venv venv
  # shellcheck source=/dev/null
  source venv/bin/activate
  # 生成简单的 requirements.txt（若不存在）
  if [ ! -f requirements.txt ]; then
    cat > requirements.txt <<EOF
Flask
flask-login
WTForms
SQLAlchemy
Werkzeug
EOF
  fi
  pip install --upgrade pip
  pip install -r requirements.txt
else
  # 激活已有 venv
  # shellcheck source=/dev/null
  source venv/bin/activate
fi

# 初始化 sqlite 数据库（仅在不存在时）
DBFILE="carelink.dev.db"
if [ ! -f "$DBFILE" ]; then
  echo "初始化数据库并插入示例数据..."
  python3 - <<'PY'
from db import init_db, seed
init_db()
seed()
print('db init+seed done')
PY
fi

# 首选端口数组（按顺序尝试）
PORTS=(5000 5002 5100)
CHOSEN_PORT=""

for P in "${PORTS[@]}"; do
  PID=$(lsof -t -iTCP:$P -sTCP:LISTEN || true)
  if [ -z "$PID" ]; then
    CHOSEN_PORT=$P
    break
  else
    echo "端口 $P 被 PID(s): $PID 占用"
    if [ "${FORCE_KILL:-0}" = "1" ]; then
      echo "FORCE_KILL=1，尝试杀掉 $PID ..."
      kill $PID || kill -9 $PID || true
      sleep 0.5
      # 确认是否释放
      PID2=$(lsof -t -iTCP:$P -sTCP:LISTEN || true)
      if [ -z "$PID2" ]; then
        CHOSEN_PORT=$P
        break
      else
        echo "端口 $P 仍被占用（$PID2），跳过"
      fi
    else
      echo "如需自动杀掉占用进程请使用: FORCE_KILL=1 ./start_server.sh"
    fi
  fi
done

if [ -z "$CHOSEN_PORT" ]; then
  echo "未找到可用端口，退出。请先释放 5000/5002/5100 中的一个端口。"
  exit 1
fi

echo "启动服务器，在浏览器打开: http://localhost:$CHOSEN_PORT"

# 以 Python 方式运行 app（保持在前台，输出到控制台）
python3 - <<PY
import sys
sys.path.insert(0, '/Users/liyuhan/Desktop/site')
import app
app.app.run(host='0.0.0.0', port=$CHOSEN_PORT, debug=False)
PY
