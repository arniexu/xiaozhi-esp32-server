#!/usr/bin/env bash
# 安装「小智 ↔ DSH agent」用的 ACP 配置档：~/.dsh/profiles/elder_helper_acp
#
# 幂等：重复执行只覆盖本脚本自己的两个文件，先备份再写。
# 不碰 ~/.dsh/profiles/elder_helper（web 版照旧可用）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE_SRC="$HERE/profile"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
PROFILE_NAME="elder_helper_acp"
PROFILE_DST="$DSH_HOME/profiles/$PROFILE_NAME"

if [ ! -d "$DSH_HOME" ]; then
  echo "找不到 DSH_HOME: $DSH_HOME" >&2
  exit 1
fi
if ! command -v dsh >/dev/null 2>&1; then
  echo "PATH 里没有 dsh，先装 dsh 或把它的 bin 目录加进 PATH" >&2
  exit 1
fi

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$PROFILE_DST"
for f in package.json cordis.patch.yml; do
  if [ -f "$PROFILE_DST/$f" ]; then
    cp -p "$PROFILE_DST/$f" "$PROFILE_DST/$f.bak-$stamp"
  fi
  cp "$PROFILE_SRC/$f" "$PROFILE_DST/$f"
done
echo "已写入配置档：$PROFILE_DST"

# 做一次组合校验：--dump-config 不启动应用，只把层叠好的配置打出来
if dsh --profile "$PROFILE_NAME" --dump-config >/tmp/dsh-${PROFILE_NAME}-dump.txt 2>/tmp/dsh-${PROFILE_NAME}-dump.err; then
  echo "配置组合校验通过（dump: /tmp/dsh-${PROFILE_NAME}-dump.txt）"
else
  echo "配置组合失败，看 /tmp/dsh-${PROFILE_NAME}-dump.err：" >&2
  tail -20 /tmp/dsh-${PROFILE_NAME}-dump.err >&2
  exit 1
fi

echo
echo "下一步：在小智服务端 config.yaml 里启用"
echo "  LLM: DshAgentLLM"
echo "  LLM:\\n    DshAgentLLM:\\n      type: dshagent\\n      command: dsh --profile $PROFILE_NAME"
