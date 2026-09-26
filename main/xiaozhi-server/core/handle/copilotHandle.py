"""Copilot 桥接：把设备对话接到本机 VS Code 的 Copilot Chat（小智插件）。

设计文档：docs/copilot-bridge-plan.md；VS Code 扩展：tools/vscode-copilot-bridge/。

工作方式：
- 关键词进入/退出 Copilot 模式（默认「问 Copilot…」/「退出 Copilot」，见 config.yaml 的 copilot_bridge 段）；
- 模式内：语音/文本转发到扩展桥接（WebSocket，仅本机），回复流式写入 TTS 队列由设备播报；
- 模式外：完全不介入原有对话链路（伴侣/记忆/工具调用均不受影响）；
- 打断（barge-in）：复用既有机制（conn.client_abort + clear_queues）；本模块额外用
  conn._copilot_active_request 作废进行中的转发，避免陈旧回包串入新句子。
"""

import inspect
import json
import time
import uuid

from core.handle.sendAudioHandle import send_stt_message
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO

TAG = __name__

# 关键词匹配时忽略的字符（空白与常见中英标点；不影响转发给 Copilot 的原文）
_IGNORE_CHARS = set(" \t\r\n,，。.!！?？、~～:：;；\"“”'‘’`-—_")


def _compact(text):
    """去空白/标点并小写，仅用于关键词匹配。"""
    return "".join(ch for ch in str(text).lower() if ch not in _IGNORE_CHARS)


def _compact_keywords(keywords):
    return [kw for kw in (_compact(k) for k in (keywords or [])) if kw]


def _match_prefix(compact_text, compact_keywords):
    for kw in compact_keywords:
        if compact_text.startswith(kw):
            return kw
    return None


def _strip_prefix(text, keyword_compact):
    """从原文开头剥掉关键词（按去噪后的字符数对齐），返回剩余原文。"""
    need = len(keyword_compact)
    if need == 0:
        return ""
    seen = 0
    for i, ch in enumerate(text):
        if ch.lower() in _IGNORE_CHARS:
            continue
        seen += 1
        if seen >= need:
            return text[i + 1 :].strip(" \t\r\n,，。.!！?？、")
    return ""


def _user_text(raw):
    """从可能的 JSON（声纹包裹 {"speaker":..,"content":..}）里取出真正的用户话语。"""
    text = raw
    try:
        if (
            isinstance(raw, str)
            and raw.strip().startswith("{")
            and raw.strip().endswith("}")
        ):
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "content" in parsed:
                text = parsed["content"]
    except (json.JSONDecodeError, TypeError):
        pass
    return str(text)


def _get_config(conn):
    cfg = conn.config.get("copilot_bridge") or {}
    if cfg.get("enabled", False) is not True:
        return None
    return cfg


def _session_id(conn):
    """每台设备一个多轮会话（扩展按 session_id 维护上下文）。"""
    try:
        device_id = (conn.headers or {}).get("device-id") or ""
    except Exception:
        device_id = ""
    return f"{device_id or 'default'}#copilot"


def _speak_once(conn, text):
    """一次性播报（提示语/报错），不写对话历史。信封格式与 connection.chat() 一致。"""
    conn.sentence_id = uuid.uuid4().hex
    conn.llm_finish_task = True
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )
    conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=text)
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )


def _shorten(text, limit=60):
    text = "".join(ch for ch in str(text) if ch not in "\r\n")
    return text if len(text) <= limit else text[:limit] + "…"


def _submit(conn, query):
    cfg = _get_config(conn) or {}
    request_id = uuid.uuid4().hex
    conn._copilot_active_request = request_id
    try:
        conn.executor.submit(
            _forward_to_copilot, conn, request_id, _session_id(conn), query, cfg
        )
    except RuntimeError as e:
        # 连接断开中，executor 已关闭
        conn.logger.bind(tag=TAG).warning(f"Copilot 转发提交失败：{e}")


def _forward_to_copilot(conn, request_id, session_id, query, cfg):
    """在连接线程池中执行：请求扩展桥接并流式写入 TTS 队列。"""
    logger = conn.logger.bind(tag=TAG)
    url = str(cfg.get("url", "ws://127.0.0.1:8767"))
    connect_timeout = float(cfg.get("connect_timeout", 3))
    reply_timeout = float(cfg.get("reply_timeout", 120))

    def _aborted():
        return (
            conn.client_abort
            or conn.stop_event.is_set()
            or getattr(conn, "_copilot_active_request", None) != request_id
        )

    ws = None
    envelope_open = False
    spoke_any = False
    try:
        # websockets>=12 提供 sync API；仓库 requirements 已含 websockets
        from websockets.sync.client import connect as ws_connect

        # 强制直连：禁用 websockets>=15 的环境代理（公司网络 socks_proxy/http_proxy
        # 会劫持 localhost 连接，导致 InvalidProxy/403）；老版本无 proxy 参数则跳过
        connect_kwargs = {"open_timeout": connect_timeout}
        if "proxy" in inspect.signature(ws_connect).parameters:
            connect_kwargs["proxy"] = None
        ws = ws_connect(url, **connect_kwargs)
        ws.send(
            json.dumps(
                {
                    "type": "request",
                    "request_id": request_id,
                    "session_id": session_id,
                    "text": query,
                }
            )
        )

        conn.sentence_id = uuid.uuid4().hex
        conn.llm_finish_task = False
        conn.client_abort = False
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(
                sentence_id=conn.sentence_id,
                sentence_type=SentenceType.FIRST,
                content_type=ContentType.ACTION,
            )
        )
        envelope_open = True

        deadline = time.monotonic() + reply_timeout
        while True:
            if _aborted():
                # 打断/作废：通知扩展取消 LLM 请求
                try:
                    ws.send(json.dumps({"type": "cancel", "request_id": request_id}))
                except Exception:
                    pass
                break
            if time.monotonic() > deadline:
                logger.warning(f"Copilot 回复超时（>{reply_timeout}s）")
                if not spoke_any:
                    _speak_once(conn, "Copilot 回复超时了，稍后再试吧")
                break
            try:
                raw = ws.recv(timeout=0.25)
            except TimeoutError:
                continue
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "chunk":
                content = str(msg.get("text") or "")
                if content:
                    spoke_any = True
                    conn.tts.tts_text_queue.put(
                        TTSMessageDTO(
                            sentence_id=conn.sentence_id,
                            sentence_type=SentenceType.MIDDLE,
                            content_type=ContentType.TEXT,
                            content_detail=content,
                        )
                    )
            elif mtype == "done":
                break
            elif mtype == "error":
                message = _shorten(msg.get("message") or "未知错误")
                logger.warning(f"Copilot 桥接返回错误：{message}")
                if not spoke_any:
                    _speak_once(conn, f"Copilot 暂时用不了了：{message}")
                break
    except Exception as e:
        logger.warning(f"Copilot 桥接连接失败：{type(e).__name__}: {e}")
        if not spoke_any:
            _speak_once(conn, "Copilot 桥接没连上，请确认 VS Code 已打开并启用了桥接扩展")
    finally:
        conn.llm_finish_task = True
        # LAST 只在「本次请求仍有效且未被打断」时发出（被打断时 stop 已由打断流程发出）
        if (
            envelope_open
            and not conn.client_abort
            and getattr(conn, "_copilot_active_request", None) == request_id
        ):
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=conn.sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


async def maybe_handle_copilot_message(conn, text, source="user"):
    """startToChat 的分叉点：Copilot 模式切换与转发。

    返回 True 表示消息已由本模块处理，调用方应终止常规流程。
    """
    if source != "user":
        return False
    cfg = _get_config(conn)
    if cfg is None:
        return False

    logger = conn.logger.bind(tag=TAG)
    user_text = _user_text(text)
    compact = _compact(user_text)
    enter_kws = _compact_keywords(cfg.get("enter_keywords"))
    exit_kws = _compact_keywords(cfg.get("exit_keywords"))

    if not getattr(conn, "copilot_mode", False):
        matched = _match_prefix(compact, enter_kws)
        if not matched:
            return False
        conn.copilot_mode = True
        remainder = _strip_prefix(user_text, matched)
        await send_stt_message(conn, text)
        if remainder:
            logger.info(f"进入 Copilot 模式，首问：{remainder[:80]}")
            _submit(conn, remainder)
        else:
            logger.info("进入 Copilot 模式，等待提问")
            _speak_once(conn, "好，我在，直接问吧")
        return True

    # ---- 已在 Copilot 模式内 ----
    if _match_prefix(compact, exit_kws):
        conn.copilot_mode = False
        conn._copilot_active_request = None  # 作废进行中的转发
        conn.client_abort = True
        conn.clear_queues()
        logger.info("退出 Copilot 模式")
        await send_stt_message(conn, text)
        _speak_once(conn, "好的，已退出 Copilot")
        return True

    # 常规退出指令（例如“再见”）仍然生效（关闭连接等标准行为）
    try:
        from core.handle.intentHandler import check_direct_exit

        if await check_direct_exit(conn, user_text):
            return True
    except Exception as e:
        logger.warning(f"退出指令检查失败（已忽略）：{e}")

    matched = _match_prefix(compact, enter_kws)
    remainder = _strip_prefix(user_text, matched) if matched else ""
    await send_stt_message(conn, text)
    if matched and not remainder:
        # 只有触发词、没有内容
        _speak_once(conn, "我在呢，直接说就行")
    else:
        query = remainder or user_text
        logger.info(f"Copilot 转发：{query[:80]}")
        _submit(conn, query)
    return True
