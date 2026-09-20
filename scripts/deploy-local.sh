#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "缺少 .env 文件，请先根据 .env.example 配置 Supabase 参数。" >&2
  exit 1
fi

PORT="${APP_PORT:-8507}"
python3 -m pip install --user -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

nohup python3 -m streamlit run app.py \
  --server.address=0.0.0.0 \
  --server.port="$PORT" \
  --server.headless=true \
  --server.enableCORS=true \
  --server.enableXsrfProtection=true \
  > app.log 2>&1 &

echo $! > streamlit.pid
echo "预约系统已在端口 ${PORT} 启动，PID: $(cat streamlit.pid)"
