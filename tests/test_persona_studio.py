from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import time

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
        acm = SimpleNamespace(default_conf=self.configs['bot-a'], confs=self.configs,
                              ucr=SimpleNamespace(umop_to_conf_id={b+'::': b for b in self.configs}))
        self.manager = PersonaManager(self.db, acm)
        await self.manager.initialize()
        for pid in ['friend-a', 'friend-b']:
            await self.manager.create_persona(pid, 'original-' + pid, tools=['future_task'], skills=[],
                                              begin_dialogs=['你好', '你好呀'], custom_error_message='稍后重试')
        platforms = [{'id': b, 'enable': True, 'type': 'qq_official'} for b in self.configs]
        tools = SimpleNamespace(func_list=[SimpleNamespace(name='future_task')], iter_builtin_tools=lambda: [])
        self.context = SimpleNamespace(persona_manager=self.manager, register_web_api=Mock(),
                                       astrbot_config_mgr=acm,
                                       get_llm_tool_manager=lambda: tools,
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

    def qq_event(self, text, bot='bot-a', sender='owner', scope=None, private=True, admin=False):
        return SimpleNamespace(get_message_str=lambda: text, get_platform_id=lambda: bot,
                               get_sender_id=lambda: sender, is_admin=lambda: admin,
                               is_private_chat=lambda: private,
                               unified_msg_origin=scope or f'{bot}:FriendMessage:{sender}')

    def allow_qq_owner(self):
        self.plugin.config['qq_editor_enabled_bots'] = ['bot-a', 'bot-b']

    async def test_qq_preset_preview_confirm_is_native_and_does_not_change_other_bot(self):
        self.allow_qq_owner()
        original = await self.plugin.snapshot('bot-a')
        other = await self.plugin.snapshot('bot-b')
        command = self.plugin.qq_commands.execute
        self.assertIn('体贴甜蜜女友', await command(self.qq_event('/人设')))
        self.assertIn('待确认：体贴甜蜜女友', await command(self.qq_event('/人设 5')))
        self.assertEqual(original, await self.plugin.snapshot('bot-a'))
        self.assertIn('已保存', await command(self.qq_event('/确认人设')))
        current = await self.plugin.snapshot('bot-a')
        self.assertEqual(self.plugin.presets[4]['bio'], current['bio'])
        self.assertEqual(self.plugin.presets[4]['prompt'], current['prompt'])
        self.assertIn('体贴甜蜜女友', await command(self.qq_event('/当前人设')))
        self.assertEqual(other, await self.plugin.snapshot('bot-b'))
        self.assertEqual(['future_task'], (await self.manager.get_persona('friend-a')).tools)
        self.assertIn('没有待确认', await command(self.qq_event('/确认人设')))

    async def test_qq_custom_text_preserves_spaces_and_newlines_and_cancel_keeps_native(self):
        self.allow_qq_owner()
        command = self.plugin.qq_commands.execute
        original = await self.plugin.snapshot('bot-a')
        text = '你是一位体贴的 AI 好友。\n说话温柔，少用套话。'
        self.assertIn('待确认', await command(self.qq_event('/自定义人设 ' + text)))
        self.assertIn('已取消', await command(self.qq_event('/取消人设')))
        self.assertEqual(original, await self.plugin.snapshot('bot-a'))
        await command(self.qq_event('/setpersona ' + text))
        self.assertIn('已保存', await command(self.qq_event('/confirmpersona')))
        self.assertEqual(text, (await self.plugin.snapshot('bot-a'))['prompt'])

    async def test_qq_switch_blocks_writes_when_off_and_rejects_groups_and_spoofed_scope(self):
        self.allow_qq_owner()
        command = self.plugin.qq_commands.execute
        original = await self.plugin.snapshot('bot-a')
        self.plugin.config['qq_editor_enabled_bots'] = []
        self.assertIn('开关已关闭', await command(self.qq_event('/人设 5', sender='stranger')))
        self.allow_qq_owner()
        self.assertIn('群聊中不执行', await command(self.qq_event('/人设 5', private=False, admin=True)))
        self.assertIn('消息来源不一致', await command(self.qq_event('/人设 5', sender='stranger', scope='bot-a:FriendMessage:owner')))
        self.assertIn('未找到', await command(self.qq_event('/人设 5', bot='unknown', admin=True)))
        self.assertEqual(original, await self.plugin.snapshot('bot-a'))
        self.assertEqual({}, self.plugin.qq_commands.pending)

    async def test_qq_expired_drafts_and_cross_bot_confirmation_do_not_save(self):
        self.allow_qq_owner()
        command = self.plugin.qq_commands.execute
        original = await self.plugin.snapshot('bot-a')
        await command(self.qq_event('/人设 体贴甜蜜女友'))
        self.assertIn('没有待确认', await command(self.qq_event('/确认人设', bot='bot-b')))
        self.plugin.qq_commands.pending[('bot-a:FriendMessage:owner', 'owner')]['expires'] = time.monotonic() - 1
        self.assertIn('已过期', await command(self.qq_event('/确认人设')))
        self.assertEqual(original, await self.plugin.snapshot('bot-a'))

    async def test_qq_confirmation_rejects_web_edits_with_enabled_robot(self):
        self.allow_qq_owner()
        command = self.plugin.qq_commands.execute
        await command(self.qq_event('/人设 5', admin=True))
        await self.manager.update_persona('friend-a', system_prompt='New web content')
        self.assertIn('未保存', await command(self.qq_event('/确认人设', admin=True)))
        self.assertEqual('New web content', (await self.plugin.snapshot('bot-a'))['prompt'])

    async def test_qq_invalid_or_oversized_custom_input_never_saves(self):
        self.allow_qq_owner()
        command = self.plugin.qq_commands.execute
        original = await self.plugin.snapshot('bot-a')
        self.assertIn('未找到', await command(self.qq_event('/人设 99')))
        self.assertIn('请直接发送', await command(self.qq_event('/自定义人设')))
        self.assertIn('20000', await command(self.qq_event('/自定义人设 ' + 'x' * 20001)))
        self.assertEqual(original, await self.plugin.snapshot('bot-a'))

    async def test_native_command_filter_accepts_alias_and_handler_stops_without_llm(self):
        from astrbot.api.event import AstrMessageEvent
        from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
        from astrbot.core.platform.message_type import MessageType
        from astrbot.core.platform.platform_metadata import PlatformMetadata
        from astrbot.core.star.star_handler import star_handlers_registry, EventType
        from astrbot.core.star.filter.command import CommandFilter
        self.allow_qq_owner()
        message = AstrBotMessage()
        message.type = MessageType.FRIEND_MESSAGE
        message.sender = MessageMember(user_id='owner', nickname='owner')
        event = AstrMessageEvent('presets 5', message, PlatformMetadata('qq_official', 'isolated test', 'bot-a'), 'owner')
        event.is_at_or_wake_command = True
        handler = next(h for h in star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent)
                       if h.handler_name == 'qq_persona_command' and h.handler_module_path == PersonaStudio.__module__)
        command_filter = next(f for f in handler.event_filters if isinstance(f, CommandFilter))
        self.assertTrue(command_filter.filter(event, {}))
        replies = [reply async for reply in self.plugin.qq_persona_command(event)]
        self.assertEqual(1, len(replies))
        self.assertIn('待确认', replies[0].chain[0].text)
        self.assertFalse(event.call_llm)
        self.assertTrue(event.is_stopped())
