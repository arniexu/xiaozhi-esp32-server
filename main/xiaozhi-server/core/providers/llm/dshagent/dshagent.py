"""小智服务端 → 本机 DSH agent 的 LLM 适配器。

数据流：
    设备语音 → ASR 文本 → 本适配器（ACP 发给 `dsh --profile <elder 类档>`）
    → agent 组织出的回复文本 → 交回服务端 → TTS → 设备播报

设计取舍：
* 一台设备一个常驻 agent 子进程 + 一个 ACP 会话，进程启动成本只付一次；
  长时间不用的会话按 idle_timeout 回收。
* 只转发用户最后一句话；多轮上下文由 agent 自己的会话记忆负责，
  服务端这边的 dialogue / 记忆不再回灌，避免两套记忆打架。
* 工具调用、思考过程不进 TTS：只取 agent_message_chunk 的正文。
"""

import os
import shlex
import threading
import time
from typing import Dict, Iterator, Tuple

from config.logger import setup_logging
from core.providers.llm.base import LLMProviderBase

from .acp_client import AcpClient, AcpError, AcpTimeout

TAG = __name__
logger = setup_logging()

DEFAULT_COMMAND = "dsh --profile elder_helper_acp"
DEFAULT_FALLBACK = "抱歉，我这边暂时连不上，等会儿再问一次好吗？"


class _AgentSession:
    """一条设备会话：agent 子进程 + ACP sessionId。"""

    def __init__(self, client: AcpClient, session_id: str) -> None:
        self.client = client
        self.session_id = session_id
        self.last_used = time.monotonic()


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.command = self._parse_command(config.get("command") or DEFAULT_COMMAND)
        self.workspace = os.path.expanduser(
            config.get("workspace") or "~/.dsh/elder-workspace"
        )
        self.request_timeout = float(config.get("timeout", 120))
        self.chunk_timeout = float(config.get("chunk_timeout", 60))
        self.idle_timeout = float(config.get("idle_timeout", 1800))
        self.permission = str(config.get("permission", "allow")).lower()
        self.fallback = config.get("fallback_reply") or DEFAULT_FALLBACK

        os.makedirs(self.workspace, exist_ok=True)

        self._sessions: Dict[str, _AgentSession] = {}
        # 同一设备并发预热/请求时，只允许一个线程在建会话
        self._starting: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 接口

    def response(self, session_id, dialogue, **kwargs) -> Iterator[str]:
        text = self._last_user_text(dialogue)
        if not text:
            return

        try:
            client, agent_session_id = self._ensure_session(session_id)
            produced = False
            for chunk in client.prompt(agent_session_id, text):
                if chunk:
                    produced = True
                    yield chunk
            if not produced:
                logger.bind(tag=TAG).warning(f"agent 没吐正文（会话 {session_id}）")
                yield self.fallback
        except AcpTimeout as exc:
            logger.bind(tag=TAG).error(f"agent 超时: {exc}")
            self._drop_session(session_id)
            yield self.fallback
        except AcpError as exc:
            logger.bind(tag=TAG).error(f"agent 调用失败: {exc}")
            self._drop_session(session_id)
            yield self.fallback
        except Exception as exc:  # 兜底：不能让一条异常把整轮对话打挂
            logger.bind(tag=TAG).error(f"agent 异常: {type(exc).__name__}: {exc}")
            self._drop_session(session_id)
            yield self.fallback

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for item in sessions:
            try:
                item.client.close()
            except Exception:
                pass

    def prewarm(self, session_id) -> bool:
        """提前把 agent 会话建起来（设备刚连上、还没开口时调）。

        首轮冷启动要 10s 级（node 起进程 + 插件装载），挪到用户开口之前，
        第一句话的延迟就能降到跟第二句差不多。
        """
        try:
            self._ensure_session(session_id)
            return True
        except Exception as exc:
            logger.bind(tag=TAG).warning(f"agent 预热失败（不影响后续按需启动）: {exc}")
            return False

    # ---------------------------------------------------------------- 内部实现

    def _ensure_session(self, xiaozhi_session_id: str) -> Tuple[AcpClient, str]:
        # 预热线程和真正的请求可能同时进来：同一设备只允许一个在建，另一个等它建好
        while True:
            with self._lock:
                self._reap_idle_locked()
                item = self._sessions.get(xiaozhi_session_id)
                if item is not None and item.client.alive:
                    item.last_used = time.monotonic()
                    return item.client, item.session_id
                if item is not None:  # 进程死了，重建
                    self._sessions.pop(xiaozhi_session_id, None)
                    self._close_item(item)

                waiting = self._starting.get(xiaozhi_session_id)
                if waiting is None:
                    waiting = threading.Event()
                    self._starting[xiaozhi_session_id] = waiting
                    break
            # 别人正在建这条会话，等它出结果再重试
            waiting.wait(timeout=self.request_timeout)

        # 建连接放在锁外，避免一次慢启动把所有设备都堵住
        try:
            client = AcpClient(
                self.command,
                cwd=self.workspace,
                request_timeout=self.request_timeout,
                chunk_timeout=self.chunk_timeout,
                permission=self.permission,
            )
            client.start()
            try:
                client.initialize()
                agent_session_id = client.new_session(self.workspace)
            except Exception:
                client.close()
                raise
        except Exception:
            with self._lock:
                self._starting.pop(xiaozhi_session_id, None)
            waiting.set()
            raise

        item = _AgentSession(client, agent_session_id)
        with self._lock:
            self._sessions[xiaozhi_session_id] = item
            self._starting.pop(xiaozhi_session_id, None)
        waiting.set()
        logger.bind(tag=TAG).info(
            f"agent 会话就绪 device={xiaozhi_session_id} acp={agent_session_id}"
        )
        return client, agent_session_id

    def _reap_idle_locked(self) -> None:
        now = time.monotonic()
        stale = [
            sid
            for sid, item in self._sessions.items()
            if now - item.last_used > self.idle_timeout
        ]
        for sid in stale:
            item = self._sessions.pop(sid)
            self._close_item(item)
            logger.bind(tag=TAG).info(f"回收闲置 agent 会话 {sid}")


    def _drop_session(self, xiaozhi_session_id: str) -> None:
        with self._lock:
            item = self._sessions.pop(xiaozhi_session_id, None)
        if item is not None:
            self._close_item(item)

    def _close_item(self, item: _AgentSession) -> None:
        try:
            item.client.close()
        except Exception:
            pass

    @staticmethod
    def _parse_command(value) -> list:
        if isinstance(value, (list, tuple)):
            return [str(part) for part in value]
        return shlex.split(str(value))

    @staticmethod
    def _last_user_text(dialogue) -> str:
        for message in reversed(dialogue or []):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):  # 多模态块：只取文本块
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                joined = "".join(parts).strip()
                if joined:
                    return joined
        return ""
