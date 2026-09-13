"""授权审批上下文管理（单例）。

设备端一次只展示一张授权卡，因此本模块按 ``device_id`` 维护“每设备一条待决上下文”：

    {request_id, danger, created_at, cancelled}

- HTTP 端点（``core/api/agent_approval_handler.py``）在向设备下发 tools/call 前
  ``register``，在 ``finally`` 中 ``remove``；
- ASR 路径（``core/handle/receiveAudioHandle.py``）用 ``find(conn)`` 判断当前设备
  是否有待决授权，从而做“批准/拒绝”关键词拦截（仅提示，不 resolve 决定）。

关键词表两端逐字一致：去空格/标点后做子串匹配（见 ``match_decision``）。
"""

import re
import time
import threading

# 批准 / 拒绝关键词表（与固件端逐字一致，禁止单方面改动）
APPROVE_KEYWORDS = ("批准", "同意", "允许", "approve", "allow")
DENY_KEYWORDS = ("拒绝", "不行", "取消", "不允许", "不同意", "deny", "reject")

_NORMALIZE_RE = re.compile(r"[\s\W]+", re.UNICODE)


def normalize_text(text) -> str:
    """去除空格与标点后转小写，便于子串匹配。"""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return _NORMALIZE_RE.sub("", text).lower()


def match_decision(text):
    """命中返回 ``"allow"`` / ``"deny"``，未命中返回 ``None``。

    拒绝优先：同时出现批准与拒绝词时按更安全的“拒绝”处理。
    """
    normalized = normalize_text(text)
    if not normalized:
        return None
    for keyword in DENY_KEYWORDS:
        if keyword in normalized:
            return "deny"
    for keyword in APPROVE_KEYWORDS:
        if keyword in normalized:
            return "allow"
    return None


class ApprovalManager:
    """每设备一条待决授权的单例管理器。

    运行在同一个事件循环内（HTTP handler 与 WebSocket handler 同进程），
    但仍用 ``threading.Lock`` 保护字典，避免误用。
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init_state()
                    cls._instance = instance
        return cls._instance

    def _init_state(self):
        self._pending = {}  # device_id -> pending dict
        self._lock = threading.Lock()

    def register(self, device_id: str, request_id: str, danger: str,
                 created_at=None) -> bool:
        """登记待决上下文；该设备已有待决时返回 ``False``（busy）。"""
        if not device_id:
            return False
        with self._lock:
            if device_id in self._pending:
                return False
            self._pending[device_id] = {
                "request_id": request_id,
                "danger": danger,
                "created_at": created_at if created_at is not None else time.time(),
                "cancelled": False,
            }
            return True

    def find(self, conn):
        """按连接对象（``conn.device_id``）找待决上下文；没有返回 ``None``。"""
        device_id = getattr(conn, "device_id", None)
        if not device_id:
            return None
        with self._lock:
            pending = self._pending.get(device_id)
            return dict(pending) if pending else None

    def get(self, device_id: str):
        """按 device_id 找待决上下文（副本）；没有返回 ``None``。"""
        with self._lock:
            pending = self._pending.get(device_id)
            return dict(pending) if pending else None

    def is_busy(self, device_id: str) -> bool:
        if not device_id:
            return False
        with self._lock:
            return device_id in self._pending

    def remove(self, request_id: str):
        """按 request_id 移除待决上下文，返回被移除的副本（无则 ``None``）。"""
        with self._lock:
            for device_id, pending in list(self._pending.items()):
                if pending["request_id"] == request_id:
                    del self._pending[device_id]
                    return dict(pending)
        return None

    def cancel(self, request_id: str) -> bool:
        """标记待决上下文已取消（设备卡片当前无撤卡通道，仅作标记）。"""
        with self._lock:
            for pending in self._pending.values():
                if pending["request_id"] == request_id:
                    pending["cancelled"] = True
                    return True
        return False

    def clear(self):
        """仅供测试/排障：清空所有待决上下文。"""
        with self._lock:
            self._pending.clear()


# 单例（模块级引用）
approval_manager = ApprovalManager()
