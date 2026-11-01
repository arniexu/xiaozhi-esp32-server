#!/usr/bin/env python3
"""语音输入/输出双端探针：把服务端真实吐出来的音频接住、拆开、量化并落成 wav。

跟 e2e_voice_from_text.py 的区别：那个只数帧，这个把服务端回的每一帧 opus
连同到达时刻一起存下来，解码成 wav 供人耳听，同时算出「听起来怪」通常对应的
几个客观量：时长/语速、F0（是不是被变速）、到达间隔（是不是卡）、削波/静音。

用法：
    .venv/bin/python test/voice_probe.py --text "你好，我今天有点冷"
    .venv/bin/python test/voice_probe.py --text "..." --text "..." --out /tmp/probe
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import wave
from difflib import SequenceMatcher

import edge_tts
import numpy as np
import opuslib_next
import websockets

SR = 16000
FRAME = 960          # 60ms @16k，服务端发送节奏按 60ms/帧
SRC_HZ = 16000

HELLO = {
    "type": "hello",
    "version": 1,
    "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": SRC_HZ,
                     "channels": 1, "frame_duration": 60},
}


# ---------- 造输入音频 ----------
async def synth(text, voice, proxy, mp3_path):
    communicate = edge_tts.Communicate(text, voice=voice, proxy=proxy)
    with open(mp3_path, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])


def to_pcm(mp3_path, pcm_path):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path,
         "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(SRC_HZ), pcm_path],
        check=True,
    )


def encode_frames(pcm_path):
    encoder = opuslib_next.Encoder(SRC_HZ, 1, "voip")
    data = open(pcm_path, "rb").read()
    step = FRAME * 2
    frames = [encoder.encode(data[i:i + step], FRAME)
              for i in range(0, len(data) - step + 1, step)]
    return frames


def silence_frame():
    encoder = opuslib_next.Encoder(SRC_HZ, 1, "voip")
    return encoder.encode(b"\x00\x00" * FRAME, FRAME)


# ---------- 收音频 ----------
async def run_turn(ws, text, frames_in, args, turn_idx):
    if args.mode == "text":
        # 绕开 ASR：直接以 detect+text 触发 LLM→TTS，只听「播出来什么」
        await ws.send(json.dumps({"type": "listen", "state": "detect", "text": text}))
    else:
        await ws.send(json.dumps({"type": "listen", "mode": "manual", "state": "start"}))
        await asyncio.sleep(args.lead)
        for frame in frames_in:
            await ws.send(frame)
            await asyncio.sleep(0.06)
        sil = silence_frame()
        for _ in range(int(args.tail / 0.06)):
            await ws.send(sil)
            await asyncio.sleep(0.06)
        await ws.send(json.dumps({"type": "listen", "state": "stop"}))

    stt, sentences, packets = [], [], []
    t_stop = time.perf_counter()
    deadline = t_stop + args.wait
    while time.perf_counter() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=min(5, max(0.1, deadline - time.perf_counter())))
        except asyncio.TimeoutError:
            continue
        now = time.perf_counter() - t_stop
        if isinstance(msg, bytes):
            packets.append((now, msg))
            continue
        payload = json.loads(msg)
        kind = payload.get("type")
        if kind == "stt":
            stt.append(payload.get("text", ""))
        elif kind == "tts":
            state = payload.get("state")
            if state == "sentence_start":
                sentences.append(payload.get("text", ""))
            elif state == "stop":
                break
    return {"idx": turn_idx, "text": text, "stt": "".join(stt),
            "sentences": sentences, "packets": packets}


# ---------- 分析 ----------
def decode_packets(packets):
    decoder = opuslib_next.Decoder(SR, 1)
    samples, bad = [], 0
    for _, data in packets:
        try:
            pcm = decoder.decode(data, 1920)
            samples.append(np.frombuffer(pcm, dtype="<i2"))
        except Exception:
            bad += 1
    if not samples:
        return np.zeros(0, dtype="<i2"), bad
    return np.concatenate(samples), bad


def f0_estimate(x, sr=SR):
    """自相关粗估基频，判断是否被变速（正常中文女声 150~300Hz）。"""
    if len(x) < sr // 2:
        return None
    f = x.astype(np.float64)
    f -= f.mean()
    # 取最响的 1s 窗口
    win = sr
    if len(f) > win:
        energy = np.convolve(f ** 2, np.ones(win), "valid")
        start = int(np.argmax(energy))
        f = f[start:start + win]
    f = f[:win]
    corr = np.correlate(f, f, "full")[len(f) - 1:]
    lo, hi = sr // 500, sr // 60
    if hi <= lo + 2:
        return None
    seg = corr[lo:hi]
    if seg.size == 0 or corr[0] <= 0:
        return None
    lag = lo + int(np.argmax(seg))
    return sr / lag


def analyze(turn, outdir):
    packets = turn["packets"]
    pcm, bad = decode_packets(packets)
    dur = len(pcm) / SR
    name = f"turn{turn['idx']}"
    wav_path = os.path.join(outdir, name + ".wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.astype("<i2").tobytes())

    times = np.array([p[0] for p in packets], dtype=float)
    gaps = np.diff(times) * 1000 if len(times) > 1 else np.zeros(0)

    peak = int(np.max(np.abs(pcm))) if len(pcm) else 0
    rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2))) if len(pcm) else 0.0
    clip = int(np.sum(np.abs(pcm.astype(np.int32)) >= 32000)) if len(pcm) else 0
    # 帧级能量，找静音段
    body = pcm[: (len(pcm) // FRAME) * FRAME]
    if len(body):
        fr = body.reshape(-1, FRAME).astype(np.float64)
        fr_rms = np.sqrt(np.mean(fr ** 2, axis=1))
        silent = int(np.sum(fr_rms < 200))
    else:
        silent = 0

    sent_chars = sum(len(s) for s in turn["sentences"]) or len(turn["text"])
    f0 = f0_estimate(pcm)

    return {
        "turn": turn["idx"],
        "text": turn["text"],
        "stt": turn["stt"],
        "asr_similarity": round(SequenceMatcher(None, turn["text"], turn["stt"]).ratio(), 3),
        "sentences": turn["sentences"],
        "wav": wav_path,
        "frames": len(packets),
        "decode_errors": bad,
        "audio_seconds": round(dur, 2),
        "first_frame_at": round(times[0], 2) if len(times) else None,
        "last_frame_at": round(times[-1], 2) if len(times) else None,
        "wall_span_seconds": round(float(times[-1] - times[0]), 2) if len(times) > 1 else 0,
        "gap_p50_ms": round(float(np.percentile(gaps, 50)), 1) if gaps.size else None,
        "gap_p95_ms": round(float(np.percentile(gaps, 95)), 1) if gaps.size else None,
        "gap_max_ms": round(float(gaps.max()), 1) if gaps.size else None,
        "gaps_over_100ms": int(np.sum(gaps > 100)) if gaps.size else 0,
        "chars_per_second": round(sent_chars / dur, 2) if dur else None,
        "peak": peak,
        "rms": round(rms, 1),
        "clipped_samples": clip,
        "silent_frames": silent,
        "f0_hz": round(f0, 1) if f0 else None,
    }


async def main_async(args):
    outdir = args.out or f"/tmp/xzs-probe-{int(time.time())}"
    os.makedirs(outdir, exist_ok=True)
    src = os.path.join(outdir, "_input")
    os.makedirs(src, exist_ok=True)

    prepared = []
    for i, text in enumerate(args.text if args.mode == "voice" else []):
        mp3 = os.path.join(src, f"in{i}.mp3")
        pcm = os.path.join(src, f"in{i}.pcm")
        await synth(text, args.voice, args.proxy, mp3)
        to_pcm(mp3, pcm)
        prepared.append(encode_frames(pcm))
        print(f"[in] {text} -> {len(prepared[-1])} 帧")

    turns = []
    async with websockets.connect(args.url,
                                  additional_headers={"device-id": args.device_id},
                                  open_timeout=10, max_size=None) as ws:
        await ws.send(json.dumps(HELLO))
        hello = await asyncio.wait_for(ws.recv(), timeout=10)
        print(f"[hello] {hello[:120]}")
        await asyncio.sleep(args.warm)
        for i, text in enumerate(args.text):
            print(f"[turn {i}] 推入 {text}")
            frames_in = prepared[i] if args.mode == "voice" else []
            turns.append(await run_turn(ws, text, frames_in, args, i))

    reports = [analyze(t, outdir) for t in turns]
    with open(os.path.join(outdir, "report.json"), "w") as fh:
        json.dump(reports, fh, ensure_ascii=False, indent=2)

    print("\n=== 报告 ===")
    for r in reports:
        print(f"turn{r['turn']}: {r['audio_seconds']}s / {r['frames']} 帧 / "
              f"语速 {r['chars_per_second']} 字/秒 / F0 {r['f0_hz']}Hz")
        print(f"  到达间隔 p50={r['gap_p50_ms']}ms p95={r['gap_p95_ms']}ms "
              f"max={r['gap_max_ms']}ms >100ms={r['gaps_over_100ms']} 处")
        print(f"  ASR 相似度 {r['asr_similarity']}  ({r['stt']!r})")
        print(f"  峰值 {r['peak']} / RMS {r['rms']} / 削波 {r['clipped_samples']} / "
              f"静音帧 {r['silent_frames']} / 解码错 {r['decode_errors']}")
        print(f"  wav: {r['wav']}")
    print(f"\n输出目录: {outdir}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="append", required=True,
                        help="可重复；每个 --text 是一轮")
    parser.add_argument("--url", default="ws://127.0.0.1:8010/xiaozhi/v1/")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--proxy", default=os.environ.get("http_proxy"))
    parser.add_argument("--out", default=None)
    parser.add_argument("--wait", type=float, default=90)
    parser.add_argument("--warm", type=float, default=3.0)
    parser.add_argument("--lead", type=float, default=1.5)
    parser.add_argument("--tail", type=float, default=2.0)
    parser.add_argument("--device-id", default="voice-probe")
    parser.add_argument("--mode", choices=["text", "voice"], default="text",
                        help="text=detect+文本直通TTS（只测播放）；voice=推音频走ASR（测输入+输出）")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
