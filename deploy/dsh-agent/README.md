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

## 语音链路自测（不需要麦克风）

```bash
cd main/xiaozhi-server

# 合成一句话 → 按真机协议推 opus 帧（listen start → 音频 → listen stop）
.venv/bin/python test/e2e_voice_from_text.py --text "你好，我今天有点冷"

# 只想知道云端 ASR 通不通（绕开小智服务端）
.venv/bin/python test/debug_aliyun_asr.py
```

第一个脚本通过时会打印 `[stt] 你好，我今天有点冷` 和若干 `[tts]` 句子，最后 `RESULT: PASS`。

两个坑，都是实测踩过的：

* **必须补尾部静音**。阿里云流式 ASR 靠 `max_sentence_silence`（默认 800ms）断句，
  句子结束才给 `SentenceEnd`；只推语音帧然后立刻 `listen stop`，永远等不到识别结果。
  真实设备是一直在送帧的（没人说话也在送静音），脚本里用 `--tail 2.0` 复现这一点。
* **没配代理时要显式关掉环境代理**。公司网常见 `socks_proxy=socks://…`，websockets
  会拿它当代理然后报 `isn't a valid proxy: scheme`；`aliyun_stream.py` 现在没配
  `proxy` 时会显式传 `proxy=None`，报错从“莫名其妙的代理错误”变成“连接超时”，好排查。

## elder_helper 的 web UI（3081）：大字号 + 请求实时日志

插件源码：[deploy/dsh-agent/elder-ui/index.mjs](elder-ui/index.mjs)，挂在
`~/.dsh/profiles/elder_helper/cordis.patch.yml`：

```yaml
- insert:
    - id: elder-ui
      name: file:///home/xuqj/.dsh/plugins/elder-ui/index.mjs
```

两件事：

1. **请求实时打印**：挂 `agent/pre-step`，每次推理前把最后一条 user 消息写到
   `~/.dsh/logs/elder-prompts.log`，同时打到 dsh 进程 stdout。
   ```
   [07:55:38] 8722e99f 用户: 今天外面天气怎么样
   ```
   看实时流：`tail -f ~/.dsh/logs/elder-prompts.log`
2. **老人友好 CSS**：通过 `webServer.tapIndex` 注入 `<style data-elder-ui>`。
   样式放在 `elder-ui/elder-ui.css`，插件**每次请求现读**，改完刷新页面就生效（不用重启）。
   现状：正文 20px / 行高 1.85（原来是 14.7px）、用户气泡 19px、输入框 18px、
   按钮最小高度 2.5rem、侧边栏 15px。
   注意 DSH 的组件用 CSS Modules 哈希类名（`_markdown_1ypvv_5` 这种），选择器要用
   `[class*="_markdown_"]` 这类子串匹配——第一版按 `[class*="message"]` 写，一个都没命中，
   看起来像"UI 没变"。

> 注意：`agent/pre-step` 是 **waterfall** 事件，处理函数必须 `return next()`；
> 只写副作用不调用 next 会把推理链打断，页面报
> `This turn failed: Cannot read properties of undefined (reading 'kind')`（已被这个坑坑过）。

启动与查看：

```bash
cd /tmp && setsid nohup dsh --profile elder_helper --port 3081 \
  > ~/.dsh/logs/elder-web.log 2>&1 < /dev/null &
grep -o 'http://127.0.0.1:3081/?token=[A-Za-z0-9_-]*' ~/.dsh/logs/elder-web.log | tail -1
tail -f ~/.dsh/logs/elder-prompts.log      # 看收到的话
```

## 人设：老人陪伴助手「小安」

约束正文在 [persona/elder-persona.md](persona/elder-persona.md)，分六块：面对的是谁、怎么说话、
怎么想事、怎么办事、安全边界、绝对不要。要点：

- **说话**：一次两三句、先说最要紧的、先接话再办事、一次只问一个问题、给两个选项比开放式提问好、重要的事复述确认、不催不纠正口音。
- **想事**：先想他方不方便（天气/饭点/腿脚）、记不记得、做不做得到、愿不愿意、会不会担心。
- **办事**：先问清再动手（谁/何时/在哪/要不要人陪），能落地就落地（查天气、定提醒、记事情），复杂操作拆成一步一句，办不成直说。
- **边界**：不诊断不劝停药；胸痛/喘不上气/说话不利索/摔倒起不来 → 直接让他打 120 或叫家人；不推销不诱导消费；不打听隐私；不冒充亲人。

装到两处（`apply-persona.py` 幂等执行）：

```bash
python3 deploy/dsh-agent/apply-persona.py            # 两个都装
python3 deploy/dsh-agent/apply-persona.py --only web # 只装 web 档
```

| 档 | 落点 | 说明 |
|---|---|---|
| `elder_helper_acp`（小智语音） | `system-prompt.personaPrefix` | 不加载任何 AGENTS.md |
| `elder_helper`（web UI 3081） | `preset-standard.plugins.persona.prefix` | preset 的 persona 会 shadow 部署级人设，所以整列替换 preset 的 plugins（32 项，脚本自动从 `dsh --dump-config` 取当前版本，**dsh 升级后重跑一次**） |

装完要重启对应实例：web 档重启 3081；语音档在下一条连接时自动加载。

实测（同一句话："我一个人在家，腿有点疼，也不想麻烦孩子"）：

- web：`哎哟，腿疼可别硬撑着。一个人在家也别总觉着麻烦孩子，这事儿咱先自己看明白。` / `我想先问一句：您是走路的时候疼，还是坐着不动也疼？`
- 语音档：`哎哟，腿疼可别硬撑着，先坐下歇会儿。` / `我想先问一句：腿疼是走路的时候才疼，还是坐着不动也疼？`

## OTA 下发的 websocket 地址：回显设备用的 host

设备连服务器前会先请求 OTA，服务器把 websocket 地址回给它。老逻辑是按**服务器自己的网卡**算
（`ws://10.112.230.11:8010/...`），于是经 SSH 隧道/反向代理进来的设备会被指回服务器。

现在改成**回显设备访问 OTA 时用的 host**，优先级：

1. `server.websocket` 显式配置（写死了就用它，包含"你的"占位符则视为没配）；
2. `server.websocket_echo_host`（默认 `true`）→ 用请求的 `Host` 头；
3. 服务器本机 IP 兜底。

实测（同一台服务器）：

```bash
curl http://10.112.230.11:8003/xiaozhi/ota/                      # → ws://10.112.230.11:8010/xiaozhi/v1/
curl -H 'Host: 192.168.1.50:8003' http://10.112.230.11:8003/xiaozhi/ota/   # → ws://192.168.1.50:8010/xiaozhi/v1/
```

所以设备只要**OTA 地址填的是隧道侧的 Windows IP**，拿到的 websocket 地址也会是那个 IP，
不用在服务器上写死。想保持旧行为：`server.websocket_echo_host: false`。

## 记忆体：小智专用 Context Recall 实例（127.0.0.1:8877）

```bash
bash deploy/dsh-agent/start-xiaozhi-cr.sh      # 数据固定在 ~/.local/share/xiaozhi-cr
```

**为什么单独一个实例**：小智的记忆不能和别人项目的知识库混在一个库，也不能放 `/tmp`
（之前 `service_url` 指向 `/tmp/xiaozhi-cr-test`，重启机器就没了）。

**配置（`data/.config.yaml`）**：

```yaml
Memory:
  context_recall:
    service_url: http://127.0.0.1:8877
    workspace_id: xiaozhi
    llm: DeepSeekLLM      # ← 关键：组织/总结必须用能吐 JSON 的 API 模型
```

> `llm` 留空会退回**主 LLM**（也就是陪伴 agent）。实测后果很隐蔽：agent 不会吐 JSON，
> 组织失败 → 静默降级成"原始会话记录"入库，检索出来全是
> `会话记录 xiaozhi:xxx`，等于没记忆。日志特征是
> `组织 LLM 返回无法解析为 JSON，降级零 LLM 最小节点`。

**踩过的第二个坑**：`_save_and_close` 保存记忆前会 `init_memory(llm=self.llm)` 重新绑定，
把专用 LLM 又覆盖回主 LLM。已修：连接上记住 `memory_llm`，保存时用它。

**注入链路**：`<memory>` 随会话首句带给 agent（和 `<context>` 一起），并过滤掉
"会话记录"这类原始转写、去重、限 400 字——否则等于往 prompt 里灌噪声。

**实测**：先聊 3 轮喂进事实（王秀兰 / 孙子豆豆 / 腿疼半个月），断开后**新会话**问
「你还记得我孙子叫什么吗」→ `记着呢，您孙子叫豆豆，每个周末来看您`。
改之前同样的问题只能答「这个我还真不知道」。

**性能**：单次召回 `POST /v1/search` 实测 **0.08–0.14 s**，相对一轮 2 s 的对话可以忽略；
它不是延迟瓶颈，瓶颈在 agent 推理与工具调用（已经通过"别重复查工具"把天气类从 12 s 压到 2 s）。

## 本地 TTS（sherpa-onnx）：把每句的 0.5–1.5 s 压到 0.1 s

Edge TTS 每句都要走一次 WSS 握手（公司网走代理，实测 0.5–1.5 s，偶尔 403）；
sherpa-onnx 在本机 CPU 上离线合成，短句 **90–180 ms**。

```bash
# 1) 模型（31 MB，中文 aishell3，8kHz）
mkdir -p ~/.cache/xiaozhi-tts && cd ~/.cache/xiaozhi-tts
curl -L -O https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-icefall-zh-aishell3.tar.bz2
tar xjf vits-icefall-zh-aishell3.tar.bz2
```

```yaml
selected_module:
  TTS: SherpaTTS
TTS:
  SherpaTTS:
    type: sherpa
    model_dir: ~/.cache/xiaozhi-tts/vits-icefall-zh-aishell3
    speaker: 0
    speed: 1.0
    num_threads: 2
```

**短语缓存 + 预合成**（`core/providers/tts/base.py` / `connection.py`）：

- `to_tts` 按 (provider, voice, text) 缓存 opus 结果，重复句子直接命中；
- 连接建立后后台把 `tts_prewarm_texts`（默认「我看看啊。」「好嘞。」）预合成进缓存。

实测（同一句）：

| 路径 | 耗时 |
|---|---|
| Edge 首次合成 | ~500–1500 ms |
| sherpa 首次合成 | **92–176 ms** |
| sherpa 命中短语缓存 | **0 ms** |

> 取舍：aishell3 是 8 kHz（听起来像电话），胜在 31 MB / 90 ms。
> 要更自然可换 `vits-melo-tts-zh_en`（~163 MB，22 kHz），合成会慢一些但仍远快于 Edge。
