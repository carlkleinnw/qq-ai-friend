"""Build the source-only payload and a standard NSIS Windows setup executable."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def build(version, compiler, conda, output):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Version must have three numeric components.')
    work = ROOT / 'runtime/installer-build' / version
    work.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / 'installer/installer-lock.json').read_text(encoding='utf-8'))
    if hashlib.sha256(conda.read_bytes()).hexdigest() != lock['conda_standalone']['executable_sha256']:
        raise ValueError('Conda standalone hash mismatch.')
    source_files = []
    for directory in ['scripts', 'plugins', 'config', 'docs', 'installer']:
        source_files += [file for file in (ROOT / directory).rglob('*')
                         if file.is_file() and not any(part in {'__pycache__', '.git', '.pytest_cache'} for part in file.parts)
                         and file.suffix not in {'.pyc', '.log'} and not file.name.endswith('.local.json')
                         and not file.name.startswith('.env')]
    source_files += [ROOT / name for name in ['README.md', 'LICENSE', 'NOTICE.md', 'CONTRIBUTING.md', 'THIRD_PARTY.md', 'requirements.lock.txt', 'environment.yml', 'upstream.lock.json', '交付说明_稳定版.md']]
    source_files += list(ROOT.glob('*.cmd'))
    files = {}
    for file in sorted(source_files):
        data = file.read_bytes()
        if file.suffix == '.ps1' and not data.startswith(b'\xef\xbb\xbf'):
            raise ValueError('Windows PowerShell scripts must use UTF-8 BOM: ' + str(file))
        if file.name == 'installer-lock.json':
            copy = {**lock, 'version': version}
            data = (json.dumps(copy, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        files[file.relative_to(ROOT).as_posix()] = data
    launcher = work / 'AI好友.exe'
    launcher_source = work / 'launcher.cs'
    launcher_source.write_text((ROOT / 'installer/launcher.cs').read_text(encoding='utf-8').replace(
        'AssemblyVersion("0.4.0.0")', 'AssemblyVersion("' + version + '.0")'), encoding='utf-8-sig')
    csc = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(csc), '/nologo', '/codepage:65001', '/target:winexe', '/reference:System.Windows.Forms.dll',
                    '/out:' + str(launcher), str(launcher_source)], check=True)
    files['AI好友.exe'] = launcher.read_bytes()
    actions = {'启动AI好友.cmd': 'Start', '停止AI好友.cmd': 'Stop', '打开人设设置.cmd': 'Persona',
               '备份AI好友.cmd': 'Backup', '检查备份能否恢复.cmd': 'Verify', '日常状态检查.cmd': 'Status',
               '查看登录说明.cmd': 'LoginInfo', '启用登录后启动.cmd': 'EnableAutostart', '关闭登录后启动.cmd': 'DisableAutostart'}
    for name, action in actions.items():
        files[name] = ('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\\launch.ps1" -Action ' + action + '\r\nif errorlevel 1 pause\r\n').encode('ascii')
    manifest = {'product': 'ai-friend', 'format': 1, 'version': version, 'data_format': lock['data_format'],
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    payload = work / 'payload.zip'
    with ZipFile(payload, 'w', ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('package-manifest.json', json.dumps(manifest))
    directories = set()
    lines = []
    for name in sorted(files, reverse=True):
        windows = name.replace('/', '\\')
        if '$' in windows or '"' in windows:
            raise ValueError('Unexpected installer filename.')
        lines.append('Delete "$INSTDIR\\' + windows + '"')
        directories.update(parent.as_posix() for parent in Path(name).parents if str(parent) != '.')
    for directory in sorted(directories, key=lambda item: (item.count('/'), item), reverse=True):
        lines.append('RMDir "$INSTDIR\\' + directory.replace('/', '\\') + '"')
    delete_include = work / 'uninstall-managed.nsh'
    delete_include.write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    output.parent.mkdir(parents=True, exist_ok=True)
    compiled = work / ('installer-' + uuid.uuid4().hex + '.exe')
    subprocess.run([str(compiler), '/V2', '/INPUTCHARSET', 'UTF8', '/DVERSION=' + version,
                    '/DSOURCE=' + str(ROOT), '/DOUTPUT=' + str(compiled), '/DPAYLOAD=' + str(payload),
                    '/DPAYLOADSHA=' + hashlib.sha256(payload.read_bytes()).hexdigest(),
                    '/DCONDAEXE=' + str(conda), '/DDELETEINCLUDE=' + str(delete_include),
                    str(ROOT / 'installer/setup.nsi')], check=True)
    os.replace(compiled, output)
    output.with_suffix('.sha256.txt').write_text(hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n', encoding='utf-8')
    print('Installer created:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='0.4.0')
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--conda', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.version, args.compiler.resolve(), args.conda.resolve(), args.output.resolve())
