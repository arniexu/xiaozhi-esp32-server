# 小智 Copilot 桥接（VS Code 扩展）

把 VS Code 的 GitHub Copilot 接到小智设备：

```
小智设备「问 Copilot 帮我看看…」 → xiaozhi-server（copilot_bridge） → 本扩展（ws://127.0.0.1:8767）
    → GitHub Copilot 模型（Language Model API） → 口语化过滤 → 回传设备播报
```

对话会镜像到 **@xiaozhi 聊天面板**（可见，可在设置里关掉）；每台设备一个多轮会话。

服务端配套：`main/xiaozhi-server/core/handle/copilotHandle.py`（设计文档：`docs/copilot-bridge-plan.md`）。

## 构建与安装（远程 SSH / VS Code Server 场景）

在**运行 xiaozhi-server 的同一台机器**上（即 VS Code Server 所在远端）：

```bash
cd tools/vscode-copilot-bridge
./install-remote.sh        # npm install + 编译 + 复制到 ~/.vscode-server/extensions/
```

然后在 VS Code 里执行 `开发人员: 重新加载窗口 (Developer: Reload Window)`。
激活后右下角状态栏出现 `📡 小智桥接:8767`。

> 也可用 `npm run compile` 后把整个目录（含 `node_modules/`、`out/`、`package.json`）手动复制到
> `~/.vscode-server/extensions/arniexu.xiaozhi-copilot-bridge-0.1.0/`，同样 reload 生效。

## 使用

1. 确认 xiaozhi-server 的 `config.yaml` 里 `copilot_bridge.enabled: true` 且 `url` 与端口一致（默认 8767）；
2. 设备说「**问 Copilot 帮我看看明天天气**」→ 进入 Copilot 模式，回答由设备播报；
3. 继续追问（多轮上下文保留）；说「**退出 Copilot**」回到常规对话；
4. 首次使用时 Copilot 会弹一次授权请求（扩展访问语言模型），选择允许即可。

## 设置

| 设置项 | 默认 | 说明 |
|---|---|---|
| `xiaozhiBridge.port` | 8767 | 桥接监听端口（仅 127.0.0.1） |
| `xiaozhiBridge.mirrorToChat` | true | 设备对话镜像到 @xiaozhi 面板（失败自动回退直连） |
| `xiaozhiBridge.mirrorPickupMs` | 2000 | 镜像接管等待时间，超时回退直连 |
| `xiaozhiBridge.spokenMaxChars` | 300 | 单条播报文本最大字数 |
| `xiaozhiBridge.modelFamily` | （空） | 直连路径指定模型 family，留空自动选第一个可用模型 |

## 故障排查

- **设备播报「Copilot 桥接没连上」**：VS Code 未开 / 扩展未激活 / 端口不一致；看输出面板「小智桥接」日志。
- **播报「额度受限（可能已达配额上限）」**：账号 Copilot 配额不足（CLI 无头模式会被单独限流，注意区分）。
- **首次请求弹授权框**：属于 VS Code 语言模型访问同意流程，允许一次即可。
- **面板里出现两条相同问答**：镜像注入恰好晚于 2 秒回退定时器（面板繁忙时可能出现），属已知边角，不影响设备侧。
