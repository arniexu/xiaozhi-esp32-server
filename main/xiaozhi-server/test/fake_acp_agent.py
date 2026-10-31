#!/usr/bin/env python3
"""假的 ACP agent：不需要 DSH 就能验证客户端协议实现。

行为：
  initialize      → 回 {protocolVersion:1, agentCapabilities:{}}
  session/new     → 回固定 sessionId
  session/prompt  → 先发一次 session/request_permission（验证自动应答），
                    再按字面回显，最后回 {stopReason:"end_turn"}

用法：python test/fake_acp_agent.py
"""

import json
import os
import sys
import time

SESSION_ID = "fake-session-1"
_state = {"prompt_count": 0}


def _send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _respond(request_id, result):
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id, code, message):
    _send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def _ask_permission():
    """发一个权限请求，读回客户端的选择。"""
    request_id = "perm-1"
    _send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "session/request_permission",
            "params": {
                "sessionId": SESSION_ID,
                "toolCall": {"toolCallId": "call-1", "title": "fake tool"},
                "options": [
                    {"optionId": "allow", "name": "允许", "kind": "allow_once"},
                    {"optionId": "deny", "name": "拒绝", "kind": "reject_once"},
                ],
            },
        }
    )
    reply = json.loads(sys.stdin.readline())
    outcome = (reply.get("result") or {}).get("outcome") or {}
    return outcome.get("optionId")


def _handle_prompt(request_id, params):
    delay = float(os.environ.get("FAKE_ACP_DELAY", "0"))
    if delay:
        time.sleep(delay)  # 模拟 agent 思考，用来验证“先给应答”
    text = "".join(
        block.get("text", "")
        for block in params.get("prompt") or []
        if block.get("type") == "text"
    )
    _state["prompt_count"] += 1

    chosen = _ask_permission()
    print(f"[fake] permission -> {chosen}", file=sys.stderr, flush=True)

    reply = f"收到：{text}（第 {_state['prompt_count']} 次）"
    # 分片下发，模拟流式
    for index in range(0, len(reply), 4):
        _send(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": SESSION_ID,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": reply[index : index + 4]},
                    },
                },
            }
        )
    # 夹一个非正文的 update，确认客户端会丢掉
    _send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": SESSION_ID,
                "update": {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"type": "text", "text": "（这里是想事情，不该念）"},
                },
            },
        }
    )
    _respond(request_id, {"stopReason": "end_turn"})


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        message = json.loads(raw)
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if request_id is None:
            continue
        if method == "initialize":
            _respond(request_id, {"protocolVersion": 1, "agentCapabilities": {}})
        elif method == "session/new":
            _respond(request_id, {"sessionId": SESSION_ID})
        elif method == "session/prompt":
            _handle_prompt(request_id, params)
        elif method == "session/cancel":
            pass
        else:
            _error(request_id, -32601, f"unknown method {method}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
