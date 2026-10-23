import ast
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]

def cleanup_function():
    from scripts.repair_plugin_routes import PATCHES
    source=PATCHES[2][1].split('    @staticmethod\n    async def _terminate_plugin')[0]
    tree=ast.parse('class Harness:\n'+source)
    ns={};exec(compile(tree,'route_cleanup','exec'),ns)
    return ns['Harness']._remove_plugin_web_apis

def test_route_cleanup_removes_page_objects_and_free_functions_only_for_exact_package():
    clean=cleanup_function()
    cls=type('Page',(),{'__module__':'data.plugins.example.page','route':lambda self:None})
    other=type('Page',(),{'__module__':'data.plugins.example_extra.page','route':lambda self:None})
    def free_handler():pass
    free_handler.__module__='data.plugins.example.api'
    keep=('/other',other().route,['GET'],'')
    ctx=SimpleNamespace(registered_web_apis=[('/page',cls().route,['GET'],''),('/free',free_handler,['POST'],''),keep])
    original_list=ctx.registered_web_apis
    clean(ctx,'data.plugins.example')
    assert ctx.registered_web_apis is original_list
    assert ctx.registered_web_apis==[keep]
    clean(ctx,'data.plugins.example')
    assert ctx.registered_web_apis==[keep]

def test_missing_context_and_routes_are_safe():
    clean=cleanup_function()
    clean(None,'data.plugins.example');clean(SimpleNamespace(),'data.plugins.example')

def test_pinned_repair_is_idempotent_and_rejects_unknown_versions(tmp_path,monkeypatch):
    from scripts import repair_plugin_routes as repair
    import hashlib
    original=''.join(old for old,_ in repair.PATCHES)
    target=tmp_path/'star_manager.py';target.write_bytes(original.encode())
    monkeypatch.setattr(repair,'ROOT',tmp_path)
    monkeypatch.setattr(repair,'ORIGINAL',hashlib.sha256(original.encode()).hexdigest())
    repair.repair(target);first=target.read_bytes();repair.repair(target)
    assert target.read_bytes()==first
    target.write_bytes(first+b'\n# another edit')
    import pytest
    with pytest.raises(ValueError,match='version changed'):repair.repair(target)
