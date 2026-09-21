# -*- coding: utf-8 -*-
"""快照构造：把 xiaozhi 的 Message 列表转成 Context Recall ``/v1/import/extension`` 契约。

设计文档：docs/singleton-mode-plan.md §4.2（保存路径 v2）。
契约参考：main/xiaozhi-server/test/test_context_recall_smoke.py（W1 已实测 7/7）。

数据模型（extension model.ts）：KnowledgeSnapshot = {schemaVersion, sessions, turns,
vectors, nodes, edges, events}；服务端不落 turns，turns 只用于 evidence 解析与
scope 映射，因此 evidenceTurnIds 必须指向本快照内真实存在的 turn id。
"""

import re
import time

SHORT_TURN_SKIP_ROLES = ("system", "tool")


def new_session_id(role_id: str) -> str:
    """生成会话 ID：``xiaozhi:{设备}:{时间戳}``（设备取 role_id 中 # 前部分）。

    例：role_id="aa:bb:cc:dd:ee:ff#agent-1" → "xiaozhi:aa_bb_cc_dd_ee_ff:20260921-101530"
    """
    device = (role_id or "device").split("#", 1)[0] or "device"
    safe_device = re.sub(r"[^0-9A-Za-z]", "_", device)
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"xiaozhi:{safe_device}:{ts}"


def dialogue_to_turns(msgs, session_id: str, now_iso: str) -> list:
    """Message 列表 → turn 记录（跳过 system/tool 与空内容；i 从 1 递增）。"""
    turns = []
    for msg in msgs or []:
        role = getattr(msg, "role", None)
        if role in SHORT_TURN_SKIP_ROLES:
            continue
        content = getattr(msg, "content", None)
        if content is None:
            continue
        text = content if isinstance(content, str) else str(content)
        if not text.strip():
            continue
        turns.append(
            {
                "id": f"{session_id}#t{len(turns) + 1}",
                "sessionId": session_id,
                "role": role,
                "text": text,
                "createdAt": now_iso,
            }
        )
    return turns


def dialogue_to_text(msgs) -> str:
    """Message 列表 → 组织用纯文本（User/Assistant 拼接，格式对齐 mem_local_short）。

    与 ``dialogue_to_turns`` 保持一致：跳过空内容（tool_calls 的 assistant 消息常为 None）。
    """
    text = ""
    for msg in msgs or []:
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", None)
        if content is None:
            continue
        body = content if isinstance(content, str) else str(content)
        if not body.strip():
            continue
        if role == "user":
            text += f"User: {body}\n"
        elif role == "assistant":
            text += f"Assistant: {body}\n"
    return text


def user_turn_count(turns: list) -> int:
    """用户发言轮数（只统计 role=user 的 turn）。"""
    return sum(1 for turn in turns or [] if turn.get("role") == "user")


def build_session(
    role_id: str, session_id: str, turn_ids: list, now_iso: str, workspace_id: str
) -> dict:
    """构造 SessionRecord；scope 取自 session.workspaceId（服务端行为）。"""
    return {
        "id": session_id,
        "title": f"xiaozhi 会话 {session_id}",
        "workspaceId": workspace_id,
        "createdAt": now_iso,
        "updatedAt": now_iso,
        "turnIds": list(turn_ids),
    }


def build_snapshot(session: dict, turns: list, nodes: list, edges: list) -> dict:
    """构造 KnowledgeSnapshot（vectors / events 本波不用，保持空数组）。"""
    return {
        "schemaVersion": 1,
        "sessions": [session],
        "turns": turns,
        "vectors": [],
        "nodes": nodes,
        "edges": edges,
        "events": [],
    }
