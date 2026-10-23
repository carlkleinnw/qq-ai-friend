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
