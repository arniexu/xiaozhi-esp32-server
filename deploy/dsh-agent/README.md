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
* **只转发最后一句话**：多轮上下文由 agent 自己的会话记忆负责，服务端 dialogue/记忆不再
  回灌——避免两套记忆互相打架。
* **只念正文**：`agent_message_chunk` 的文本才进 TTS，思考过程、工具调用一律丢弃。
* **权限请求自动应答**：ACP 的 `session/request_permission` 按 `permission` 配置自动选
  放行/拒绝选项，不会卡住。
* **兜底**：agent 超时/崩溃/空回复时播报 `fallback_reply`，并把该设备的会话丢弃重建。

## 实测延迟（开发机，deepseek-flash）

| 场景 | 首字延迟 | 说明 |
|---|---|---|
| 冷启动第一轮 | 11–17 s | 含 node 起进程、插件装载 |
| 同会话第二轮 | ~2.8 s | 进程复用后的稳态 |

首轮偏慢，如果在意可以后续在设备连上时预热进程（见“后续可做”）。

## 自测

```bash
cd main/xiaozhi-server

# 1) 协议层：不用 DSH，用假 agent 验客户端/适配器逻辑
.venv/bin/python test/test_dshagent.py          # PASS 4/4

# 2) 真机：连本机 DSH agent，打印一条回复
.venv/bin/python test/smoke_dshagent_live.py
```

## 后续可做

* **预热**：设备连上（`hello`）时就 `session/new`，把 11 s 的冷启动挪到用户还没开口之前。
* **流式切句**：现在按 chunk 直接交给 TTS；若要更自然的停顿，可在句号/问号处切分。
* **人设收敛**：语音人设写在配置档的 `system-prompt.personaPrefix` 里，改完重启 agent 生效。
* **拒绝策略**：`permission: deny` 可以禁止 agent 自行调用工具，只让它“纯聊天”。
