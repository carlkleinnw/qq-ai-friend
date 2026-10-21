import importlib.util
from pathlib import Path

import pytest
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("dafeiyu_voice", ROOT / "scripts/setup_dafeiyu_voice.py")
voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)


def test_voice_configuration_preserves_other_settings_and_input():
    original = {"provider_tts_settings": {"enable": False, "use_file_service": False},
                "provider_settings": {"provider_id": "user-model"}, "other": ["user-data"]}
    updated = voice.voice_profile(original, "fish-voice")
    assert original["provider_tts_settings"] == {"enable": False, "use_file_service": False}
    assert updated["provider_settings"] == original["provider_settings"]
    assert updated["other"] == ["user-data"]
    assert updated["provider_tts_settings"] == {"enable": True, "use_file_service": False,
                                               "provider_id": "fish-voice", "dual_output": True, "trigger_probability": 1.0}
    disabled = voice.voice_profile(updated, "unused", enabled=False)
    assert disabled["provider_tts_settings"] == {**updated["provider_tts_settings"], "enable": False}


def test_speaking_style_is_appended_once_without_overwriting_user_edits():
    original = "用户原有角色和工具规则。\n"
    style = voice.STYLE_HEADER + "\n测试风格。"
    updated = voice.speaking_prompt(original, style)
    assert updated.startswith(original)
    assert voice.speaking_prompt(updated, style) == updated
    with pytest.raises(ValueError, match="was edited"):
        voice.speaking_prompt(updated.replace("测试风格", "用户修改的风格"), style)


class NativeVoicePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def run_native_stage(self, *, failure=False, enabled=True):
        from astrbot.core.config.default import DEFAULT_CONFIG
        from astrbot.core.message.components import Plain
        from astrbot.core.message.message_event_result import MessageEventResult, ResultContentType
        from astrbot.core.pipeline.result_decorate.stage import ResultDecorateStage, star_handlers_registry, SessionServiceManager

        config = deepcopy(DEFAULT_CONFIG)
        config["platform_settings"].update(reply_prefix="", reply_with_mention=False, reply_with_quote=False)
        config["platform_settings"]["segmented_reply"]["enable"] = False
        config["provider_tts_settings"].update(enable=enabled, dual_output=True)
        config["t2i"] = False
        config["content_safety"]["also_use_in_response"] = False
        provider = SimpleNamespace(get_audio=AsyncMock(return_value="test-voice.wav"))
        if failure:
            provider.get_audio.side_effect = RuntimeError("Synthetic service outage")
        context = SimpleNamespace(astrbot_config=config, plugin_manager=SimpleNamespace(
            context=SimpleNamespace(get_using_tts_provider_async=AsyncMock(return_value=provider))))
        result = MessageEventResult(chain=[Plain("这是保留给用户的回复。")], result_content_type=ResultContentType.LLM_RESULT)
        event = SimpleNamespace(get_result=lambda: result, get_extra=lambda key: None,
                                get_platform_name=lambda: "qq_official", plugins_name=None,
                                unified_msg_origin="qq-test:FriendMessage:test")
        stage = ResultDecorateStage()
        await stage.initialize(context)
        with patch.object(star_handlers_registry, "get_handlers_by_event_type", return_value=[]), \
             patch.object(SessionServiceManager, "should_process_tts_request", AsyncMock(return_value=True)):
            async for _ in stage.process(event):
                pass
        return result, provider

    async def test_native_pipeline_keeps_text_with_voice(self):
        from astrbot.core.message.components import Plain, Record
        result, provider = await self.run_native_stage()
        self.assertEqual([type(c) for c in result.chain], [Record, Plain])
        self.assertEqual(result.chain[1].text, "这是保留给用户的回复。")
        provider.get_audio.assert_awaited_once()

    async def test_native_synthesis_failure_keeps_original_text(self):
        from astrbot.core.message.components import Plain
        result, provider = await self.run_native_stage(failure=True)
        self.assertEqual([type(c) for c in result.chain], [Plain])
        self.assertEqual(result.chain[0].text, "这是保留给用户的回复。")
        provider.get_audio.assert_awaited_once()

    async def test_disabled_voice_does_not_call_synthesis(self):
        from astrbot.core.message.components import Plain
        result, provider = await self.run_native_stage(enabled=False)
        self.assertEqual([type(c) for c in result.chain], [Plain])
        provider.get_audio.assert_not_awaited()
