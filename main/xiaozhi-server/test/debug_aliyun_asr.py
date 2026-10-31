#!/usr/bin/env python3
"""诊断脚本：绕开小智服务端，直接跟阿里云流式 ASR 对话，定位“连上了但识别不出字”。

用法：
    .venv/bin/python test/debug_aliyun_asr.py                 # 用 data/.config.yaml 的配置
    .venv/bin/python test/debug_aliyun_asr.py --no-proxy      # 强制直连
    .venv/bin/python test/debug_aliyun_asr.py --silence       # 推静音，验证链路本身

它会打印每一条服务端消息（TranscriptionStarted / ResultChanged / SentenceEnd …），
所以能区分三种情况：连不上 / 连上但没数据 / 有数据但没识别结果。
"""

import argparse
import asyncio
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets  # noqa: E402
import yaml  # noqa: E402

from core.providers.asr.aliyun_stream import AccessToken  # noqa: E402


def load_asr_config():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    merged = {}
    for name in ("config.yaml", "data/.config.yaml"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                merged.update(yaml.safe_load(handle) or {})
    block = (merged.get("ASR") or {}).get("AliyunStreamASR") or {}
    return block


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--silence", action="store_true", help="（保留位，已改为推真实语音）")
    parser.add_argument("--audio", help="直接给一个 16k 单声道 pcm 文件")
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()

    cfg = load_asr_config()
    appkey = cfg.get("appkey")
    ak = cfg.get("access_key_id")
    sk = cfg.get("access_key_secret")
    host = cfg.get("host", "nls-gateway-cn-shanghai.aliyuncs.com")
    proxy = None if args.no_proxy else cfg.get("proxy")
    print(f"appkey={appkey} host={host} proxy={proxy}")

    token, _ = AccessToken.create_token(ak, sk)
    if not token:
        print("FAIL: 取不到 token（AK/SK 无效？）")
        return 1
    print(f"token 获取成功（{token[:12]}…）")

    url = f"wss://{host}/ws/v1"
    kwargs = {"additional_headers": {"X-NLS-Token": token}, "ping_interval": None, "ping_timeout": None}
    if proxy:
        kwargs["proxy"] = proxy
    else:
        kwargs["proxy"] = None

    try:
        ws = await websockets.connect(url, open_timeout=10, **kwargs)
    except Exception as exc:
        print(f"FAIL: 连接失败 {type(exc).__name__}: {exc}")
        return 1

    start = {
        "header": {
            "namespace": "SpeechTranscriber",
            "name": "StartTranscription",
            "status": 20000000,
            "message_id": "".join(random.choices("0123456789abcdef", k=32)),
            "task_id": "".join(random.choices("0123456789abcdef", k=32)),
            "status_text": "Gateway:SUCCESS:Success.",
            "appkey": appkey,
        },
        "payload": {
            "format": "pcm",
            "sample_rate": 16000,
            "enable_intermediate_result": True,
            "enable_punctuation_prediction": True,
            "enable_inverse_text_normalization": True,
            "max_sentence_silence": 800,
            "enable_voice_detection": False,
        },
    }
    await ws.send(json.dumps(start))
    print("已发送 StartTranscription")

    ready = False
    results = []

    async def reader():
        nonlocal ready
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("[reader] 30s 无消息")
                return
            except Exception as exc:
                print(f"[reader] 结束: {type(exc).__name__}: {exc}")
                return
            try:
                message = json.loads(raw)
            except Exception:
                continue
            name = (message.get("header") or {}).get("name")
            status = (message.get("header") or {}).get("status")
            text = (message.get("payload") or {}).get("result") or ""
            print(f"[asr] {name} status={status} result={text!r}")
            if name == "TranscriptionStarted":
                ready = True
            if name in ("SentenceEnd", "TranscriptionCompleted"):
                results.append(text)

    task = asyncio.create_task(reader())
    for _ in range(50):
        if ready:
            break
        await asyncio.sleep(0.1)
    if not ready:
        print("FAIL: 没等到 TranscriptionStarted")
        task.cancel()
        await ws.close()
        return 1

    # 推真实语音：edge-tts 合成一句话 → ffmpeg 转 16k 单声道 → 按 60ms 推
    import struct
    import subprocess
    import tempfile

    import edge_tts

    workdir = tempfile.mkdtemp(prefix="asr-debug-")
    mp3 = os.path.join(workdir, "say.mp3")
    pcm_path = os.path.join(workdir, "say.pcm")
    if args.audio:
        pcm_path = args.audio
    else:
        text = "你好，我今天有点冷，想喝点热的"
        communicate = edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural", proxy=proxy)
        with open(mp3, "wb") as handle:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    handle.write(chunk["data"])
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-f", "s16le",
             "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", pcm_path],
            check=True,
        )
        print(f"合成样例音频：{text}")

    with open(pcm_path, "rb") as handle:
        data = handle.read()
    frame_bytes = 960 * 2
    frames = 0
    for offset in range(0, len(data) - frame_bytes + 1, frame_bytes):
        try:
            await ws.send(data[offset : offset + frame_bytes])
        except Exception as exc:
            print(f"FAIL: 发送音频失败 {type(exc).__name__}: {exc}")
            break
        frames += 1
        await asyncio.sleep(0.06)
    print(f"已推送 {frames} 帧（{frames * 0.06:.1f}s）")

    # 推静音收尾，触发 max_sentence_silence
    for _ in range(12):
        await ws.send(b"\x00\x00" * 960)
        await asyncio.sleep(0.06)

    await asyncio.sleep(3)
    task.cancel()
    try:
        await ws.close()
    except Exception:
        pass
    print(f"识别结果: {results or '(无)'}")
    return 0 if results else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
