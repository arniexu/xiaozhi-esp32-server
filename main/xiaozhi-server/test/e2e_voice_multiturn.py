#!/usr/bin/env python3
"""多轮语音对话压测：20 轮真实老人会说的话，走完整语音链路。

每轮都按真机协议推 opus 音频（listen start → 音频 → 2s 尾部静音 → listen stop），
统计每轮的 ASR 文本、回复句数、首帧延迟，最后给出汇总（成功率 / 首帧均值 / p95）。

运行：
    .venv/bin/python test/e2e_voice_multiturn.py                 # 默认 20 轮剧本
    .venv/bin/python test/e2e_voice_multiturn.py --turns 20 --gap 1.0
    .venv/bin/python test/e2e_voice_multiturn.py --only 3        # 只跑第 3 轮
"""

import argparse
import asyncio
import json
import os
import statistics
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
    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
}

SAMPLE_RATE = 16000
FRAME_SAMPLES = 960
FRAME_BYTES = FRAME_SAMPLES * 2

# 20 句老人真会说的话：寒暄、天气、吃饭、身体、记忆、情绪、设备指令、告别
SCRIPT = [
    "你好呀，你在吗",
    "今天天气怎么样啊",
    "明天出门要不要带伞",
    "我早上就喝了点粥，中午不知道吃啥",
    "我这条腿有点疼",
    "你说要不要去医院看看",
    "我孙子叫什么来着",
    "帮我记一下，明天下午三点去医院复查",
    "我记性不好，刚才让你记的啥事",
    "现在几点了",
    "我该吃药了吗",
    "晚上老是睡不着怎么办",
    "给我讲个笑话吧",
    "我有点想孩子了",
    "放首歌听听",
    "声音大一点",
    "昨天你说的那个我忘了",
    "你会不会嫌我烦啊",
    "今天星期几",
    "行，那先这样吧，再见",
]


async def synth(text, voice, proxy, path):
    communicate = edge_tts.Communicate(text, voice=voice, proxy=proxy)
    with open(path, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])


def to_pcm(mp3_path, pcm_path):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path, "-f", "s16le",
         "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), pcm_path],
        check=True,
    )


def encode(pcm_path):
    encoder = opuslib_next.Encoder(SAMPLE_RATE, 1, "voip")
    data = open(pcm_path, "rb").read()
    return [encoder.encode(data[i:i + FRAME_BYTES], FRAME_SAMPLES)
            for i in range(0, len(data) - FRAME_BYTES + 1, FRAME_BYTES)]


def silence_frames(seconds):
    encoder = opuslib_next.Encoder(SAMPLE_RATE, 1, "voip")
    frame = encoder.encode(b"\x00\x00" * FRAME_SAMPLES, FRAME_SAMPLES)
    return [frame] * int(seconds / 0.06)


async def one_turn(ws, frames, silence, wait):
    started = time.time()
    stop_at = None
    sentences, first_audio = [], None
    first_audio_after_stop = None
    audio_bytes = 0

    await ws.send(json.dumps({"type": "listen", "mode": "manual", "state": "start"}))
    await asyncio.sleep(0.3)
    for frame in frames:
        await ws.send(frame)
        await asyncio.sleep(0.06)
    for frame in silence:
        await ws.send(frame)
        await asyncio.sleep(0.06)
    await ws.send(json.dumps({"type": "listen", "state": "stop"}))
    stop_at = time.time()   # 用户"说完"的时刻：首帧延迟按这个算才真实

    stt = ""
    deadline = started + wait
    while time.time() < deadline:
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=min(5, deadline - time.time()))
        except asyncio.TimeoutError:
            continue
        if isinstance(message, bytes):
            audio_bytes += len(message)
            if first_audio is None:
                first_audio = time.time() - started
                if stop_at:
                    first_audio_after_stop = time.time() - stop_at
            continue
        payload = json.loads(message)
        kind = payload.get("type")
        if kind == "stt":
            stt = payload.get("text", "") or stt
        elif kind == "tts":
            if payload.get("state") == "sentence_start":
                sentences.append(payload.get("text", ""))
            elif payload.get("state") == "stop" and audio_bytes:
                break
        elif kind == "iot":
            # 设备指令（音量/播放）不会回 TTS，记一笔就继续等
            sentences.append(f"[iot] {json.dumps(payload.get('commands') or payload, ensure_ascii=False)[:60]}")

    elapsed = time.time() - started
    return {
        "stt": stt,
        "sentences": [s for s in sentences if s],
        "first_audio": first_audio,
        "after_stop": first_audio_after_stop,
        "audio_bytes": audio_bytes,
        "elapsed": elapsed,
    }


async def run(args):
    texts = SCRIPT[: args.turns]
    if args.only:
        texts = [SCRIPT[args.only - 1]]

    workdir = tempfile.mkdtemp(prefix="xzs-multi-")
    print(f"[prep] 合成 {len(texts)} 句样例语音…")
    jobs = []
    for index, text in enumerate(texts, 1):
        mp3 = os.path.join(workdir, f"{index}.mp3")
        pcm = os.path.join(workdir, f"{index}.pcm")
        jobs.append((index, text, mp3, pcm))
        await synth(text, args.voice, args.proxy, mp3)
    clips = {}
    for index, text, mp3, pcm in jobs:
        to_pcm(mp3, pcm)
        clips[index] = encode(pcm)
    silence = silence_frames(args.tail)

    results = []
    async with websockets.connect(
        args.url, additional_headers={"device-id": args.device_id}, open_timeout=10, max_size=None
    ) as ws:
        await ws.send(json.dumps(HELLO))
        await asyncio.wait_for(ws.recv(), timeout=10)
        await asyncio.sleep(args.warm)

        for index, text in enumerate(texts, 1):
            print(f"\n[{index}/{len(texts)}] 说：{text}")
            result = await one_turn(ws, clips[index], silence, args.wait)
            result["index"] = index
            result["said"] = text
            results.append(result)
            reply = " ".join(result["sentences"])[:80]
            first = f"{result['first_audio']:.1f}s" if result["first_audio"] else "无音频"
            after = f"{result['after_stop']:.1f}s" if result.get("after_stop") else "-"
            print(f"    ASR={result['stt']!r} 首帧={first} 说完后={after} 句数={len(result['sentences'])}")
            print(f"    回复={reply or '（空）'}")
            await asyncio.sleep(args.gap)

    ok = [r for r in results if r["sentences"] and r["audio_bytes"]]
    firsts = [r["first_audio"] for r in ok if r["first_audio"]]
    afters = [r["after_stop"] for r in ok if r.get("after_stop")]
    print("\n" + "=" * 60)
    print(f"轮数 {len(results)}　有语音回复 {len(ok)}　失败 {len(results) - len(ok)}")
    if firsts:
        print(f"首帧（含推音频）平均 {statistics.mean(firsts):.1f}s　中位 {statistics.median(firsts):.1f}s"
              f"　最大 {max(firsts):.1f}s")
    if afters:
        print(f"说完→出声 平均 {statistics.mean(afters):.2f}s　中位 {statistics.median(afters):.2f}s"
              f"　最大 {max(afters):.2f}s")
    for r in results:
        if not (r["sentences"] and r["audio_bytes"]):
            print(f"  ✗ 第 {r['index']} 轮失败：说「{r['said']}」ASR={r['stt']!r}")
    print("RESULT:", "PASS" if len(ok) >= len(results) - args.tolerate else "FAIL")
    return 0 if len(ok) >= len(results) - args.tolerate else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8010/xiaozhi/v1/")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--proxy", default=os.environ.get("http_proxy"))
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--only", type=int, help="只跑第 N 轮，便于单点排查")
    parser.add_argument("--wait", type=float, default=90, help="每轮最长等待")
    parser.add_argument("--gap", type=float, default=1.0, help="轮间隔")
    parser.add_argument("--tail", type=float, default=2.0, help="尾部静音（触发云端断句）")
    parser.add_argument("--warm", type=float, default=3.0)
    parser.add_argument("--tolerate", type=int, default=1, help="允许几轮没有语音回复")
    parser.add_argument("--device-id", default="e2e-multiturn")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
