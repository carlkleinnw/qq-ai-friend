"""Native registry reconciliation and QQ library changes share the real store."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import unittest
import tests.test_persona_repair as repair


class MultiBotSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await repair.PersonaRepair.asyncSetUp(self)
        self.platforms = [{'id': 'qq', 'type': 'qq_official', 'appid': 'test-qq', 'enable': True}]
        self.acm.default_conf['platform'] = self.platforms
        self.confs = {'old': self.acm.default_conf}
        self.routes = {'qq::': 'old'}
        self.acm.confs = self.confs
        self.acm.ucr = SimpleNamespace(umop_to_conf_id=self.routes)
        async def update(routes):
            self.routes.clear()
            self.routes.update(routes)
        self.acm.ucr.update_routing_data = AsyncMock(side_effect=update)
        async def create(config, name):
            key = 'new-' + str(len(self.confs))
            self.confs[key] = deepcopy(config)
            return key
        self.acm.create_conf = AsyncMock(side_effect=create)
        self.acm.delete_conf = AsyncMock()
        def get_config(umo=None):
            if not umo:
                return self.acm.default_conf
            return self.confs.get(self.routes.get(umo.split(':')[0] + '::'), self.acm.default_conf)
        self.plugin.context.astrbot_config_mgr = self.acm
        self.plugin.context.reload_pipeline_scheduler = AsyncMock()
        self.plugin.context.get_config = get_config
        self.plugin.context.get_platform_inst = lambda bot: SimpleNamespace(appid=next((p.get('appid','') for p in self.platforms if p['id']==bot),''),
            client=SimpleNamespace(robot=SimpleNamespace(name={'qq': '可名', 'qq-new': '新机器人'}.get(bot))))

    asyncTearDown = repair.PersonaRepair.asyncTearDown
    create = repair.PersonaRepair.create

    async def test_new_bot_gets_independent_native_persona_and_route_once(self):
        from astrbot.core import AstrBotConfig
        from pathlib import Path
        self.acm.default_conf = AstrBotConfig(config_path=str(Path(self.temp.name) / 'native.json'),
                                              default_config=deepcopy(self.acm.default_conf))
        self.platforms = self.acm.default_conf['platform']
        self.platforms.append({'id': 'qq-new', 'type': 'qq_official', 'enable': True})
        before = await self.plugin.snapshot('qq')
        await self.plugin.reconcile_bots()
        self.assertEqual({b['bot_id'] for b in self.plugin.targets()}, {'qq', 'qq-new'})
        self.assertEqual(self.plugin.targets()[1]['name'], '新机器人')
        created = await self.plugin.snapshot('qq-new')
        self.assertNotEqual(created['persona_id'], before['persona_id'])
        await self.plugin.save_form({**created, 'prompt': 'only new robot'})
        self.assertEqual(await self.plugin.snapshot('qq'), before)
        await self.plugin.reconcile_bots()
        self.assertEqual(self.acm.create_conf.await_count, 1)
        self.plugin.context.reload_pipeline_scheduler.assert_awaited_once()

    async def test_disabled_bot_remains_visible_and_deleted_bot_disappears(self):
        self.platforms[0]['enable'] = False
        await self.plugin.reconcile_bots()
        self.assertFalse(self.plugin.targets()[0]['enabled'])
        self.platforms.clear()
        await self.plugin.reconcile_bots()
        self.assertEqual(self.plugin.targets(), [])
        self.assertEqual((await self.manager.get_persona('robot')).system_prompt, 'existing')

    async def test_specific_session_rules_are_kept_before_new_bot_default(self):
        self.platforms.append({'id': 'qq-new', 'type': 'qq_official'})
        self.routes.update({'qq-new:FriendMessage:owner': 'old', '::': 'old'})
        await self.plugin.reconcile_bots()
        keys = list(self.routes)
        self.assertLess(keys.index('qq-new:FriendMessage:owner'), keys.index('qq-new::'))
        self.assertLess(keys.index('qq-new::'), keys.index('::'))

    async def test_failed_route_write_cleans_new_profile_and_persona(self):
        self.platforms.append({'id': 'qq-new', 'type': 'qq_official'})
        self.acm.ucr.update_routing_data.side_effect = OSError('disk full')
        before = {p.persona_id for p in await self.manager.get_all_personas()}
        await self.plugin.reconcile_bots()
        self.assertEqual({p.persona_id for p in await self.manager.get_all_personas()}, before)
        self.acm.delete_conf.assert_awaited_once()
        self.assertEqual(self.acm.ucr.umop_to_conf_id, {'qq::': 'old'})
        self.assertTrue(self.plugin.targets()[1]['error'])

    async def test_native_route_edit_during_profile_creation_is_preserved(self):
        self.platforms.append({'id': 'qq-new', 'type': 'qq_official'})
        create = self.acm.create_conf.side_effect
        async def create_with_native_edit(config, name):
            result = await create(config, name)
            self.routes['other:FriendMessage:session'] = 'old'
            return result
        self.acm.create_conf.side_effect = create_with_native_edit
        await self.plugin.reconcile_bots()
        self.assertEqual(self.routes['other:FriendMessage:session'], 'old')

    async def test_companion_registration_uses_existing_native_profile_operation(self):
        cfg = repair.Config(basic_config={'multi_persona_ids': ['primary']})
        create = AsyncMock(return_value={'ok': True})
        companion = SimpleNamespace(config=cfg, enable_multi_persona_mode=True,
                                    _primary_persona_id=lambda: 'primary',
                                    _configured_multi_persona_ids=lambda: cfg['basic_config']['multi_persona_ids'],
                                    _persona_config_exists=lambda pid: False,
                                    _create_persona_config_async=create)
        self.plugin.context.get_registered_star = lambda name: SimpleNamespace(activated=True, star_cls=companion)
        await self.plugin.reconcile_bots()
        self.assertIn('robot', cfg.saved['basic_config']['multi_persona_ids'])
        create.assert_awaited_once_with('robot', bot_name='可名', mode='copy', source_persona_id='primary')

    async def test_missing_scheduler_never_publishes_a_dead_route(self):
        self.platforms.append({'id': 'qq-new', 'type': 'qq_official'})
        self.plugin.context.reload_pipeline_scheduler.side_effect = RuntimeError('not ready')
        await self.plugin.reconcile_bots()
        self.assertNotIn('qq-new::', self.routes)
        self.assertTrue(self.plugin.targets()[1]['error'])

    def event(self, text, sender='owner'):
        return SimpleNamespace(get_message_str=lambda: text, get_platform_id=lambda: 'qq',
                               get_sender_id=lambda: sender, is_private_chat=lambda: True,
                               is_admin=lambda: False, unified_msg_origin=f'qq:FriendMessage:{sender}')

    async def test_qq_library_crud_updates_web_store_without_applying(self):
        self.config['qq_editor_enabled_bots'] = ['qq']
        execute = self.plugin.qq_commands.execute
        before = await self.plugin.snapshot('qq')
        self.assertIn('待确认', await execute(self.event('/newpersona 测试好友 | keep it short')))
        self.assertFalse(any(p['name'] == '测试好友' for p in await self.plugin.get_presets()))
        self.assertIn('已创建', await execute(self.event('/confirmpersona')))
        item = next(p for p in await self.plugin.get_presets() if p['name'] == '测试好友')
        self.assertIn('keep it short', await execute(self.event('/showpersona ' + item['id'])))
        self.assertIn('待确认', await execute(self.event('/editpersona 测试好友 | edited from QQ')))
        self.assertIn('已更新', await execute(self.event('/confirmpersona')))
        self.assertIn('待确认', await execute(self.event('/renamepersona 测试好友 | 新名字')))
        self.assertIn('已更新', await execute(self.event('/confirmpersona')))
        updated = next(p for p in await self.plugin.get_presets() if p['id'] == item['id'])
        self.assertEqual((updated['name'], updated['prompt']), ('新名字', 'edited from QQ'))
        self.assertIn('待确认', await execute(self.event('/deletepersona ' + item['id'])))
        self.assertIn('已删除', await execute(self.event('/confirmpersona')))
        self.assertNotIn(item['id'], [p['id'] for p in await self.plugin.get_presets()])
        self.assertEqual(await self.plugin.snapshot('qq'), before)

    async def test_qq_library_permissions_and_conflict_do_not_overwrite(self):
        self.config['qq_editor_enabled_bots'] = ['qq']
        execute = self.plugin.qq_commands.execute
        self.config['qq_editor_enabled_bots'] = []
        self.assertIn('开关已关闭', await execute(self.event('/newpersona test | prompt', sender='stranger')))
        self.config['qq_editor_enabled_bots'] = ['qq']
        item = await self.create()
        await execute(self.event('/deletepersona ' + item['id']))
        await self.plugin.change_preset({**item, 'preset_id': item['id'], 'name': '网页新名字', 'bot_id': 'qq'})
        self.assertIn('未保存', await execute(self.event('/confirmpersona')))
        self.assertIn(item['id'], [p['id'] for p in await self.plugin.get_presets()])

    async def test_qq_named_creation_can_take_next_message_and_cancel(self):
        self.config['qq_editor_enabled_bots'] = ['qq']
        execute = self.plugin.qq_commands.execute
        self.assertIn('请直接发送', await execute(self.event('/新建人设 分步创建')))
        self.assertIn('待确认', await self.plugin.qq_commands.consume_custom(self.event('Be kind and concise.')))
        self.assertIn('已创建', await execute(self.event('/确认人设')))
        self.assertEqual(next(p for p in await self.plugin.get_presets() if p['name'] == '分步创建')['prompt'], 'Be kind and concise.')
        await execute(self.event('/删除人设 分步创建'))
        await execute(self.event('/取消人设'))
        self.assertTrue(any(p['name'] == '分步创建' for p in await self.plugin.get_presets()))

    async def test_rename_invalidates_a_pending_delete_even_with_same_prompt(self):
        self.config['qq_editor_enabled_bots'] = ['qq']
        item = await self.create()
        await self.plugin.qq_commands.execute(self.event('/删除人设 ' + item['id']))
        await self.plugin.change_preset({**item, 'preset_id': item['id'], 'name': '另一个名字', 'bot_id': 'qq'})
        self.assertIn('未保存', await self.plugin.qq_commands.execute(self.event('/确认人设')))
