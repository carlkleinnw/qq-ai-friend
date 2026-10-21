import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'installer'))
from archive_utils import extract_payload, read_payload
spec = importlib.util.spec_from_file_location('installer_deploy', ROOT / 'installer/deploy.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


def package(path, files=None, version='0.4.0', data_format='v1'):
    files = files or {'README.md': b'Old release', 'scripts/demo.py': b'print(1)',
                      'installer/installer-lock.json': b'{"plugins": [], "dashboard": {}}'}
    manifest = {'product': 'ai-friend', 'format': 1, 'version': version, 'data_format': data_format,
                'files': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    with ZipFile(path, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        archive.writestr('package-manifest.json', json.dumps(manifest))
    return manifest


@pytest.mark.parametrize('name', ['../outside.py', 'runtime/app/data/cmd_config.json', 'C:/outside.txt', 'scripts\\outside.py'])
def test_payload_rejects_traversal_and_private_data_entries(tmp_path, name):
    archive = tmp_path / 'bad.zip'
    package(archive, {name: b'invalid'})
    with pytest.raises(ValueError):
        extract_payload(archive, tmp_path / 'output')
    assert not (tmp_path / 'outside.py').exists()


def test_payload_hash_mismatch_and_case_duplicate_are_rejected(tmp_path):
    archive = tmp_path / 'bad.zip'
    manifest = package(archive)
    manifest['files']['README.md'] = '0' * 64
    with ZipFile(archive, 'w') as z:
        z.writestr('package-manifest.json', json.dumps(manifest))
        z.writestr('README.md', b'Changed')
        z.writestr('scripts/demo.py', b'print(1)')
        z.writestr('installer/installer-lock.json', b'{"plugins": [], "dashboard": {}}')
    with pytest.raises(ValueError, match='校验'):
        read_payload(archive)
    package(archive, {'README.md': b'a', 'readme.md': b'b'})
    with pytest.raises(ValueError, match='重名'):
        read_payload(archive)


def test_existing_unmanaged_development_data_is_never_adopted(tmp_path):
    (tmp_path / 'runtime/app/data').mkdir(parents=True)
    with pytest.raises(ValueError, match='已有开发版'):
        deployment.validate_root(tmp_path)


def test_changed_program_files_stop_upgrade_before_overwrite(tmp_path):
    archive = tmp_path / 'payload.zip'
    state = package(archive)
    extract_payload(archive, tmp_path / 'app')
    (tmp_path / 'app/README.md').write_text('User code edit')
    with pytest.raises(ValueError, match='手动修改'):
        deployment.check_owned_files(tmp_path / 'app', state)


def test_program_rollback_preserves_private_data_and_environment_pointer(tmp_path):
    root = tmp_path / 'app'
    backup = root / 'runtime/upgrades/old'
    backup.mkdir(parents=True)
    state = package(backup / 'code.zip')
    deployment.write_json(backup / 'state.json', state)
    deployment.write_json(backup / 'installation.json', {'environment': 'envs/old', 'port': 6190})
    (root / 'scripts').mkdir()
    (root / 'scripts/new.py').write_text('new')
    private = root / 'runtime/app/data/user-memory.json'
    private.parent.mkdir(parents=True)
    private.write_bytes(b'private-user-data')
    restored = deployment.restore_code(root, backup, {'README.md', 'scripts/new.py'})
    assert restored['version'] == '0.4.0'
    assert not (root / 'scripts/new.py').exists()
    assert private.read_bytes() == b'private-user-data'
    assert json.loads((root / 'runtime/installation.local.json').read_text())['environment'] == 'envs/old'


def test_failed_first_install_can_resume_without_resetting_user_data(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    prefix = root / 'runtime/envs/clean'
    prefix.mkdir(parents=True)
    (prefix / 'python.exe').write_bytes(b'fixture')
    archive = tmp_path / 'payload.zip'
    package(archive)
    service = SimpleNamespace(run_action=lambda *a, **k: None, ready=lambda: True)
    monkeypatch.setattr(deployment, 'service_module', lambda root: service)
    monkeypatch.setattr(deployment, 'download_plugins', lambda *a: None)
    monkeypatch.setattr(deployment, 'prepare_dashboard', lambda *a: None)
    def interrupted(*args, **kwargs):
        data = root / 'runtime/app/data'
        data.mkdir(parents=True, exist_ok=True)
        (data / 'user.json').write_bytes(b'keep-existing-data')
        raise RuntimeError('interrupted setup')
    monkeypatch.setattr(deployment, 'run_script', interrupted)
    with pytest.raises(RuntimeError, match='interrupted'):
        deployment.deploy(root, archive, prefix)
    assert (root / 'runtime/installation-in-progress.local.json').exists()
    monkeypatch.setattr(deployment, 'run_script', lambda *a, **k: None)
    deployment.deploy(root, archive, prefix)
    assert (root / 'runtime/app/data/user.json').read_bytes() == b'keep-existing-data'
    assert not (root / 'runtime/installation-in-progress.local.json').exists()
    assert (root / 'runtime/deployment-state.local.json').exists()


def test_uninstall_keeps_runtime_and_unowned_notes(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    root.mkdir()
    archive = tmp_path / 'payload.zip'
    state = package(archive)
    extract_payload(archive, root)
    private = root / 'runtime/app/data/keep.json'
    private.parent.mkdir(parents=True)
    private.write_bytes(b'private data')
    notes = root / 'my-notes.txt'
    notes.write_bytes(b'user notes')
    deployment.write_json(root / 'runtime/deployment-state.local.json', state)
    calls = []
    monkeypatch.setattr(deployment, 'service_module', lambda root: SimpleNamespace(run_action=lambda action: calls.append(action)))
    deployment.uninstall_program(root)
    assert calls == ['stop']
    assert private.read_bytes() == b'private data'
    assert notes.read_bytes() == b'user notes'
    assert not (root / 'README.md').exists()
    assert (root / 'runtime/uninstalled.local.json').exists()


def test_reinstall_does_not_overwrite_edited_retained_plugins(tmp_path):
    name = 'plugins/example/main.py'
    installed = tmp_path / 'runtime/app/data' / name
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b'manual changes')
    with pytest.raises(ValueError, match='插件有其他改动'):
        deployment.check_owned_files(tmp_path, {'files': {name: hashlib.sha256(b'old').hexdigest()}}, allow_missing=True)


def test_failed_upgrade_restores_code_and_environment_without_reverting_data(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    old_archive = tmp_path / 'old.zip'
    old = package(old_archive)
    extract_payload(old_archive, root)
    old_python = root / 'runtime/envs/old/python.exe'
    new_python = root / 'runtime/envs/new/python.exe'
    for python in [old_python, new_python]:
        python.parent.mkdir(parents=True)
        python.write_bytes(b'fixture')
    deployment.write_json(root / 'runtime/deployment-state.local.json', old)
    deployment.write_json(root / 'runtime/installation.local.json', {'environment': 'envs/old', 'port': 6190})
    private = root / 'runtime/app/data/user.json'
    private.parent.mkdir(parents=True)
    private.write_bytes(b'keep')
    new_archive = tmp_path / 'new.zip'
    package(new_archive, {'README.md': b'new', 'scripts/demo.py': b'print(2)',
            'installer/installer-lock.json': b'{"plugins": [], "dashboard": {}}'}, version='0.4.1')
    calls = []
    service = SimpleNamespace(PYTHON=old_python, managed_process=lambda: object(), run_action=lambda action, **k: calls.append(action))
    monkeypatch.setattr(deployment, 'service_module', lambda root: service)
    monkeypatch.setattr(deployment, 'download_plugins', lambda *a: None)
    monkeypatch.setattr(deployment, 'prepare_dashboard', lambda *a: None)
    def run(root, python, script, *args):
        if 'initialize_installation' in script:
            raise RuntimeError('injected upgrade failure')
    monkeypatch.setattr(deployment, 'run_script', run)
    with pytest.raises(RuntimeError, match='injected'):
        deployment.deploy(root, new_archive, new_python.parent)
    assert (root / 'README.md').read_bytes() == b'Old release'
    assert json.loads((root / 'runtime/installation.local.json').read_text())['environment'] == 'envs/old'
    assert private.read_bytes() == b'keep'
    assert calls[-1] == 'start'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell 5.1 regression')
def test_bootstrap_reports_real_native_exit_codes():
    script = r'''
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__BOOTSTRAP__',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Bootstrap syntax errors' }
$function=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-SetupCommand'},$true)
. ([scriptblock]::Create($function.Extent.Text))
Invoke-SetupCommand $env:ComSpec @('/c','exit','0')
$failed=$false
try { Invoke-SetupCommand $env:ComSpec @('/c','exit','7') } catch { $failed=$true }
if (-not $failed) { throw 'Native failure was not reported' }
Write-Output 'native-exit-scope-ok'
exit 0
'''.replace('__BOOTSTRAP__', str(ROOT / 'installer/bootstrap.ps1').replace("'", "''"))
    shell = Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'native-exit-scope-ok' in result.stdout


@pytest.mark.skipif(sys.platform != 'win32', reason='NSIS Windows pipe integration')
def test_nsis_reads_bootstrap_chinese_without_system_codepage(tmp_path):
    compiler = Path('E:/DeveloperTools/nsis-3.12/NSIS/makensis.exe')
    if not compiler.exists():
        pytest.skip('NSIS compiler is not installed')
    payload = tmp_path / 'payload.zip'
    payload.write_bytes(b'invalid fixture')
    capture = tmp_path / 'output.txt'
    executable = tmp_path / 'probe.exe'
    source = tmp_path / 'probe.nsi'
    source.write_text('''Unicode true
RequestExecutionLevel user
SilentInstall silent
OutFile "__EXE__"
Section
nsExec::ExecToStack '"$SYSDIR\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "__BOOTSTRAP__" -InstallRoot "__INSTALL__" -Payload "__PAYLOAD__" -ExpectedSha "__HASH__" -CondaExe "missing.exe"'
Pop $0
Pop $1
FileOpen $2 "__CAPTURE__" w
FileWriteUTF16LE $2 "$0$\\r$\\n$1"
FileClose $2
SectionEnd
'''.replace('__EXE__', str(executable)).replace('__BOOTSTRAP__', str(ROOT / 'installer/bootstrap.ps1'))
        .replace('__INSTALL__', str(tmp_path / '中文 空格')).replace('__PAYLOAD__', str(payload))
        .replace('__HASH__', '0' * 64).replace('__CAPTURE__', str(capture)), encoding='utf-8-sig')
    subprocess.run([str(compiler), '/V1', '/INPUTCHARSET', 'UTF8', str(source)], check=True, capture_output=True)
    subprocess.run([str(executable)], check=True, timeout=30)
    text = capture.read_text(encoding='utf-16-le')
    assert text.splitlines()[0] == '1', text
    assert '安装未完成：安装内容校验失败。' in text, repr(text)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell native pipe integration')
@pytest.mark.parametrize('native_exit', [0, 7])
def test_native_utf8_stdout_stderr_are_streamed_without_loss(tmp_path, native_exit):
    child = tmp_path / '中文 工具.py'
    child.write_text('import sys\nfor n in range(500):\n'
                     ' print("标准输出：中文路径 " + str(n), flush=True)\n'
                     ' print("标准错误：中文提示 " + str(n), file=sys.stderr, flush=True)\n'
                     'print(repr(sys.argv[1:]), flush=True)\n'
                     f'sys.exit({native_exit})\n', encoding='utf-8')
    script = tmp_path / 'run.ps1'
    script.write_text(r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::Unicode
$env:PYTHONIOENCODING='utf-8'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__BOOTSTRAP__',[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-SetupCommand'},$true)
. ([scriptblock]::Create($function.Extent.Text))
try { Invoke-SetupCommand '__PYTHON__' @('__CHILD__','含 空格','C:\中文 路径\'); Write-Output 'native-ok' }
catch { Write-Output $_.Exception.Message }
'''.replace('__BOOTSTRAP__', str(ROOT / 'installer/bootstrap.ps1'))
        .replace('__PYTHON__', sys.executable).replace('__CHILD__', str(child)), encoding='utf-8-sig')
    shell = Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-File', str(script)],
                            capture_output=True, timeout=30)
    text = result.stdout.decode('utf-16-le')
    assert result.returncode == 0
    assert text.count('标准输出：中文路径 ') == 500
    assert text.count('标准错误：中文提示 ') == 500
    assert "['含 空格', 'C:\\\\中文 路径\\\\']" in text
    assert ('native-ok' in text) == (native_exit == 0)
    if native_exit:
        assert '安装子步骤返回错误 7' in text


def test_payload_accepts_root_license(tmp_path):
    archive = tmp_path / 'licensed.zip'
    package(archive, {'LICENSE': b'GNU license', 'NOTICE.md': b'Attribution'})
    extract_payload(archive, tmp_path / 'installed')
    assert (tmp_path / 'installed/LICENSE').read_bytes() == b'GNU license'
