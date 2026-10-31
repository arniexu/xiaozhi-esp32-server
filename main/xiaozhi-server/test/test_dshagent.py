#!/usr/bin/env python3
"""dshagent provider 自测：用假 ACP agent 跑通「文本进 → 文本出」。

运行：cd main/xiaozhi-server && .venv/bin/python test/test_dshagent.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.providers.llm.dshagent.dshagent import LLMProvider  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, "fake_acp_agent.py")


def _collect(provider, session_id, text):
    dialogue = [{"role": "user", "content": text}]
    return "".join(provider.response(session_id, dialogue))


def main():
    workspace = tempfile.mkdtemp(prefix="dshagent-test-")
    provider = LLMProvider(
        {
            "command": [sys.executable, FAKE],
            "workspace": workspace,
            "timeout": 30,
            "chunk_timeout": 10,
        }
    )
    failures = []

    first = _collect(provider, "device-1", "你好小智")
    expected_first = "收到：你好小智（第 1 次）"
    if first != expected_first:
        failures.append(f"第一次回复不符：{first!r} != {expected_first!r}")

    second = _collect(provider, "device-1", "今天天气怎么样")
    expected_second = "收到：今天天气怎么样（第 2 次）"
    if second != expected_second:
        failures.append(f"第二次回复不符：{second!r} != {expected_second!r}")

    # 另一个设备要拿到独立进程（计数从 1 开始）
    other = _collect(provider, "device-2", "早上好")
    if other != "收到：早上好（第 1 次）":
        failures.append(f"设备隔离失效：{other!r}")

    # 空文本不应发起请求
    empty = "".join(provider.response("device-1", [{"role": "user", "content": "   "}]))
    if empty != "":
        failures.append(f"空文本产生了回复：{empty!r}")

    # 预热：进程/会话应在用户开口前就建好，且不重复建
    if not provider.prewarm("device-3"):
        failures.append("prewarm 返回 False")
    warm_sessions = len(provider._sessions)
    if provider._sessions.get("device-3") is None:
        failures.append("prewarm 之后 device-3 没有会话")
    provider.prewarm("device-3")  # 幂等
    if len(provider._sessions) != warm_sessions:
        failures.append("重复 prewarm 建了多余会话")
    reply3 = _collect(provider, "device-3", "预热后第一句")
    if reply3 != "收到：预热后第一句（第 1 次）":
        failures.append(f"预热会话首句不符：{reply3!r}")

    # 立即应答：agent 慢于 ack_delay 时，第一句必须是 ack，然后才是正文
    slow_provider = LLMProvider(
        {
            "command": [sys.executable, FAKE],
            "workspace": workspace,
            "timeout": 30,
            "chunk_timeout": 10,
            "ack_delay": 0.5,
            "ack_text": "嗯，我看看啊。",
        }
    )
    os.environ["FAKE_ACP_DELAY"] = "2"
    try:
        chunks = list(
            slow_provider.response("device-slow", [{"role": "user", "content": "我想想"}])
        )
        if not chunks or chunks[0] != "嗯，我看看啊。":
            failures.append(f"慢 agent 没有先回应答：{chunks[:2]!r}")
        elif "收到：我想想" not in "".join(chunks):
            failures.append(f"应答之后没有正文：{''.join(chunks)!r}")
        else:
            print(f"  ack 用例通过：先「{chunks[0]}」再正文")
    finally:
        os.environ.pop("FAKE_ACP_DELAY", None)
        slow_provider.close()

    provider.close()

    if failures:
        print("FAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("PASS 6/6  (首轮/二轮/设备隔离/空文本/预热/立即应答)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
