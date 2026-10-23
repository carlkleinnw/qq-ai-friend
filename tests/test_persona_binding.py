import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest

from plugins.astrbot_plugin_persona_studio.binding import PersonaBinding


class SavedConfig(dict):
    def __init__(self, pid):
        super().__init__(agent_runner={'runner_type': 'local', 'config': {'persona': {'persona_id': pid}, 'model': {'provider_id': 'keep-model'}}})
        self.saved = deepcopy(dict(self))

    def save_config(self):
        self.saved = deepcopy(dict(self))


def setup():
    configs = {'a': SavedConfig('persona-a'), 'b': SavedConfig('persona-b')}
    personas = {}
    for pid in ['persona-a', 'persona-b', 'new-persona']:
        personas[pid] = SimpleNamespace(persona_id=pid, system_prompt=pid, tools=['keep-tool'], skills=[], begin_dialogs=[], custom_error_message=None)
    async def get(pid):
        if pid not in personas: raise ValueError('missing')
        return personas[pid]
    async def create(pid, system_prompt, **kwargs):
        personas[pid] = SimpleNamespace(persona_id=pid, system_prompt=system_prompt, **kwargs)
    manager = SimpleNamespace(get_persona=get, create_persona=AsyncMock(side_effect=create), delete_persona=AsyncMock())
    manager.get_all_personas = AsyncMock(side_effect=lambda: list(personas.values()))
    router = SimpleNamespace(umop_to_conf_id={'bot-a::': 'a', 'bot-b::': 'b'})
    ctx = SimpleNamespace(astrbot_config_mgr=SimpleNamespace(confs=configs, ucr=router), persona_manager=manager,
                          reload_pipeline_scheduler=AsyncMock())
    plugin = SimpleNamespace(config={}, context=ctx, targets=lambda: [{'bot_id':'bot-a'}, {'bot_id':'bot-b'}],
                             lock=asyncio.Lock(), logger=Mock(), registry=SimpleNamespace(ensure_companion=AsyncMock()))
    return PersonaBinding(plugin), configs, personas


def test_binding_persists_native_config_and_reloads_only_target():
    binding, configs, _ = setup()
    result = asyncio.run(binding.save({'bot_id':'bot-a', 'persona_id':'new-persona', 'expected_persona_id':'persona-a', 'config_id':'a'}))
    assert result['persona_id'] == 'new-persona'
    assert configs['a'].saved['agent_runner']['config']['persona']['persona_id'] == 'new-persona'
    assert configs['b'].saved['agent_runner']['config']['persona']['persona_id'] == 'persona-b'
    assert configs['a']['agent_runner']['config']['model']['provider_id'] == 'keep-model'
    binding.plugin.context.reload_pipeline_scheduler.assert_awaited_once_with('a')


def test_shared_persona_is_copied_without_changing_other_robot():
    binding, configs, personas = setup()
    result = asyncio.run(binding.save({'bot_id':'bot-a','persona_id':'persona-b','expected_persona_id':'persona-a','config_id':'a'}))
    assert result['copied'] is True and result['persona_id'] != 'persona-b'
    assert personas[result['persona_id']].system_prompt == 'persona-b'
    assert personas[result['persona_id']].tools == ['keep-tool']
    assert configs['b']['agent_runner']['config']['persona']['persona_id'] == 'persona-b'


def test_failed_pipeline_reload_restores_saved_binding():
    binding, configs, _ = setup()
    binding.plugin.context.reload_pipeline_scheduler.side_effect = [RuntimeError('failed'), None]
    with pytest.raises(RuntimeError):
        asyncio.run(binding.save({'bot_id':'bot-a','persona_id':'new-persona','expected_persona_id':'persona-a','config_id':'a'}))
    assert configs['a'].saved['agent_runner']['config']['persona']['persona_id'] == 'persona-a'


def test_native_edit_during_persona_lookup_is_preserved():
    binding, configs, personas = setup()
    async def concurrent_edit(pid):
        configs['a']['agent_runner']['config']['model']['provider_id'] = 'changed-by-native-page'
        configs['a'].save_config()
        return personas[pid]
    binding.plugin.context.persona_manager.get_persona = concurrent_edit
    # The snapshot is made before awaiting the native persona lookup.
    with pytest.raises(ValueError, match='别处修改'):
        asyncio.run(binding.save({'bot_id':'bot-a','persona_id':'new-persona','expected_persona_id':'persona-a','config_id':'a'}))
    assert configs['a'].saved['agent_runner']['config']['model']['provider_id'] == 'changed-by-native-page'


def test_missing_persona_has_explicit_repairable_state():
    binding, configs, _ = setup()
    configs['a']['agent_runner']['config']['persona']['persona_id'] = 'deleted-persona'
    state = asyncio.run(binding.describe('bot-a'))
    assert state['editable'] is True and state['available'] is False
    assert '尚未设置' in state['message']
    assert len(state['choices']) == 3


def test_external_agent_does_not_expose_an_old_local_persona_for_editing():
    binding, configs, _ = setup()
    configs['a']['agent_runner']['runner_type'] = 'dify'
    state = asyncio.run(binding.describe('bot-a'))
    assert state['editable'] is False and state['persona_id'] is None
    assert 'Agent' in state['message']


@pytest.mark.parametrize('changes',[{'bot_id':'missing'}, {'config_id':'b'}, {'expected_persona_id':'changed'}, {'persona_id':'missing'}])
def test_invalid_or_stale_binding_does_not_write(changes):
    binding, configs, _ = setup()
    body={'bot_id':'bot-a','persona_id':'new-persona','expected_persona_id':'persona-a','config_id':'a', **changes}
    with pytest.raises(ValueError): asyncio.run(binding.save(body))
    assert configs['a'].saved['agent_runner']['config']['persona']['persona_id'] == 'persona-a'
    binding.plugin.context.reload_pipeline_scheduler.assert_not_awaited()
