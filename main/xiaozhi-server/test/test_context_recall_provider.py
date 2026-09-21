#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""context_recall 记忆 provider 的纯 Python 自跑测试（无 pytest、无网络、无真实 LLM）。

运行（须在 main/xiaozhi-server 下）：
    .venv/bin/python test/test_context_recall_provider.py

覆盖：
  1) organizer 正常 JSON → 节点/边/摘要节点/确定性 ID；
  2) organizer 坏 JSON / LLM 异常 → fallback_minimal（evidence 非空、status=active）；
  3) 边引用不存在的 label → 丢弃；
  4) snapshot 结构与 evidence；
  5) Outbox put → flush 失败保留 → flush 成功清空；RawTurnStore 追加写；
  6) query_memory 命中格式化 / 空结果 / 异常 / 禁用降级；
  7) save_memory 全流程（Fake LLM + Fake CRClient）与 <3 轮用户发言跳过组织；
  8) config.yaml 的 Memory.context_recall 配置块 + selected_module.Memory 未被改动；
  9) core.utils.memory.create_instance 能按约定加载本 provider。

全部通过退出码 0；任一失败退出码 1。
"""

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from unittest import mock

# ---------------------------------------------------------------------------
# 环境加固（仅本进程，不修改任何仓库文件）
# ---------------------------------------------------------------------------
# 1) 本机 no_proxy 含 "[::1]"，会让 httpx 构造 Client 时抛 InvalidURL（Invalid port: ':1]'）。
#    与 test_context_recall_smoke.py 里 ProxyHandler({}) 的绕过同理。
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

# 2) 本机 data/.config.yaml 指向 manager-api（密钥已失效），而任何 app 模块导入时
#    config.logger.setup_logging() → config_loader.load_config() 会真实请求该 API 并抛异常。
#    测试不依赖真实配置：这里让 load_config 只合并本地 config.yaml（不访问 API），
#    并让 check_config_file 空转（兼容没有 data/.config.yaml 的环境）。
import config.config_loader as _config_loader  # noqa: E402
import config.settings as _config_settings  # noqa: E402


def _local_load_config():
    project_dir = _config_loader.get_project_dir()
    base = _config_loader.read_config(project_dir + "config.yaml")
    custom_path = project_dir + "data/.config.yaml"
    custom = _config_loader.read_config(custom_path) if os.path.exists(custom_path) else {}
    custom.pop("manager-api", None)  # 不访问管理台 API
    return _config_loader.merge_configs(base, custom)


_config_loader.load_config = _local_load_config
_config_settings.check_config_file = lambda: None

from core.providers.memory.context_recall import organizer as organizer_mod  # noqa: E402
from core.providers.memory.context_recall import snapshot as snapshot_mod  # noqa: E402
from core.providers.memory.context_recall import storage as storage_mod  # noqa: E402
from core.providers.memory.context_recall.context_recall import MemoryProvider  # noqa: E402
from core.providers.memory.context_recall.cr_client import CRClient  # noqa: E402
from core.utils.dialogue import Message  # noqa: E402

NOW = "2026-09-21T10:00:00+08:00"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("✅" if ok else "❌") + f" {name}" + (f" — {detail}" if detail else ""))


def run(name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - 单项失败不阻断其余用例
        check(f"{name}（未捕获异常）", False, f"{type(exc).__name__}: {exc}")


def msg(role, content):
    return Message(role=role, content=content)


class FakeLLM:
    """只记录调用并返回预置文本（或抛异常）。"""

    def __init__(self, response_text=None, exc=None):
        self.response_text = response_text
        self.exc = exc
        self.calls = []

    def response_no_stream(self, system_prompt, user_prompt, **kwargs):
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "kwargs": kwargs}
        )
        if self.exc is not None:
            raise self.exc
        return self.response_text


class FakeCRClient:
    """只记录调用并返回预置结果的 CR 客户端（不建连接）。"""

    def __init__(
        self, search_hits=None, import_result=None, search_exc=None, import_exc=None
    ):
        self.search_hits = list(search_hits or [])
        self.import_result = import_result
        self.search_exc = search_exc
        self.import_exc = import_exc
        self.search_calls = []
        self.import_calls = []

    async def search(self, query, workspace_id, limit=6, min_similarity=0.35):
        self.search_calls.append(
            {
                "query": query,
                "workspace_id": workspace_id,
                "limit": limit,
                "min_similarity": min_similarity,
            }
        )
        if self.search_exc is not None:
            raise self.search_exc
        return list(self.search_hits)

    async def import_snapshot(self, snapshot, timeout=10.0):
        self.import_calls.append(snapshot)
        if self.import_exc is not None:
            raise self.import_exc
        return self.import_result


def provider_config(**overrides):
    config = {
        "type": "context_recall",
        "service_url": "http://127.0.0.1:9",
        "workspace_id": "xiaozhi",
        "min_similarity": 0.35,
        "limit": 6,
        "timeout": 0.5,
        "min_user_turns": 3,
    }
    config.update(overrides)
    return config


SAMPLE_PAYLOAD = {
    "summary": "用户偏好暖光，并提到儿子小明。",
    "nodes": [
        {
            "kind": "fact",
            "label": "客厅灯光偏好",
            "summary": "用户偏好客厅暖光",
            "confidence": "low",
            "tags": ["Preference", "灯光"],
        },
        {
            "kind": "person",
            "label": "小明",
            "summary": "用户的儿子",
            "confidence": "medium",
            "tags": [],
        },
    ],
    "edges": [
        {
            "from": "客厅灯光偏好",
            "to": "小明",
            "type": "related to",
            "confidence": "low",
        },
        {"from": "不存在的节点", "to": "小明", "type": "mentions"},
    ],
}
SAMPLE_JSON = json.dumps(SAMPLE_PAYLOAD, ensure_ascii=False)

SAMPLE_TURNS = [
    {"id": "sess-1#t1", "sessionId": "sess-1", "role": "user", "text": "我偏好暖光"},
    {"id": "sess-1#t2", "sessionId": "sess-1", "role": "assistant", "text": "好的"},
    {"id": "sess-1#t3", "sessionId": "sess-1", "role": "user", "text": "我儿子叫小明"},
]


def sha20(text):
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------
# 1) organizer：正常 JSON、确定性 ID、悬空边丢弃
# ---------------------------------------------------------------------------
def test_organizer_normal():
    llm = FakeLLM(SAMPLE_JSON)
    r1 = organizer_mod.organize(llm, "User: 我偏好暖光\n", SAMPLE_TURNS, "sess-1", NOW)
    r2 = organizer_mod.organize(
        FakeLLM(SAMPLE_JSON), "User: 我偏好暖光\n", SAMPLE_TURNS, "sess-1", NOW
    )

    check(
        "1.1 正常 JSON → 1 摘要节点 + 2 知识节点，摘要节点在首位",
        len(r1.nodes) == 3
        and r1.nodes[0]["kind"] == "workflow"
        and r1.nodes[0]["label"] == "会话 sess-1"
        and r1.nodes[0]["tags"] == ["session-summary"],
        f"nodes={[(n['kind'], n['label']) for n in r1.nodes]}",
    )
    check(
        "1.2 摘要节点 id = knowledge:sha256('session-summary|会话id')[:20]",
        r1.nodes[0]["id"] == "knowledge:" + sha20("session-summary|sess-1"),
        r1.nodes[0]["id"],
    )
    check(
        "1.3 知识节点 id（fact = kind|label|summary）",
        r1.nodes[1]["id"] == "knowledge:" + sha20("fact|客厅灯光偏好|用户偏好客厅暖光"),
        r1.nodes[1]["id"],
    )
    check(
        "1.4 person 节点 id 只含 kind|label，且确定性（同输入两次一致）",
        r1.nodes[2]["id"] == "knowledge:" + sha20("person|小明")
        and [n["id"] for n in r1.nodes] == [n["id"] for n in r2.nodes]
        and [e["id"] for e in r1.edges] == [e["id"] for e in r2.edges],
        f"{r1.nodes[2]['id']}",
    )
    check(
        "1.5 不存在的 label 引用的边被丢弃（2 条只剩 1 条）",
        len(r1.edges) == 1 and r1.edges[0]["type"] == "RELATED_TO",
        f"edges={r1.edges}",
    )
    check(
        "1.6 边 id = edge:sha256('from|to|type')[:20]",
        r1.edges[0]["id"]
        == "edge:"
        + sha20(f"{r1.nodes[1]['id']}|{r1.nodes[2]['id']}|RELATED_TO")
        and r1.edges[0]["from"] == r1.nodes[1]["id"]
        and r1.edges[0]["to"] == r1.nodes[2]["id"],
        r1.edges[0]["id"],
    )
    turn_ids = [t["id"] for t in SAMPLE_TURNS]
    check(
        "1.7 全部节点/边 status=active、evidence 为全部 turn id、时间戳一致",
        all(
            n["status"] == "active"
            and n["evidenceTurnIds"] == turn_ids
            and n["createdAt"] == NOW
            and n["updatedAt"] == NOW
            for n in r1.nodes
        )
        and all(
            e["evidenceTurnIds"] == turn_ids and e["createdAt"] == NOW
            for e in r1.edges
        ),
    )
    check(
        "1.8 tags 归一化（小写、去空）",
        r1.nodes[1]["tags"] == ["preference", "灯光"] and r1.nodes[2]["tags"] == [],
        f"{r1.nodes[1]['tags']}",
    )
    check(
        "1.9 LLM 调用参数与 user_content 含 turn id 列表",
        llm.calls
        and llm.calls[0]["kwargs"] == {"max_tokens": 2000, "temperature": 0.2}
        and "sess-1#t1" in llm.calls[0]["user"]
        and "我偏好暖光" in llm.calls[0]["user"],
    )
    check(
        "1.10 summary 字段透传",
        r1.summary == SAMPLE_PAYLOAD["summary"] and r1.fallback is False,
        r1.summary,
    )
    fenced = "结果如下：\n```json\n" + SAMPLE_JSON + "\n```\n以上。"
    r3 = organizer_mod.organize(
        FakeLLM(fenced), "User: x\n", SAMPLE_TURNS, "sess-1", NOW
    )
    check(
        "1.11 ```json 围栏容错解析",
        len(r3.nodes) == 3 and r3.fallback is False,
        f"nodes={len(r3.nodes)}",
    )
    check(
        "1.12 节点数上限 8（超出被截断）",
        len(
            organizer_mod.organize(
                FakeLLM(
                    json.dumps(
                        {
                            "summary": "s",
                            "nodes": [
                                {"kind": "fact", "label": f"L{i}", "summary": f"S{i}"}
                                for i in range(20)
                            ],
                            "edges": [],
                        },
                        ensure_ascii=False,
                    )
                ),
                "User: x\n",
                SAMPLE_TURNS,
                "sess-1",
                NOW,
            ).nodes
        )
        == 9,  # 8 知识节点 + 1 摘要节点
    )


# ---------------------------------------------------------------------------
# 2) organizer：坏 JSON / LLM 异常 → fallback_minimal
# ---------------------------------------------------------------------------
def test_organizer_fallback():
    r = organizer_mod.organize(
        FakeLLM("抱歉，这不是 JSON。"), "User: 你好\n", SAMPLE_TURNS, "sess-2", NOW
    )
    check(
        "2.1 坏 JSON → fallback=True 且只有 1 个节点",
        r.fallback is True and len(r.nodes) == 1 and r.edges == [],
        f"nodes={len(r.nodes)}",
    )
    node = r.nodes[0]
    check(
        "2.2 fallback 节点可检索（evidence 非空 + status=active + kind=workflow）",
        bool(node["evidenceTurnIds"])
        and node["status"] == "active"
        and node["kind"] == "workflow"
        and node["tags"] == ["session-record"]
        and node["confidence"] == "low",
        f"evidence={node['evidenceTurnIds']}",
    )
    check(
        "2.3 fallback summary 与节点 summary 一致且 ≤1500 字符",
        r.summary == node["summary"] and len(node["summary"]) <= 1500,
        f"len={len(node['summary'])}",
    )
    r_exc = organizer_mod.organize(
        FakeLLM(exc=RuntimeError("llm down")),
        "User: 你好\n",
        SAMPLE_TURNS,
        "sess-3",
        NOW,
    )
    check(
        "2.4 LLM 抛异常 → fallback（不向上抛）",
        r_exc.fallback is True and len(r_exc.nodes) == 1,
    )
    r_long = organizer_mod.fallback_minimal("x" * 3000, SAMPLE_TURNS, "sess-4", NOW)
    check(
        "2.5 fallback 原文截断到 1500 字符",
        len(r_long.nodes[0]["summary"]) == 1500,
        f"len={len(r_long.nodes[0]['summary'])}",
    )
    check(
        "2.6 extract_json 对空/非字符串返回 None",
        organizer_mod.extract_json("") is None
        and organizer_mod.extract_json(None) is None,
    )


# ---------------------------------------------------------------------------
# 3) CRClient：空 base_url 与不可达端口的静默降级（不访问任何外部网络）
# ---------------------------------------------------------------------------
def test_cr_client_degrade():
    empty = CRClient("")
    check(
        "3.1 base_url 为空 → search=[] / import=None / health=False",
        asyncio.run(empty.search("q", "w")) == []
        and asyncio.run(empty.import_snapshot({})) is None
        and asyncio.run(empty.health()) is False,
    )
    down = CRClient("http://127.0.0.1:9", timeout=0.5)
    hits = asyncio.run(down.search("q", "w"))
    imported = asyncio.run(down.import_snapshot({"schemaVersion": 1}))
    check(
        "3.2 不可达端口 → 静默降级（search=[]、import=None，trust_env=False 不抛）",
        hits == [] and imported is None,
        f"hits={hits}, import={imported}",
    )


# ---------------------------------------------------------------------------
# 4) snapshot：结构与 evidence
# ---------------------------------------------------------------------------
def test_snapshot():
    msgs = [
        msg("system", "sys prompt"),
        msg("user", "你好"),
        msg("assistant", "在的"),
        msg("tool", None),
        msg("user", "记住我偏好暖光"),
        msg("assistant", ""),
    ]
    turns = snapshot_mod.dialogue_to_turns(msgs, "sess-x", NOW)
    check(
        "4.1 跳过 system/tool/空内容，turn id 从 t1 连续递增",
        [t["id"] for t in turns] == ["sess-x#t1", "sess-x#t2", "sess-x#t3"]
        and [t["role"] for t in turns] == ["user", "assistant", "user"],
        f"{[t['id'] for t in turns]}",
    )
    check(
        "4.2 turn 字段完整（sessionId/text/createdAt）",
        set(turns[0].keys()) == {"id", "sessionId", "role", "text", "createdAt"}
        and turns[0]["sessionId"] == "sess-x"
        and turns[0]["text"] == "你好"
        and turns[0]["createdAt"] == NOW,
    )
    check(
        "4.3 dialogue_to_text 为 User/Assistant 拼接",
        snapshot_mod.dialogue_to_text(msgs)
        == "User: 你好\nAssistant: 在的\nUser: 记住我偏好暖光\n",
        repr(snapshot_mod.dialogue_to_text(msgs)),
    )
    check("4.4 user_turn_count=2", snapshot_mod.user_turn_count(turns) == 2)
    session = snapshot_mod.build_session(
        "dev-01#role-a", "sess-x", [t["id"] for t in turns], NOW, "xiaozhi"
    )
    nodes = [
        organizer_mod.fallback_minimal(
            snapshot_mod.dialogue_to_text(msgs), turns, "sess-x", NOW
        ).nodes[0]
    ]
    snap = snapshot_mod.build_snapshot(session, turns, nodes, [])
    check(
        "4.5 快照结构（schemaVersion/workspaceId/turnIds/vectors/events）",
        snap["schemaVersion"] == 1
        and snap["sessions"][0]["workspaceId"] == "xiaozhi"
        and snap["sessions"][0]["turnIds"] == ["sess-x#t1", "sess-x#t2", "sess-x#t3"]
        and snap["sessions"][0]["title"] == "xiaozhi 会话 sess-x"
        and snap["turns"] == turns
        and snap["vectors"] == []
        and snap["events"] == [],
    )
    check(
        "4.6 evidenceTurnIds 非空且指向快照内真实 turn",
        all(
            n["evidenceTurnIds"]
            and set(n["evidenceTurnIds"]) <= {t["id"] for t in snap["turns"]}
            for n in snap["nodes"]
        ),
    )
    check(
        "4.7 session_id 规则 xiaozhi:{safe_device}:{ts}",
        re.fullmatch(
            r"xiaozhi:aa_bb_cc_dd_ee_ff:\d{8}-\d{6}",
            snapshot_mod.new_session_id("aa:bb:cc:dd:ee:ff#agent-1"),
        )
        is not None,
        snapshot_mod.new_session_id("aa:bb:cc:dd:ee:ff#agent-1"),
    )


# ---------------------------------------------------------------------------
# 5) storage：RawTurnStore / Outbox
# ---------------------------------------------------------------------------
def test_storage():
    with tempfile.TemporaryDirectory() as tmp:
        outbox = storage_mod.Outbox(tmp, "dev-01")
        snap = {
            "schemaVersion": 1,
            "sessions": [{"id": "sess-outbox-1"}],
            "turns": [],
            "nodes": [],
            "edges": [],
        }
        outbox_path = os.path.join(tmp, "outbox", "sess-outbox-1.json")
        check(
            "5.1 put 落盘 + pending_count=1",
            outbox.put(snap) and outbox.pending_count() == 1 and os.path.exists(outbox_path),
            f"pending={outbox.pending_count()}",
        )
        sent = asyncio.run(outbox.flush(FakeCRClient(import_result=None)))
        check(
            "5.2 flush 失败（返回 None）→ 文件保留",
            sent == 0 and outbox.pending_count() == 1,
            f"sent={sent}, pending={outbox.pending_count()}",
        )
        sent = asyncio.run(
            outbox.flush(FakeCRClient(import_exc=RuntimeError("network down")))
        )
        check(
            "5.3 flush 异常 → 不向上抛且文件保留",
            sent == 0 and outbox.pending_count() == 1,
            f"sent={sent}, pending={outbox.pending_count()}",
        )
        sent = asyncio.run(
            outbox.flush(FakeCRClient(import_result={"imported_memories": 1}))
        )
        check(
            "5.4 flush 成功 → 删除文件、pending=0",
            sent == 1 and outbox.pending_count() == 0 and not os.path.exists(outbox_path),
            f"sent={sent}, pending={outbox.pending_count()}",
        )

        store = storage_mod.RawTurnStore(tmp, "dev-01")
        store.append_turns([{"id": "a", "text": "暖光"}, {"id": "b", "text": "小明"}])
        store.append_turns([{"id": "c", "text": "计划"}])
        with open(store.path, "r", encoding="utf-8") as file:
            raw_lines = [line for line in file.read().split("\n") if line.strip()]
        check(
            "5.5 RawTurnStore 追加写 jsonl（ensure_ascii=False，中文不转义）",
            len(raw_lines) == 3
            and json.loads(raw_lines[0])["id"] == "a"
            and "暖光" in raw_lines[0],
            f"lines={len(raw_lines)}",
        )
        check(
            "5.6 目录不存在时 pending_count=0（不抛）",
            storage_mod.Outbox(os.path.join(tmp, "nope"), "x").pending_count() == 0,
        )


# ---------------------------------------------------------------------------
# 6) query_memory 格式化与降级
# ---------------------------------------------------------------------------
def test_query_memory():
    provider = MemoryProvider(provider_config(), None)
    provider.client = FakeCRClient(
        search_hits=[
            {
                "id": "k1",
                "summary": "用户偏好暖光",
                "resolution": "客厅使用暖光照明",
                "score": 0.9,
            },
            {
                "id": "k1",
                "summary": "用户偏好暖光",
                "resolution": "客厅使用暖光照明",
            },
            {"id": "k2", "summary": "用户儿子叫小明", "resolution": ""},
            {"id": "k3", "summary": "", "resolution": ""},
        ]
    )
    provider.init_memory("dev-01#role-a", None)
    out = asyncio.run(provider.query_memory("暖光"))
    check(
        "6.1 命中格式化 + 按 id 去重 + 跳过空条目",
        out == "- 用户偏好暖光：客厅使用暖光照明\n- 用户儿子叫小明",
        repr(out),
    )
    check(
        "6.2 检索参数（workspace/limit/min_similarity）",
        provider.client.search_calls
        == [
            {
                "query": "暖光",
                "workspace_id": "xiaozhi",
                "limit": 6,
                "min_similarity": 0.35,
            }
        ],
        f"{provider.client.search_calls}",
    )

    empty = MemoryProvider(provider_config(), None)
    empty.client = FakeCRClient(search_hits=[])
    empty.init_memory("dev-01", None)
    check("6.3 空结果 → ''", asyncio.run(empty.query_memory("x")) == "")

    boom = MemoryProvider(provider_config(), None)
    boom.client = FakeCRClient(search_exc=RuntimeError("cr down"))
    boom.init_memory("dev-01", None)
    check("6.4 检索异常 → ''（不抛）", asyncio.run(boom.query_memory("x")) == "")

    disabled = MemoryProvider(provider_config(service_url=""), None)
    disabled.client = FakeCRClient(search_hits=[{"id": "k", "summary": "s"}])
    disabled.init_memory("dev-01", None)
    check(
        "6.5 service_url 空 → 禁用（不发起检索）",
        asyncio.run(disabled.query_memory("x")) == ""
        and disabled.client.search_calls == [],
    )

    many = MemoryProvider(provider_config(limit=20), None)
    many.client = FakeCRClient(
        search_hits=[
            {"id": f"k{i}", "summary": "S" * 100, "resolution": "R" * 200}
            for i in range(20)
        ]
    )
    many.init_memory("dev-01", None)
    out_many = asyncio.run(many.query_memory("x"))
    check(
        "6.6 单条 ≤160 字符、总长 ≤800 字符",
        all(len(line) <= 160 for line in out_many.split("\n"))
        and len(out_many) <= 800,
        f"lines={len(out_many.split(chr(10)))}, len={len(out_many)}",
    )

    limited = MemoryProvider(provider_config(limit=2), None)
    limited.client = FakeCRClient(
        search_hits=[
            {"id": f"k{i}", "summary": f"s{i}", "resolution": "r"} for i in range(5)
        ]
    )
    limited.init_memory("dev-01", None)
    check(
        "6.7 limit 生效（最多 2 行）",
        len(asyncio.run(limited.query_memory("x")).split("\n")) == 2,
    )


# ---------------------------------------------------------------------------
# 7) save_memory 全流程
# ---------------------------------------------------------------------------
def test_save_memory():
    full_msgs = [
        msg("system", "sys"),
        msg("user", "我偏好暖光"),
        msg("assistant", "好的"),
        msg("user", "我儿子叫小明"),
        msg("assistant", "记住了"),
        msg("user", "以后都这样"),
    ]
    short_msgs = [msg("user", "你好"), msg("assistant", "在的"), msg("user", "今天天气如何")]

    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(storage_mod, "get_project_dir", lambda: tmp + "/"):
            raw_path = os.path.join(
                tmp, "data", "context_recall", "dev-01_role-a", "turns.jsonl"
            )

            provider = MemoryProvider(provider_config(), None)
            client = FakeCRClient(import_result={"imported_memories": 3})
            provider.client = client
            llm = FakeLLM(SAMPLE_JSON)
            provider.init_memory("dev-01#role-a", llm)
            asyncio.run(provider.save_memory(full_msgs))

            check(
                "7.1 全流程 → import 被调用 1 次",
                len(client.import_calls) == 1,
                f"calls={len(client.import_calls)}",
            )
            body = client.import_calls[0]
            check(
                "7.2 快照 session.workspaceId=='xiaozhi' 且 nodes 非空",
                body["sessions"][0]["workspaceId"] == "xiaozhi"
                and len(body["nodes"]) >= 1
                and body["schemaVersion"] == 1,
                f"nodes={len(body['nodes'])}",
            )
            check(
                "7.3 每个节点 evidence 非空且 ⊆ session.turnIds",
                all(
                    n["evidenceTurnIds"]
                    and set(n["evidenceTurnIds"]) <= set(body["sessions"][0]["turnIds"])
                    for n in body["nodes"]
                ),
                f"turnIds={body['sessions'][0]['turnIds']}",
            )
            check(
                "7.4 摘要节点在首位（tags=['session-summary']）",
                body["nodes"][0]["tags"] == ["session-summary"]
                and body["nodes"][0]["kind"] == "workflow",
            )
            check(
                "7.5 LLM 收到对话原文与 turn id 列表",
                llm.calls
                and "我偏好暖光" in llm.calls[0]["user"]
                and body["turns"][0]["id"] in llm.calls[0]["user"],
            )
            with open(raw_path, "r", encoding="utf-8") as file:
                raw_lines = [line for line in file.read().split("\n") if line.strip()]
            check(
                "7.6 raw turns 已写（5 条，跳过 system）",
                len(raw_lines) == 5
                and json.loads(raw_lines[0])["role"] == "user"
                and json.loads(raw_lines[0])["text"] == "我偏好暖光",
                f"lines={len(raw_lines)}",
            )
            check(
                "7.7 推送成功 → outbox 为空",
                provider.outbox.pending_count() == 0,
                f"pending={provider.outbox.pending_count()}",
            )

            provider2 = MemoryProvider(provider_config(), None)
            client2 = FakeCRClient(import_result={"imported_memories": 1})
            provider2.client = client2
            provider2.init_memory("dev-01#role-a", FakeLLM(SAMPLE_JSON))
            asyncio.run(provider2.save_memory(short_msgs))
            check(
                "7.8 <3 轮用户发言 → 不组织、不 import",
                client2.import_calls == [] and provider2.llm.calls == [],
                f"import_calls={len(client2.import_calls)}, llm_calls={len(provider2.llm.calls)}",
            )
            with open(raw_path, "r", encoding="utf-8") as file:
                raw_lines2 = [line for line in file.read().split("\n") if line.strip()]
            check(
                "7.9 <3 轮仍写本地 raw turns（5+3=8 条）",
                len(raw_lines2) == 8,
                f"lines={len(raw_lines2)}",
            )

            provider3 = MemoryProvider(provider_config(), None)
            provider3.client = FakeCRClient(import_result=None)
            provider3.init_memory("dev-01#role-a", FakeLLM(SAMPLE_JSON))
            asyncio.run(provider3.save_memory(full_msgs))
            check(
                "7.10 推送失败 → 落 outbox 保留 1 条",
                provider3.outbox.pending_count() == 1,
                f"pending={provider3.outbox.pending_count()}",
            )
            provider3.client = FakeCRClient(import_result={"imported_memories": 1})
            asyncio.run(provider3.save_memory(full_msgs))
            check(
                "7.11 下次保存成功 → outbox 补投清空",
                provider3.outbox.pending_count() == 0,
                f"pending={provider3.outbox.pending_count()}",
            )

            disabled = MemoryProvider(provider_config(service_url=""), None)
            client4 = FakeCRClient(import_result={"imported_memories": 1})
            disabled.client = client4
            disabled.init_memory("dev-01#role-a", FakeLLM(SAMPLE_JSON))
            asyncio.run(disabled.save_memory(full_msgs))
            with open(raw_path, "r", encoding="utf-8") as file:
                raw_lines3 = [line for line in file.read().split("\n") if line.strip()]
            check(
                "7.12 service_url 空 → 不推送、不写 outbox，但 raw turns 仍落盘（23 条）",
                client4.import_calls == []
                and disabled.outbox.pending_count() == 0
                and len(raw_lines3) == 23,
                f"lines={len(raw_lines3)}",
            )

            provider4 = MemoryProvider(provider_config(), None)
            provider4.client = FakeCRClient(import_exc=RuntimeError("boom"))
            provider4.init_memory("dev-01#role-a", FakeLLM(SAMPLE_JSON))
            asyncio.run(provider4.save_memory(full_msgs))
            check(
                "7.13 客户端抛异常 → 也落 outbox（不丢数据）",
                provider4.outbox.pending_count() == 1,
                f"pending={provider4.outbox.pending_count()}",
            )


# ---------------------------------------------------------------------------
# 8) config.yaml 配置块（只校验本波新增内容 + 未动 selected_module.Memory）
# ---------------------------------------------------------------------------
def test_config_yaml():
    import yaml

    with open(os.path.join(_PROJECT_ROOT, "config.yaml"), "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    block = (config.get("Memory") or {}).get("context_recall") or {}
    check(
        "8.1 Memory.context_recall 配置块存在且字段正确",
        block.get("type") == "context_recall"
        and block.get("service_url") == "http://127.0.0.1:8765"
        and block.get("workspace_id") == "xiaozhi"
        and block.get("scope_fallback") == "none"
        and block.get("min_similarity") == 0.35
        and block.get("limit") == 6
        and block.get("timeout") == 2.5
        and block.get("min_user_turns") == 3,
        f"{block}",
    )
    check(
        "8.2 selected_module.Memory 保持 nomem 不动",
        config["selected_module"]["Memory"] == "nomem",
        config["selected_module"]["Memory"],
    )


# ---------------------------------------------------------------------------
# 9) 加载器约定：core.utils.memory.create_instance("context_recall", ...)
# ---------------------------------------------------------------------------
def test_loader():
    from core.utils import memory as memory_utils

    instance = memory_utils.create_instance(
        "context_recall", provider_config(service_url=""), None
    )
    check(
        "9.1 create_instance 按约定加载 provider",
        isinstance(instance, MemoryProvider) and instance.enabled is False,
        f"{type(instance).__name__}",
    )
    provider = MemoryProvider(provider_config(service_url=""), None)
    provider.init_memory(
        "dev-01#role-a", None, summary_memory="历史摘要", save_to_file=True
    )
    check(
        "9.2 init_memory 兼容 connection.py 的 kwargs（summary_memory/save_to_file）",
        provider.role_id == "dev-01#role-a" and provider.llm is None,
    )


# ---------------------------------------------------------------------------
# 10) init_memory 的 outbox 补投与角色切换重建
# ---------------------------------------------------------------------------
def test_init_memory():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.object(storage_mod, "get_project_dir", lambda: tmp + "/"):
            seed = MemoryProvider(provider_config(), None)
            seed.client = FakeCRClient(import_result=None)
            seed.init_memory("dev-01#role-a", None)
            seed.outbox.put(
                {"schemaVersion": 1, "sessions": [{"id": "sess-init-1"}], "turns": [],
                 "nodes": [], "edges": []}
            )

            provider = MemoryProvider(provider_config(), None)
            provider.client = FakeCRClient(import_result={"imported_memories": 1})

            async def scenario():
                # 运行中的事件循环 → _best_effort_flush 应 create_task 后台补投
                provider.init_memory("dev-01#role-a", None)
                await asyncio.sleep(0.05)

            asyncio.run(scenario())
            check(
                "10.1 init_memory 在事件循环内后台补投 outbox（pending → 0）",
                provider.outbox.pending_count() == 0,
                f"pending={provider.outbox.pending_count()}",
            )

            sync_provider = MemoryProvider(provider_config(), None)
            sync_provider.client = FakeCRClient()
            sync_provider.init_memory("dev-01#role-a", None)  # 同步上下文：不应抛
            check("10.2 同步上下文调用 init_memory 不抛异常", True)

            sync_provider.init_memory("dev-02#role-b", None)
            check(
                "10.3 角色切换按新 role_id 重建存储目录",
                "dev-02_role-b" in sync_provider.raw_store.base_dir
                and "dev-02_role-b" in sync_provider.outbox.dir,
                sync_provider.raw_store.base_dir,
            )


def main():
    print("=" * 60)
    print("context_recall provider 自跑测试（无 pytest / 无网络 / 无真实 LLM）")
    print("=" * 60)
    run("1 organizer 正常 JSON", test_organizer_normal)
    run("2 organizer 降级", test_organizer_fallback)
    run("3 CRClient 降级", test_cr_client_degrade)
    run("4 snapshot", test_snapshot)
    run("5 storage", test_storage)
    run("6 query_memory", test_query_memory)
    run("7 save_memory", test_save_memory)
    run("8 config.yaml", test_config_yaml)
    run("9 加载器约定", test_loader)
    run("10 init_memory", test_init_memory)

    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    print("-" * 60)
    print(f"结果：{passed}/{total} 通过")
    if passed != total:
        for name, ok in RESULTS:
            if not ok:
                print(f"  失败: {name}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
