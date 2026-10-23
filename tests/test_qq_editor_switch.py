"""QQ persona authorization uses the real command and HTTP handlers."""
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

# AstrBot creates default files during import; keep those out of the install data.
with TemporaryDirectory(prefix='qq-editor-test-', dir=Path(__file__).resolve().parents[1] / 'runtime') as sandbox:
    with patch.dict(os.environ, {'ASTRBOT_ROOT': sandbox}):
        from plugins.astrbot_plugin_persona_studio import main
        from plugins.astrbot_plugin_persona_studio.qq_commands import QQPersonaCommands


def event(bot='bot-a', sender='user', private=True, admin=False, text='/当前人设'):
    return SimpleNamespace(
        unified_msg_origin=f'{bot}:FriendMessage:{sender}',
        get_platform_id=lambda: bot, get_sender_id=lambda: sender,
        is_private_chat=lambda: private, is_admin=lambda: admin,
        get_message_str=lambda: text,
    )


def plugin(enabled=()):
    instance = main.PersonaStudio.__new__(main.PersonaStudio)
    instance.config = Config(qq_editor_enabled_bots=list(enabled), qq_editor_sessions=[])
    instance.lock = asyncio.Lock()
    instance.targets = lambda: [{'bot_id': 'bot-a'}, {'bot_id': 'bot-b'}]
    instance.target_persona = Mock(return_value='persona-a')
    instance.get_presets = AsyncMock(return_value=[])
    instance.snapshot = AsyncMock(return_value={
        'bot_id': 'bot-a', 'persona_id': 'persona-a', 'bio': '',
        'prompt': '原有人设', 'revision': 'v1', 'tools': [],
    })
    instance.save_form = AsyncMock()
    instance.logger = Mock()
    instance.qq_commands = QQPersonaCommands(instance)
    return instance


class Config(dict):
    fail = False
    saves = 0

    def save_config(self):
        if self.fail:
            raise OSError('simulated disk write failure')
        self.saves += 1


def run(coro):
    return asyncio.run(coro)


def switch(monkeypatch, instance, body):
    monkeypatch.setattr(main, 'request', SimpleNamespace(json=AsyncMock(return_value=body)))
    return run(instance.authorize_qq())


def test_enabled_bot_needs_no_umo_or_admin():
    instance = plugin(['bot-a'])
    assert instance.qq_commands.authorize(event())[1] == 'bot-a'
    assert instance.qq_commands.authorize(event(sender='another-user'))[1] == 'bot-a'


@pytest.mark.parametrize('admin', [False, True])
def test_off_blocks_legacy_sessions_and_admin(admin):
    instance = plugin()
    instance.config['qq_editor_sessions'] = ['bot-a:FriendMessage:user']
    with pytest.raises(ValueError, match='开关'):
        instance.qq_commands.authorize(event(admin=admin))


def test_switch_is_per_bot_and_private_only():
    instance = plugin(['bot-a'])
    with pytest.raises(ValueError):
        instance.qq_commands.authorize(event(bot='bot-b'))
    with pytest.raises(ValueError, match='私聊'):
        instance.qq_commands.authorize(event(private=False))
    forged = event()
    forged.unified_msg_origin = 'bot-a:FriendMessage:someone-else'
    with pytest.raises(ValueError):
        instance.qq_commands.authorize(forged)


def test_switch_saves_and_does_not_enable_other_bots(monkeypatch):
    instance = plugin()
    response = switch(monkeypatch, instance, {'bot_id': 'bot-a', 'enabled': True})
    assert response.status_code == 200
    assert json.loads(response.body)['enabled'] is True
    assert instance.config['qq_editor_enabled_bots'] == ['bot-a']
    assert instance.config.saves == 1
    instance.qq_commands.authorize(event())
    with pytest.raises(ValueError):
        instance.qq_commands.authorize(event(bot='bot-b'))


def test_disable_discards_only_this_bots_drafts(monkeypatch):
    instance = plugin(['bot-a', 'bot-b'])
    key_a = ('bot-a:FriendMessage:user', 'user')
    key_b = ('bot-b:FriendMessage:user', 'user')
    instance.qq_commands.pending = {key_a: {}, key_b: {}}
    instance.qq_commands.waiting_custom = {key_a: {}, key_b: {}}
    response = switch(monkeypatch, instance, {'bot_id': 'bot-a', 'enabled': False})
    assert response.status_code == 200
    assert instance.config['qq_editor_enabled_bots'] == ['bot-b']
    assert set(instance.qq_commands.pending) == {key_b}
    assert set(instance.qq_commands.waiting_custom) == {key_b}
    assert '开关' in run(instance.qq_commands.execute(event(text='/确认人设')))
    instance.save_form.assert_not_awaited()


@pytest.mark.parametrize('body', [
    {'bot_id': 'bot-a', 'enabled': 'false'},
    {'bot_id': 'bot-a', 'enabled': 1},
    {'bot_id': 'bot-a'}, {'bot_id': 'unknown', 'enabled': True},
    {'umo': 'bot-a:FriendMessage:user'}, [],
])
def test_reject_invalid_switch_requests(monkeypatch, body):
    instance = plugin()
    response = switch(monkeypatch, instance, body)
    assert response.status_code == 400
    assert instance.config.saves == 0
    assert instance.config['qq_editor_enabled_bots'] == []


def test_save_failure_keeps_switch_and_drafts(monkeypatch):
    instance = plugin(['bot-a'])
    instance.config.fail = True
    key = ('bot-a:FriendMessage:user', 'user')
    instance.qq_commands.pending[key] = {'draft': True}
    response = switch(monkeypatch, instance, {'bot_id': 'bot-a', 'enabled': False})
    assert response.status_code == 500
    assert instance.config['qq_editor_enabled_bots'] == ['bot-a']
    assert key in instance.qq_commands.pending


def test_enabled_command_previews_then_confirms():
    instance = plugin(['bot-a'])
    result = run(instance.qq_commands.execute(event(text='/自定义人设 温柔细心')))
    assert '待确认' in result
    instance.save_form.assert_not_awaited()
    assert '已保存' in run(instance.qq_commands.execute(event(text='/确认人设')))
    assert instance.save_form.await_args.args[0]['prompt'] == '温柔细心'


def test_help_explains_switch_without_sid():
    result = run(plugin().qq_commands.execute(event(text='/人设')))
    assert '开关' in result
    assert '/sid' not in result
