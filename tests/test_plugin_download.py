import ast,asyncio
from contextlib import AsyncExitStack,asynccontextmanager
from types import SimpleNamespace
import httpx,pytest
from scripts.repair_plugin_download import CHANGES

def harness(error,monkeypatch,proxy=True):
    import os
    for key in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
        monkeypatch.delenv(key,raising=False)
    if proxy:monkeypatch.setenv('HTTPS_PROXY','http://audit.invalid')
    calls=[]
    class Client:
        def __init__(self,**kw):calls.append(kw);self.direct=kw.get('trust_env') is False
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        @asynccontextmanager
        async def stream(self,*args):
            if error and not self.direct:raise error
            yield 'response'
    fake=SimpleNamespace(AsyncClient=Client,ConnectError=httpx.ConnectError,ProxyError=httpx.ProxyError)
    source=CHANGES[1][1].split('    async def _download_file(')[0]
    ns=dict(asynccontextmanager=asynccontextmanager,AsyncExitStack=AsyncExitStack,httpx=fake,os=os,logger=SimpleNamespace(warning=lambda *args:None))
    exec(compile(ast.parse('class Harness:\n'+source),'download_retry','exec'),ns)
    obj=ns['Harness']();obj._httpx_verify='verified-ca';obj._create_httpx_client=lambda timeout:Client(timeout=timeout,trust_env=True)
    return obj,calls

@pytest.mark.parametrize('error',[httpx.ConnectError('offline'),httpx.ProxyError('tunnel')])
def test_connection_failure_retries_once_direct_with_same_tls(error,monkeypatch):
    obj,calls=harness(error,monkeypatch)
    async def run():
        async with obj._open_repository_download('https://example.invalid/file',12) as response:assert response=='response'
    asyncio.run(run());assert len(calls)==2 and calls[1]['trust_env'] is False and calls[1]['verify']=='verified-ca'

def test_without_proxy_original_error_is_preserved(monkeypatch):
    obj,calls=harness(httpx.ConnectError('offline'),monkeypatch,False)
    async def run():
        async with obj._open_repository_download('https://example.invalid/file',12):pass
    with pytest.raises(httpx.ConnectError):asyncio.run(run())
    assert len(calls)==1

def test_read_timeout_is_not_retried(monkeypatch):
    obj,calls=harness(httpx.ReadTimeout('slow'),monkeypatch)
    async def run():
        async with obj._open_repository_download('https://example.invalid/file',12):pass
    with pytest.raises(httpx.ReadTimeout):asyncio.run(run())
    assert len(calls)==1

def test_download_repair_is_idempotent_and_rejects_other_edits(tmp_path,monkeypatch):
    import hashlib
    from scripts import repair_plugin_download as repair
    source=''.join(old for old,_ in repair.CHANGES)
    target=tmp_path/'zip_updater.py';target.write_bytes(source.encode())
    monkeypatch.setattr(repair,'ROOT',tmp_path)
    monkeypatch.setattr(repair,'ORIGINAL',hashlib.sha256(source.encode()).hexdigest())
    repair.repair(target);first=target.read_bytes();repair.repair(target);assert target.read_bytes()==first
    target.write_bytes(first+b'\n# other change')
    with pytest.raises(ValueError,match='version changed'):repair.repair(target)
