"""Retry only failed repository GET connections directly; preserve provider networking."""
import hashlib
from pathlib import Path
try:
    from .service import PYTHON
except ImportError:
    from service import PYTHON

ROOT=Path(__file__).resolve().parents[1]
TARGET=PYTHON.parent/'Lib/site-packages/astrbot/core/zip_updater.py'
ORIGINAL='22537dedd4cc9094c86fe0220b23ddf5c699da6e86e14a63d59aa38d6144c332'
CHANGES=[
('import asyncio\n','import asyncio\nfrom contextlib import AsyncExitStack, asynccontextmanager\n'),
('    async def _download_file(\n','''    @asynccontextmanager
    async def _open_repository_download(self, url, timeout):
        # An inherited system proxy can accept TCP but fail its upstream tunnel.
        # Retry only opening this idempotent GET; TLS verification stays enabled.
        async with AsyncExitStack() as stack:
            client = await stack.enter_async_context(self._create_httpx_client(timeout=timeout))
            try:
                response = await stack.enter_async_context(client.stream("GET", url))
            except (httpx.ConnectError, httpx.ProxyError):
                if not any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")):
                    raise
                logger.warning("Repository proxy connection failed; retrying this download directly with TLS verification.")
                direct = await stack.enter_async_context(httpx.AsyncClient(follow_redirects=True, timeout=timeout, trust_env=False, verify=self._httpx_verify))
                response = await stack.enter_async_context(direct.stream("GET", url))
            yield response

    async def _download_file(
'''),
('            async with self._create_httpx_client(timeout=timeout) as client:\n                async with client.stream("GET", url) as response:\n',
 '            async with AsyncExitStack():\n                async with self._open_repository_download(url, timeout) as response:\n')]

def repair(target=TARGET):
    data=target.read_bytes();current=data.decode('utf-8');base=current
    for old,new in reversed(CHANGES):
        if new in base:base=base.replace(new,old,1)
    if hashlib.sha256(base.encode()).hexdigest()!=ORIGINAL:
        raise ValueError('Repository downloader version changed; refusing to overwrite other code')
    for old,new in CHANGES:
        if new in current:continue
        if current.count(old)!=1:raise ValueError('Ambiguous download patch location')
        current=current.replace(old,new,1)
    if current!=data.decode('utf-8'):
        backup=ROOT/'runtime/backups/plugin-download/zip_updater.py.before-direct-retry'
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():backup.write_bytes(data)
        target.write_bytes(current.encode())

if __name__=='__main__':
    repair();print('Repository GET connection retry installed; provider settings preserved.')
