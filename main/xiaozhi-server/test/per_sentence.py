#!/usr/bin/env python3
"""按「服务端实际发的一句一段」切分抓包，逐句存 wav 并量化。

用途：听感说「第一句和后几句音色不一样」时，先确认服务端到底发了几段、
每段的亮度（有声帧谱质心）、音高、时长差多少——用数据区分「真有差异」和
「短句听起来平」这类主观感受。

用法：
    .venv/bin/python test/per_sentence.py --text "您今天身体怎么样？"
"""

import argparse
import asyncio
import json
import os
import time
import wave

import numpy as np
import opuslib_next
import websockets

HELLO = {
    "type": "hello", "version": 1, "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000,
                     "channels": 1, "frame_duration": 60},
}


async def capture(url, text, device_id, wait):
    segments, label, cur = [], "(未标注)", []
    async with websockets.connect(url, additional_headers={"device-id": device_id},
                                  max_size=None) as ws:
        await ws.send(json.dumps(HELLO))
        await asyncio.wait_for(ws.recv(), timeout=10)
        await asyncio.sleep(3)  # 等预热
        await ws.send(json.dumps({"type": "listen", "state": "detect", "text": text}))
        deadline = time.perf_counter() + wait
        while time.perf_counter() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, bytes):
                cur.append(msg)
                continue
            payload = json.loads(msg)
            if payload.get("type") != "tts":
                continue
            state = payload.get("state")
            if state == "sentence_start":
                if cur:
                    segments.append((label, cur))
                cur, label = [], payload.get("text", "")
            elif state in ("sentence_end", "stop"):
                if cur:
                    segments.append((label, cur))
                    cur = []
                if state == "stop":
                    break
    return segments


def decode(packets):
    decoder = opuslib_next.Decoder(16000, 1)
    chunks = []
    for pkt in packets:
        try:
            chunks.append(np.frombuffer(decoder.decode(pkt, 1920), dtype="<i2"))
        except Exception:
            pass
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype="<i2>")


def voiced_centroid(x, sr=16000):
    """只在有声帧上算谱质心——否则每段末尾的静音会把质心拉低，造成假差异。"""
    win, hop = int(sr * 0.04), int(sr * 0.02)
    xf = x.astype(np.float64)
    thr = max(200.0, np.percentile(np.abs(xf), 95) * 0.2) if len(xf) else 200.0
    cents = []
    for i in range(0, len(xf) - win, hop):
        frame = xf[i:i + win]
        if np.sqrt((frame ** 2).mean()) < thr:
            continue
        spec = np.abs(np.fft.rfft(frame * np.hanning(win)))
        if spec.sum() > 0:
            cents.append((spec * np.fft.rfftfreq(win, 1 / sr)).sum() / spec.sum())
    return float(np.mean(cents)) if cents else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="您今天身体怎么样？")
    ap.add_argument("--url", default="ws://127.0.0.1:8010/xiaozhi/v1/")
    ap.add_argument("--out", default="test/tts-ab/segments")
    ap.add_argument("--device-id", default="per-sentence")
    ap.add_argument("--wait", type=float, default=45)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    for old in os.listdir(args.out):
        if old.startswith("seg") and old.endswith(".wav"):
            os.remove(os.path.join(args.out, old))

    segments = asyncio.run(capture(args.url, args.text, args.device_id, args.wait))
    print(f"共 {len(segments)} 段")
    for i, (label, packets) in enumerate(segments, 1):
        pcm = decode(packets)
        if not len(pcm):
            continue
        dur = len(pcm) / 16000
        path = os.path.join(args.out, f"seg{i}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm.astype("<i2").tobytes())
        print(f"#{i} 「{label[:20]}」 {dur:5.2f}s  包={len(packets):>3}  "
              f"有声帧质心={voiced_centroid(pcm):5.0f}Hz  峰值={int(np.abs(pcm).max()):>5}  {path}")


if __name__ == "__main__":
    main()
