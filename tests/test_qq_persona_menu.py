from copy import deepcopy
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch
import json

import pytest

from plugins.astrbot_plugin_persona_studio.qq_menu import merge_persona_menu

PRESETS = [{'name': name} for name in ['俏皮人鱼娘', '温柔倾听者', '理性搭子', '元气伙伴', '体贴甜蜜女友']]


def test_menu_exposes_settings_preset_buttons_and_custom_without_nested_submenus():
    menu = merge_persona_menu(None, PRESETS)
    settings, presets = menu['items']
    assert settings['name'] == '人设设置'
    assert any(c['name'] == '自定义人设' and c['send_message'].startswith('/自定义人设') for c in settings['sub_menu_items'])
    assert len(presets['sub_menu_items']) == 5
    assert presets['sub_menu_items'][-1]['send_message'] == '/人设 5'
    assert all(c['type'] == 'send_message' for m in menu['items'] for c in m['sub_menu_items'])


def test_existing_menus_are_preserved_and_repeated_sync_is_idempotent():
    current = {'items': [{'name': '官网', 'type': 'link', 'link': 'https://example.com'}]}
    before = deepcopy(current)
    menu = merge_persona_menu(current, PRESETS)
    assert current == before
    assert menu['items'][0] == before['items'][0]
    assert merge_persona_menu(menu, PRESETS) == menu
    menu['items'][1]['icon'] = 'https://example.com/qq-default-menu-icon.png'
    assert merge_persona_menu(menu, PRESETS) == menu


def test_foreign_collision_and_official_menu_limits_are_rejected_before_write():
    with pytest.raises(ValueError, match='同名'):
        merge_persona_menu({'items': [{'name': '人设设置', 'type': 'link', 'link': 'https://example.com'}]}, PRESETS)
    with pytest.raises(ValueError, match='十项'):
        merge_persona_menu({'items': [{'name': str(i), 'type': 'send_message', 'send_message': 'help'} for i in range(9)]}, PRESETS)
    with pytest.raises(ValueError, match='十项'):
        merge_persona_menu(None, PRESETS * 10)


def test_saved_custom_presets_are_paged_with_stable_ids():
    custom = {'id': 'custom-stable-id', 'name': '贴心搭子'}
    menu = merge_persona_menu(None, PRESETS + [custom])
    assert len(menu['items']) == 3
    assert menu['items'][-1]['name'] == '预设2'
    assert menu['items'][-1]['sub_menu_items'] == [
        {'type': 'send_message', 'name': '贴心搭子', 'send_message': '/人设 custom-stable-id'}]


def test_publisher_uses_existing_qq_sdk_and_does_not_rewrite_unchanged_menu():
    asyncio.run(check_publisher())


async def check_publisher():
    import astrbot.api
    from plugins.astrbot_plugin_persona_studio.main import PersonaStudio
    # Actual QQ response for a newly scanned bot omits version.
    http = SimpleNamespace(request=AsyncMock(side_effect=[{'menu': {}}, {'version': 1}]))
    adapter = SimpleNamespace(client=SimpleNamespace(api=SimpleNamespace(_http=http)))
    context = SimpleNamespace(register_web_api=lambda *args: None,
        get_config=lambda: {'platform': [{'id': 'bot-a', 'type': 'qq_official', 'enable': True}]},
        get_platform_inst=lambda bot: adapter)
    plugin = PersonaStudio(context, {'bots': [{'bot_id': 'bot-a'}]})
    assert (await plugin.publish_qq_menu('bot-a'))['changed']
    calls = http.request.call_args_list
    assert [(c.args[0].method, c.args[0].path) for c in calls] == [('GET', '/v2/menu'), ('PUT', '/v2/menu')]
    assert calls[1].kwargs['json']['menu'] == merge_persona_menu(None, plugin.presets)
    http.request.reset_mock()
    http.request.side_effect = None
    server_menu = merge_persona_menu(None, plugin.presets)
    server_menu['items'][0]['icon'] = 'https://example.com/qq-default-menu-icon.png'
    http.request.return_value = {'menu': server_menu, 'version': 1}
    assert not (await plugin.publish_qq_menu('bot-a'))['changed']
    assert http.request.await_count == 1
    request = SimpleNamespace(json=AsyncMock(return_value={'bot_id': 'bot-a'}))
    with patch('plugins.astrbot_plugin_persona_studio.main.request', new=request):
        response = await plugin.qq_menu()
        assert json.loads(response.body) == {'status': 'ok', 'data': {'changed': False, 'version': 1}}
    with pytest.raises(ValueError, match='先同步'):
        await plugin.publish_qq_menu('unknown')
