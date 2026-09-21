#!/usr/bin/env bash
# 单例模式验收脚本（开发机与树莓派通用）：编译 + provider 自测 + 服务契约冒烟。
#
# 用法：
#   bash main/xiaozhi-server/scripts/run-acceptance.sh
#   CR_SMOKE_URL=http://127.0.0.1:8876 bash main/xiaozhi-server/scripts/run-acceptance.sh
#
# 说明：
# - 第 3 项会向目标 CR 实例写入固定测试数据（additive、无删除；用统一前缀便于辨认）；
#   若只想跑前两项，确保目标地址不可达即可（第 3 项会按契约失败）。
# - 通过标准：三项全过（compileall ✓ / 60/60 ✓ / 冒烟 7/7 ✓）。
set -uo pipefail

server_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$server_dir"

python="$server_dir/.venv/bin/python"
cr_url="${CR_SMOKE_URL:-http://127.0.0.1:8765}"
passed=0
failed=0

run() {
  local name="$1"
  shift
  echo "────────────────────────────────────────────────────"
  echo "▶ $name"
  if "$@"; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    echo "（该项失败）"
  fi
}

run "1/3 compileall（provider 模块）" \
  "$python" -m compileall -q core/providers/memory/context_recall
run "2/3 provider 自测（60 项，无网络/无真实 LLM）" \
  "$python" test/test_context_recall_provider.py
run "3/3 CR 服务契约冒烟（导入/命中/幂等/隔离/降级）@ $cr_url" \
  "$python" test/test_context_recall_smoke.py --base-url "$cr_url"

echo "────────────────────────────────────────────────────"
echo "结果：通过 $passed 项，失败 $failed 项"
[[ "$failed" -eq 0 ]]
