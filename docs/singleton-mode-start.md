# 单例模式启动手册（Raspberry Pi 5）

> 适用前提：Pi 侧依赖已装好（`docs/singleton-mode-deploy.md` §1–§4 已执行完）。
> 本文只回答三件事：**怎么启动、怎么确认起来了、起不来怎么办。**
> 设计依据：`docs/singleton-mode-plan.md` §2/§3 ｜ 验收：`main/xiaozhi-server/scripts/run-acceptance.sh`

## 0. 启动前 30 秒检查

| # | 检查项 | 命令 | 期望 |
|---|---|---|---|
| 1 | xiaozhi venv | `ls main/xiaozhi-server/.venv/bin/python` | 存在 |
| 2 | 运行配置 | `ls main/xiaozhi-server/data/.config.yaml` | 存在（由 `config_singleton.yaml` 复制并填好密钥） |
| 3 | CR venv | `ls <knowledge-agent-service>/.venv/bin/python` | 存在 |
| 4 | Pi 局域网 IP | `hostname -I` | 如 `192.168.1.50`（设备固件要填） |
| 5 | 端口空闲 | `ss -ltn \| grep -E ':(8000\|8003\|8765)'` | 无输出 |

## 1. 启动顺序（CR 先，xiaozhi 后）

两个服务都是**用户级 systemd**（无需 root、无需登录会话）：

```bash
# 1) 记忆服务 Context Recall（仅监听 127.0.0.1:8765，不暴露局域网）
systemctl --user start knowledge-agent-service
curl -s http://127.0.0.1:8765/health          # 期望返回健康状态

# 2) 对话服务 xiaozhi-server（8000 = WebSocket，8003 = HTTP）
systemctl --user start xiaozhi-server
```

> 为什么要先 CR：xiaozhi 不阻塞等待 CR——CR 不可达时走**空记忆降级**（对话照常，召回为空）。
> 先起 CR 可避免开机后首轮对话"记忆缺失"。

> 首次安装时：CR 的 `install-user-service.sh` 会 `enable --now`（自动启动）；
> xiaozhi 的 `install-singleton-service.sh` 只 `enable`（不自动启动），**首次必须手动 start**。

## 2. 启停速查

| 操作 | xiaozhi-server | knowledge-agent-service |
|---|---|---|
| 启动 | `systemctl --user start xiaozhi-server` | `systemctl --user start knowledge-agent-service` |
| 停止 | `systemctl --user stop xiaozhi-server` | `systemctl --user stop knowledge-agent-service` |
| 重启（改配置后） | `systemctl --user restart xiaozhi-server` | `systemctl --user restart knowledge-agent-service` |
| 状态 | `systemctl --user status xiaozhi-server` | `systemctl --user status knowledge-agent-service` |
| 实时日志 | `journalctl --user -u xiaozhi-server -f` | `journalctl --user -u knowledge-agent-service -f` |
| 最近 200 行 | `journalctl --user -u xiaozhi-server -n 200 --no-pager` | 同左（换单元名） |

## 3. 启动成功判据（三看）

1. **状态**：`systemctl --user is-active xiaozhi-server` → `active`
2. **端口在听**：`ss -ltnp | grep -E ':(8000|8003|8765)'` → 8000/8003 由 venv 内 Python 持有，8765 由 CR 持有
3. **日志无雷**：`journalctl --user -u xiaozhi-server -n 50 --no-pager`
   - 不应出现 `Traceback`、`Address already in use`
   - 应看到 WebSocket 服务在 8000 启动的日志

**前台调试启动**（排查启动类问题的备用姿势，Ctrl+C 即停）：

```bash
cd main/xiaozhi-server && .venv/bin/python app.py
```

## 4. 设备端联调（Pi 到手首次验证）

1. 固件烧录：WS 地址 = `ws://<Pi 的局域网 IP>:8000/xiaozhi/v1/`（直连，可跳过 OTA 发现）
2. 正常寒暄，**累计 ≥3 轮用户发言**再断开（组织门槛 `Memory.context_recall.min_user_turns: 3`）
3. 看保存日志：期望出现快照导入结果（`imported_memories` / `nodes` / `edges`）
4. 重连后提问验证召回是否命中；本地 raw turns 证据在 `main/xiaozhi-server/data/context_recall`

## 5. 日常运维

- 改 `data/.config.yaml` → `systemctl --user restart xiaozhi-server`
- 改 CR 配置 → `systemctl --user restart knowledge-agent-service`
- 更新代码 → `git pull` →（依赖有变时 `pip install -r requirements.txt`）→ 重启对应服务
- **开机自启核对**：`loginctl show-user $USER | grep Linger` → `Linger=yes`；
  `systemctl --user is-enabled xiaozhi-server` → `enabled`（CR 同）
- **备份**：`~/.local/share/knowledge-agent-service`（CR 数据）+
  `main/xiaozhi-server/data/context_recall`（raw turns 证据）

## 6. 验收复跑（升级/改动后建议）

```bash
bash main/xiaozhi-server/scripts/run-acceptance.sh
# 通过标准：3 项全过（compileall ✓ / provider 自测 60/60 ✓ / CR 契约冒烟 7/7 ✓）
# 默认打 127.0.0.1:8765，可用 CR_SMOKE_URL 覆盖（注意第 3 项会写入固定测试数据）
```

## 7. 启动故障速查

| 现象 | 常见原因 | 处置 |
|---|---|---|
| `Address already in use`（8000/8003） | 端口被占（开发机常见：pyserver） | `ss -ltnp \| grep ':8000'` 找到并停掉；或改 `server.port` |
| 服务反复 `activating (auto-restart)` | 配置 YAML 语法错 / 密钥缺失 | 看日志首个 `Traceback`；核对 `data/.config.yaml` 缩进与必填密钥 |
| 日志报找不到 `app.py` | venv 或 WorkingDirectory 不对 | 重跑 `bash main/xiaozhi-server/scripts/install-singleton-service.sh` |
| 对话正常但召回为空 | CR 未启动 / `service_url` 错 / workspace 不匹配 | `curl -s http://127.0.0.1:8765/health`；核对 `Memory.context_recall` 段 |
| ASR 报 `InvalidTimeStamp.Expired` | 系统时钟偏差 >15 分钟 | `timedatectl` 校准（或等 NTP 同步） |
| 外呼云服务失败（特定网络） | 出网需 HTTP 代理 | 家庭部署直连即可；公司网络需给 provider 配 `proxy`（见 deploy 手册附录） |
| ASR/TTS 模块缺失 `ffprobe` | 未装 ffmpeg | `sudo apt install -y ffmpeg` |

## 附：开发机（公司网络）差异

- 出网代理：`ASR.AliyunStreamASR.proxy` / `TTS.EdgeTTS.proxy`（**树莓派家庭网络删除该行即直连**）
- `websockets >= 15` 才支持代理参数；`edge-tts >= 7.2`
- 经 VS Code 端口转发的页面测试，断开后服务端约 **2–3 分钟**空闲超时才感知并保存；设备直连无此延迟
