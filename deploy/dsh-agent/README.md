# 小智 ↔ DSH agent（语音→文本→agent→文本→语音）

把小智设备收到的语音，经 ASR 转成文本后**直接交给本机 DSH agent**，由 agent 组织回复，
再交回小智服务端做 TTS 播报。

```
设备麦克风
   │ 音频（websocket）
   ▼
xiaozhi-server  ──ASR──▶  文本
   │                        │
   │                        ▼
   │            DshAgentLLM（core/providers/llm/dshagent）
   │                        │ ACP / JSON-RPC over stdio
   │                        ▼
   │            dsh --profile elder_helper_acp
   │                        │ 组织回复（可带自己的工具/记忆）
   │                        ▼
   └────────── TTS ◀── 回复文本
                  │
                  ▼
              设备扬声器
```

## 为什么走 ACP

`dsh` 的 ACP 应用（`@deepseek-ai/dsh-acp-app`）就是给自动化用的入口：stdin/stdout 上跑
JSON-RPC，`initialize → session/new → session/prompt` 一条链路，回答以
`session/update`（`agent_message_chunk`）流式返回。相比“每条语音起一次 `dsh headless`”，
ACP 能常驻一个进程、保留会话记忆，只付一次冷启动成本。

## 安装

```bash
bash deploy/dsh-agent/install.sh
```

它做三件事（幂等，重复执行只覆盖自己的文件）：

1. 建配置档 `~/.dsh/profiles/elder_helper_acp/`（`dsh-base` + `dsh-acp-app`，模型与
   `elder_helper` 对齐：`deepseek-flash` + `reasoningEffort: max`）；
2. **不加载任何 AGENTS.md / CLAUDE.md**（含 `~/.dsh` 那份编程约束）——那些规则是给写代码的
   会话用的，混进语音回复既慢又跑题；
3. 用 `dsh --profile elder_helper_acp --dump-config` 做一次组合校验。

`elder_helper`（web 版，人的入口）完全不受影响。

## 服务端配置

```yaml
selected_module:
  LLM: DshAgentLLM
  # DSH 不接管设备指令；音量/音乐/退出交给独立的小模型识别
  Intent: intent_llm

LLM:
  DshAgentLLM:
    type: dshagent
    command: dsh --profile elder_helper_acp
    workspace: ~/.dsh/elder-workspace   # agent 会话 cwd，必须是绝对路径
    timeout: 120          # 单次问答总超时（首轮含进程启动）
    chunk_timeout: 60     # 单条增量之间的最长静默
    idle_timeout: 1800    # 设备空闲多久回收 agent 进程
    permission: allow     # 语音场景没人点确认：allow 全放行 / deny 全拒
    fallback_reply: 抱歉，我这边暂时连不上，等会儿再问一次好吗？

Intent:
  intent_llm:
    llm: DeepSeekLLM     # 别留空：留空会退化成用 DshAgentLLM 做意图识别
```

> `data/.config.yaml`（运行时覆盖，已被 .gitignore）优先于 `config.yaml`；
> 部署机上改前者。

## 行为说明

* **一台设备一个常驻 agent 进程**：`session_id` 作键，首次说话建进程，空闲 `idle_timeout`
  回收；进程挂了下次自动重建。
* **连接即预热**：连接建立（`_initialize_components`）后立刻在后台线程 `session/new`，
  把冷启动挪到用户开口之前；同一设备并发预热/请求只起一个进程。
* **只转发最后一句话**：多轮上下文由 agent 自己的会话记忆负责，服务端 dialogue/记忆不再
  回灌——避免两套记忆互相打架。
* **只念正文**：`agent_message_chunk` 的文本才进 TTS，思考过程、工具调用一律丢弃。
* **权限请求自动应答**：ACP 的 `session/request_permission` 按 `permission` 配置自动选
  放行/拒绝选项，不会卡住。
* **兜底**：agent 超时/崩溃/空回复时播报 `fallback_reply`，并把该设备的会话丢弃重建。

## 实测延迟（开发机，deepseek-flash）

| 场景 | 耗时 | 说明 |
|---|---|---|
| agent 会话就绪（预热） | 5–11 s | 连接后后台完成，不占用户等待 |
| 端到端首轮首帧（预热完成后再开口） | ~8.5 s | 含意图识别 + agent 推理 + TTS 首帧 |
| 端到端第二轮首帧（同连接） | ~4.1 s | 进程与会话复用后的稳态 |
| 端到端首帧（含天气类工具调用） | ~27 s | agent 自己查了天气，大头不在转接 |

转接本身的开销很小，延迟主要来自 agent 的推理与工具调用。

## 自测

```bash
cd main/xiaozhi-server

# 1) 协议层：不用 DSH，用假 agent 验客户端/适配器逻辑
.venv/bin/python test/test_dshagent.py          # PASS 5/5（含预热）

# 2) 真机：连本机 DSH agent，打印一条回复
.venv/bin/python test/smoke_dshagent_live.py

# 3) 端到端：伪装设备连服务端，listen/detect 带 text 绕开 ASR，验证到 TTS 音频帧
.venv/bin/python test/e2e_text_to_voice.py --text "你好，我今天有点冷，想喝点热的"
```

第 3 项通过的样子：`[stt]` 回显 → `[tts]` 打印 agent 回复（会按句分段）→ 每轮有音频帧；两轮实测 8.5 s / 4.1 s 首帧。

> TTS 依赖：`edge_tts>=7.3.1`。7.2.x 会稳定拿到 403 Invalid response status（本机 2026-10-31
> 实测 7.2.8 全挂、升 7.3.1 立即恢复），requirements.txt 已改。

## 后续可做

* **流式切句**：现在按 chunk 直接交给 TTS；若要更自然的停顿，可在句号/问号处切分。
* **人设收敛**：语音人设写在配置档的 `system-prompt.personaPrefix` 里，改完重启 agent 生效。
* **拒绝策略**：`permission: deny` 可以禁止 agent 自行调用工具，只让它“纯聊天”。
* **降时延**：首帧 27 s 主要花在 agent 的推理/工具调用上，可考虑让它对该场景少调工具。

## 排障：能连上但语音没反应

**1) 服务端 `Invalid port: ':1]'`（本次踩到）**

启动日志里若出现 `实例化组件失败: Invalid port: ':1]'`，说明环境变量 `NO_PROXY` 里写了
带方括号的 IPv6（如 `[::1]`）：httpx 0.27 建代理挂载表时解析不了，于是**任何在连接初始化阶段
创建 httpx/OpenAI 客户端的组件**都会炸——`intent_llm` 配的独立 LLM 就是典型。异常被
`_initialize_components` 吞掉后，意图识别/上报线程/提示词增强全部被跳过，表现为：
**WebSocket 能连上、文字聊天正常，但对着说话没有任何反应**。

`app.py` 启动时会自动把 `NO_PROXY` 规范化（去掉方括号条目、保留 `::1`）并打一条 WARNING：

```
NO_PROXY 含 httpx 无法解析的 IPv6 写法（如 [::1]），已规范化为: localhost,127.0.0.1,::1
```

看到这条且没有 `实例化组件失败`，就说明修好了。

**2) 浏览器拿不到麦克风**

`getUserMedia` 只在**安全上下文**里可用：`https://` 或 `http://localhost`。
用 `http://<服务器IP>:8901` 打开测试页时，`navigator.mediaDevices` 直接是 `undefined`，
页面再怎么点也不会录音（文字聊天不受影响）。三种解法：

* 用 `http://localhost:8901` 打开（SSH 转发 `-L 8901 -L 8010` 两个端口）；
* Edge/Chrome 打开 `edge://flags/#unsafely-treat-insecure-origin-as-secure`，把
  `http://10.112.230.11:8901` 加进白名单；
* 直接用真机，绕开浏览器限制。
