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
# 重复安装防护（幂等）：
#   install 重复执行只覆盖同一个用户级 unit（~/.config/systemd/user/xiaozhi-server.service），
#   不产生第二份安装；若检测到系统级同名 unit（如 install-all-services.sh 的产物），
#   install 会拒绝执行并给出清理命令，避免"用户级+系统级"双实例（抢端口、重启循环、日志重复写）。
#   start/restart 在系统级同名实例运行中或已启用（开机自启）时同样拒绝，防止双进程。
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
  awk 'NR==1{next} /^set -euo pipefail$/{exit} {print}' "$0"
}

require_installed() {
  if [[ ! -f "$unit_path" ]]; then
    echo "服务未安装（$unit_path 不存在）。先运行：" >&2
    echo "  bash \"$0\" install" >&2
    exit 1
  fi
}

# ---- 重复安装防护（系统级同名 unit） ----------------------------------------
# install-all-services.sh（全模块部署）会把同名 unit 装到 /etc/systemd/system（系统级）。
# 用户级 + 系统级同时存在 = 双实例：抢同一端口、失败重启循环、日志重复写（小盘/树莓派敏感）。
# 规则：install 检测到系统级同名 unit 一律拒绝；start/restart 在其实例运行/已启用时拒绝。
system_unit_detect() {
  # 输出三行：fragment / active / enabled；系统级不存在该 unit 时返回 1。
  # 注意：systemctl show --value 对不存在的 unit 也返回 0，只能用"输出为空"判断。
  local fragment
  fragment="$(systemctl show --system -p FragmentPath --value "$unit_name" 2>/dev/null || true)"
  [[ -z "$fragment" ]] && return 1
  printf '%s\n%s\n%s\n' \
    "$fragment" \
    "$(systemctl is-active --system "$unit_name" 2>/dev/null || true)" \
    "$(systemctl is-enabled --system "$unit_name" 2>/dev/null || true)"
}

system_unit_hint() {
  local fragment="$1"
  cat >&2 <<EOS
处理（需 sudo）：
  sudo systemctl disable --now ${unit_name%.service}
  sudo rm -f "$fragment"
  sudo systemctl daemon-reload
（若确实要用系统级全模块部署，请不要使用本脚本：两种安装方式互斥）
EOS
}

require_no_system_unit_instance() {
  # start/restart 防护：系统级实例运行中或开机启用（enabled）时拒绝，防止双进程。
  local info fragment active enabled running=0
  info="$(system_unit_detect)" || return 0
  { read -r fragment; read -r active; read -r enabled; } <<<"$info"
  case "$active" in active|activating|reloading|deactivating) running=1 ;; esac
  if [[ "$running" -eq 0 && "$enabled" != "enabled" ]]; then
    echo "提示：存在系统级同名 unit（未运行未启用）：$fragment；建议清理，以免将来误启用造成双实例。" >&2
    return 0
  fi
  echo "错误：系统级同名服务处于运行/启用状态（active=$active enabled=$enabled），启动已被拒绝：" >&2
  echo "      $fragment" >&2
  system_unit_hint "$fragment"
  exit 1
}

do_install() {
  local info fragment active enabled verb="已安装"

  # 防重复安装：系统级同名 unit 一律不共存（见文件头"重复安装防护"）
  if info="$(system_unit_detect)"; then
    { read -r fragment; read -r active; read -r enabled; } <<<"$info"
    echo "错误：检测到系统级同名 unit，安装已拒绝（避免重复安装）：$fragment" >&2
    echo "      状态：active=$active enabled=$enabled" >&2
    system_unit_hint "$fragment"
    exit 1
  fi

  if [[ ! -x "$server_dir/.venv/bin/python" ]]; then
    echo "错误：找不到 $server_dir/.venv/bin/python" >&2
    echo "请先在 $server_dir 创建 venv 并安装依赖（见 docs/singleton-mode-deploy.md）" >&2
    exit 1
  fi

  if [[ ! -f "$server_dir/data/.config.yaml" ]]; then
    echo "警告：$server_dir/data/.config.yaml 不存在；" >&2
    echo "请先复制 config_singleton.yaml 到 data/.config.yaml 并填写密钥。" >&2
  fi

  [[ -f "$unit_path" ]] && verb="已更新"

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

  echo "$verb: $unit_path"
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
    require_no_system_unit_instance
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
    require_no_system_unit_instance
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
    if system_unit_detect >/dev/null; then
      echo "提示：系统级同名 unit 仍存在（本脚本不管理）；清理命令见 install 拒绝安装时的提示。" >&2
    fi
    ;;
  help|-h|--help) usage ;;
  *)
    echo "未知命令: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
