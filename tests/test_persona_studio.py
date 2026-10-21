from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import pytest
import astrbot.api  # Match native plugin startup order before importing manager internals.
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.persona_mgr import PersonaManager
from plugins.astrbot_plugin_persona_studio.main import PersonaStudio
from plugins.astrbot_plugin_persona_studio.persona_form import pack, unpack

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_prompt_is_lossless_and_native_edit_remains_possible():
    prompt = ' 用户原有提示词。\n工具与语气保持。\n'
    assert pack(*unpack(prompt)) == prompt
    assert unpack(pack('我从 QQ 粘贴的简介。', prompt)) == ['我从 QQ 粘贴的简介。', prompt]
    assert 'QQ 粘贴' in pack('我从 QQ 粘贴的简介。', '')


@pytest.mark.parametrize('bio,prompt', [('', '  '), (None, 'x'), ('a' * 1001, 'x'), ('ok', 'a' * 20001)])
def test_invalid_input_is_rejected(bio, prompt):
    with pytest.raises(ValueError):
        pack(bio, prompt)


class PersonaIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(dir=ROOT / 'runtime/temp')
        self.db = SQLiteDatabase(str(Path(self.directory.name) / 'personas.db'))
        await self.db.initialize()
        self.configs = {bot: {'agent_runner': {'runner_type': 'local', 'config': {'persona': {'persona_id': pid}}}}
                        for bot, pid in [('bot-a', 'friend-a'), ('bot-b', 'friend-b')]}
        acm = SimpleNamespace(default_conf=self.configs['bot-a'])
        self.manager = PersonaManager(self.db, acm)
        await self.manager.initialize()
        for pid in ['friend-a', 'friend-b']:
            await self.manager.create_persona(pid, 'original-' + pid, tools=['future_task'], skills=[],
                                              begin_dialogs=['你好', '你好呀'], custom_error_message='稍后重试')
        platforms = [{'id': b, 'enable': True} for b in self.configs]
        self.context = SimpleNamespace(persona_manager=self.manager, register_web_api=Mock(),
                                       get_config=lambda umo=None: self.configs[umo.split(':')[0]] if umo else {'platform': platforms})
        self.plugin = PersonaStudio(self.context, {'bots': [{'bot_id': b, 'name': b} for b in self.configs]})

    async def asyncTearDown(self):
        await self.db.engine.dispose()
        self.directory.cleanup()

    async def test_save_uses_native_store_preserves_tools_and_other_bot_and_survives_reload(self):
        before = await self.plugin.snapshot('bot-a')
        other = await self.plugin.snapshot('bot-b')
        await self.plugin.save_form({**before, 'bio': '自定义简介', 'prompt': '说话简洁、温柔。'})
        p = await self.manager.get_persona('friend-a')
        self.assertEqual(['future_task'], p.tools)
        self.assertEqual([], p.skills)
        self.assertEqual(['你好', '你好呀'], p.begin_dialogs)
        self.assertEqual('稍后重试', p.custom_error_message)
        self.assertEqual(other, await self.plugin.snapshot('bot-b'))
        await self.manager.initialize()
        self.assertIn('自定义简介', self.manager.get_persona_v3_by_id('friend-a')['prompt'])
        self.assertEqual('自定义简介', (await self.plugin.snapshot('bot-a'))['bio'])

    async def test_stale_revision_or_changed_route_does_not_overwrite_native_edits(self):
        before = await self.plugin.snapshot('bot-a')
        await self.manager.update_persona('friend-a', system_prompt='native-editor-change')
        with self.assertRaisesRegex(ValueError, '别处修改'):
            await self.plugin.save_form({**before, 'bio': '', 'prompt': 'overwrite'})
        self.assertEqual('native-editor-change', (await self.manager.get_persona('friend-a')).system_prompt)
        latest = await self.plugin.snapshot('bot-a')
        self.configs['bot-a']['agent_runner']['config']['persona']['persona_id'] = 'friend-b'
        with self.assertRaisesRegex(ValueError, '绑定已改变'):
            await self.plugin.save_form({**latest, 'prompt': 'overwrite'})

    async def test_shared_persona_and_unconfigured_bot_are_rejected(self):
        self.configs['bot-b'] = self.configs['bot-a']
        before = await self.plugin.snapshot('bot-a')
        with self.assertRaisesRegex(ValueError, '共用'):
            await self.plugin.save_form({**before, 'prompt': 'overwrite'})
        with self.assertRaises(ValueError):
            await self.plugin.save_form({**before, 'bot_id': 'unknown', 'prompt': 'overwrite'})

    async def test_presets_are_drafts_not_automatic_mutations(self):
        before = await self.plugin.snapshot('bot-a')
        self.assertEqual(5, len(self.plugin.presets))
        for preset in self.plugin.presets:
            self.assertTrue(pack(preset['bio'], preset['prompt']))
        self.assertEqual(before, await self.plugin.snapshot('bot-a'))
