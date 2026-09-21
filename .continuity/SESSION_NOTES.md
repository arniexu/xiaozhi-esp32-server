# Session Notes

## Goals
- 单设备（单例模式）部署裁剪：确定保留/砍除组件清单、角色存放位置、资源与算力目标
- 部署目标：树莓派5（ARM64、单例模式、源码部署）

## Blockers
- 完整模式部署前置（如采用）：本机 Java/Maven 未装、当前用户不在 docker 组、8000 端口被 pyserver 占用

## Key Decisions
- 2026-09-20：单例模式=最大节省为核心；角色固化在边缘（本地 config），不部署 manager 栈。decision-1cdd4916（保留 manager-api、角色服务器下发）仅适用于完整模式
- 2026-09-20 补充：通信协议可变——角色内容可由设备端携带（hello 可选 role 字段 / agent 消息扩展）；服务器按连接应用覆盖、缺省回落静态配置；provider 密钥仍在服务器；单例仍不部署 manager 栈
- 2026-09-20 补充：记忆机制改用 Context Recall（knowledge-agent-service：/v1/search 检索 + /v1/import/extension 快照写入；门槛=active+evidence）；scope 隔离已确认；组织策略 v2=xiaozhi 侧 LLM 总结（organizer 规范）+零 LLM 兜底+本地留证据（服务端只存节点、不落 turns）
- 2026-09-20 补充：总结在设备侧（xiaozhi/Pi）执行已接受；三细节采纳（粒度≥3轮/状态 active+confidence/上限 8-12）；默认=workspace 'xiaozhi'、outbox 重试、遗忘=状态化；部署前置待办=Pi 型号/系统/SSH/网络
- 2026-09-20 补充：Pi 在家→本地 CR 实例为部署默认（直连仅联调）；OS 首选 Bookworm Lite 64-bit（或验证 Trixie）；内存定 4GB（2GB 紧）
- 2026-09-20：原有 code change 已提交（6b53c22 feat(agent)、b5c01dc chore(gitignore)）；方案落盘 docs/singleton-mode-plan.md（b590d32）；下一步=Phase 0 联调
- 2026-09-20：工具类文件入库（d790d68 vexp / dbb4d48 continuity 决策库 / c921504 agents 配置）；工作区已干净

## Session Summary（2026-09-20 收尾）
- **完成**：方案设计闭环（单例模式 / Pi5 / 全云模型 / CR 记忆集成全部定案）；代码与工具提交（6b53c22、b5c01dc、b590d32、d790d68、dbb4d48、c921504、58f9705、70cbd5e）；方案落盘 `docs/singleton-mode-plan.md`；决策全部入 Continuity；工作区干净。
- **下一步（明日）**：W1 = Phase 0 联调（CR 一次性测试实例 + 伪造快照全链路：导入/命中/幂等/隔离/降级）；可并行 W3（organizer 移植）。
- **阻塞/排除**：Pi 部署（等硬件，已排除）；组织联调需智谱 LLM key（免费款，可先注册）。
- **工期口径**：软件侧剩余 3–5 个工作日（AI 加速），约 1 周内闭环。

## 2026-09-21（新会话）
- W1 Phase 0 联调通过（smoke 脚本 7/7）；关键发现：scope_fallback 必须显式 "none"（默认 global 会跨 workspace 召回）；企业代理需绕过。
- 下一步：W2 provider 骨架 + W3 organizer 移植（可 dsh 派发）。
- W2 完成并验收（ee6bfad）：provider 六文件+测试 60/60+真实 8876 写路径 E2E 通过；connection.py 无需改动；下一步=真机联调（需 LLM key）。；CR 本地（树莓派）方案已通过（SQLite-only 起步，工程侧保持）；ASR 定案=云端流式（aliyun_stream/doubao_stream）；Neo4j 替换定案=SQLite 内建图层（先 graph-off、组织层时实现 adapter）；前期直连现有 CR 实例可接受
- 2026-09-20 补充：核实 import/extension 只落 nodes+vectors（turns 不落库）→ 快照须带零 LLM 最小节点；分支策略=Phase 1 不建分支（CR 零改动）、Phase 2 短周期 feature 分支
