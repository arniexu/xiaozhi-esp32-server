# Session Notes - 2026-09-21

> **Collaborative workspace for you and AI**
> AI can add notes during work, you can edit them anytime.

## 🎯 Session Goals
- **完成**：方案设计闭环（单例模式 / Pi5 / 全云模型 / CR 记忆集成全部定案）；代码与工具提交（6b53c22、b5c01dc、b590d32、d790d68、dbb4d48、c921504、58f9705、70cbd5e）；方案落盘 `docs/singleton-mode-plan.md`；决策全部入 Continuity；工作区干净。
- **下一步（明日）**：W1 = Phase 0 联调（CR 一次性测试实例 + 伪造快照全链路：导入/命中/幂等/隔离/降级）；可并行 W3（organizer 移植）。
- **阻塞/排除**：Pi 部署（等硬件，已排除）；组织联调需智谱 LLM key（免费款，可先注册）。
- **工期口径**：软件侧剩余 3–5 个工作日（AI 加速），约 1 周内闭环。

## 💡 Key Decisions Made
- 2026-09-20：单例模式=最大节省为核心；角色固化在边缘（本地 config），不部署 manager 栈。decision-1cdd4916（保留 manager-api、角色服务器下发）仅适用于完整模式
- 2026-09-20 补充：通信协议可变——角色内容可由设备端携带（hello 可选 role 字段 / agent 消息扩展）；服务器按连接应用覆盖、缺省回落静态配置；provider 密钥仍在服务器；单例仍不部署 manager 栈
- 2026-09-20 补充：记忆机制改用 Context Recall（knowledge-agent-service：/v1/search 检索 + /v1/import/extension 快照写入；门槛=active+evidence）；scope 隔离已确认；组织策略 v2=xiaozhi 侧 LLM 总结（organizer 规范）+零 LLM 兜底+本地留证据（服务端只存节点、不落 turns）
- 2026-09-20 补充：总结在设备侧（xiaozhi/Pi）执行已接受；三细节采纳（粒度≥3轮/状态 active+confidence/上限 8-12）；默认=workspace 'xiaozhi'、outbox 重试、遗忘=状态化；部署前置待办=Pi 型号/系统/SSH/网络
- 2026-09-20 补充：Pi 在家→本地 CR 实例为部署默认（直连仅联调）；OS 首选 Bookworm Lite 64-bit（或验证 Trixie）；内存定 4GB（2GB 紧）
- 2026-09-20：原有 code change 已提交（6b53c22 feat(agent)、b5c01dc chore(gitignore)）；方案落盘 docs/singleton-mode-plan.md（b590d32）；下一步=Phase 0 联调
- 2026-09-20：工具类文件入库（d790d68 vexp / dbb4d48 continuity 决策库 / c921504 agents 配置）；工作区已干净

## 🚧 Blockers & Challenges
- 完整模式部署前置（如采用）：本机 Java/Maven 未装、当前用户不在 docker 组、8000 端口被 pyserver 占用

## 🔍 Attempted Approaches
<!-- No entries yet -->

## ✅ Next Steps
- 部署产物已就绪并验证（ea36e78：config_singleton.yaml / install-singleton-service.sh / run-acceptance.sh / singleton-mode-deploy.md；全量自测 3/3 通过）。待办：①智谱 key → 真机对话验证组织质量；②Pi 硬件到位 → 按 deploy 手册执行。
- 真机联调通过（DeepSeek 组织 5 节点/2 边 + CR 导入）+ 召回增强落地（359fae4：拆词多路检索，74/74，整句问句全命中）；CR 侧根治待办入库 knowledge-agent-service（13edc33）。下一步：启动 xiaozhi-server 真机语音验证（设备连 ws://10.112.229.254:8000/xiaozhi/v1/）；Pi 部署待硬件。
- 召回增强收尾（f82b03a）：两阶段检索 + 严格 workspace 白名单；电池 16/16、自测 81/81 全绿。图谱副作用：8765（Neo4j on）同步了测试实体 30 节点/40 边，用户选择暂留，清理脚本就绪（knowledge-agent-service/scripts/cleanup-xiaozhi-test-entities.py --apply）。待办：真机语音联调（建议 graph-off 实例）；Pi 部署待硬件。
- 加强版测试 hard v3 通过（d19f590）：26 条矩阵（含更新/更正/设备杂音/负例）0 失败、噪声 0、p95 259ms、稳定性 3×3 一致；唯一残留=更新旧值并存（CR 待办 #4 升级，证据 f46bc15）。后续：真机语音全链路（需设备）、长会话节点上限压力测试。

## 📝 Open Questions
<!-- No entries yet -->

---
*Last updated by AI: 2026-09-21T03:04:58.214Z*
*Last updated by User: Never*