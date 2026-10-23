import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from plugins.astrbot_plugin_persona_studio.connections import connection_summary


def context(runner, model=None):
    cfg = {'agent_runner': runner, 'provider_settings': {'enable': True}}
    provider = SimpleNamespace(meta=lambda: SimpleNamespace(id='configured-model'), get_model=lambda: 'model-name')
    return SimpleNamespace(get_config=lambda umo=None: cfg,
                           get_provider_by_id=lambda pid: provider if pid == 'configured-model' else None,
                           get_using_provider_async=AsyncMock(return_value=model),
                           astrbot_config_mgr=SimpleNamespace(ucr=SimpleNamespace(get_conf_id_for_umop=lambda umo: 'profile-a')))


def test_model_uses_selected_bots_config_not_any_enabled_provider():
    ctx = context({'runner_type': 'local', 'config': {'model': {'provider_id': 'missing-model'}}})
    data = asyncio.run(connection_summary(ctx, 'bot-a'))
    assert data['model']['id'] == 'missing-model'
    assert data['model']['status'] == 'unavailable'
    ctx.get_using_provider_async.assert_not_awaited()


def test_local_agent_and_configured_model_are_not_claimed_network_tested():
    ctx = context({'runner_type': 'local', 'config': {'model': {'provider_id': 'configured-model'}}})
    data = asyncio.run(connection_summary(ctx, 'bot-a'))
    assert data['model']['status'] == 'configured'
    assert data['agent']['status'] == 'local'
    assert data['config_id'] == 'profile-a'
    assert data['model']['tested'] is False


def test_external_agent_never_exposes_secrets_or_claims_connected():
    ctx = context({'runner_type': 'dify', 'config': {'dify_api_key': 'private-key', 'dify_api_base': 'https://private.invalid'}})
    data = asyncio.run(connection_summary(ctx, 'bot-a'))
    assert data['agent']['status'] == 'configured'
    assert data['agent']['tested'] is False
    assert 'private' not in str(data)
    assert data['model']['status'] == 'external'


def test_incomplete_external_agent_is_not_configured():
    ctx = context({'runner_type': 'coze', 'config': {'coze_api_key': 'secret', 'bot_id': ''}})
    assert asyncio.run(connection_summary(ctx, 'bot-a'))['agent']['status'] == 'incomplete'
