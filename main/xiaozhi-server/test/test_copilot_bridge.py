# -*- coding: utf-8 -*-
"""Copilot 桥接测试：不依赖真实 VS Code 扩展（用本地假桥接 WS 服务）。

运行：cd main/xiaozhi-server && .venv/bin/python test/test_copilot_bridge.py

覆盖：
1. 关键词匹配/剥离（大小写、空格、中英标点）
2. 进入模式（带首问 / 仅触发词）与退出模式
3. 模式内转发 → 假桥接 → TTS 队列流式信封断言（FIRST/TEXT…/LAST）
4. 桥接不可达 → 降级播报
5. 未启用 / 系统伪输入（source）不介入
"""

import asyncio
import json
import os
import queue
import socket
import sys
import threading
import time

# ---------------------------------------------------------------------------
# 环境加固（同 test_context_recall_provider.py 套路，仅本进程，不改仓库文件）
# ---------------------------------------------------------------------------
# 1) 企业代理环境变量会让 localhost 连接走代理（历史已踩坑）：清空常见变量，
#    并故意保留一个 socks_proxy 作为回归——桥接客户端必须显式禁用环境代理（websockets>=15）
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["socks_proxy"] = "socks://invalid-proxy.example:1080/"  # 回归：必须仍能直连 127.0.0.1

# 2) 脚本方式运行时把项目根加入 sys.path 并切到项目根
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

# 3) 应用模块导入链可能触发 config.logger → load_config 真实请求 manager-api
#    （本机 data/.config.yaml 指向的 API 已失效）；测试不依赖真实配置：
#    让 load_config 只合并本地 config.yaml（不访问 API），check_config_file 空转。
import config.config_loader as _config_loader  # noqa: E402
import config.settings as _config_settings  # noqa: E402


def _local_load_config():
    project_dir = _config_loader.get_project_dir()
    base = _config_loader.read_config(project_dir + "config.yaml")
    custom_path = project_dir + "data/.config.yaml"
    custom = _config_loader.read_config(custom_path) if os.path.exists(custom_path) else {}
    custom.pop("manager-api", None)
    return _config_loader.merge_configs(base, custom)


_config_loader.load_config = _local_load_config
_config_settings.check_config_file = lambda: None

from core.handle import copilotHandle as bridge  # noqa: E402
from core.providers.tts.dto.dto import (  # noqa: E402
    ContentType,
    SentenceType,
    TTSMessageDTO,
)

CFG = {
    "enabled": True,
    "url": "ws://127.0.0.1:8767",
    "connect_timeout": 1,
    "reply_timeout": 5,
    "enter_keywords": ["问copilot", "问一下copilot", "找copilot"],
    "exit_keywords": ["退出copilot", "结束copilot"],
}

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    mark = "✓" if cond else "✗"
    print(f"  [{mark}] {name}" + (f"  <- {detail}" if detail and not cond else ""))


# ---------------- 桩对象 ----------------

class FakeLogger:
    def bind(self, **kwargs):
        return self

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


class FakeTTS:
    def __init__(self):
        self.tts_text_queue = queue.Queue()

    def tts_one_sentence(self, conn, content_type, content_detail=None, content_file=None, sentence_id=None):
        self.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=sentence_id or conn.sentence_id,
                sentence_type=SentenceType.MIDDLE,
                content_type=content_type,
                content_detail=content_detail,
            )
        )


class SyncExecutor:
    """测试用：submit 同步执行（等价于等待转发线程完成）。"""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


class FakeConn:
    def __init__(self, cfg):
        self.config = {"copilot_bridge": dict(cfg)}
        self.logger = FakeLogger()
        self.tts = FakeTTS()
        self.executor = SyncExecutor()
        self.headers = {"device-id": "aa:bb:cc:dd:ee:ff"}
        self.sentence_id = "sid-test"
        self.client_abort = False
        self.llm_finish_task = False
        self.stop_event = threading.Event()
        self.cmd_exit = []
        self.stt_messages = []
        self.cleared = 0
        self.copilot_mode = False

    def clear_queues(self):
        self.cleared += 1
        while not self.tts.tts_text_queue.empty():
            try:
                self.tts.tts_text_queue.get_nowait()
            except queue.Empty:
                break

    def close(self):
        pass


async def fake_send_stt(conn, text):
    conn.stt_messages.append(text)


def drain(conn):
    items = []
    while not conn.tts.tts_text_queue.empty():
        m = conn.tts.tts_text_queue.get_nowait()
        items.append((m.sentence_type, m.content_type, m.content_detail))
    return items


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_fake_bridge(port):
    """假扩展桥接：收到 request 后回两个 chunk + done。"""

    def handler(ws):
        msg = json.loads(ws.recv())
        rid = msg.get("request_id")
        ws.send(json.dumps({"type": "chunk", "request_id": rid, "text": "你好，"}))
        ws.send(json.dumps({"type": "chunk", "request_id": rid, "text": "这是 Copilot 的回答。"}))
        ws.send(json.dumps({"type": "done", "request_id": rid, "text": "你好，这是 Copilot 的回答。"}))

    from websockets.sync.server import serve

    server = serve(handler, "127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)  # 等监听就绪
    return server


# ---------------- 各节测试 ----------------

def test_matching():
    print("[1] 关键词匹配与剥离")
    compact = bridge._compact("问一下 Copilot，今天天气怎么样？")
    check("去噪匹配", compact == "问一下copilot今天天气怎么样", compact)
    kws = bridge._compact_keywords(CFG["enter_keywords"])
    matched = bridge._match_prefix(compact, kws)
    check("前缀命中", matched == "问一下copilot", str(matched))
    remainder = bridge._strip_prefix("问一下 Copilot，今天天气怎么样？", matched)
    check("剥离剩余", remainder == "今天天气怎么样", repr(remainder))
    check("大小写/空格兼容", bridge._compact("Co Pilot") == "copilot")
    check("不命中", bridge._match_prefix(bridge._compact("今天天气怎么样"), kws) is None)


def test_enter_with_query(port):
    print("[2] 进入模式（带首问）→ 流式播报信封")
    conn = FakeConn({**CFG, "url": f"ws://127.0.0.1:{port}"})
    handled = asyncio.run(bridge.maybe_handle_copilot_message(conn, "问一下 Copilot，今天天气怎么样？"))
    check("已被接管", handled is True)
    check("模式已开", conn.copilot_mode is True)
    check("STT 回显", conn.stt_messages == ["问一下 Copilot，今天天气怎么样？"])
    items = drain(conn)
    kinds = [(s, c) for s, c, _ in items]
    check(
        "信封序列 FIRST→TEXT→…→LAST",
        kinds
        == [
            (SentenceType.FIRST, ContentType.ACTION),
            (SentenceType.MIDDLE, ContentType.TEXT),
            (SentenceType.MIDDLE, ContentType.TEXT),
            (SentenceType.LAST, ContentType.ACTION),
        ],
        str(kinds),
    )
    texts = "".join(t for s, c, t in items if c == ContentType.TEXT and t)
    check("流式内容拼接", texts == "你好，这是 Copilot 的回答。", texts)
    return conn


def test_in_mode_forward(port):
    print("[3] 模式内追问（多轮转发）")
    conn = FakeConn({**CFG, "url": f"ws://127.0.0.1:{port}"})
    conn.copilot_mode = True
    handled = asyncio.run(bridge.maybe_handle_copilot_message(conn, "那明天呢"))
    check("已被接管", handled is True)
    items = drain(conn)
    texts = "".join(t for s, c, t in items if c == ContentType.TEXT and t)
    check("转发并播报", texts == "你好，这是 Copilot 的回答。", texts)


def test_enter_only():
    print("[4] 仅触发词进入（无问题）")
    conn = FakeConn(dict(CFG))
    handled = asyncio.run(bridge.maybe_handle_copilot_message(conn, "问 Copilot"))
    check("已被接管", handled is True)
    check("模式已开", conn.copilot_mode is True)
    items = drain(conn)
    ack = [t for s, c, t in items if c == ContentType.TEXT and t]
    check("提示语播报", ack == ["好，我在，直接问吧"], str(ack))


def test_exit():
    print("[5] 退出模式")
    conn = FakeConn(dict(CFG))
    conn.copilot_mode = True
    handled = asyncio.run(bridge.maybe_handle_copilot_message(conn, "退出 Copilot"))
    check("已被接管", handled is True)
    check("模式已关", conn.copilot_mode is False)
    check("队列已清理", conn.cleared == 1, str(conn.cleared))
    check("进行中转发已作废", getattr(conn, "_copilot_active_request", "x") is None)
    items = drain(conn)
    ack = [t for s, c, t in items if c == ContentType.TEXT and t]
    check("退出口播报", ack == ["好的，已退出 Copilot"], str(ack))
    check(
        "退出口信封 LAST 收尾",
        items[-1][0] == SentenceType.LAST,
        str(items[-1] if items else None),
    )


def test_unreachable():
    print("[6] 桥接不可达 → 降级播报")
    port = free_port()  # 无监听
    conn = FakeConn({**CFG, "url": f"ws://127.0.0.1:{port}", "connect_timeout": 0.5})
    handled = asyncio.run(bridge.maybe_handle_copilot_message(conn, "问 Copilot 在吗"))
    check("已被接管", handled is True)
    items = drain(conn)
    texts = "".join(t for s, c, t in items if c == ContentType.TEXT and t)
    check("播报降级提示", "没连上" in texts, texts)


def test_disabled_and_source():
    print("[7] 未启用 / 系统伪输入不介入")
    conn = FakeConn({**CFG, "enabled": False})
    handled = asyncio.run(bridge.maybe_handle_copilot_message(conn, "问 Copilot 你好"))
    check("未启用不接管", handled is False and conn.copilot_mode is False)
    conn2 = FakeConn(dict(CFG))
    handled2 = asyncio.run(bridge.maybe_handle_copilot_message(conn2, "问 Copilot 你好", source="system"))
    check("系统伪输入不接管", handled2 is False and conn2.copilot_mode is False)


def main():
    bridge.send_stt_message = fake_send_stt  # 桩掉设备侧 STT 发送

    port = free_port()
    server = start_fake_bridge(port)
    try:
        test_matching()
        test_enter_with_query(port)
        test_in_mode_forward(port)
        test_enter_only()
        test_exit()
        test_unreachable()
        test_disabled_and_source()
    finally:
        server.shutdown()

    total, ok = len(RESULTS), sum(RESULTS)
    print(f"\n结果：{ok}/{total} 通过")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
