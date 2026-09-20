#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "缺少 .env 文件，请先根据 .env.example 配置 Supabase 参数。" >&2
  exit 1
fi

docker compose pull || true
docker compose up -d --build
docker compose ps

echo "部署完成。若使用腾讯云轻量服务器，请确认防火墙已放通 TCP 80 端口。"
