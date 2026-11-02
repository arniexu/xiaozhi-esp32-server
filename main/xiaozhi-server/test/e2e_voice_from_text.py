#!/usr/bin/env python3
"""无麦克风的语音链路测试：合成一句话 → 以真实设备的方式推 opus 音频进服务端。

这条路径跟真机完全一致：listen/start(manual) → 二进制 opus 帧 → listen/stop，
服务端走 VAD/ASR → 意图 → DSH agent → TTS → 回 opus 音频。

用途：浏览器拿不到麦克风（非 localhost 的 http 页面）时验证语音是否可用，
或者回归时不想张嘴。

运行：
    .venv/bin/python test/e2e_voice_from_text.py --text "你好，今天有点冷"
    .venv/bin/python test/e2e_voice_from_text.py --text "..." --proxy http://child-prc.intel.com:913
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

import edge_tts
import opuslib_next
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

SAMPLE_RATE = 16000
FRAME_SAMPLES = 960  # 60ms @16k
FRAME_BYTES = FRAME_SAMPLES * 2


async def synthesize(text, voice, proxy, out_path):
    communicate = edge_tts.Communicate(text, voice=voice, proxy=proxy)
    with open(out_path, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])


def decode_to_pcm(mp3_path, pcm_path):
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", mp3_path,
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", str(SAMPLE_RATE),
            pcm_path,
        ],
        check=True,
    )


def encoder_silence_frame():
    """一帧 60ms 的静音 opus（真实设备在没人说话时也一直在送）。"""
    encoder = opuslib_next.Encoder(SAMPLE_RATE, 1, "voip")
    return encoder.encode(b"\x00\x00" * FRAME_SAMPLES, FRAME_SAMPLES)


def encode_frames(pcm_path):
    encoder = opuslib_next.Encoder(SAMPLE_RATE, 1, "voip")
    with open(pcm_path, "rb") as handle:
        data = handle.read()
    frames = []
    for offset in range(0, len(data) - FRAME_BYTES + 1, FRAME_BYTES):
        frames.append(encoder.encode(data[offset : offset + FRAME_BYTES], FRAME_SAMPLES))
    return frames


async def run(args):
    workdir = tempfile.mkdtemp(prefix="xzs-voice-")
    mp3 = os.path.join(workdir, "say.mp3")
    pcm = os.path.join(workdir, "say.pcm")

    print(f"[tts-gen] 合成：{args.text}")
    await synthesize(args.text, args.voice, args.proxy, mp3)
    decode_to_pcm(mp3, pcm)
    frames = encode_frames(pcm)
    duration = len(frames) * 0.06
    print(f"[tts-gen] {len(frames)} 帧 opus（约 {duration:.1f}s 音频）")

    stt, sentences, audio_bytes, audio_frames = [], [], 0, 0
    async with websockets.connect(
        args.url, additional_headers={"device-id": args.device_id}, open_timeout=10
    ) as ws:
        await ws.send(json.dumps(HELLO))
        print(f"[hello] {(await asyncio.wait_for(ws.recv(), timeout=10))[:100]}")
        await asyncio.sleep(args.warm)

        await ws.send(json.dumps({"type": "listen", "mode": "manual", "state": "start"}))
        # 真实设备 start 之后用户才开口，天然有一段间隔；给云端 ASR 留出建链时间
        await asyncio.sleep(args.lead)
        print(f"[audio] 开始推送（lead {args.lead:.1f}s）")
        for frame in frames:
            await ws.send(frame)
            await asyncio.sleep(0.06)
        # 真实设备会持续送帧，说完之后还有一段静音；云端 ASR 靠这段静音
        # 触发 max_sentence_silence 才会给 SentenceEnd。不发静音就永远等不到结果。
        silence = encoder_silence_frame()
        for _ in range(int(args.tail / 0.06)):
            await ws.send(silence)
            await asyncio.sleep(0.06)
        print(f"[audio] 已补 {args.tail:.1f}s 尾部静音")
        await ws.send(json.dumps({"type": "listen", "state": "stop"}))
        print("[audio] 推送完成，等识别与回复")

        started = time.time()
        deadline = started + args.wait
        first_audio = None
        while time.time() < deadline:
            try:
                message = await asyncio.wait_for(
                    ws.recv(), timeout=min(5, deadline - time.time())
                )
            except asyncio.TimeoutError:
                continue
            if isinstance(message, bytes):
                audio_frames += 1
                audio_bytes += len(message)
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
                elif state == "stop" and audio_frames:
                    break

    print()
    print(f"ASR 文本: {''.join(stt) or '(无)'}")
    print(f"TTS 句子: {len(sentences)} 段")
    print(
        f"音频: {audio_frames} 帧 / {audio_bytes} 字节"
        + (f"，首帧 {first_audio:.1f}s" if first_audio else "")
    )
    ok = bool(stt) and bool(sentences) and audio_bytes > 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8010/xiaozhi/v1/")
    parser.add_argument("--text", default="你好，我今天有点冷，想喝点热的")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--proxy", default=os.environ.get("http_proxy"))
    parser.add_argument("--wait", type=float, default=120)
    parser.add_argument("--warm", type=float, default=3.0, help="连接后等预热的秒数")
    parser.add_argument("--lead", type=float, default=1.5, help="listen start 后等多久再推音频")
    parser.add_argument("--tail", type=float, default=2.0, help="说完后补多久静音（触发云端断句）")
    parser.add_argument("--device-id", default="e2e-voice-file")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
