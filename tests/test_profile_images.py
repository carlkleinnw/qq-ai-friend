import base64
from io import BytesIO
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from PIL import Image
from plugins.astrbot_plugin_persona_studio.profile_images import normalize_avatar
from test_qq_control import control, Config


def image_data():
    stream=BytesIO();Image.new('RGB',(32,24),'navy').save(stream,'JPEG')
    return 'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()


def test_avatar_is_decoded_reencoded_and_size_bounded():
    output=normalize_avatar(image_data())
    assert output.startswith('data:image/png;base64,')
    with Image.open(BytesIO(base64.b64decode(output.split(',')[1]))) as image:
        assert image.format=='PNG' and max(image.size)<=512


@pytest.mark.parametrize('data',['data:image/svg+xml;base64,PHN2Zz4=','data:image/png;base64,AAAA','https://example.com/a.png','data:image/png;base64,'+'A'*3_000_000],ids=['svg','corrupt','url','oversized'])
def test_invalid_or_large_uploads_are_rejected(data):
    with pytest.raises(ValueError):normalize_avatar(data)


def identity_control():
    obj=control();obj.plugin.config=Config(identity_records=[{'appid':'200','local_name':'keep other'}])
    sdk=SimpleNamespace(_update=Mock())
    adapter=SimpleNamespace(appid='100',client=SimpleNamespace(api=SimpleNamespace(me=AsyncMock(return_value={'id':'qq-user','username':'platform name','avatar':'https://example.com/qq.png'})),robot=sdk))
    obj.plugin.context=SimpleNamespace(get_platform_inst=lambda bid:adapter)
    return obj,adapter


def test_local_profile_save_does_not_call_qq_or_modify_other_appid():
    obj,adapter=identity_control()
    result=asyncio.run(obj.identity({'bot_id':'a','appid':'100','local_name':'local name','local_avatar':'','web_override':True,'avatar_data':image_data()}))
    rows=obj.plugin.config['identity_records'];assert rows[0]=={'appid':'200','local_name':'keep other'}
    assert rows[1]['local_name']=='local name' and rows[1]['local_avatar_data'].startswith('data:image/png')
    adapter.client.api.me.assert_not_awaited();adapter.client.robot._update.assert_not_called()
    assert '仅网页显示' in result['note']


def test_failed_profile_write_restores_config_and_does_not_mutate_sdk():
    obj,adapter=identity_control();before=deepcopy(dict(obj.plugin.config))
    obj.plugin.config.save_config=Mock(side_effect=OSError('disk failure'))
    with pytest.raises(OSError):asyncio.run(obj.identity({'bot_id':'a','appid':'100','sync':True}))
    assert dict(obj.plugin.config)==before
    adapter.client.robot._update.assert_not_called()


def test_read_only_qq_refresh_preserves_local_override_and_marks_read_time():
    obj,adapter=identity_control();obj.plugin.config['identity_records'].append({'appid':'100','local_name':'local','web_override':True})
    result=asyncio.run(obj.identity({'bot_id':'a','appid':'100','sync':True}))
    row=obj.plugin.config['identity_records'][1]
    assert row['local_name']=='local' and row['web_override'] is True
    assert row['qq_name']=='platform name' and row['profile_read_at']
    assert '审核状态请到开放平台' in result['note']
    adapter.client.robot._update.assert_called_once()


def test_qq_error_is_sanitized_and_does_not_overwrite_saved_metadata():
    obj,adapter=identity_control();before=deepcopy(dict(obj.plugin.config))
    adapter.client.api.me.side_effect=RuntimeError('private-token-value')
    with pytest.raises(ValueError) as exc:asyncio.run(obj.identity({'bot_id':'a','appid':'100','sync':True}))
    assert 'private-token-value' not in str(exc.value) and dict(obj.plugin.config)==before


def test_uploaded_avatar_can_be_explicitly_cleared():
    obj,adapter=identity_control()
    asyncio.run(obj.identity({'bot_id':'a','appid':'100','local_name':'local','local_avatar':'','avatar_data':image_data()}))
    asyncio.run(obj.identity({'bot_id':'a','appid':'100','local_name':'local','local_avatar':'','clear_avatar':True}))
    assert 'local_avatar_data' not in obj.plugin.config['identity_records'][1]
