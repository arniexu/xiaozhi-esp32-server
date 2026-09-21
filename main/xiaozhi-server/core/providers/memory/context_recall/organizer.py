# -*- coding: utf-8 -*-
"""会话知识组织器：把一段对话交给 LLM，产出可写入 Context Recall 的知识节点与边。

设计文档：docs/singleton-mode-plan.md §4.2（保存路径 v2）/ §4.4（治理）。
规范来源：knowledge-agent-extension/src/organizer.ts（organizeSession / extractedKnowledge）
的会话级移植（TS → Python）。

要点：
- 只提取持久知识（偏好/事实/人物/设备/计划），忽略寒暄与设备操控结果；
- 保留不确定性：用户单方面断言默认 low confidence；
- 节点/边使用确定性 ID（sha256 前 20 位）→ 同一会话重复导入幂等（服务 additive）；
- LLM 失败或坏 JSON → ``fallback_minimal`` 零 LLM 最小节点（原文截断），不丢数据。
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from ..base import logger

TAG = __name__

# 数量与长度上限（扩展 organizer.ts 的 8/12 收敛到语音场景）
MAX_NODES = 8
MAX_EDGES = 12
MAX_TAGS = 12
FALLBACK_SUMMARY_LIMIT = 1500

KINDS = {"fact", "decision", "concept", "person", "project", "tool", "workflow"}
CONFIDENCES = {"low", "medium", "high"}

ORGANIZE_SYSTEM_PROMPT = """你是小智语音助手的历史会话知识组织器。请把一段已经结束的对话整理成可长期复用的本地知识。
只输出 JSON，不要任何解释，也不要 Markdown 代码围栏。JSON 结构：
{"summary":"2-4 句、以结果为导向的会话摘要","nodes":[{"kind":"fact|decision|concept|person|project|tool|workflow","label":"规范实体名","summary":"一条可长期复用的陈述","confidence":"low|medium|high","tags":["标签"]}],"edges":[{"from":"节点 label 原文","to":"节点 label 原文","type":"UPPER_SNAKE_CASE","confidence":"low|medium|high"}]}

规则：
- 只提取持久、具体的知识：用户的偏好、事实、人物、设备、计划与约定；忽略寒暄、闲聊和一次性话题。
- 主语归属：只记录用户本人明确说出或确认过的内容，关于用户的信息一律以“用户”为主语陈述（例：“用户独自在上海工作”）。助手单方面提到、推测、附和出来的说法不是知识，不记录。
- 去扮演：助手（小智）自报的姓名、籍贯、居住地、行程、感情、性格等即兴人设与台词，以及虚构剧情和玩笑约定（见面计划、礼物、人物关系等）都不记录；person 节点只用于用户及用户明确提到的真实的人。
- 只陈述知识本身：任何情况下都不要写“助手提到”“未经用户确认”“存在矛盾”“不确定”这类评论；拿不准就降低 confidence，或干脆不记。
- 不要记录设备操控的过程或结果（调音量、开关灯、播放音乐、查天气、退出对话等），也不要记录与用户本人无关的临时信息。
- confidence 校准：用户直接陈述但无旁证的信息用 low；明确确认过的偏好用 medium；反复确认或有据可查的才用 high。
- 一个决策和它作用的对象应拆成两个节点，用边连接。
- 同一响应内复用规范 label（同一实体只用一个写法），边必须引用出现过的 label 原文。
- 最多返回 8 个节点、12 条边；没有可提取内容时 nodes 与 edges 返回空数组。
- summary 用中文，控制在 2-4 句，且同样遵守以上归属与去扮演规则。"""

ANALYZE_SYSTEM_PROMPT = """你是小智语音助手的历史会话逐句分析器。输入是编号的对话记录（`用户:` 是对话者本人，`助手:` 是语音助手小智）。
请对每一句话逐条做语义与实体分析，只输出 JSON，不要任何解释，也不要 Markdown 代码围栏：
{"turns":[{"i":1,"speaker":"user|assistant","about":"用户|助手|第三方|无","type":"user_fact|user_preference|user_plan|user_opinion|assistant_roleplay|chitchat|question|device_op|other","entities":[{"name":"实体名","kind":"person|place|org|device|time|preference|other"}],"relations":[{"from":"主体","type":"UPPER_SNAKE_CASE","to":"客体"}],"fact":"","keep":false}]}

规则：
- 每一条编号发言都必须有一条分析项，i 与编号一致；不得合并、省略或新增。
- about：这句话在讲谁——讲用户本人=用户；助手自述、扮演、回答=助手；讲第三方的人或事=第三方；无实质对象=无。
- type：user_fact=用户陈述自身事实；user_preference=用户偏好；user_plan=用户的计划或约定；user_opinion=用户观点感受；assistant_roleplay=助手的即兴人设或扮演台词；chitchat=寒暄闲聊；question=提问；device_op=设备操作相关内容。
- entities 只列这句话里明确出现的实体；没有就给空数组。
- relations 只抽稳定的“主体→关系→客体”（如 {"from":"用户","type":"LIVES_IN","to":"上海"}），主体优先写“用户”；没有就给空数组。
- 助手的即兴人设与台词（籍贯、居住地、感情、行程、玩笑约定）一律 type=assistant_roleplay、keep=false。
- fact 只在 keep=true 时填写：一句以“用户”为主语、可长期复用的事实（例：“用户独自在上海工作生活”）。
- keep=true 仅限用户本人明确说出或确认的持久信息（事实/偏好/计划/人际）；其余全为 false。
- 任何情况下都不要写“助手提到”“未经用户确认”“存在矛盾”这类评论；拿不准就 keep=false。"""

# ```json ... ``` 围栏（与 mem_local_short.extract_json_data 思路一致，但更宽容）
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class OrganizeResult:
    """组织结果：可直接进入快照的节点/边 + 会话摘要。"""

    summary: str
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    fallback: bool = False


def _stable_id(prefix: str, identity: str) -> str:
    """确定性 ID：sha256(归一化 identity) 前 20 位十六进制。"""
    digest = hashlib.sha256(identity.strip().lower().encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:20]}"


def node_id(kind: str, label: str, summary: str) -> str:
    """知识节点 ID。fact/decision 把 summary 计入 identity（同 label 不同断言不互相覆盖）。"""
    if kind in ("fact", "decision"):
        identity = f"{kind}|{label}|{summary}"
    else:
        identity = f"{kind}|{label}"
    return _stable_id("knowledge", identity)


def summary_node_id(session_id: str) -> str:
    """会话摘要节点 ID（每个会话一个，重复导入幂等）。"""
    return _stable_id("knowledge", f"session-summary|{session_id}")


def edges_to_units(nodes: list, edges: list, limit: int = MAX_EDGES) -> list:
    """把边渲染成文本知识单元：无图谱部署（如 Pi，graph off）的关系兜底注入。

    - 渲染为 ``主体 —RELATION→ 客体``，可被召回并注入对话；
    - ID 由两端节点 ID 与类型确定（与边 ID 同源）→ 跨会话重复导入幂等；
    - 由 context_recall 的 ``inject_edges`` 配置控制（默认开）。
    """
    by_id = {}
    for node in nodes or []:
        if isinstance(node, dict) and node.get("id"):
            by_id[node["id"]] = node
    units = []
    for edge in (edges or [])[:limit]:
        if not isinstance(edge, dict):
            continue
        source = by_id.get(edge.get("from"))
        target = by_id.get(edge.get("to"))
        if not source or not target:
            continue
        from_label = str(source.get("label") or "").strip()
        to_label = str(target.get("label") or "").strip()
        edge_type = str(edge.get("type") or "").strip()
        if not from_label or not to_label or not edge_type:
            continue
        units.append(
            {
                "id": _stable_id(
                    "knowledge",
                    f"edge|{edge.get('from')}|{edge_type}|{edge.get('to')}",
                ),
                "kind": "fact",
                "label": f"{from_label}→{to_label}",
                "summary": f"{from_label} —{edge_type}→ {to_label}",
                "status": "active",
                "confidence": edge.get("confidence", "low"),
                "evidenceTurnIds": list(edge.get("evidenceTurnIds") or []),
                "tags": ["relation", edge_type.lower()],
                "createdAt": edge.get("createdAt") or "",
                "updatedAt": edge.get("updatedAt") or edge.get("createdAt") or "",
            }
        )
    return units


def edge_id(from_id: str, to_id: str, edge_type: str) -> str:
    """边 ID：由两端节点 ID 与类型确定（与 label 无关，避免改名导致重复边）。"""
    return _stable_id("edge", f"{from_id}|{to_id}|{edge_type}")


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text[:limit]


def _normalize_kind(value) -> str:
    kind = value.strip().lower() if isinstance(value, str) else ""
    return kind if kind in KINDS else "concept"


def _normalize_confidence(value) -> str:
    confidence = value.strip().lower() if isinstance(value, str) else ""
    return confidence if confidence in CONFIDENCES else "medium"


def _clean_tags(value) -> list:
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip().lower()
        if tag:
            tags.append(tag)
    return tags[:MAX_TAGS]


def _normalize_edge_type(value) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").upper()


def extract_json(text) -> dict:
    """从 LLM 输出里尽力取出 JSON 对象；失败返回 None（绝不抛异常）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    candidates = []
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:  # noqa: BLE001 - 容错解析，继续尝试下一个候选
            continue
        if isinstance(data, dict):
            return data
    return None


def _build_summary_node(
    summary: str, session_id: str, turn_ids: list, now_iso: str
) -> dict:
    """会话摘要节点（kind=workflow，可被检索到）。"""
    return {
        "id": summary_node_id(session_id),
        "kind": "workflow",
        "label": f"会话 {session_id}",
        "summary": summary,
        "status": "active",
        "confidence": "medium",
        "evidenceTurnIds": list(turn_ids),
        "tags": ["session-summary"],
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }


def _turn_ids(turns) -> list:
    ids = []
    for turn in turns or []:
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        if turn_id:
            ids.append(turn_id)
    return ids


def _build_user_content(dialogue_text: str, turn_ids: list) -> str:
    ids = json.dumps(turn_ids, ensure_ascii=False)
    return (
        f"对话记录如下：\n{dialogue_text}\n\n"
        f"本次会话的 turn id 列表（仅作参考，evidence 由代码填充）：\n{ids}\n"
    )


def _numbered_dialogue(turns: list, dialogue_text: str) -> str:
    """编号对话文本（保留用户/助手原始归属，供逐句分析使用）。"""
    lines = []
    for idx, turn in enumerate(turns or [], 1):
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        role = "用户" if turn.get("role") == "user" else "助手"
        lines.append(f"[{idx}] {role}: {text[:300]}")
    return "\n".join(lines) if lines else dialogue_text


def _build_analyze_content(turns: list, dialogue_text: str) -> str:
    return (
        "对话记录如下（方括号内为 i 编号）：\n"
        f"{_numbered_dialogue(turns, dialogue_text)}\n"
    )


def _build_grounded_content(analysis: dict, turn_ids: list) -> str:
    """接地聚合的 user content：逐句分析结果（JSON）+ turn id 列表。"""
    analysis_json = json.dumps(analysis, ensure_ascii=False)
    ids = json.dumps(turn_ids, ensure_ascii=False)
    return (
        "以下是对本次会话的逐句语义/实体分析结果（JSON）。请只基于其中 keep=true 的条目"
        "聚合知识；keep=false 的条目仅用于概括会话，不进入节点：\n"
        f"{analysis_json}\n\n"
        f"本次会话的 turn id 列表（仅作参考，evidence 由代码填充）：\n{ids}\n"
    )


def _analyze_dialogue(llm, turns: list, dialogue_text: str) -> dict:
    """阶段 1：逐句语义/实体分析；失败返回 None（调用方回退单次组织）。"""
    content = _build_analyze_content(turns, dialogue_text)
    try:
        raw = llm.response_no_stream(
            ANALYZE_SYSTEM_PROMPT,
            content,
            max_tokens=4000,
            temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001 - 分析失败回退
        logger.bind(tag=TAG).warning(f"逐句分析 LLM 调用失败，回退单次组织: {e}")
        return None
    payload = extract_json(raw)
    items = payload.get("turns") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        logger.bind(tag=TAG).warning("逐句分析返回缺少 turns，回退单次组织")
        return None
    kept = sum(1 for item in items if isinstance(item, dict) and item.get("keep"))
    logger.bind(tag=TAG).info(
        f"逐句分析完成: turns={len(items)}, keep={kept}；进入接地聚合"
    )
    return payload


def organize(
    llm, dialogue_text: str, turns: list, session_id: str, now_iso: str
) -> OrganizeResult:
    """两阶段组织：①逐句语义/实体分析 ②接地聚合；任一阶段失败回退单次组织/最小节点。"""
    turn_ids = _turn_ids(turns)
    analysis = _analyze_dialogue(llm, turns, dialogue_text)
    payload = None
    if analysis is not None:
        try:
            raw = llm.response_no_stream(
                ORGANIZE_SYSTEM_PROMPT,
                _build_grounded_content(analysis, turn_ids),
                max_tokens=2000,
                temperature=0.2,
            )
            payload = extract_json(raw)
        except Exception as e:  # noqa: BLE001 - 聚合失败回退单次组织
            logger.bind(tag=TAG).warning(f"接地聚合 LLM 调用失败，回退单次组织: {e}")
            payload = None
    if payload is None:
        # 回退：单次组织（兼容旧模型/旧行为）
        try:
            raw = llm.response_no_stream(
                ORGANIZE_SYSTEM_PROMPT,
                _build_user_content(dialogue_text, turn_ids),
                max_tokens=2000,
                temperature=0.2,
            )
        except Exception as e:  # noqa: BLE001 - LLM 失败必须降级，不能丢数据
            logger.bind(tag=TAG).warning(f"组织 LLM 调用失败，降级零 LLM 最小节点: {e}")
            return fallback_minimal(dialogue_text, turns, session_id, now_iso)
        payload = extract_json(raw)
        if payload is None:
            logger.bind(tag=TAG).warning("组织 LLM 返回无法解析为 JSON，降级零 LLM 最小节点")
            return fallback_minimal(dialogue_text, turns, session_id, now_iso)

    # 1) 知识节点（label/summary 必须是非空字符串，最多 8 个）
    nodes = []
    labels = {}
    raw_nodes = payload.get("nodes")
    if isinstance(raw_nodes, list):
        for item in raw_nodes[:MAX_NODES]:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            summary = item.get("summary")
            if not isinstance(label, str) or not label.strip():
                continue
            if not isinstance(summary, str) or not summary.strip():
                continue
            label, summary = label.strip(), summary.strip()
            kind = _normalize_kind(item.get("kind"))
            node = {
                "id": node_id(kind, label, summary),
                "kind": kind,
                "label": label,
                "summary": summary,
                "status": "active",
                "confidence": _normalize_confidence(item.get("confidence")),
                "evidenceTurnIds": list(turn_ids),
                "tags": _clean_tags(item.get("tags")),
                "createdAt": now_iso,
                "updatedAt": now_iso,
            }
            # 同一响应内后写的 label 覆盖先写的（对齐扩展 organizer.ts 的 Map.set 语义）
            labels[label.lower()] = node["id"]
            nodes.append(node)

    # 2) 边：label → 本次生成的节点 ID，未命中/自环/空类型一律丢弃
    edges = []
    raw_edges = payload.get("edges")
    if isinstance(raw_edges, list):
        for item in raw_edges[:MAX_EDGES]:
            if not isinstance(item, dict):
                continue
            source = item.get("from")
            target = item.get("to")
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            from_id = labels.get(source.strip().lower())
            to_id = labels.get(target.strip().lower())
            if not from_id or not to_id or from_id == to_id:
                continue
            edge_type = _normalize_edge_type(item.get("type"))
            if not edge_type:
                continue
            edges.append(
                {
                    "id": edge_id(from_id, to_id, edge_type),
                    "from": from_id,
                    "to": to_id,
                    "type": edge_type,
                    "confidence": _normalize_confidence(item.get("confidence")),
                    "evidenceTurnIds": list(turn_ids),
                    "createdAt": now_iso,
                }
            )

    # 3) 摘要节点放在最前（provider 直接使用本结果作为快照 nodes）
    summary = payload.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""
    if not summary:
        # LLM 没给摘要时退回原文截断，保证摘要节点始终可检索
        summary = _truncate(dialogue_text, FALLBACK_SUMMARY_LIMIT)
    summary_node = _build_summary_node(summary, session_id, turn_ids, now_iso)
    return OrganizeResult(
        summary=summary, nodes=[summary_node] + nodes, edges=edges, fallback=False
    )


def fallback_minimal(
    dialogue_text: str, turns: list, session_id: str, now_iso: str
) -> OrganizeResult:
    """零 LLM 最小节点：原文截断成单个可检索节点（evidence 非空、status=active）。"""
    turn_ids = _turn_ids(turns)
    text = _truncate(dialogue_text, FALLBACK_SUMMARY_LIMIT)
    label = f"会话记录 {session_id}"
    node = {
        "id": node_id("workflow", label, text),
        "kind": "workflow",
        "label": label,
        "summary": text,
        "status": "active",
        "confidence": "low",
        "evidenceTurnIds": list(turn_ids),
        "tags": ["session-record"],
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }
    return OrganizeResult(summary=text, nodes=[node], edges=[], fallback=True)
