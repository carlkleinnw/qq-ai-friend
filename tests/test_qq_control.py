import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from copy import deepcopy
from plugins.astrbot_plugin_persona_studio.persona_form import revision
import pytest
from plugins.astrbot_plugin_persona_studio.control import QQControl


def control():
    bots=[{'bot_id':'a','appid':'100','name':'甲','identity_conflict':False}, {'bot_id':'b','appid':'200','name':'乙','identity_conflict':False}]
    plugin=SimpleNamespace(targets=lambda:bots,context=SimpleNamespace(),lock=asyncio.Lock())
    obj=QQControl(plugin,preferences=SimpleNamespace())
    obj.sessions=AsyncMock(side_effect=lambda bid:[{'umo':f'{bid}:FriendMessage:same-user','display_name':'同一昵称'}])
    return obj


def test_stable_appid_must_match_not_display_name():
    obj=control()
    with pytest.raises(ValueError,match='AppID'): obj.robot('a','200')
    assert obj.robot('a','100')['bot_id']=='a'


def test_session_from_other_robot_is_rejected():
    obj=control()
    with pytest.raises(ValueError): asyncio.run(obj.validate_umo('a','b:FriendMessage:same-user'))
    assert asyncio.run(obj.validate_umo('a','a:FriendMessage:same-user'))=='a:FriendMessage:same-user'


@pytest.mark.parametrize('umo',['a:FriendMessage:*','a::','a:GroupMessage:same-user','a:FriendMessage:unknown'])
def test_wildcards_groups_and_unknown_private_sessions_are_not_accepted(umo):
    with pytest.raises(ValueError): asyncio.run(control().validate_umo('a',umo))


class Config(dict):
    def save_config(self): self.saved=deepcopy(dict(self))


def writable():
    obj=control();prefs={}; configs={}; routes={'a::':'profile-a','b::':'profile-b'}
    for name in ['a','b']:
        configs['profile-'+name]=Config(agent_runner={'runner_type':'local','config':{'model':{'provider_id':'model'},'persona':{'persona_id':'persona-'+name}}},provider_settings={'enable':True})
    personas={pid:SimpleNamespace(persona_id=pid,system_prompt=pid,tools=[],skills=[],begin_dialogs=[],custom_error_message=None) for pid in ['persona-a','persona-b']}
    async def create_conf(value,name):
        configs['session-profile']=Config(deepcopy(value)); return 'session-profile'
    async def delete_conf(cid): configs.pop(cid,None)
    async def update_routes(value): routes.clear();routes.update(value)
    async def create_persona(pid,prompt,**kwargs): personas[pid]=SimpleNamespace(persona_id=pid,system_prompt=prompt,**kwargs)
    async def delete_persona(pid): personas.pop(pid,None)
    acm=SimpleNamespace(confs=configs,create_conf=create_conf,delete_conf=delete_conf,ucr=SimpleNamespace(umop_to_conf_id=routes,update_routing_data=update_routes))
    ctx=SimpleNamespace(astrbot_config_mgr=acm,persona_manager=SimpleNamespace(get_persona=AsyncMock(side_effect=lambda pid:personas[pid]),create_persona=create_persona,delete_persona=delete_persona),get_all_providers=lambda:[SimpleNamespace(meta=lambda:SimpleNamespace(id='model'))],reload_pipeline_scheduler=AsyncMock())
    async def get(umo,key,default=None): return deepcopy(prefs.get((umo,key),default))
    async def put(umo,key,value): prefs[umo,key]=deepcopy(value)
    async def remove(umo,key): prefs.pop((umo,key),None)
    obj.sp=SimpleNamespace(session_get=get,session_put=put,session_remove=remove)
    obj.sp.global_get=lambda key,default=None:get('global',key,default)
    obj.sp.global_put=lambda key,value:put('global',key,value)
    obj.sp.global_remove=lambda key:remove('global',key)
    obj.plugin.context=ctx;obj.plugin.logger=Mock();obj.plugin.registry=SimpleNamespace(ensure_companion=AsyncMock())
    async def resolved(bid,umo=None):
        cid=routes.get(umo) or routes[bid+'::'];cfg=configs[cid];service=await get(umo,'session_service_config',{})
        pid=service.get('persona_id') or cfg['agent_runner']['config'].get('persona',{}).get('persona_id')
        return {'config':cfg,'config_id':cid,'service':service,'provider_override':await get(umo,'provider_perf_chat_completion'),
                'persona_id':pid,'revision':revision({'cid':cid,'cfg':dict(cfg),'service':service})}
    obj._resolved=resolved
    async def read(bid,umo): return {**(await resolved(bid,umo)),'apply_result':obj.applied.get(umo or bid)}
    obj.read=read
    return obj,configs,routes,prefs,personas


def save_body(obj):
    initial=asyncio.run(obj._resolved('a','a:FriendMessage:same-user'))
    return {'bot_id':'a','appid':'100','umo':'a:FriendMessage:same-user','revision':initial['revision'],
            'runner_type':'local','provider_id':'model','persona_id':'persona-a','prompt':'new scoped persona',
            'session_enabled':True,'llm_enabled':True}


def test_scoped_save_publishes_exact_native_route_and_keeps_other_robot():
    obj,configs,routes,prefs,personas=writable(); before=deepcopy(dict(configs['profile-b']))
    result=asyncio.run(obj.save(save_body(obj)))
    assert next(iter(routes))=='a:FriendMessage:same-user'
    assert routes['a::']=='profile-a' and routes['b::']=='profile-b'
    assert dict(configs['profile-b'])==before
    pid=prefs['a:FriendMessage:same-user','session_service_config']['persona_id']
    assert pid!= 'persona-a' and personas[pid].system_prompt=='new scoped persona'
    assert personas['persona-a'].system_prompt=='persona-a'
    assert result['apply_result']['pipeline_loaded'] is True


def test_pipeline_failure_does_not_publish_route_or_leave_partial_profile():
    obj,configs,routes,prefs,personas=writable()
    obj.plugin.context.reload_pipeline_scheduler.side_effect=RuntimeError('native load failed')
    with pytest.raises(RuntimeError):asyncio.run(obj.save(save_body(obj)))
    assert routes=={'a::':'profile-a','b::':'profile-b'}
    assert set(configs)=={'profile-a','profile-b'} and not prefs
    assert set(personas)=={'persona-a','persona-b'}


def test_companion_failure_restores_routes_and_session_preferences():
    obj,configs,routes,prefs,personas=writable()
    prefs['a:FriendMessage:same-user','session_service_config']={'custom_name':'keep this name'}
    obj.plugin.registry.ensure_companion.side_effect=RuntimeError('unavailable')
    with pytest.raises(RuntimeError):asyncio.run(obj.save(save_body(obj)))
    assert routes=={'a::':'profile-a','b::':'profile-b'}
    assert prefs=={('a:FriendMessage:same-user','session_service_config'):{'custom_name':'keep this name'}}


def test_connection_save_changes_only_the_selected_native_adapter():
    obj=control();platforms=[{'id':'a','appid':'100','enable':True,'enable_group_c2c':True,'secret':'keep-a'}, {'id':'b','appid':'200','enable':True,'secret':'keep-b'}]
    cfg=Config(platform=platforms);reload=AsyncMock();obj.plugin.context=SimpleNamespace(get_config=lambda:cfg,platform_manager=SimpleNamespace(reload=reload))
    asyncio.run(obj.connection({'bot_id':'a','appid':'100','enable':False,'enable_group_c2c':False}))
    assert platforms[0]['enable'] is False and platforms[0]['secret']=='keep-a'
    assert platforms[1]=={'id':'b','appid':'200','enable':True,'secret':'keep-b'}
    reload.assert_awaited_once_with(platforms[0])


def test_connection_reload_failure_restores_saved_adapter_options():
    obj=control();platform={'id':'a','appid':'100','enable':True};cfg=Config(platform=[platform]);reload=AsyncMock(side_effect=[RuntimeError('load failed'),None]);obj.plugin.context=SimpleNamespace(get_config=lambda:cfg,platform_manager=SimpleNamespace(reload=reload))
    with pytest.raises(RuntimeError):asyncio.run(obj.connection({'bot_id':'a','appid':'100','enable':False}))
    assert platform['enable'] is True and cfg.saved['platform'][0]['enable'] is True


def test_model_page_preserves_persona_and_chat_switches_without_prompt_fields():
    obj,configs,routes,prefs,personas=writable()
    umo='a:FriendMessage:same-user'
    prefs[umo,'session_service_config']={'persona_id':'persona-a','llm_enabled':False,'session_enabled':False}
    prefs[umo,'provider_perf_chat_completion']='stale-model'
    body=save_body(obj)
    for key in ('prompt','persona_id','llm_enabled','session_enabled','runner_type'):body.pop(key)
    body['section']='model'
    before=deepcopy(personas)
    asyncio.run(obj.save(body))
    assert prefs[umo,'session_service_config']=={'persona_id':'persona-a','llm_enabled':False,'session_enabled':False}
    assert (umo,'provider_perf_chat_completion') not in prefs
    assert set(personas)==set(before)
    assert configs[routes[umo]]['agent_runner']['config']['persona']['persona_id']=='persona-a'


def test_agent_switch_retains_credentials_and_restores_previous_runner_settings():
    obj,configs,routes,prefs,personas=writable()
    umo='a:FriendMessage:same-user'
    async def switch(kind,fields=None):
        initial=await obj._resolved('a',umo)
        return await obj.save({'section':'agent','bot_id':'a','appid':'100','umo':umo,
            'revision':initial['revision'],'runner_type':kind,'agent_fields':fields or {}})
    asyncio.run(switch('dify',{'dify_api_key':'private-test-key','dify_api_base':'https://example.invalid/v1','variables':{'name':'value'},'proxy':'http://localhost:9999'}))
    cid=routes[umo]
    asyncio.run(switch('local'))
    assert configs[cid]['agent_runner']['config']['model']['provider_id']=='model'
    assert configs[cid]['agent_runner']['config']['persona']['persona_id']=='persona-a'
    asyncio.run(switch('dify',{'dify_api_key':''}))
    runner=configs[cid]['agent_runner']['config']
    assert runner['dify_api_key']=='private-test-key'
    assert runner['dify_api_base']=='https://example.invalid/v1'
    assert runner['variables']=={'name':'value'}
    assert configs['profile-b']['agent_runner']['runner_type']=='local'


@pytest.mark.parametrize('fields',[
    {'variables':[]}, {'timeout':True}, {'dify_api_type':'unknown'}, {'dify_api_base':'file:///private'},
])
def test_invalid_agent_settings_do_not_write_or_publish_routes(fields):
    obj,configs,routes,prefs,personas=writable()
    body=save_body(obj);body.update(section='agent',runner_type='dify',agent_fields=fields)
    with pytest.raises(ValueError):asyncio.run(obj.save(body))
    assert set(configs)=={'profile-a','profile-b'}
    assert routes=={'a::':'profile-a','b::':'profile-b'} and not prefs


def test_connection_stale_revision_rejected_before_reloading():
    obj=control();platform={'id':'a','appid':'100','enable':True};cfg=Config(platform=[platform]);reload=AsyncMock()
    obj.plugin.context=SimpleNamespace(get_config=lambda:cfg,platform_manager=SimpleNamespace(reload=reload))
    with pytest.raises(ValueError,match='重新读取'):
        asyncio.run(obj.connection({'bot_id':'a','appid':'100','qq_revision':'stale','enable':False}))
    assert platform['enable'] is True
    reload.assert_not_awaited()


def test_failed_agent_route_publish_rolls_back_archived_secrets():
    obj,configs,routes,prefs,personas=writable()
    obj.plugin.context.astrbot_config_mgr.ucr.update_routing_data=AsyncMock(side_effect=[RuntimeError('route failure'),None])
    body=save_body(obj);body.update(section='agent',runner_type='dify',agent_fields={'dify_api_key':'temporary-private-key'})
    with pytest.raises(RuntimeError):asyncio.run(obj.save(body))
    assert not prefs
    assert set(configs)=={'profile-a','profile-b'}
