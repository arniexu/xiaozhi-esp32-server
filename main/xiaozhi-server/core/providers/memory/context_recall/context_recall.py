# -*- coding: utf-8 -*-
"""Context Recall 记忆 provider。

设计文档：docs/singleton-mode-plan.md §4（记忆集成）/ §5（实现清单）。

职责：
- ``save_memory``（会话结束，跑在独立线程的独立事件循环里，允许同步等待）：
  本地落 raw turns → 用户发言 ≥3 轮时调 LLM 组织知识节点/边 → 构造快照 →
  ``POST /v1/import/extension``；推送失败落本地 outbox，下次重投。
- ``query_memory``（每轮对话前，跑在主事件循环，禁止阻塞）：
  ``POST /v1/search``（显式 ``scope_fallback="none"``）→ 受控长度的短文本注入 prompt。
  多路拆词检索（query_utils）：原文 + 候选片段并行查询后合并，模拟 OR 语义。
- ``init_memory``（连接建立 / 角色切换，同步接口）：记录 role_id/llm，按角色重建本地
  存储与 outbox，并尽力而为地补投历史失败快照。

配置（``config.yaml`` 的 ``Memory.context_recall``，实例化时传入的就是该块，
见 core/utils/modules_initialize.py:72-76）：``service_url`` 为空表示整体禁用。
"""

import asyncio
from datetime import datetime

from ..base import MemoryProviderBase, logger
from .cr_client import CRClient
from .organizer import fallback_minimal, organize
from .query_utils import (
    build_fallback_candidates,
    build_query_candidates,
    merge_hit_lists,
)
from .snapshot import (
    build_session,
    build_snapshot,
    dialogue_to_text,
    dialogue_to_turns,
    new_session_id,
    user_turn_count,
)
from .storage import Outbox, RawTurnStore, storage_base_dir

TAG = __name__

DEFAULT_SERVICE_URL = ""
DEFAULT_WORKSPACE_ID = "xiaozhi"
DEFAULT_MIN_SIMILARITY = 0.35
DEFAULT_LIMIT = 6
DEFAULT_TIMEOUT = 2.5
DEFAULT_MIN_USER_TURNS = 3

MAX_HIT_CHARS = 160
MAX_MEMORY_CHARS = 800


def _now_iso() -> str:
    """本地时区 ISO8601（与 W1 快照样例一致，带时区偏移）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class MemoryProvider(MemoryProviderBase):
    def __init__(self, config, summary_memory=None):
        super().__init__(config)
        # 传进来的就是 Memory.context_recall 配置块本身
        config = config if isinstance(config, dict) else {}
        self.service_url = str(config.get("service_url") or DEFAULT_SERVICE_URL).strip()
        self.workspace_id = str(
            config.get("workspace_id") or DEFAULT_WORKSPACE_ID
        ).strip()
        self.min_similarity = _as_float(
            config.get("min_similarity"), DEFAULT_MIN_SIMILARITY
        )
        self.limit = _as_int(config.get("limit"), DEFAULT_LIMIT)
        self.timeout = _as_float(config.get("timeout"), DEFAULT_TIMEOUT)
        self.min_user_turns = _as_int(
            config.get("min_user_turns"), DEFAULT_MIN_USER_TURNS
        )
        self.summary_memory = summary_memory
        # 短连接客户端：可同时被主循环与保存线程的两个事件循环使用（见 cr_client.py）
        self.client = CRClient(self.service_url, self.timeout)
        # storage 组件在 init_memory 里按 role_id 重建
        self.raw_store = None
        self.outbox = None
        self._flush_task = None

    @property
    def enabled(self) -> bool:
        """service_url 为空 → 整体禁用（查询返回空、不推送、不写 outbox）。"""
        return bool(self.service_url)

    def init_memory(self, role_id, llm, **kwargs):
        """连接建立/角色切换时调用；同步接口，不能阻塞（见 _best_effort_flush）。"""
        super().init_memory(role_id, llm, **kwargs)
        base_dir = storage_base_dir(self.role_id or "unknown")
        self.raw_store = RawTurnStore(base_dir, self.role_id)
        self.outbox = Outbox(base_dir, self.role_id)
        logger.bind(tag=TAG).debug(
            f"Context Recall 记忆初始化: role={self.role_id}, workspace={self.workspace_id}, "
            f"enabled={self.enabled}, storage={base_dir}"
        )
        self._best_effort_flush()

    def _best_effort_flush(self):
        """尽力而为地补投 outbox（不阻塞、不抛异常）。

        init_memory 是同步接口，调用点可能在异步上下文（连接建立/角色切换）也可能不在
        （测试、其它线程）。这里只做最稳妥的一件事：**有运行中的事件循环**时用
        ``create_task`` 后台补投；没有运行循环就跳过——绝不在同步上下文里
        ``run_until_complete``（那会在已有循环的线程里直接抛 RuntimeError，也会阻塞
        连接建立）。跳过的代价很小：下一次 ``save_memory`` 末尾一定会 flush。
        """
        if not self.enabled or self.outbox is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.bind(tag=TAG).debug("init_memory 无运行中事件循环，跳过 outbox 补投")
            return
        try:
            # 保存引用避免任务被 GC；flush 内部已保证绝不抛出
            self._flush_task = loop.create_task(self.outbox.flush(self.client))
        except Exception as e:  # noqa: BLE001 - 补投失败不影响连接建立
            logger.bind(tag=TAG).debug(f"outbox 后台补投创建失败（忽略）: {e}")

    async def query_memory(self, query: str) -> str:
        """检索记忆并格式化为注入 prompt 的短文本；失败/空结果返回 ""。

        两阶段检索（query_utils）：首轮"原文 + 拆词候选"；全空时用二字组/单字
        兑底再搜一轮，模拟 OR 语义。背景：CR 词法门对 CJK 是"连续子串 AND"
        （整句必漏，真机实测）；停用词剔除还会把内容字粘连成不存在的字面。
        命中还要过 workspace 过滤：CR 会把 ws='' 单元并入任意检索（实测噪声）。
        """
        if not self.enabled or not query:
            return ""
        try:
            hits = await self._search_candidates(build_query_candidates(query))
            if not hits:
                fallback = build_fallback_candidates(query)
                if fallback:
                    hits = await self._search_candidates(fallback)
        except Exception as e:  # noqa: BLE001 - 检索异常必须降级为空记忆
            logger.bind(tag=TAG).debug(f"记忆检索异常（降级为空记忆）: {e}")
            return ""
        try:
            return self._format_hits(hits)
        except Exception as e:  # noqa: BLE001 - 格式化异常同样降级
            logger.bind(tag=TAG).debug(f"记忆格式化异常（降级为空记忆）: {e}")
            return ""

    async def _search_candidates(self, candidates):
        """并行检索一组候选并合并（按路序去重 → 本 workspace 过滤 → 限量）。"""
        results = await asyncio.gather(
            *(
                self.client.search(
                    candidate, self.workspace_id, self.limit, self.min_similarity
                )
                for candidate in candidates
            ),
            return_exceptions=True,
        )
        merged = merge_hit_lists([item for item in results if isinstance(item, list)])
        return self._in_scope_hits(merged)[: self.limit]

    def _in_scope_hits(self, hits):
        """只保留**声明了本 workspace** 的命中（严格白名单）。

        实测噪声来源（真机电池）：
        - CR 把 ws='' 的单元并入任意 workspace 检索（memory_store._match 显式包含）；
        - graph 通道返回的图实体**没有 workspace 字段**（服务端接了 Neo4j 时，
          其它项目的历史决策会被带进来）。
        单设备场景两者都是噪声 → 只认 workspace_id 等于本 workspace 的条目；
        无字段/空值/异 workspace 一律丢弃。
        """
        scoped = []
        for hit in hits or []:
            if not isinstance(hit, dict):
                continue
            if str(hit.get("workspace_id") or "") != self.workspace_id:
                continue
            scoped.append(hit)
        return scoped
        try:
            return self._format_hits(hits)
        except Exception as e:  # noqa: BLE001 - 格式化异常同样降级
            logger.bind(tag=TAG).debug(f"记忆格式化异常（降级为空记忆）: {e}")
            return ""

    def _format_hits(self, hits) -> str:
        """去重 + 限量 + 限长：每行 ``- {summary}：{resolution}``，总长 ≤ 800 字符。"""
        lines = []
        seen = set()
        for hit in hits or []:
            if not isinstance(hit, dict):
                continue
            summary = str(hit.get("summary") or "").strip()
            resolution = str(hit.get("resolution") or "").strip()
            if not summary and not resolution:
                continue
            key = hit.get("id") or f"{summary}|{resolution}"
            if key in seen:
                continue
            seen.add(key)
            if len(lines) >= self.limit:
                break
            if summary and resolution:
                line = f"- {summary}：{resolution}"
            else:
                line = f"- {summary or resolution}"
            line = line[:MAX_HIT_CHARS]
            used = sum(len(item) + 1 for item in lines)
            if used + len(line) > MAX_MEMORY_CHARS:
                break
            lines.append(line)
        if not lines:
            return ""
        return "\n".join(lines)[:MAX_MEMORY_CHARS]

    async def save_memory(self, msgs) -> None:
        """会话结束保存：raw turns → 组织 → 快照 → 导入（失败落 outbox）。"""
        try:
            await self._save_memory_inner(msgs)
        except Exception as e:  # noqa: BLE001 - 保存失败绝不能影响关连接流程
            logger.bind(tag=TAG).error(f"Context Recall 记忆保存异常（忽略）: {e}")

    async def _save_memory_inner(self, msgs):
        now_iso = _now_iso()
        session_id = new_session_id(self.role_id)
        turns = dialogue_to_turns(msgs, session_id, now_iso)

        # 1) 无论是否组织，raw turns 都先落本地（证据源）
        if self.raw_store is not None and turns:
            self.raw_store.append_turns(turns)

        if not self.enabled:
            logger.bind(tag=TAG).debug("Context Recall 未配置 service_url，跳过组织与推送")
            return

        # 2) 用户发言不足 min_user_turns：不组织，只补投历史 outbox
        if user_turn_count(turns) < self.min_user_turns:
            logger.bind(tag=TAG).debug(
                f"用户发言不足 {self.min_user_turns} 轮（{user_turn_count(turns)}），跳过组织"
            )
            await self._flush_outbox()
            return

        # 3) 组织：LLM 可用则调 LLM，异常/无 LLM 一律降级零 LLM 最小节点
        dialogue_text = dialogue_to_text(msgs)
        llm = getattr(self, "llm", None)
        if llm is not None and hasattr(llm, "response_no_stream"):
            result = organize(llm, dialogue_text, turns, session_id, now_iso)
        else:
            logger.bind(tag=TAG).warning("未配置组织 LLM，使用零 LLM 最小节点")
            result = fallback_minimal(dialogue_text, turns, session_id, now_iso)

        # 4) 快照（organizer 已把会话摘要节点放在 nodes 首位）
        session = build_session(
            self.role_id,
            session_id,
            [turn["id"] for turn in turns],
            now_iso,
            self.workspace_id,
        )
        snapshot = build_snapshot(session, turns, result.nodes, result.edges)

        # 5) 推送；失败落 outbox（服务 additive 且 ID 确定性 → 重投幂等）
        response = None
        try:
            response = await self.client.import_snapshot(snapshot)
        except Exception as e:  # noqa: BLE001 - 客户端异常同样按推送失败处理
            logger.bind(tag=TAG).warning(f"快照推送异常，按失败处理: {e}")
        if response is None:
            if self.outbox is not None:
                self.outbox.put(snapshot)
            logger.bind(tag=TAG).warning(
                f"快照推送失败，已落 outbox 待重投: session={session_id}, "
                f"pending={self.outbox.pending_count() if self.outbox else 0}"
            )
        else:
            logger.bind(tag=TAG).info(
                f"快照推送成功: session={session_id}, "
                f"imported_memories={response.get('imported_memories')}, "
                f"nodes={len(result.nodes)}, edges={len(result.edges)}, "
                f"fallback={result.fallback}"
            )

        # 6) 顺带补投历史失败快照
        await self._flush_outbox()

    async def _flush_outbox(self):
        if self.outbox is None or not self.enabled:
            return
        try:
            await self.outbox.flush(self.client)
        except Exception as e:  # noqa: BLE001 - 补投失败不影响本次保存
            logger.bind(tag=TAG).debug(f"outbox 补投失败（忽略）: {e}")
