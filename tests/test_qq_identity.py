from types import SimpleNamespace
from plugins.astrbot_plugin_persona_studio.bot_registry import BotRegistry, avatar_url


def registry(closed=False, websocket=True, platforms=None):
    client = SimpleNamespace(robot=SimpleNamespace(name='QQ真实名称', avatar='https://example.com/avatar.png', id=123),
                             is_closed=lambda: False,
                             _active_websockets=[SimpleNamespace(_conn=SimpleNamespace(closed=closed), _session={'session_id':'ready'})] if websocket else [])
    config = {'platform': platforms or [{'id':'arbitrary-local-id','type':'qq_official','appid':'80001','enable':True}]}
    context = SimpleNamespace(get_config=lambda:config, get_platform_inst=lambda bid:SimpleNamespace(client=client,appid='80001'))
    return BotRegistry(SimpleNamespace(context=context,config={}))


def test_identity_is_from_configured_appid_and_official_metadata():
    bot = registry().targets()[0]
    assert bot['appid'] == '80001' and bot['name'] == 'QQ真实名称'
    assert bot['name_source'] == 'qq' and bot['avatar'].startswith('https://')
    assert bot['avatar_source'] == 'qq'


def test_mismatched_runtime_appid_cannot_supply_name_or_avatar():
    obj=registry(platforms=[{'id':'other','appid':'90002','type':'qq_official','enable':True}])
    bot=obj.targets()[0]
    assert bot['name']=='other' and not bot['avatar'] and not bot['connected']
    assert bot['name_source']=='local' and bot['avatar_source']=='unavailable'


def test_local_fallback_avatar_is_distinguished_from_cached_qq_name():
    obj=registry(platforms=[{'id':'other','appid':'90002','type':'qq_official','enable':True}])
    obj.plugin.config['identity_records']=[{'appid':'90002','qq_name':'QQ缓存名称','local_avatar':'https://example.com/local.png'}]
    bot=obj.targets()[0]
    assert bot['name_source']=='qq_cache' and bot['avatar_source']=='local'


def test_web_override_changes_display_but_preserves_official_identity_and_instance():
    obj=registry();obj.plugin.config['identity_records']=[{'appid':'80001','local_name':'网页自定义','local_avatar':'https://example.com/local.png','web_override':True}]
    bot=obj.targets()[0]
    assert bot['name']=='网页自定义' and bot['name_source']=='local'
    assert bot['qq_name']=='QQ真实名称' and bot['qq_avatar']=='https://example.com/avatar.png'
    assert bot['appid']=='80001' and bot['bot_id']=='arbitrary-local-id'
    assert bot['avatar']=='https://example.com/local.png' and bot['connected']


def test_cached_robot_metadata_does_not_mean_connected():
    assert registry(closed=True).targets()[0]['connected'] is False
    assert registry(websocket=False).targets()[0]['connected'] is False


def test_duplicate_appid_is_explicitly_ambiguous():
    rows = [{'id':i,'appid':'80001','type':'qq_official','enable':True} for i in ['one','two']]
    assert all(b['identity_conflict'] for b in registry(platforms=rows).targets())


def test_qq_http_avatar_is_upgraded_without_allowing_untrusted_http():
    assert avatar_url('http://thirdqq.qlogo.cn/g?b=oidb')=='https://thirdqq.qlogo.cn/g?b=oidb'
    assert avatar_url('http://thirdqq.qlogo.cn.evil.invalid/g')==''
    assert avatar_url('javascript:alert(1)')==''
