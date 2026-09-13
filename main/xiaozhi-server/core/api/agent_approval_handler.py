"""授权中继端点：POST /api/agent/approval 与 /api/agent/approval/cancel。

契约见 ``/home/xuqj/authentication/docs/xiaozhi-relay-contract.md``（v2）。
本模块只做“中转 + 干扰抑制”：

1. 校验 v2 请求（回带 ``request_id`` / ``input_sha256`` 供插件防重放）；
2. 找到设备在线连接，通过设备 MCP 工具 ``auth_approval`` 下发授权卡并 await 结果；
3. 设备工具返回值里的 ``decision`` 才是最终决定，服务器不自己 resolve。

设备空闲时 WebSocket 不连（固件设计），因此本波只支持“会话内推送”。
"""

import json
import hmac
import time
import uuid
from datetime import datetime

from aiohttp import web
from config.logger import setup_logging

from core.agent_approval import approval_manager

TAG = __name__

PROTOCOL = "authentication/xiaozhi-relay"
VERSION = 2
DEVICE_TOOL_NAME = "auth_approval"  # 设备注册 auth.approval -> sanitize 后
DANGERS = {"high", "medium", "normal", "unknown"}

# deadline_at 剩余时间要预留的回吐/回落余量（秒）
DEADLINE_MARGIN_S = 2
MIN_WAIT_S = 1
MAX_WAIT_S = 120


def _is_valid_sha256(value) -> bool:
    """契约要求 64 位小写十六进制。"""
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in "0123456789abcdef" for ch in value)


def _parse_iso8601(value):
    """解析 ISO8601（兼容 py3.10 的 ``Z`` 后缀），失败返回 ``None``。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class AgentApprovalHandler:
    def __init__(self, config: dict, ws_server=None):
        self.config = config
        self.logger = setup_logging()
        self.ws_server = ws_server
        self.auth_key = config.get("server", {}).get("auth_key", "")

    # ------------------------------------------------------------------ utils
    def _json(self, body: dict, status: int = 200) -> web.Response:
        response = web.Response(
            text=json.dumps(body, ensure_ascii=False),
            content_type="application/json",
            status=status,
        )
        self._add_cors_headers(response)
        return response

    def _error(self, status: int, message: str) -> web.Response:
        return self._json({"error": message}, status=status)

    def _add_cors_headers(self, response):
        response.headers["Access-Control-Allow-Headers"] = (
            "client-id, content-type, device-id, authorization"
        )
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"

    def _verify_auth(self, request) -> bool:
        """``Authorization: Bearer <server.auth_key>`` 常量时间比较。"""
        if not self.auth_key:
            return False
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[len("Bearer "):]
        return hmac.compare_digest(token, self.auth_key)

    def _collect_online_connections(self):
        if self.ws_server is None:
            return []
        connections = getattr(self.ws_server, "active_connections", None) or []
        return [
            conn for conn in connections if getattr(conn, "device_id", None)
        ]

    def _find_connection(self, device_id):
        """带 device_id 按它找；不带则要求唯一在线设备。找不到/多个返回 None。"""
        online = self._collect_online_connections()
        if device_id:
            for conn in online:
                if conn.device_id == device_id:
                    return conn
            return None
        if len(online) == 1:
            return online[0]
        return None

    def _validate_payload(self, payload):
        """返回错误信息字符串；合法返回 ``None``。"""
        if not isinstance(payload, dict):
            return "invalid body"
        if payload.get("protocol") != PROTOCOL:
            return "invalid protocol"
        if payload.get("version") != VERSION:
            return "invalid version"
        for field in ("request_id", "tool", "detail"):
            value = payload.get(field)
            if not isinstance(value, str) or not value:
                return f"invalid {field}"
        if payload.get("danger") not in DANGERS:
            return "invalid danger"
        timeout_ms = payload.get("timeout_ms")
        # bool 是 int 子类，需显式排除
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            return "invalid timeout_ms"
        if timeout_ms <= 0:
            return "invalid timeout_ms"
        if not _is_valid_sha256(payload.get("input_sha256")):
            return "invalid input_sha256"
        device_id = payload.get("device_id")
        if device_id is not None and not isinstance(device_id, str):
            return "invalid device_id"
        return None

    def _compute_wait_seconds(self, payload):
        """返回 (wait_s, expired)。expired=True 表示 deadline_at 已过。"""
        timeout_s = payload["timeout_ms"] / 1000.0
        deadline = _parse_iso8601(payload.get("deadline_at"))
        if deadline is None:
            remaining = timeout_s
        else:
            remaining = (deadline.timestamp() - time.time())
        if remaining <= 0:
            return 0, True
        wait_s = remaining - DEADLINE_MARGIN_S
        if wait_s < MIN_WAIT_S:
            wait_s = MIN_WAIT_S
        elif wait_s > MAX_WAIT_S:
            wait_s = MAX_WAIT_S
        return wait_s, False

    @staticmethod
    def _parse_device_result(raw):
        """从设备 MCP 结果里解析 ``{"decision":..., "reason":...}``。"""
        text = None
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, dict):
            content = raw.get("content")
            if (
                isinstance(content, list)
                and content
                and isinstance(content[0], dict)
                and "text" in content[0]
            ):
                text = content[0]["text"]
            else:
                text = raw.get("text")
        if text is None:
            return None, None
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None, None
        if not isinstance(data, dict):
            return None, None
        decision = data.get("decision")
        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            reason = str(reason)
        return decision, reason

    def _speak(self, conn, text):
        """best-effort 语音提示；失败不影响主流程。"""
        try:
            if not getattr(conn, "sentence_id", None):
                conn.sentence_id = str(uuid.uuid4().hex)
            from core.handle.intentHandler import speak_txt

            speak_txt(conn, text)
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"授权请求语音提示失败: {e}")

    # --------------------------------------------------------------- 主端点
    async def handle_post(self, request):
        if not self._verify_auth(request):
            return self._error(401, "unauthorized")

        try:
            payload = await request.json()
        except Exception:
            return self._error(400, "invalid json")

        error = self._validate_payload(payload)
        if error:
            return self._error(400, error)

        request_id = payload["request_id"]
        input_sha256 = payload["input_sha256"]
        danger = payload["danger"]

        conn = self._find_connection(payload.get("device_id"))
        if conn is None:
            return self._error(503, "device offline")

        device_id = conn.device_id
        if approval_manager.is_busy(device_id):
            return self._error(409, "busy")

        wait_s, expired = self._compute_wait_seconds(payload)
        if expired:
            # 契约不变量：deadline_at 之后必须丢弃，不弹卡、不回决定
            return self._error(504, "timeout")

        if not approval_manager.register(device_id, request_id, danger):
            return self._error(409, "busy")

        try:
            # b. best-effort 语音提示“请在屏幕上处理”
            self._speak(conn, "收到一条授权请求，请在屏幕上处理")

            # c. 确认设备 MCP 就绪且注册了授权工具
            mcp_client = getattr(conn, "mcp_client", None)
            if mcp_client is None or not await mcp_client.is_ready():
                return self._error(503, "device offline")
            if not mcp_client.has_tool(DEVICE_TOOL_NAME):
                self.logger.bind(tag=TAG).warning(
                    f"设备未注册 {DEVICE_TOOL_NAME} 工具: {device_id}"
                )
                return self._error(503, "device offline")

            options = payload.get("options")
            if not isinstance(options, list):
                options = ["allow", "deny"]
            args = {
                "request_id": request_id,
                "title": payload.get("title") or payload["tool"],
                "detail": payload["detail"],
                "danger": danger,
                "timeout_ms": int(payload["timeout_ms"]),
                "options": json.dumps(options),
            }

            # 延迟导入，避免 http_server 加载期就拉起 ASR/TTS 依赖链
            from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool

            raw = await call_mcp_tool(
                conn,
                mcp_client,
                DEVICE_TOOL_NAME,
                json.dumps(args, ensure_ascii=False),
                timeout=wait_s,
            )
        except TimeoutError:
            return self._error(504, "timeout")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"授权请求下发失败: {e}")
            return self._error(503, "device unavailable")
        finally:
            approval_manager.remove(request_id)

        decision, reason = self._parse_device_result(raw)
        if decision in ("allow", "deny"):
            if not reason:
                reason = "用户在小智设备上批准" if decision == "allow" else "用户在小智设备上拒绝"
            return self._json(
                {
                    "decision": decision,
                    "reason": reason,
                    "version": VERSION,
                    "request_id": request_id,
                    "input_sha256": input_sha256,
                    "by": "device",
                }
            )
        if decision == "timeout":
            return self._error(504, "timeout")
        if decision == "busy":
            return self._error(409, "busy")
        self.logger.bind(tag=TAG).warning(f"无法识别的设备授权结果: {raw!r}")
        return self._error(503, "invalid device response")

    # --------------------------------------------------------------- 取消端点
    async def handle_cancel(self, request):
        if not self._verify_auth(request):
            return self._error(401, "unauthorized")

        try:
            payload = await request.json()
        except Exception:
            return self._error(400, "invalid json")
        if not isinstance(payload, dict):
            return self._error(400, "invalid body")
        if payload.get("protocol") not in (None, PROTOCOL):
            return self._error(400, "invalid protocol")
        if payload.get("version") not in (None, VERSION):
            return self._error(400, "invalid version")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return self._error(400, "invalid request_id")

        # 设备卡片当前无撤卡通道，只能标记取消（设备端会自行倒计时结束）
        approval_manager.cancel(request_id)
        return self._json({})

    # -------------------------------------------------------------- CORS 预检
    async def handle_options(self, request):
        response = web.Response(status=204)
        self._add_cors_headers(response)
        return response
