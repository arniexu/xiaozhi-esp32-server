"""ACP（Agent Client Protocol）客户端：用 NDJSON 走子进程 stdio 跟 DSH agent 对话。

`dsh --profile <acp 档>` 暴露的就是标准 ACP：JSON-RPC 2.0，一行一条消息。
这里只实现小智服务端用得到的表面：

    initialize  →  session/new  →  session/prompt（流式）  →  session/cancel

另外自动应答 `session/request_permission`（语音场景没人点按钮，默认全允许，
可用 permission="deny" 关掉），未知的 agent→client 请求一律回 -32601。

依赖只有标准库，Python 3.10 可直接跑。
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Sequence

# ACP 协议版本（@agentclientprotocol/sdk 的 PROTOCOL_VERSION）
PROTOCOL_VERSION = 1

_METHOD_NOT_FOUND = -32601
_INTERNAL_ERROR = -32603


class AcpError(RuntimeError):
    """协议层或进程层错误。"""


class AcpTimeout(AcpError):
    """等待 agent 响应超时。"""


class AcpClient:
    """一个 agent 子进程 + 一条 ACP 连接。

    线程模型：调用方在自己的线程里同步调用；内部一个读线程负责收包并分发
    响应/通知，另一个线程抽干 stderr 免得管道写满把 agent 卡死。
    """

    def __init__(
        self,
        command: Sequence[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        *,
        request_timeout: float = 120.0,
        chunk_timeout: float = 60.0,
        permission: str = "allow",
        name: str = "xiaozhi-server",
        version: str = "0.1.0",
    ) -> None:
        self.command = list(command)
        self.cwd = cwd
        self.env = env
        self.request_timeout = request_timeout
        self.chunk_timeout = chunk_timeout
        self.permission = permission
        self.client_name = name
        self.client_version = version

        self._proc: Optional[subprocess.Popen] = None
        self._write_lock = threading.Lock()
        self._pending: Dict[str, "queue.Queue[dict]"] = {}
        self._pending_lock = threading.Lock()
        self._sessions: Dict[str, "queue.Queue[tuple]"] = {}
        self._prompt_ids: Dict[str, str] = {}  # request id -> session id
        self._stderr_tail: List[str] = []
        self._reader: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._next_id = 0

    # ---------------------------------------------------------------- 生命周期

    def start(self) -> None:
        """拉起子进程（幂等）。"""
        if self._proc is not None and self._proc.poll() is None:
            return

        argv = self.command
        try:
            proc = subprocess.Popen(
                argv,
                cwd=self.cwd,
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise AcpError(f"找不到 agent 启动命令: {argv[0]!r}") from exc

        self._proc = proc
        self._closed.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name="acp-reader", daemon=True
        )
        self._reader.start()
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, name="acp-stderr", daemon=True
        )
        self._stderr_thread.start()

    def close(self, timeout: float = 5.0) -> None:
        """关连接、回收子进程。"""
        self._closed.set()
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
        self._fail_pending(AcpError("ACP 连接已关闭"))

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stderr_tail(self, limit: int = 20) -> str:
        return "\n".join(self._stderr_tail[-limit:])

    # ------------------------------------------------------------------ ACP 方法

    def initialize(self) -> dict:
        return self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
        )

    def new_session(self, cwd: str, mcp_servers: Optional[List[dict]] = None) -> str:
        result = self.request("session/new", {"cwd": cwd, "mcpServers": mcp_servers or []})
        session_id = result.get("sessionId")
        if not session_id:
            raise AcpError(f"session/new 未返回 sessionId: {result!r}")
        return session_id

    def prompt(self, session_id: str, text: str) -> Iterator[str]:
        """发一句话，边收边吐 agent 的正文增量。

        只转发 `agent_message_chunk` 里的 text；思考过程、工具调用等其他
        update 类型直接丢弃（TTS 不该念出来）。
        """
        q: "queue.Queue[tuple]" = queue.Queue()
        self._sessions[session_id] = q
        request_id = ""
        finished = False
        try:
            request_id = self._send_request(
                "session/prompt",
                {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            )
            self._prompt_ids[request_id] = session_id
            deadline = time.monotonic() + self.request_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AcpTimeout(f"session/prompt 超时（{self.request_timeout}s）")
                try:
                    kind, payload = q.get(timeout=min(remaining, self.chunk_timeout))
                except queue.Empty:
                    raise AcpTimeout(
                        f"{self.chunk_timeout}s 内没收到任何增量（会话 {session_id}）"
                    )
                if kind == "chunk":
                    yield payload
                elif kind == "done":
                    finished = True
                    return
                elif kind == "error":
                    raise AcpError(payload)
        finally:
            self._sessions.pop(session_id, None)
            self._prompt_ids.pop(request_id, None)
            if not finished:
                # 调用方提前 break 或出错：把这一轮取消掉，别让 agent 空转
                self._cancel_quietly(session_id)

    def cancel(self, session_id: str) -> None:
        self.notify("session/cancel", {"sessionId": session_id})

    # ---------------------------------------------------------------- 底层收发

    def request(self, method: str, params: dict, timeout: Optional[float] = None) -> dict:
        request_id = self._send_request(method, params)
        return self._wait_response(request_id, method, timeout)

    def notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _send_request(self, method: str, params: dict) -> str:
        with self._pending_lock:
            self._next_id += 1
            request_id = f"xzs-{self._next_id}-{uuid.uuid4().hex[:8]}"
            waiter: "queue.Queue[dict]" = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter
        try:
            self._write(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        return request_id

    def _wait_response(
        self, request_id: str, method: str, timeout: Optional[float]
    ) -> dict:
        with self._pending_lock:
            waiter = self._pending.get(request_id)
        if waiter is None:
            raise AcpError(f"{method} 请求未登记")
        try:
            message = waiter.get(timeout=timeout or self.request_timeout)
        except queue.Empty:
            raise AcpTimeout(f"{method} 超时（{timeout or self.request_timeout}s）")
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if "error" in message:
            err = message["error"] or {}
            raise AcpError(f"{method} 失败: {err.get('message') or err!r}")
        return message.get("result") or {}

    def _write(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise AcpError(f"agent 进程不可用（stderr: {self.stderr_tail(3) or '空'}）")
        data = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                raise AcpError(f"写入 agent 失败: {exc}") from exc

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        stream = proc.stdout
        while not self._closed.is_set():
            line = stream.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # stdout 上混进非协议内容：留证据，但不致命
                self._stderr_tail.append(f"[non-json stdout] {line[:300]}")
                continue
            try:
                self._dispatch(message)
            except Exception as exc:  # 读线程不能因为单条消息挂掉
                self._stderr_tail.append(f"[dispatch error] {exc!r}")
        self._fail_pending(AcpError("agent 进程已退出"))

    def _dispatch(self, message: dict) -> None:
        # agent → client 的请求（要我们应答）
        if "method" in message and "id" in message:
            self._handle_agent_request(message)
            return

        # 我们发出的请求的响应
        if "id" in message and ("result" in message or "error" in message):
            session_id = self._prompt_ids.get(message["id"])
            if session_id is not None:
                q = self._sessions.get(session_id)
                if q is not None:
                    if "error" in message:
                        err = message["error"] or {}
                        q.put(("error", f"prompt 失败: {err.get('message') or err!r}"))
                    else:
                        stop = (message.get("result") or {}).get("stopReason")
                        q.put(("done", stop))
                return
            with self._pending_lock:
                waiter = self._pending.get(message["id"])
            if waiter is not None:
                try:
                    waiter.put_nowait(message)
                except queue.Full:
                    pass
            return

        # 通知
        if message.get("method") == "session/update":
            params = message.get("params") or {}
            session_id = params.get("sessionId")
            update = params.get("update") or {}
            target = self._sessions.get(session_id)
            if target is None:
                return
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content") or {}
                if content.get("type") == "text" and content.get("text"):
                    target.put(("chunk", content["text"]))

    def _handle_agent_request(self, message: dict) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        try:
            if method == "session/request_permission":
                result = self._answer_permission(params)
            else:
                self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {
                            "code": _METHOD_NOT_FOUND,
                            "message": f"unsupported client method: {method}",
                        },
                    }
                )
                return
            self._write({"jsonrpc": "2.0", "id": message["id"], "result": result})
        except Exception as exc:
            try:
                self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": _INTERNAL_ERROR, "message": str(exc)},
                    }
                )
            except AcpError:
                pass

    def _answer_permission(self, params: dict) -> dict:
        options = params.get("options") or []
        if self.permission == "deny":
            for option in options:
                if str(option.get("kind", "")).startswith("reject"):
                    return {
                        "outcome": {"outcome": "selected", "optionId": option["optionId"]}
                    }
            return {"outcome": {"outcome": "cancelled"}}

        # 语音场景没有人点确认，默认挑一个放行选项
        for kind in ("allow_always", "allow_once"):
            for option in options:
                if option.get("kind") == kind:
                    return {
                        "outcome": {
                            "outcome": "selected",
                            "optionId": option["optionId"],
                        }
                    }
        if options:
            return {"outcome": {"outcome": "selected", "optionId": options[0]["optionId"]}}
        return {"outcome": {"outcome": "cancelled"}}

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            line = line.rstrip("\n")
            if line:
                self._stderr_tail.append(line)
                del self._stderr_tail[:-200]

    def _fail_pending(self, exc: Exception) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            try:
                waiter.put_nowait({"error": {"code": _INTERNAL_ERROR, "message": str(exc)}})
            except queue.Full:
                pass
        for q in list(self._sessions.values()):
            try:
                q.put_nowait(("error", str(exc)))
            except queue.Full:
                pass

    def _cancel_quietly(self, session_id: str) -> None:
        try:
            if self.alive:
                self.cancel(session_id)
        except Exception:
            pass
