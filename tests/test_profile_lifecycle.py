import hashlib
import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('profile_bridge', ROOT / 'scripts/repair_profile_lifecycle.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_pinned_profile_bridge_is_idempotent_and_refuses_other_changes(tmp_path):
    import astrbot.core.core_lifecycle as lifecycle
    native = Path(lifecycle.__file__).read_bytes()
    original = native.replace(bridge.NEW, bridge.OLD, 1)
    assert hashlib.sha256(original).hexdigest() == bridge.ORIGINAL
    file = tmp_path / 'core_lifecycle.py'
    file.write_bytes(original)
    bridge.repair(file)
    patched = file.read_bytes()
    assert patched.count(bridge.NEW) == 1
    bridge.repair(file)
    assert file.read_bytes() == patched
    file.write_bytes(patched + b'\n# someone else edited this file\n')
    with pytest.raises(ValueError, match='version changed'):
        bridge.repair(file)
