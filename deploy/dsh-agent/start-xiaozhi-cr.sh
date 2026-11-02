#!/usr/bin/env bash
# 启动「小智专用」的 Context Recall 记忆实例（数据固定在 ~/.local/share/xiaozhi-cr）。
#
# 为什么单独一个：xiaozhi 的记忆不该和别人项目的知识库混在一起，也不该放 /tmp
# （之前配置指向 /tmp/xiaozhi-cr-test，重启机器就没了）。
set -eu

KAS_DIR="${KAS_DIR:-$HOME/knowledge-agent-service}"
DATA_DIR="${DATA_DIR:-$HOME/.local/share/xiaozhi-cr}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8877}"

[ -d "$KAS_DIR/src/knowledge_agent_service" ] || { echo "找不到 knowledge-agent-service: $KAS_DIR" >&2; exit 1; }
mkdir -p "$DATA_DIR" "$HOME/.dsh/logs"

cd "$KAS_DIR"
PYTHONPATH="$KAS_DIR/src:$KAS_DIR/.runtime" \
KNOWLEDGE_AGENT_DATA_DIR="$DATA_DIR" \
KNOWLEDGE_AGENT_HOST="$HOST" \
KNOWLEDGE_AGENT_PORT="$PORT" \
setsid nohup /usr/bin/python3 -m knowledge_agent_service.cli serve \
  > "$HOME/.dsh/logs/xiaozhi-cr.log" 2>&1 < /dev/null &

sleep 5
if curl -s "http://$HOST:$PORT/health" | grep -q '"status":"ok"'; then
  echo "小智记忆实例已启动: http://$HOST:$PORT  数据: $DATA_DIR"
else
  echo "启动失败，看 $HOME/.dsh/logs/xiaozhi-cr.log" >&2
  tail -5 "$HOME/.dsh/logs/xiaozhi-cr.log" >&2
  exit 1
fi
