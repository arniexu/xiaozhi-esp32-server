# 单例模式设计方案（单设备 · 树莓派 5 · Context Recall 记忆）

> **定稿**：2026-09-20 ｜ **状态**：设计闭环，待实现与部署
> **决策档案**：Continuity 决策库（`.continuity/decisions.jsonl`，2026-09-20 系列条目）
> **范围**：后端只服务一台小智设备（单例模式）；**资源与算力最大节省**为第一目标

## 1. 已定决策摘要

| 维度 | 决策 |
|---|---|
| 部署形态 | 单例模式：不部署 manager 栈（manager-api / manager-web / MySQL / Redis 均不部署） |
| 部署机 | Raspberry Pi 5 **4GB**（已确认；2GB 存在但余量薄，不采用） |
| 操作系统 | Raspberry Pi OS **Lite 64-bit**；首选 Bookworm（Python 3.11），Trixie（3.13）需先验证依赖兼容 |
| 网络 | 家庭部署：出网（云服务）+ 局域网（设备 ↔ Pi）；不依赖办公网络 |
| LLM | **全部云端**（默认智谱 glm-4-flash 免费款；稳定后建议 DoubaoLLM） |
| ASR | **云端流式**（`aliyun_stream` / `doubao_stream` 二选一） |
| TTS / VAD | EdgeTTS（云端免费）；Silero VAD（本地轻量） |
| 记忆 | **Context Recall 本地实例**（knowledge-agent-service，SQLite-only 起步，graph-off） |
| 角色 | 静态单角色；角色协议扩展（设备端携带 role）后置，等固件联调时定 |
| 需求边界 | 无控制台；改配置 = 改 `data/.config.yaml` + 重启 |

## 2. 总体架构

```mermaid
flowchart LR
    D["小智设备 ESP32"] -- "WebSocket ws://pi:8000" --> X["xiaozhi-server<br/>Pi 5 · Python"]
    X -- "HTTPS" --> C1["云端 LLM<br/>ChatGLM / Doubao"]
    X -- "WSS 流式" --> C2["云端 ASR<br/>阿里 / 火山"]
    X -- "HTTPS" --> C3["EdgeTTS"]
    X -- "HTTP 127.0.0.1:8765" --> CR["knowledge-agent-service<br/>Pi 5 · SQLite-only"]
    CR -. "Phase 2 可选" .-> SG["SQLite 图层 adapter"]
```

Pi 上两个 user 级 systemd 服务：

- `xiaozhi-server`：8000（WebSocket）、8003（HTTP：OTA / 视觉 / 审批端点）
- `knowledge-agent-service`：127.0.0.1:8765（仅本机回环，不暴露局域网）

## 3. 部署形态（Pi 侧）

- **OS**：Raspberry Pi OS Lite 64-bit（无桌面）；官方 Imager 烧录时预置 WiFi / SSH / 用户
- **硬件**：官方 27W USB-C 电源、主动散热；存储建议 NVMe（M.2 HAT+），底线 A2 级 32GB+ SD
- **服务**：两个 user 级 systemd + linger（开机自启，无需登录）；CR 用自带 `scripts/install-user-service.sh`
- **已知修正项**：
  - `main/xixaozhi-server.service`：**移除 `Requires=manager-web.service`**、修正 WorkingDirectory/User、ExecStart 改用 venv 解释器
  - 依赖裁剪（可选）：不启用 FunASR 时可从 `requirements.txt` 移除 torch/funasr/modelscope 等（省磁盘，需回归验证）
- **备份**：定期备份 CR 数据目录 `~/.local/share/knowledge-agent-service`

## 4. 记忆集成（Context Recall）

### 4.1 服务事实（已按代码核实）

- **API**：`GET /health`、`/v1/stats`、`/v1/capabilities`；`POST /v1/search`、`/v1/import/{extension,continuity,documents}`、`/v1/graph/*`
- **存储**：`memory_units`（raw / candidate / active + FTS5）+ 向量库 +（可选）Neo4j；**turns/sessions 不落库**（仅用于 evidence 解析与 scope 映射）
- **可检索门槛**：`status='active' AND memory_kind='memory' AND evidence 非空`
- 服务不调模型（组织由调用方完成）；scope 取自快照 `session.workspaceId`

### 4.2 保存路径（v2：xiaozhi 侧 LLM 组织）

1. 会话结束触发（同一连接内 **≥3 轮用户发言**才组织；长会话中途快照）
2. 本地保存 raw turns（证据源，服务端不落 turns）
3. 调组织 LLM（独立配置，可用便宜款）→ 按 organizer 规范产出：
   - 1 个会话摘要节点 + **≤8 知识节点 + ≤12 边**
   - 字段：kind / label / summary / confidence / tags / aliases；**evidenceTurnIds 必填**；status=active；确定性 ID（幂等）
4. 构造快照 `{session(workspaceId='xiaozhi'), turns, nodes, edges}` → `POST /v1/import/extension`
5. **降级链**：LLM 失败 / 坏 JSON → 零 LLM 最小节点（原文截断）；网络失败 → 本地 outbox 重试

### 4.3 查询路径

- 每轮对话前 `POST /v1/search`（`workspace_id=xiaozhi`、min_similarity≈0.35、limit≈6、timeout≈2.5s）
- 服务不可达 / 超时 → **空记忆降级**，对话不阻塞
- 结果组装为短文本注入对话（条数与长度受控，适合语音场景）

### 4.4 治理与隔离

- **workspace 隔离**：`xiaozhi`（可配置；session id 带设备号，预留多设备）
- 服务 additive **无删除**："遗忘" = 状态化（superseded 后不可检索）；本地 raw 可自行删除
- 联调测试数据以固定前缀 id 标记（与工程库物理同库、逻辑隔离）

## 5. 实现清单（xiaozhi 侧）

| 文件 / 模块 | 内容 |
|---|---|
| `core/providers/memory/context_recall/`（新） | provider：`save_memory`（快照 + 组织）/ `query_memory`（搜索）/ `init_memory`（scope） |
| 组织模块（新） | `organizer.ts` 规范移植（TS → Python）：prompt、JSON 容忍解析、确定性 ID、数量上限 |
| 快照 / outbox（新） | 快照构造、失败重试队列、本地 raw turns 存储 |
| `config.yaml` / `data/.config.yaml` | `Memory` 配置块 + `selected_module.Memory` 切换 |
| `connection.py` | 复用现有 `_save_and_close` 异步模式，挂接保存流程（不改接口契约） |

## 6. 分阶段计划与验收

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **Phase 0 联调** | 一次性 CR 测试实例（空数据目录、独立端口）+ 伪造快照脚本 | 导入 → `/v1/search` 命中 → 幂等 → workspace 隔离 → 降级 |
| **Phase 1 实现** | provider + 组织 + 快照 + outbox | 本机对 CR 实例端到端；真实对话可召回 |
| **Phase 2 Pi 部署** | OS + 双服务 + 联调脚本复跑 | pip aarch64 wheels 齐全；内存峰值 / 温度 10 分钟稳定；设备端到端语音 |
| **Phase 3 可选** | CR 侧 SQLite 图层 adapter；图算法（PPR / 社区发现） | 组织层上线后按需 |

## 7. CR 侧改动（Phase 2，短周期 feature 分支）

- `SqliteGraphStore` adapter（接口固定 8 方法：`health / search / upsert / entity_catalog / upsert_documents / mentions / document_links / relink`）；家庭实例先实现知识实体部分
- 配置：`KNOWLEDGE_GRAPH_BACKEND=neo4j|sqlite|none`；工程实例继续 Neo4j，两实例同 main、配置区分
- 不建 fork；向后兼容 + 测试；双实例验证后合回 main

## 8. 开放项（待定）

- ~~云凭据~~：已定 DeepSeek（LLM）+ 阿里云流式 ASR（2026-09-21 联调）；智谱免费款留作备选
- 存储选型：NVMe vs SD（建议 NVMe）
- 完整模式（manager 栈）去留：决定 manager 侧角色切换改动的后续处置
- 角色协议扩展形态（hello 携带 role vs agent 消息携带）——建议 Pi 首版静态单角色

## 9. 2026-09-21 真机联调发现与处置（DeepSeek + 阿里云 ASR + CR@8765）

**链路结论**：组织/导入真机通过（真实 DeepSeek：nodes=5、edges=2、fallback=False）；整句问句召回经增强后全部命中。

**发现**：
1. CR 词法门对 CJK 是"连续子串 AND"：查询每个连续片段必须逐字出现——`儿子` 命中、`我儿子叫什么名字` 必漏；停用词剔除还会把手邻内容字粘连成不存在字面（"早餐吃"）。
2. 语义通道要求调用方随请求携带 `embedding`（`source_kind='knowledge'`）；xiaozhi 侧无嵌入器 → 实际不参与。
3. `workspace_id=''` 单元全库参与检索（`memory_store._match` 显式包含）——单字候选"光"曾把 continuity 历史决策拉进客厅灯检索。
4. graph 通道返回的图实体**无 workspace 字段**（实例启用 Neo4j 时其它项目实体进入检索，实测"今天天气"拉进 P1 缺陷决策）；且该实例 `/v1/import/extension` 会把导入同步进 Neo4j（联调合成数据已入图谱 30 节点/40 边，用户决定暂留；清理脚本见 knowledge-agent-service `scripts/cleanup-xiaozhi-test-entities.py`，`--apply` 执行）。

**处置（xiaozhi 侧已实现）**：两阶段检索（拆词多路 + 二字组/单字兜底）+ **严格 workspace 白名单**（只认本 workspace；无字段/空值/异 ws 一律丢弃）+ 按路序合并去重；自测 81/81；真机电池 16/16（13 条整句问句全部**直连命中**、3 条负例全部正确返回空）。

**加强版验证（`test/test_context_recall_live_hard.py`，对 graph-off 实例 8876）**：3 段会话（含更正/变更/设备杂音）+ 26 条查询矩阵——直连命中 18/18、负例 4/4、**噪声行 0**、时延 p95 259ms、设备杂音未入库、10 组事实全覆盖、稳定性 3×3 一致；唯一残留：**更新后旧节点并存**（爬山↔游泳实测 1 例），注入时可能新旧同现 → CR 待办 #4（supersede/近似去重）优先级上升。脚本内置安全阀：目标启用 Neo4j 时默认拒跑（防再写用户图谱）。

**标准姿势对照（extension vs xiaozhi，2026-09-21 读码判明）**：接口同为 `/v1/search`。extension 的完整姿势 = ①每次携带客户端 `embed(query)`（`vector.ts`：FNV-1a 256 维签名词袋；词=普通词+CJK 单字+双字；NFKC/小写）+ 导入时同样生成向量；②不传 `scope_fallback`（默认 `global` 跨 scope 兜底）+ `workspace_ids` 别名集；③客户端**加权重排**（`rankRetrievalResults`：semantic 1.0 / lexical 1.2 / graph 0.8，graph 要求词面重叠）——即"客户端增强"本身是标准架构的一部分。xiaozhi 偏离：①未带 embedding（semantic 恒空；**可选对齐项**：Python 复刻 embed 约 40 行 + 导入/查询接线 + 测试）；②`scope_fallback=none` + 严格白名单（单设备隔离，实测需要）；③增强更激进（拆词/二阶段兜底）。

**方向确认（2026-09-21）**：语义统一**修在 CR 侧**（flag 兼容演进：`strict_workspace` / `scope_match` 诚实化 / CJK OR 回退 / `include_graph`），不背永久 workaround；xiaozhi 客户端增强退为防御层，CR 修复落地后用 battery/hard 回归验证可安全简化。提案见 knowledge-agent-service `docs/cjk-recall-todo.md`。

**CR 侧待办**（详见 knowledge-agent-service `docs/cjk-recall-todo.md`）：CJK bigram OR 回退；空 workspace 严格隔离开关；memory 单元向量通道；跨会话近义节点去重。

---

### 附：关键外部参考（开发机路径）

- 组织规范：`knowledge-agent-extension/src/organizer.ts`（prompt / schema / 限制 / 确定性 ID）
- 数据模型：`knowledge-agent-extension/src/model.ts`（KnowledgeSnapshot / KnowledgeNode / SessionRecord / TurnRecord）
- 服务实现：`knowledge-agent-service/src/knowledge_agent_service/{api.py, memory_store.py, migration.py}`

---

## 10. 记忆质量修复：身份混淆与逐句分析（2026-09-21 晚）

**问题（真机实测）**：助手的即兴扮演人设（自编“台湾女生/现居北京/男友在字节跳动”，非系统设定、非用户要求）被组织器当作知识存储；且把助手自己的错误陈述再次入库（“用户所在地…存在矛盾，不确定”“助手提到…未经用户确认”），召回注入后模型开始混淆“用户 vs 助手”，并向用户泄露“节点”等系统词。

**根因**：① 组织器把（a）助手扮演内容、（b）对记忆的分析评论（“未确认/矛盾”）都写进了节点；② 注入端未声明“用户=对话者、助手=你自己”的身份框架。

**修复（xiaozhi 侧，四层）**：
1. **逐句语义/实体分析前置**（`organizer.ANALYZE_SYSTEM_PROMPT`）：每句一条分析项（speaker/about/type/entities/relations/fact/keep）；助手扮演一律 `assistant_roleplay & keep=false`；禁写“未确认/矛盾”类评论；
2. **接地聚合**：聚合只基于 `keep=true` 条目生成节点/边（防模型自由发挥）；分析失败自动回退旧的单次组织（兼容）；
3. **注入身份框架**（`agent-base-prompt.txt` 历史记忆段）：明确“用户”=对话者、“助手/小智”条目=你自己的角色扮演、冲突时以用户当前说法为准、禁止提及“记忆/节点”等系统词；
4. **存量防御**（`context_recall._format_hits`）：含“未经用户确认/属于单方面记忆/存在矛盾”标记的旧节点在注入时直接丢弃。

**边注入（无图谱部署的关系兜底）**：CR 仅在 graph on 时把 `edges` 写入 Neo4j，graph off（Pi 方案）会丢弃边；现由 `organizer.edges_to_units` 把边渲染成文本单元（`主体 —RELATION→ 客体`，确定性 ID 可跨会话去重）一并导入，配置项 `Memory.context_recall.inject_edges`（默认开）。

**验证**：provider 自测 85/85（新增两阶段链路/边单元/inject_edges 用例）；真实 DeepSeek 仿写污染场景：人设与元评论 0 入库，产出 5 个用户事实节点 + 4 条干净关系边（`用户 —LIVES_IN→ 上海` 等）。
