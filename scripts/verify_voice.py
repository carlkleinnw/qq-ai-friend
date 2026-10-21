"""Generate a public, non-personal voice sample using the upstream adapter."""
from __future__ import annotations

import asyncio
import argparse
import json
import os
from pathlib import Path
import shutil
import wave

ROOT = Path(__file__).resolve().parents[1]
os.environ["ASTRBOT_ROOT"] = str(ROOT / "runtime/app")
os.environ["PATH"] = str(ROOT / "runtime/tools") + os.pathsep + os.environ.get("PATH", "")


async def main():
    from astrbot.core.provider.sources.edge_tts_source import ProviderEdgeTTS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = {
        "id": "edge_tts", "type": "edge_tts", "provider_type": "text_to_speech",
        "edge-tts-voice": "zh-CN-XiaoxiaoNeural", "timeout": 20,
    }
    text = "你好，今天过得怎么样？我在这里听你说。"
    if args.preset:
        config = json.loads(args.preset.read_text(encoding="utf-8"))
        if config.get("type") != "edge_tts":
            raise ValueError("This check uses the installed Edge TTS adapter")
        text = "哼，本鱼听见啦。今天想聊点什么？要是累了，就先歇一会儿，我在这儿陪你。"
    provider = ProviderEdgeTTS(config, {})
    try:
        path = await asyncio.wait_for(provider.get_audio(text), timeout=45)
        with wave.open(path, "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            assert wav.getnchannels() == 1 and wav.getsampwidth() == 2 and duration > 0
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, args.output)
            path = str(args.output.resolve())
        print(json.dumps({"generated": True, "audio_path": path, "duration_seconds": round(duration, 2)}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"generated": False, "error_type": type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    asyncio.run(main())
