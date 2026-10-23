"""Protect the installer boundary: layout updates never rewrite private data."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('panel_layout', Path(__file__).parents[1] / 'scripts/apply_panel_layout.py')
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)


@pytest.fixture
def installation(tmp_path):
    files = {
        'runtime/app/data/dist/index.html': '<html><head><title>Native</title></head><body>Native</body></html>',
        'installer/dashboard/friend-panel.js': '// presentation',
        'installer/dashboard/friend-panel.css': 'body {}',
        'runtime/app/data/config/private.json': '{"existing": true}',
    }
    for name in ['index.html', 'style.css', 'app.js']:
        files[f'plugins/astrbot_plugin_persona_studio/views/editor/{name}'] = 'new ' + name
        files[f'runtime/app/data/plugins/astrbot_plugin_persona_studio/views/editor/{name}'] = 'original ' + name
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    return tmp_path


def test_update_backs_up_and_is_repeatable(installation):
    backup = panel.apply(installation)
    index = installation / 'runtime/app/data/dist/index.html'
    first = index.read_bytes()
    assert panel.apply(installation) is None
    assert index.read_bytes() == first
    assert (backup / 'runtime/app/data/dist/index.html').read_text() == '<html><head><title>Native</title></head><body>Native</body></html>'
    assert (backup / 'runtime/app/data/plugins/astrbot_plugin_persona_studio/views/editor/app.js').read_text() == 'original app.js'
    assert (installation / 'runtime/app/data/config/private.json').read_text() == '{"existing": true}'
    panel.apply(installation, restore=True)
    assert panel.MARKER_START not in index.read_text()
    assert 'Native</body>' in index.read_text()


def test_missing_source_does_not_partially_install(installation):
    index = installation / 'runtime/app/data/dist/index.html'
    before = index.read_bytes()
    (installation / 'installer/dashboard/friend-panel.css').unlink()
    with pytest.raises(RuntimeError, match='缺少页面源文件'):
        panel.apply(installation)
    assert index.read_bytes() == before
    assert not (installation / 'runtime/app/data/dist/assets/friend-panel.js').exists()
