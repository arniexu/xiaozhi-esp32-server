#!/usr/bin/env python3
"""把「播放很奇怪」拆成可听可选的 A/B：同一句话，只改一个变量，各出一段音频。

产出目录里是若干 wav/mp3 + 一个 index.html（点开就能对比着听）。
变量只有三类：
  1) 链路环节：8k 原始 / 经 opus 16k 往返 / 服务器真实回放
  2) 语速：1.0 / 1.2 / 1.4
  3) 音色：aishell3 的不同 speaker + Edge 云端参考
"""

import asyncio
import os
import sys
import wave

import numpy as np
import opuslib_next
import sherpa_onnx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_DIR = os.path.expanduser("~/.cache/xiaozhi-tts/vits-icefall-zh-aishell3")
TEXT = "奶奶，今天天气不错，我陪您到院子里坐一会儿吧。"


def build_tts():
    kwargs = {
        "model": os.path.join(MODEL_DIR, "model.onnx"),
        "tokens": os.path.join(MODEL_DIR, "tokens.txt"),
    }
    lexicon = os.path.join(MODEL_DIR, "lexicon.txt")
    if os.path.exists(lexicon):
        kwargs["lexicon"] = lexicon
    vits = sherpa_onnx.OfflineTtsVitsModelConfig(**kwargs)
    model = sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=2)
    config = sherpa_onnx.OfflineTtsConfig(model=model, max_num_sentences=1)
    return sherpa_onnx.OfflineTts(config)


def write_wav(path, samples, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(
            b"".join(
                int(max(-1.0, min(1.0, v)) * 32767).to_bytes(2, "little", signed=True)
                for v in samples
            )
        )


def opus_roundtrip(samples, sr, bitrate=None):
    """按服务端真实做法：重采样到 16k → opus 60ms 编码 → 解码回来。"""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "in.raw")
        pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767
        pcm.astype("<i2").tofile(raw)
        pcm16 = os.path.join(td, "pcm16.raw")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(sr),
             "-ac", "1", "-i", raw, "-ar", "16000", "-ac", "1", "-f", "s16le", pcm16],
            check=True,
        )
        data = open(pcm16, "rb").read()

    enc = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
    if bitrate:                      # 不设则用 libopus 默认（实测 ~15.6kbps，偏低）
        enc.bitrate = bitrate
    dec = opuslib_next.Decoder(16000, 1)
    out = []
    for i in range(0, len(data), 1920):
        chunk = data[i:i + 1920]
        if len(chunk) < 1920:
            chunk += b"\x00" * (1920 - len(chunk))
        packet = enc.encode(chunk, 960)
        out.append(np.frombuffer(dec.decode(packet, 1920), dtype="<i2").astype(np.float32) / 32768.0)
    return (np.concatenate(out) if out else np.zeros(0, dtype=np.float32)), 16000


async def edge_tts_sample(text, out_mp3):
    import edge_tts

    communicate = edge_tts.Communicate(
        text, voice="zh-CN-XiaoxiaoNeural", proxy=os.environ.get("http_proxy")
    )
    with open(out_mp3, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])


def main():
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts-ab")
    outdir = sys.argv[1] if len(sys.argv) > 1 else default
    os.makedirs(outdir, exist_ok=True)
    tts = build_tts()
    print(f"模型采样率 {tts.sample_rate} Hz，说话人 {tts.num_speakers} 个")

    items = []

    def add(name, title, note, samples, sr):
        path = os.path.join(outdir, name + ".wav")
        write_wav(path, samples, sr)
        items.append((name + ".wav", title, note))

    # 1) 链路环节
    audio = tts.generate(TEXT, sid=0, speed=1.2)
    raw = audio.samples
    add("A_线上全链路", "A · 现在线上听到的", "8k 音源 + opus 16k 编解码（服务器就是这么发的）",
        *opus_roundtrip(raw, audio.sample_rate))
    add("B_仅8k原始", "B · 只有 8k 音源", "同一句，没走 opus，直接是模型输出（8kHz）",
        raw, audio.sample_rate)

    add("A2_高码率", "A2 · 只把 opus 码率提到 32kbps", "音源仍是 8k、语速仍 1.2，唯一变量是码率",
        *opus_roundtrip(raw, audio.sample_rate, bitrate=32000))

    # 2) 语速
    for sp in (1.0, 1.4):
        a = tts.generate(TEXT, sid=0, speed=sp)
        add(f"C_语速{sp}", f"C · 语速 {sp}", f"同一句、同一声音，speed={sp}",
            *opus_roundtrip(a.samples, a.sample_rate))

    # 3) 音色
    for sid in (20, 60):
        a = tts.generate(TEXT, sid=sid, speed=1.2)
        add(f"D_音色{sid}", f"D · 换声音 #{sid}", "aishell3 多说话人模型里的另一个音色",
            *opus_roundtrip(a.samples, a.sample_rate))

    # 4) 云端参考
    mp3 = os.path.join(outdir, "E_Edge参考.mp3")
    try:
        asyncio.run(edge_tts_sample(TEXT, mp3))
        items.append(("E_Edge参考.mp3", "E · Edge 云端参考", "24kHz 宽带、真人感强；代价是要走代理，慢"))
    except Exception as exc:  # 网络不通就不生成，不中断
        print(f"Edge 参考生成失败：{exc}")

    html = ["<!doctype html><meta charset='utf-8'><title>小智 TTS 对比</title>",
            "<style>body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 16px}"
            "section{margin:28px 0;padding:14px 18px;border:1px solid #ddd;border-radius:10px}"
            "h2{font-size:17px;margin:0 0 4px}p{color:#666;font-size:13px;margin:2px 0 10px}"
            "audio{width:100%}</style>",
            f"<h1>同一句话，只改一个变量</h1><p>原句：{TEXT}</p>"]
    for group, prefix in (("1 · 先定位是哪一环", ("A", "B")),
                          ("2 · 码率（一行改动的效果）", ("A2",)),
                          ("3 · 语速", ("C",)),
                          ("4 · 音色", ("D", "E"))):
        html.append(f"<section><h2>{group}</h2>")
        for filename, title, note in items:
            if filename[0] in prefix:
                html.append(f"<div style='margin:16px 0'><strong>{title}</strong>"
                            f"<p>{note}</p><audio controls preload='none' src='{filename}'></audio></div>")
        html.append("</section>")
    html.append("</body>")

    index = os.path.join(outdir, "index.html")
    with open(index, "w") as fh:
        fh.write("\n".join(html))
    print(f"\n生成 {len(items)} 段音频：{outdir}")
    print(f"打开：{os.path.abspath(index)}")


if __name__ == "__main__":
    main()
