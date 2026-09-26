#!/usr/bin/env bash
# 构建并安装「小智 Copilot 桥接」扩展（适用于 VS Code Server / 远程 SSH 场景）
# 用法：./install-remote.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> npm install"
npm install --no-audit --no-fund

echo "==> 编译 TypeScript"
npm run compile

VERSION="$(node -p "require('./package.json').version")"
NAME="$(node -p "require('./package.json').publisher + '.' + require('./package.json').name")"
TARGET="$HOME/.vscode-server/extensions/${NAME}-${VERSION}"

echo "==> 安装到 $TARGET"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r package.json out node_modules README.md "$TARGET/"

echo ""
echo "完成。请在 VS Code 执行「开发人员: 重新加载窗口 (Developer: Reload Window)」使扩展生效。"
