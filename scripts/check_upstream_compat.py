"""Run pinned upstream regressions with explicit test-fixture compatibility corrections."""
import ast
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
AUDITED_EVENT_LOCAL_HOOKS = {
    "_on_external_plugin_loaded": "d8e263fdcea857bc89caa9fce72c6005b866b349751522bfca42706f71631bbb",
    "_on_external_plugin_unloaded": "276a2925dc85f6bc15cb455cefda980e2f8d3bbb4b9544f6826513a6b5b631f0",
    "preserve_addressed_user_message": "8fe85f7b21cd5ce447c06cf7f863ef15eee663812113abaa8724d123217fb273",
    "restore_addressed_user_request": "c4da4f40c6fb5412c26420670446491df9871bf647cf3a8bc938de85eafe25ac",
}


def main():
    original = ROOT / "runtime/vendor/private_companion"
    locked = next(p["commit"] for p in json.loads((ROOT / "upstream.lock.json").read_text())["plugins"] if p["directory"] == "private_companion")
    if (original/'.git').exists():
        actual = subprocess.check_output(["git", "-C", str(original), "rev-parse", "HEAD"], text=True).strip()
        if actual != locked or subprocess.run(["git", "-C", str(original), "diff", "--quiet", "HEAD"]).returncode:
            raise ValueError("Upstream checkout changed; review compatibility against its exact source")
    else:
        # Installed releases ship verified source archives rather than Git metadata.
        lock=json.loads((ROOT/'installer/installer-lock.json').read_text('utf-8'))
        expected=next(p['sha256'] for p in lock['plugins'] if p['directory']=='private_companion')
        archive=ROOT/'runtime/cache/downloads'/(expected+'.zip')
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:
            raise ValueError('Cached upstream archive integrity check failed')
        with ZipFile(archive) as source_zip:
            for member in source_zip.infolist():
                if member.is_dir():continue
                relative=Path(*Path(member.filename).parts[1:])
                target=(original/relative).resolve()
                if not target.is_relative_to(original.resolve()) or target.read_bytes()!=source_zip.read(member):
                    raise ValueError('Installed vendor source changed; review compatibility before testing')
    source = (original / "main.py").read_text(encoding="utf-8")
    audited = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in AUDITED_EVENT_LOCAL_HOOKS:
            audited[node.name] = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
    if audited != AUDITED_EVENT_LOCAL_HOOKS:
        raise ValueError("Audited hooks changed; review their data boundaries before correcting the static check")
    workspace = ROOT / "verification/private/upstream-compat" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    shutil.copytree(original, workspace, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    wake = workspace / "tests/test_wake_message_context.py"
    text = wake.read_text(encoding="utf-8")
    old = "SimpleNamespace(astrbot_config=plugin.context.get_config.return_value)"
    if text.count(old) != 1:
        raise ValueError("Wake fixture version changed")
    wake.write_text(text.replace(old, "SimpleNamespace(astrbot_config=plugin.context.get_config.return_value, db_helper=None, astrbot_config_id='compat-fixture')"), encoding="utf-8")
    static = workspace / "tests/test_multi_persona_isolation.py"
    text = static.read_text(encoding="utf-8")
    old = 'if "_multi_persona_event_context" not in decorators'
    if text.count(old) != 1:
        raise ValueError("Static test version changed")
    corrected = old + " and name not in " + repr(set(AUDITED_EVENT_LOCAL_HOOKS))
    static.write_text(text.replace(old, corrected), encoding="utf-8")
    tests = ["test_multi_persona_isolation.py", "test_primary_persona_startup_config.py", "test_wake_message_context.py", "test_external_bridge_resolver.py"]
    env = os.environ.copy()
    env.update(ASTRBOT_ROOT=str(ROOT / "verification/private/compat-runtime"), PYTHONIOENCODING="utf-8")
    command = [sys.executable, "-m", "pytest", *[str(workspace / "tests" / name) for name in tests], "-q",
               "--memory-plugin-root", str(ROOT / "runtime/vendor/memory_companion"),
               "--junitxml", str(workspace / "junit.xml")]
    with (workspace / "pytest.log").open("w", encoding="utf-8") as log:
        outcome = subprocess.run(command, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    print("Compatibility tests exit code:", outcome.returncode)
    print("Original vendor tests and production plugin unchanged; copied fixture and scoped static check corrected.")
    print("Private results directory:", workspace.relative_to(ROOT))
    raise SystemExit(outcome.returncode)


if __name__ == "__main__":
    main()
