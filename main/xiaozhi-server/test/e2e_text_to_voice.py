#!/usr/bin/env python3
"""端到端：一句话 → 小智服务端（意图 + DSH agent）→ TTS 音频回到客户端。

绕开 ASR：`listen` 消息的 `detect` 状态可以带 `text` 字段，服务端会直接用这段文本
走 startToChat，于是整条链路（连接初始化 / 预热 / 意图识别 / LLM / TTS）都能验证。

运行：
    .venv/bin/python test/e2e_text_to_voice.py --text "你好，我今天有点冷"
    .venv/bin/python test/e2e_text_to_voice.py --url ws://127.0.0.1:8010/xiaozhi/v1/
"""

import argparse
import asyncio
import json
import sys
import time

import websockets


HELLO = {
    "type": "hello",
    "version": 1,
    "transport": "websocket",
    "audio_params": {
        "format": "opus",
        "sample_rate": 16000,
        "channels": 1,
        "frame_duration": 60,
    },
}


async def run(url, text, wait, device_id):
    stt = []
    sentences = []
    audio_bytes = 0
    audio_frames = 0
    started = time.time()
    first_audio = None

    async with websockets.connect(
        url, additional_headers={"device-id": device_id}, open_timeout=10
    ) as ws:
        await ws.send(json.dumps(HELLO))
        hello_reply = await asyncio.wait_for(ws.recv(), timeout=10)
        print(f"[hello] {hello_reply[:160]}")

        # 给预热线程一点时间起 agent（真实设备也是先连上再说第一句）
        await asyncio.sleep(1.0)
        await ws.send(json.dumps({"type": "listen", "state": "detect", "text": text}))
        print(f"[user] {text}")

        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=min(5, deadline - time.time()))
            except asyncio.TimeoutError:
                continue
            if isinstance(message, bytes):
                audio_bytes += len(message)
                audio_frames += 1
                if first_audio is None:
                    first_audio = time.time() - started
                continue
            payload = json.loads(message)
            kind = payload.get("type")
            if kind == "stt":
                stt.append(payload.get("text", ""))
                print(f"[stt] {payload.get('text', '')}")
            elif kind == "tts":
                state = payload.get("state")
                if state == "sentence_start":
                    sentences.append(payload.get("text", ""))
                    print(f"[tts] {payload.get('text', '')}")
                elif state == "stop":
                    print("[tts] stop")

    elapsed = time.time() - started
    print()
    print(f"STT 文本: {''.join(stt) or '(无)'}")
    print(f"TTS 句子: {sentences or '(无)'}")
    print(f"音频帧: {audio_frames} 帧 / {audio_bytes} 字节" + (f"，首帧 {first_audio:.1f}s" if first_audio else ""))
    print(f"总耗时: {elapsed:.1f}s")

    ok = bool(sentences) and audio_bytes > 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8010/xiaozhi/v1/")
    parser.add_argument("--text", default="你好，我今天有点冷，想喝点热的")
    parser.add_argument("--wait", type=float, default=60)
    parser.add_argument("--device-id", default="e2e-dshagent")
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.text, args.wait, args.device_id))


if __name__ == "__main__":
    sys.exit(main())
