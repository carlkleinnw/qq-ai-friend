"""Regression coverage using AstrBot's real SQLite persona store, never QQ or an LLM."""
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / 'runtime/temp').mkdir(parents=True, exist_ok=True)
SANDBOX = tempfile.TemporaryDirectory(dir=ROOT / 'runtime/temp')
os.environ['ASTRBOT_ROOT'] = SANDBOX.name

import astrbot.api
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.persona_mgr import PersonaManager
from plugins.astrbot_plugin_persona_studio.main import PersonaStudio
from plugins.astrbot_plugin_persona_studio.qq_menu import merge_persona_menu, persona_menu


class Config(dict):
    fail = False

    def save_config(self):
        if self.fail:
            raise OSError('disk full')
        self.saved = json.loads(json.dumps(self))


class PersonaRepair(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SANDBOX.name)
        self.db = SQLiteDatabase(str(Path(self.temp.name) / 'personas.db'))
        await self.db.initialize()
        cfg = {'agent_runner': {'runner_type': 'local', 'config': {'persona': {'persona_id': 'robot'}}}, 'platform': []}
        self.acm = SimpleNamespace(default_conf=cfg, get_conf=lambda umo=None: cfg)
        self.manager = PersonaManager(self.db, self.acm)
        await self.manager.initialize()
        await self.manager.create_persona('robot', 'existing', tools=['memory'], skills=['read'])
        self.config = Config(bots=[{'bot_id': 'qq', 'name': 'QQ'}], custom_presets=[])
        context = SimpleNamespace(persona_manager=self.manager, get_config=lambda umo=None: cfg,
                                  register_web_api=lambda *args: None,
                                  get_llm_tool_manager=lambda: SimpleNamespace(
                                      func_list=[SimpleNamespace(name='memory')], iter_builtin_tools=lambda: []))
        self.plugin = PersonaStudio(context, self.config)
        self.plugin.sync_menus = AsyncMock(return_value=[])

    async def asyncTearDown(self):
        await self.db.engine.dispose()
        self.temp.cleanup()

    async def create(self, name='测试预设'):
        result = await self.plugin.save_preset({'name': name, 'bio': '', 'prompt': 'original', 'bot_id': 'qq'})
        return next(p for p in result['presets'] if p['id'] == result['preset_id'])

    async def test_create_inherits_tools_and_survives_reload(self):
        item = await self.create()
        ref = self.config['custom_presets'][0]
        native = await self.manager.get_persona(ref['persona_id'])
        self.assertEqual(native.tools, ['memory'])
        self.assertEqual(native.skills, ['read'])
        self.plugin.config = Config(self.config.saved)
        self.assertIn(item['id'], [p['id'] for p in await self.plugin.get_presets()])
        self.assertEqual((await self.manager.get_persona('robot')).system_prompt, 'existing')

    async def test_edit_keeps_stable_id_and_capabilities(self):
        item = await self.create()
        result = await self.plugin.change_preset({**item, 'preset_id': item['id'], 'name': '新名字', 'prompt': 'new', 'bot_id': 'qq'})
        changed = next(p for p in result['presets'] if p['id'] == item['id'])
        self.assertEqual((changed['name'], changed['prompt']), ('新名字', 'new'))
        native = await self.manager.get_persona(self.config['custom_presets'][0]['persona_id'])
        self.assertEqual(native.tools, ['memory'])

    async def test_builtin_edit_uses_native_store(self):
        item = (await self.plugin.get_presets())[0]
        await self.plugin.change_preset({**item, 'preset_id': item['id'], 'name': '我的预设', 'bot_id': 'qq'})
        items = await self.plugin.get_presets()
        self.assertEqual(sum(p['id'] == item['id'] for p in items), 1)
        self.assertTrue(self.config['custom_presets'][0]['persona_id'].startswith('preset-'))

    async def test_delete_hides_builtin_and_preserves_active_persona(self):
        item = (await self.plugin.get_presets())[0]
        result = await self.plugin.change_preset({'preset_id': item['id'], 'revision': item['revision']}, delete=True)
        self.assertNotIn(item['id'], [p['id'] for p in result['presets']])
        self.assertEqual((await self.manager.get_persona('robot')).system_prompt, 'existing')

    async def test_delete_custom_does_not_resurface_as_native(self):
        item = await self.create()
        await self.plugin.change_preset({'preset_id': item['id'], 'revision': item['revision']}, delete=True)
        self.assertNotIn(item['name'], [p['name'] for p in await self.plugin.get_presets()])
        await self.manager.get_persona(self.config['custom_presets'][0]['persona_id'])

    async def test_existing_native_persona_is_visible(self):
        await self.manager.create_persona('原生人设', 'native')
        self.assertIn('native-原生人设', [p['id'] for p in await self.plugin.get_presets()])

    async def test_concurrent_edits_reject_stale_revision(self):
        item = await self.create()
        body = {**item, 'preset_id': item['id'], 'prompt': 'changed', 'bot_id': 'qq'}
        await self.plugin.change_preset(body)
        with self.assertRaises(ValueError):
            await self.plugin.change_preset(body)

    async def test_duplicate_name_rejected(self):
        await self.create()
        with self.assertRaises(ValueError):
            await self.create()

    async def test_failed_config_save_rolls_back_native_edit(self):
        item = await self.create()
        self.config.fail = True
        with self.assertRaises(OSError):
            await self.plugin.change_preset({**item, 'preset_id': item['id'], 'prompt': 'lost', 'bot_id': 'qq'})
        self.assertEqual((await self.plugin.get_presets())[-1]['prompt'], 'original')

    async def test_failed_create_cleans_up_native_row(self):
        count = len(await self.manager.get_all_personas())
        self.config.fail = True
        with self.assertRaises(OSError):
            await self.create()
        self.assertEqual(len(await self.manager.get_all_personas()), count)
        self.assertEqual(self.config['custom_presets'], [])

    async def test_current_persona_tools_support_null_empty_and_selected(self):
        for tools in (None, [], ['memory']):
            current = await self.plugin.snapshot('qq')
            result = await self.plugin.save_form({**current, 'prompt': 'updated', 'tools': tools})
            self.assertEqual(result['tools'], tools)
            self.assertEqual((await self.manager.get_persona('robot')).skills, ['read'])

    async def test_unknown_tools_rejected(self):
        current = await self.plugin.snapshot('qq')
        with self.assertRaises(ValueError):
            await self.plugin.save_form({**current, 'tools': ['unknown']})

    async def test_unchanged_browser_text_preserves_original_line_endings(self):
        await self.manager.update_persona('robot', system_prompt='first\r\nsecond\r\nthird')
        current = await self.plugin.snapshot('qq')
        await self.plugin.save_form({**current, 'prompt': current['prompt'].replace('\r\n', '\n'), 'tools': []})
        native = await self.manager.get_persona('robot')
        self.assertEqual(native.system_prompt, 'first\r\nsecond\r\nthird')
        self.assertEqual(native.tools, [])

    async def test_qq_unauthorized_private_cannot_write(self):
        event = SimpleNamespace(is_private_chat=lambda: True, unified_msg_origin='qq:FriendMessage:user',
                                get_platform_id=lambda: 'qq', is_admin=lambda: False, get_sender_id=lambda: 'user')
        with self.assertRaises(ValueError):
            self.plugin.qq_commands.authorize(event)
        self.config['qq_editor_sessions'] = ['qq:FriendMessage:user']
        self.assertEqual(self.plugin.qq_commands.authorize(event)[1], 'qq')


class Menus(unittest.TestCase):
    def test_native_long_and_duplicate_names_fit_qq_without_changing_ids(self):
        presets = [{'id': 'a', 'name': '这是一个很长的原生人格名字'},
                   {'id': 'b', 'name': '这是一个很长的原生人格名字'}]
        items = persona_menu(presets)[1]['sub_menu_items']
        self.assertNotEqual(items[0]['name'], items[1]['name'])
        self.assertTrue(all(sum(2 if ord(c) > 127 else 1 for c in i['name']) <= 14 for i in items))
        self.assertEqual(items[1]['send_message'], '/人设 b')

    def test_stable_commands_do_not_depend_on_list_order(self):
        p = [{'id': 'warm', 'name': '温柔'}]
        self.assertEqual(persona_menu(p)[1]['sub_menu_items'][0]['send_message'], '/人设 warm')

    def test_deleted_pages_pruned_and_unrelated_metadata_preserved(self):
        presets = [{'id': str(i), 'name': '预设' + str(i)} for i in range(7)]
        unrelated = {'type': 'send_message', 'name': '帮助', 'send_message': '/help'}
        old = {'items': [unrelated, *persona_menu(presets)], 'custom': 'keep'}
        new = merge_persona_menu(old, presets[:1])
        self.assertNotIn('预设2', [m['name'] for m in new['items']])
        self.assertIn(unrelated, new['items'])
        self.assertEqual(new['custom'], 'keep')
        self.assertEqual(new, merge_persona_menu(new, presets[:1]))

    def test_empty_library_keeps_settings_menu(self):
        self.assertEqual(len(merge_persona_menu({}, [])['items']), 1)

    def test_foreign_menu_collision_is_rejected(self):
        with self.assertRaises(ValueError):
            merge_persona_menu({'items': [{'name': '选择预设', 'type': 'menu', 'sub_menu_items': [
                {'type': 'send_message', 'send_message': '/unrelated'}]}]}, [{'id': 'a', 'name': 'A'}])


if __name__ == '__main__':
    unittest.main()
