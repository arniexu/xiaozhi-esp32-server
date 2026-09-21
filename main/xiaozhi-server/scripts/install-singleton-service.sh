#!/usr/bin/env bash
# 单例模式：把 xiaozhi-server 安装为 user 级 systemd 服务（无 manager 依赖、开机自启）。
# 设计文档：docs/singleton-mode-plan.md §3 ｜ 参考：knowledge-agent-service/scripts/install-user-service.sh
#
# 用法（仓库任意位置）：
#   bash main/xiaozhi-server/scripts/install-singleton-service.sh
# 前置：
#   1. main/xiaozhi-server/.venv 已创建并装好依赖
#   2. data/.config.yaml 已按 config_singleton.yaml 配好（密钥、memory service_url）
set -euo pipefail

server_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit_dir="$HOME/.config/systemd/user"
unit_name="xiaozhi-server.service"

if [[ ! -x "$server_dir/.venv/bin/python" ]]; then
  echo "错误：找不到 $server_dir/.venv/bin/python" >&2
  echo "请先在 $server_dir 创建 venv 并安装依赖（见 docs/singleton-mode-deploy.md）" >&2
  exit 1
fi

if [[ ! -f "$server_dir/data/.config.yaml" ]]; then
  echo "警告：$server_dir/data/.config.yaml 不存在；" >&2
  echo "请先复制 config_singleton.yaml 到 data/.config.yaml 并填写密钥。" >&2
fi

mkdir -p "$unit_dir"
cat > "$unit_dir/$unit_name" <<EOF
[Unit]
Description=XiaoZhi ESP32 Server (singleton mode)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$server_dir
ExecStart=$server_dir/.venv/bin/python app.py
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$unit_name"
loginctl enable-linger "$USER" >/dev/null 2>&1 || true

echo "已安装: $unit_dir/$unit_name"
echo "启动:   systemctl --user start $unit_name"
echo "状态:   systemctl --user status $unit_name"
echo "日志:   journalctl --user -u $unit_name -f"
