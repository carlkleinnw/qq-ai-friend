"""Generate a public, non-personal voice sample using the upstream adapter."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["ASTRBOT_ROOT"] = str(ROOT / "runtime/app")
os.environ["PATH"] = str(ROOT / "runtime/tools") + os.pathsep + os.environ.get("PATH", "")


async def main():
    from astrbot.core.provider.sources.edge_tts_source import ProviderEdgeTTS

    provider = ProviderEdgeTTS({
        "id": "edge_tts", "type": "edge_tts", "provider_type": "text_to_speech",
        "edge-tts-voice": "zh-CN-XiaoxiaoNeural", "timeout": 20,
    }, {})
    try:
        path = await asyncio.wait_for(provider.get_audio("你好，今天过得怎么样？我在这里听你说。"), timeout=40)
        print(json.dumps({"generated": True, "audio_path": path}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"generated": False, "error_type": type(exc).__name__}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
