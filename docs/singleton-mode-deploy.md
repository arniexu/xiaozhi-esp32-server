# 单例模式部署手册（Pi 5 / 开发机通用）

> 设计文档：`docs/singleton-mode-plan.md` ｜ 验收脚本：`main/xiaozhi-server/scripts/run-acceptance.sh`
> 本文只列"到手即执行"的步骤（开发机同样适用）。

## 0. 前置清单

- 硬件：Raspberry Pi 5 4GB；27W 官方电源；主动散热；NVMe（建议）或 A2 级 32GB+ SD
- 系统：Raspberry Pi OS **Lite 64-bit**（Bookworm 首选；Trixie 需先过验收）
- 云密钥：LLM 密钥（智谱免费款 / DeepSeek / Kimi 任一，配置见 `config_singleton.yaml` LLM 段）；火山语音 `appid/access_token`（或阿里云语音）
- 项目文件：`xiaozhi-esp32-server` 仓库 + `knowledge-agent-service` 仓库（git clone 或 rsync）

## 1. 基础环境

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip ffmpeg
python3 --version    # 期望 3.11+（Bookworm）；3.13（Trixie）需先过验收
```

## 2. xiaozhi-server（单例模式）

```bash
cd <repo>/main/xiaozhi-server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# 可选裁剪（省磁盘）：不启用 FunASR 时可移除 torch/torchaudio/funasr/modelscope —— 改动后须重跑验收
cp config_singleton.yaml data/.config.yaml
# 编辑 data/.config.yaml：选 LLM（ChatGLM/DeepSeek/Kimi/Doubao）填对应 api_key、火山语音密钥；
# 确认 Memory.context_recall.service_url
```

## 3. Context Recall 本地实例（SQLite-only，不配 Neo4j）

```bash
cd <knowledge-agent-service>
bash scripts/install-user-service.sh        # 用户级 systemd，默认 127.0.0.1:8765
systemctl --user status knowledge-agent-service
```

## 4. 安装 xiaozhi-server 服务

```bash
cd <repo>
bash main/xiaozhi-server/scripts/install-singleton-service.sh
systemctl --user start xiaozhi-server
systemctl --user status xiaozhi-server
```

## 5. 验收（原样复用，通过标准：三项全过）

```bash
bash main/xiaozhi-server/scripts/run-acceptance.sh
# 期望：1/3 compileall ✓ ；2/3 provider 60/60 ✓ ；3/3 冒烟 7/7 ✓
```

## 6. 设备端

- 固件烧录：WS 地址 = `ws://<Pi 的局域网 IP>:8000/xiaozhi/v1/`（固件直连，可跳过 OTA 发现）
- 首次对话验证：正常寒暄 → 累计 ≥3 轮用户发言 → 断开重连 → 提问验证记忆召回
  （组织 LLM 的总结质量是本步主要观察项）

## 7. 运维

- 备份：`~/.local/share/knowledge-agent-service`（CR 数据）+ `main/xiaozhi-server/data/context_recall`（证据源）
- 日志：`journalctl --user -u xiaozhi-server -f` / `-u knowledge-agent-service -f`
- 已知注意：
  - 企业代理环境需绕过 localhost（脚本内建 `trust_env=False`/空 ProxyHandler，无需处理）；
  - CR 服务 additive 无删除："遗忘"以状态化处理（superseded）；
  - 修改 `data/.config.yaml` 后：`systemctl --user restart xiaozhi-server`。

## 附：开发机（公司网络）联调备注

- **出网需 HTTP 代理**：写入 `ASR.AliyunStreamASR.proxy` / `TTS.EdgeTTS.proxy`（家庭/树莓派部署删除该行即直连）
- **`websockets` 需 >=15** 才支持代理参数（`pip install -U "websockets>=15"`；cozepy 钉 <15，启用 Coze 时需权衡）
- **`edge-tts` 需 >=7.2**（7.0.0 会被 Microsoft 403 拒绝）
- **音频转换需 `ffprobe`**（可放 `~/.local/bin`；树莓派走 `apt install ffmpeg`）
- **时钟必须准**（阿里云签名容忍 ±15 分钟；`timedatectl` 或手动校准）
- 页面测试经 VS Code 端口转发时，**断开后服务端约 2-3 分钟空闲超时才感知并保存**（转发链路不传递关闭信号）；设备直连无此延迟
