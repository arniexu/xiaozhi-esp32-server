#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 0 联调冒烟脚本：验证 xiaozhi ↔ Context Recall 的快照契约。

目标实例：一次性测试实例（空数据目录、独立端口，如 8876）。
验证项：
  1) 健康检查 /health
  2) 导入快照 /v1/import/extension（imported_memories >= 1）
  3) 检索命中 /v1/search（同 workspace、scope_fallback=none）
  4) 幂等：重复导入同一快照 → 记忆总数不变、检索仍单条
  5) 隔离：其它 workspace + scope_fallback=none → 不可见
     （并观察默认 global fallback 的跨 domain 行為——用于提醒 provider 必须显式传 scope_fallback）
  6) 降级：端口不可达 → 快速失败（< 2s，不挂起）

仅标准库；Pi 验收可原样复用：
  python3 test_context_recall_smoke.py --base-url http://127.0.0.1:8876
"""

import argparse
import json
import sys
import time
import urllib.request

WORKSPACE = "xiaozhi"
OTHER_WORKSPACE = "other-workspace"
SESSION_ID = "test-session-0001"
NODE_ID = "knowledge:test-0001"
NOW = "2026-09-21T10:00:00+08:00"


# 显式绕过 http_proxy/https_proxy（企业环境变量会把 localhost/LAN 请求也走代理 → 403）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(method: str, url: str, payload=None, timeout: float = 5.0):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with _OPENER.open(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def build_snapshot():
    turns = [
        {"id": "test-turn-0001", "sessionId": SESSION_ID, "role": "user",
         "text": "把客厅的灯调亮一点", "createdAt": NOW},
        {"id": "test-turn-0002", "sessionId": SESSION_ID, "role": "assistant",
         "text": "好的，已调亮客厅灯光", "createdAt": NOW},
        {"id": "test-turn-0003", "sessionId": SESSION_ID, "role": "user",
         "text": "记住我偏好暖光", "createdAt": NOW},
    ]
    session = {
        "id": SESSION_ID,
        "title": "联调测试会话",
        "workspaceId": WORKSPACE,
        "createdAt": NOW,
        "updatedAt": NOW,
        "turnIds": [t["id"] for t in turns],
    }
    node = {
        "id": NODE_ID,
        "kind": "fact",
        "label": "用户偏好暖光",
        "summary": "用户偏好客厅暖光照明",
        "status": "active",
        "confidence": "medium",
        "evidenceTurnIds": [t["id"] for t in turns],
        "tags": ["preference", "lighting"],
        "createdAt": NOW,
        "updatedAt": NOW,
    }
    return {
        "schemaVersion": 1,
        "sessions": [session],
        "turns": turns,
        "vectors": [],
        "nodes": [node],
        "edges": [],
        "events": [],
    }


def search(base: str, query: str, workspace_id: str, scope_fallback: str | None = None):
    payload = {
        "query": query,
        "workspace_id": workspace_id,
        "limit": 6,
        "min_similarity": 0.35,
    }
    if scope_fallback is not None:
        payload["scope_fallback"] = scope_fallback
    return http_json("POST", f"{base}/v1/search", payload)


def find_node(resp: dict, node_id: str) -> bool:
    for key in ("lexical", "semantic_memories", "graph"):
        for item in resp.get(key) or []:
            if item.get("id") == node_id:
                return True
    return False


def count_node(resp: dict, node_id: str) -> int:
    return sum(
        1
        for key in ("lexical", "semantic_memories", "graph")
        for item in (resp.get(key) or [])
        if item.get("id") == node_id
    )


def health_total(base: str):
    health = http_json("GET", f"{base}/health", timeout=3)
    return health.get("memory", {}).get("total")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8876")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    results = []

    def check(name: str, ok: bool, detail: str = ""):
        results.append((name, ok))
        mark = "✅" if ok else "❌"
        print(f"{mark} {name}" + (f" — {detail}" if detail else ""))

    # 1. 健康检查
    try:
        health = http_json("GET", f"{base}/health", timeout=3)
        check("健康检查 /health", health.get("status") == "ok",
              f"version={health.get('version')}")
    except Exception as exc:  # noqa: BLE001
        check("健康检查 /health", False, f"{exc}（测试实例未启动？）")
        return _summary(results)

    # 2. 导入快照
    import_resp = http_json("POST", f"{base}/v1/import/extension",
                            build_snapshot(), timeout=10)
    check("导入快照 imported_memories>=1",
          (import_resp.get("imported_memories") or 0) >= 1,
          f"imported={import_resp.get('imported_memories')}")

    # 3. 检索命中（严格 scope）
    hit = search(base, "暖光", WORKSPACE, scope_fallback="none")
    check("检索命中（同 workspace / scope_fallback=none）",
          find_node(hit, NODE_ID), f"scope_match={hit.get('scope_match')}")

    # 4. 幂等
    before = health_total(base)
    http_json("POST", f"{base}/v1/import/extension", build_snapshot(), timeout=10)
    after = health_total(base)
    hit2 = search(base, "暖光", WORKSPACE, scope_fallback="none")
    check("重复导入幂等（记忆总数不变）", before == after,
          f"total: {before} -> {after}")
    check("检索不重复（单条命中）", count_node(hit2, NODE_ID) == 1,
          f"count={count_node(hit2, NODE_ID)}")

    # 5. 隔离（严格 scope）
    other = search(base, "暖光", OTHER_WORKSPACE, scope_fallback="none")
    check("workspace 隔离（其它 scope 不可见）",
          not find_node(other, NODE_ID),
          f"scope_match={other.get('scope_match')}, suppressed={other.get('scope_suppressed')}")

    # 5b. 观察默认 fallback 行为（信息项，不作为失败判据）
    default_fallback = search(base, "暖光", OTHER_WORKSPACE)
    leaked = find_node(default_fallback, NODE_ID)
    print(f"ℹ️ 默认 scope_fallback=global 时跨 scope 可见：{leaked}"
          f"（scope_match={default_fallback.get('scope_match')}）"
          f" → provider 必须显式传 scope_fallback='none'")

    # 6. 降级：端口不可达快速失败
    start = time.time()
    failed = False
    try:
        http_json("POST", "http://127.0.0.1:9/v1/search", {"query": "x"}, timeout=2)
    except Exception:  # noqa: BLE001
        failed = True
    elapsed = time.time() - start
    check("不可达降级（快速失败不挂起）", failed and elapsed < 2.0,
          f"{elapsed:.2f}s")

    return _summary(results)


def _summary(results) -> int:
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print("-" * 52)
    print(f"结果：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
