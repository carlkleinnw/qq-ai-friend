"""Pinned native lifecycle fix: revoke plugin APIs on termination and failed load."""
import hashlib
from pathlib import Path
try:
    from .service import PYTHON
except ImportError:
    from service import PYTHON

ROOT=Path(__file__).resolve().parents[1]
TARGET=PYTHON.parent/'Lib/site-packages/astrbot/core/star/star_manager.py'
ORIGINAL='6146ef6162716a6aa64cae5bf13bd93bcdd6c681a45e35ffd017f690715255fd'
PATCHES=[
('        # 清理 sys.modules\n', '''        self._remove_plugin_web_apis(self.context, module_prefix)

        # 清理 sys.modules
'''),
('        plugin = None\n        del star_map[plugin_module_path]\n', '''        plugin = None
        self._remove_plugin_web_apis(self.context, plugin_module_path.rsplit(".", 1)[0])
        del star_map[plugin_module_path]
'''),
('    @staticmethod\n    async def _terminate_plugin(star_metadata: StarMetadata) -> None:\n', '''    @staticmethod
    def _remove_plugin_web_apis(context, module_prefix):
        """Release bound routes without touching similarly named plugins."""
        if context is None or not module_prefix:
            return
        routes = getattr(context, "registered_web_apis", None)
        if not isinstance(routes, list):
            return
        def owned(api):
            handler = api[1]
            owner = getattr(handler, "__self__", None)
            module = getattr(type(owner), "__module__", "") if owner is not None else getattr(handler, "__module__", "")
            return module == module_prefix or module.startswith(module_prefix + ".")
        routes[:] = [api for api in routes if not owned(api)]

    @staticmethod
    async def _terminate_plugin(star_metadata: StarMetadata) -> None:
'''),
('        logger.info(f"Terminating plugin {star_metadata.name} ...")\n', '''        logger.info(f"Terminating plugin {star_metadata.name} ...")
        instance = star_metadata.star_cls
        module_prefix = (star_metadata.module_path or "").rsplit(".", 1)[0]
        PluginManager._remove_plugin_web_apis(getattr(instance, "context", None), module_prefix)
''')]

def repair(target=TARGET):
    data=target.read_bytes(); text=data.decode('utf-8'); original=text
    for old,new in reversed(PATCHES):
        if new in original:
            original=original.replace(new,old,1)
    if hashlib.sha256(original.encode('utf-8')).hexdigest()!=ORIGINAL:
        raise ValueError('Native manager version changed; refusing to overwrite other code')
    for old,new in PATCHES:
        if text.count(new)==1:
            continue
        if text.count(old)!=1:
            raise ValueError('Ambiguous lifecycle patch location')
        text=text.replace(old,new,1)
    if text!=data.decode('utf-8'):
        backup=ROOT/'runtime/backups/plugin-routes/star_manager.py.before-route-cleanup'
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():backup.write_bytes(data)
        target.write_bytes(text.encode('utf-8'))

if __name__=='__main__':
    repair();print('Plugin route lifecycle cleanup verified; existing plugin data untouched.')
