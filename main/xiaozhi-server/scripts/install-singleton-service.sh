#!/usr/bin/env bash
# 单例模式：安装与维护 xiaozhi-server（user 级 systemd，无 manager 依赖、开机自启）。
# 设计文档：docs/singleton-mode-plan.md §3 ｜ 部署手册：docs/singleton-mode-deploy.md ｜ 启动手册：docs/singleton-mode-start.md
#
# 用法（仓库任意位置）：
#   bash main/xiaozhi-server/scripts/install-singleton-service.sh [命令]
#
# 命令：
#   install    生成/更新 unit 并启用（默认命令；不自动启动）
#   start      启动服务
#   stop       停止服务
#   restart    重启服务（改配置/改代码后使用）
#   status     查看运行状态
#   logs       跟随查看日志（Ctrl+C 退出）
#   uninstall  停止并移除服务（不动数据文件）
#   help       显示本帮助
#
# 前置（仅 install 需要）：
#   1. main/xiaozhi-server/.venv 已创建并装好依赖
#   2. data/.config.yaml 已按 config_singleton.yaml 配好（密钥、memory service_url）
set -euo pipefail

server_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit_dir="$HOME/.config/systemd/user"
unit_name="xiaozhi-server.service"
unit_path="$unit_dir/$unit_name"

usage() {
  sed -n '2,20p' "$0"
}

require_installed() {
  if [[ ! -f "$unit_path" ]]; then
    echo "服务未安装（$unit_path 不存在）。先运行：" >&2
    echo "  bash \"$0\" install" >&2
    exit 1
  fi
}

do_install() {
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
  cat > "$unit_path" <<EOF
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

  echo "已安装: $unit_path"
  if systemctl --user is-active --quiet "$unit_name"; then
    echo "服务运行中；unit 已更新，如需生效请执行：bash \"$0\" restart"
  else
    echo "启动:   bash \"$0\" start"
  fi
}

cmd="${1:-install}"
case "$cmd" in
  install) do_install ;;
  start)
    require_installed
    systemctl --user start "$unit_name"
    echo "已启动: $unit_name"
    ;;
  stop)
    require_installed
    systemctl --user stop "$unit_name" || true
    echo "已停止: $unit_name"
    ;;
  restart)
    require_installed
    systemctl --user restart "$unit_name"
    echo "已重启: $unit_name"
    ;;
  status)
    require_installed
    systemctl --user status "$unit_name" --no-pager || true
    ;;
  logs)
    require_installed
    echo "跟随日志（Ctrl+C 退出）..."
    journalctl --user -u "$unit_name" -f -n 50
    ;;
  uninstall)
    require_installed
    systemctl --user stop "$unit_name" 2>/dev/null || true
    systemctl --user disable "$unit_name" 2>/dev/null || true
    rm -f "$unit_path"
    systemctl --user daemon-reload
    echo "已卸载: $unit_name（数据文件未受影响）"
    ;;
  help|-h|--help) usage ;;
  *)
    echo "未知命令: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
