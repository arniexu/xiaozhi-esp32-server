"""本地 TTS：sherpa-onnx 离线模型（不联网、不依赖代理）。

为什么加它：Edge TTS 每句要走一次 WSS 握手，实测 0.5–1.5 s，公司网代理抖动时更慢甚至 403；
sherpa 在本机 CPU 上合成，短句 **80–150 ms**，短句首包快到几乎无感。

配置（config.yaml）：

    TTS:
      SherpaTTS:
        type: sherpa
        model_dir: ~/.cache/xiaozhi-tts/vits-icefall-zh-aishell3
        speaker: 0        # 多说话人模型的声音编号
        speed: 1.0
        num_threads: 2

模型（31 MB，中文）下载：
    https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-icefall-zh-aishell3.tar.bz2
模型目录里需要 model.onnx / tokens.txt / lexicon.txt。
"""

import io
import os
import wave

try:
    import sherpa_onnx
except ImportError:  # 没装 sherpa_onnx 时给出可读的报错
    sherpa_onnx = None

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        if sherpa_onnx is None:
            raise RuntimeError("未安装 sherpa_onnx，无法使用本地 TTS")

        self.audio_file_type = "wav"
        self.voice = config.get("voice") or "sherpa"
        model_dir = os.path.expanduser(
            config.get("model_dir") or "~/.cache/xiaozhi-tts/vits-icefall-zh-aishell3"
        )
        self.speaker = int(config.get("speaker", 0))
        self.speed = float(config.get("speed", 1.0))
        threads = int(config.get("num_threads", 2))

        model_path = os.path.join(model_dir, "model.onnx")
        if not os.path.exists(model_path):
            raise RuntimeError(f"本地 TTS 模型不存在: {model_path}")

        rule_fsts = ",".join(
            os.path.join(model_dir, name)
            for name in ("date.fst", "number.fst", "phone.fst")
            if os.path.exists(os.path.join(model_dir, name))
        )
        vits_kwargs = {
            "model": model_path,
            "tokens": os.path.join(model_dir, "tokens.txt"),
        }
        lexicon = os.path.join(model_dir, "lexicon.txt")
        if os.path.exists(lexicon):
            vits_kwargs["lexicon"] = lexicon
        # aishell3 这类多说话人模型依赖 dict 目录
        if os.path.isdir(os.path.join(model_dir, "dict")):
            vits_kwargs["dict_dir"] = os.path.join(model_dir, "dict")
        elif os.path.exists(os.path.join(model_dir, "rule.far")):
            vits_kwargs["dict_dir"] = model_dir

        model_config = sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(**vits_kwargs),
            num_threads=threads,
        )
        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=model_config,
            rule_fsts=rule_fsts,
            max_num_sentences=1,
        )
        self.tts = sherpa_onnx.OfflineTts(tts_config)
        self.sample_rate = self.tts.sample_rate
        logger.bind(tag=TAG).info(
            f"本地 TTS 就绪: {os.path.basename(model_dir)} "
            f"({self.sample_rate} Hz, {self.tts.num_speakers} 个声音)"
        )

    async def text_to_speak(self, text, output_file):
        if not text:
            return None
        audio = self.tts.generate(text, sid=self.speaker, speed=self.speed)
        samples = getattr(audio, "samples", None)
        if not samples:
            return None

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(audio.sample_rate or self.sample_rate)
            handle.writeframes(
                b"".join(
                    int(max(-1.0, min(1.0, value)) * 32767).to_bytes(2, "little", signed=True)
                    for value in samples
                )
            )
        data = buffer.getvalue()

        if output_file:
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
            with open(output_file, "wb") as handle:
                handle.write(data)
            return None
        return data
