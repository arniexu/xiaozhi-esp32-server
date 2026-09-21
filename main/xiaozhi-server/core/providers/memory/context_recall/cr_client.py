# -*- coding: utf-8 -*-
"""Context Recall HTTP 客户端。

设计文档：docs/singleton-mode-plan.md §4.1（服务事实）/ §4.3（查询路径）。

三条硬约束（W1 联调实测，勿改）：
1. 每个方法内部新建短连接 ``httpx.AsyncClient``：本 provider 会同时被主事件循环
   （``query_memory``）和保存线程的独立事件循环（``save_memory``）使用，跨事件循环
   复用一个 client/连接池会出问题。
2. ``trust_env=False``：企业代理环境变量会让 127.0.0.1 的请求也走代理并返回 403。
3. ``/v1/search`` 必须显式传 ``scope_fallback="none"``：服务默认 ``global`` 会跨
   workspace 合并召回（同一份数据在其它 workspace 也能查到）。

所有方法都不向上抛异常：CR 不可达时记忆链路必须静默降级，不能影响对话。
"""

import httpx

from ..base import logger

TAG = __name__

# 检索响应里可能出现记忆条目的三个桶（按服务 v0.1.7 实测）
_SEARCH_BUCKETS = ("lexical", "semantic_memories", "graph")


class CRClient:
    """Context Recall 服务的最小 HTTP 客户端（短连接、绝不抛出）。"""

    def __init__(self, base_url: str, timeout: float = 2.5):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 6,
        min_similarity: float = 0.35,
    ) -> list:
        """检索记忆；失败/无结果一律返回空列表。"""
        if not self.base_url:
            return []
        payload = {
            "query": query,
            "workspace_id": workspace_id,
            # 勿改：默认 global 会跨 workspace 合并召回（W1 实测）
            "scope_fallback": "none",
            "limit": limit,
            "min_similarity": min_similarity,
        }
        try:
            async with httpx.AsyncClient(
                trust_env=False, timeout=self.timeout
            ) as client:
                resp = await client.post(self._url("/v1/search"), json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001 - 检索失败必须降级为空记忆
            logger.bind(tag=TAG).debug(f"Context Recall 检索失败（降级为空记忆）: {e}")
            return []

        if not isinstance(data, dict):
            return []

        merged: list = []
        seen = set()
        for bucket in _SEARCH_BUCKETS:
            items = data.get(bucket)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if item_id:
                    if item_id in seen:
                        continue
                    seen.add(item_id)
                merged.append(item)
        return merged

    async def import_snapshot(self, snapshot: dict, timeout: float = 10.0) -> dict:
        """推送快照；失败返回 None（由调用方落 outbox 重试）。"""
        if not self.base_url:
            return None
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
                resp = await client.post(
                    self._url("/v1/import/extension"), json=snapshot
                )
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {}
        except Exception as e:  # noqa: BLE001 - 推送失败必须走 outbox，不能抛出
            logger.bind(tag=TAG).warning(f"Context Recall 快照导入失败: {e}")
            return None

    async def health(self) -> bool:
        """健康检查；不可达返回 False。"""
        if not self.base_url:
            return False
        try:
            async with httpx.AsyncClient(
                trust_env=False, timeout=min(self.timeout, 2.5)
            ) as client:
                resp = await client.get(self._url("/health"))
                return resp.status_code == 200
        except Exception:  # noqa: BLE001 - 健康检查失败即 False
            return False
