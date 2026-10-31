#!/usr/bin/env python3
"""端到端：一句话 → 小智服务端（意图 + DSH agent）→ TTS 音频回到客户端。

绕开 ASR：`listen` 消息的 `detect` 状态可以带 `text` 字段，服务端会直接用这段文本
走 startToChat，于是整条链路（连接初始化 / 预热 / 意图识别 / LLM / TTS）都能验证。

运行：
    .venv/bin/python test/e2e_text_to_voice.py --text "你好，我今天有点冷"
    .venv/bin/python test/e2e_text_to_voice.py \
        --text "你好呀" --text "我腿有点疼，怎么办"      # 多轮，验证同连接的第二轮延迟
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


async def say(ws, text, wait, label):
    """发一句话，收到 tts stop 或超时为止，返回本轮统计。"""
    started = time.time()
    sentences = []
    audio_bytes = 0
    audio_frames = 0
    first_audio = None

    await ws.send(json.dumps({"type": "listen", "state": "detect", "text": text}))
    print(f"[user{label}] {text}")

    deadline = started + wait
    while time.time() < deadline:
        try:
            message = await asyncio.wait_for(
                ws.recv(), timeout=min(5, deadline - time.time())
            )
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
            print(f"[stt] {payload.get('text', '')}")
        elif kind == "tts":
            state = payload.get("state")
            if state == "sentence_start":
                sentences.append(payload.get("text", ""))
                print(f"[tts] {payload.get('text', '')}")
            elif state == "stop" and audio_frames > 0:
                break

    elapsed = time.time() - started
    print(
        f"[turn{label}] 首帧 {first_audio:.1f}s | 总 {elapsed:.1f}s | "
        f"{audio_frames} 帧 / {audio_bytes} 字节 | 句子 {len(sentences)} 段"
        if first_audio
        else f"[turn{label}] 没有音频（总 {elapsed:.1f}s）"
    )
    return {
        "sentences": sentences,
        "audio_frames": audio_frames,
        "audio_bytes": audio_bytes,
        "first_audio": first_audio,
    }


async def run(url, texts, wait, device_id, gap):
    results = []
    async with websockets.connect(
        url, additional_headers={"device-id": device_id}, open_timeout=10
    ) as ws:
        await ws.send(json.dumps(HELLO))
        hello_reply = await asyncio.wait_for(ws.recv(), timeout=10)
        print(f"[hello] {hello_reply[:120]}")

        # 预热在连接建立后后台跑；真实设备也是先连上、过一会儿才说第一句
        await asyncio.sleep(gap)
        for index, text in enumerate(texts, 1):
            label = f"#{index}" if len(texts) > 1 else ""
            results.append(await say(ws, text, wait, label))

    print()
    ok = all(r["sentences"] and r["audio_bytes"] > 0 for r in results)
    for index, result in enumerate(results, 1):
        print(
            f"轮 {index}: {len(result['sentences'])} 句 / {result['audio_bytes']} 字节 / "
            f"首帧 {result['first_audio']:.1f}s"
            if result["first_audio"]
            else f"轮 {index}: 失败"
        )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8010/xiaozhi/v1/")
    parser.add_argument(
        "--text",
        action="append",
        help="可以给多次，按顺序多轮发问",
    )
    parser.add_argument("--wait", type=float, default=90, help="每轮最长等待（秒）")
    parser.add_argument("--gap", type=float, default=1.0, help="连接后等多久说第一句")
    parser.add_argument("--device-id", default="e2e-dshagent")
    args = parser.parse_args()
    texts = args.text or ["你好，我今天有点冷，想喝点热的"]
    return asyncio.run(run(args.url, texts, args.wait, args.device_id, args.gap))


if __name__ == "__main__":
    sys.exit(main())
