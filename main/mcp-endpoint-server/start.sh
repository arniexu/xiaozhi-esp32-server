#!/bin/bash

# 关闭8004端口相关进程
pids=$(sudo lsof -t -i:8004)
if [ -n "$pids" ]; then
  echo "Killing processes on port 8004: $pids"
  sudo kill $pids
fi

# 清理上一次启动的容器和镜像
set -e

echo "Stopping and removing containers/images..."
docker compose -f docker-compose.yml down || true
docker stop mcp-endpoint-server || true
docker rm mcp-endpoint-server || true
docker rmi ghcr.nju.edu.cn/xinnan-tech/mcp-endpoint-server:latest || true

# 启动docker容器

echo "Starting new container..."
docker compose -f docker-compose.yml up -d

echo "Showing logs..."
docker logs -f mcp-endpoint-server
