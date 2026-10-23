"""Transactional program deployment; data backup stays with AstrBot's exporter."""
import argparse
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import urllib.request
import time
from zipfile import ZipFile, ZIP_DEFLATED

from filelock import FileLock
from archive_utils import digest, extract_payload, read_payload, safe_member, is_program_member

STATE_NAME = 'deployment-state.local.json'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def validate_root(root):
    root = Path(root).resolve()
    if root == Path(root.anchor) or root.is_relative_to(Path(os.environ.get('SystemRoot', 'C:/Windows')).resolve()):
        raise ValueError('请选择独立的程序安装文件夹')
    if ((root / 'runtime/app/data').exists() and not (root / 'runtime' / STATE_NAME).exists()
            and not (root / 'runtime/installation-in-progress.local.json').exists()):
        raise ValueError('检测到已有开发版或未登记的数据目录，请选择新的安装文件夹')
    return root


def service_module(root):
    spec = importlib.util.spec_from_file_location('installer_owned_service', root / 'scripts/service.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(root, python, script, *args, app=None):
    environment = os.environ.copy()
    environment.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', ASTRBOT_ROOT=str(app or root / 'runtime/app'))
    environment['PATH'] = str(python.parent) + os.pathsep + str(python.parent / 'Library/bin') + os.pathsep + environment.get('PATH', '')
    subprocess.run([str(python), str(root / script), *map(str, args)], cwd=root, env=environment, check=True, timeout=1200)


def check_owned_files(root, state, allow_missing=False):
    for name, expected in state['files'].items():
        file = root / safe_member(name)
        if (not file.exists() and not allow_missing) or (file.exists() and digest(file) != expected):
            raise ValueError('程序文件已被手动修改，升级已暂停以保留改动：' + name)
        if name.startswith('plugins/'):
            relative = Path(name).relative_to('plugins')
            installed = root / 'runtime/app/data/plugins' / relative
            if installed.exists() and digest(installed) != expected:
                raise ValueError('已安装的本项目插件有其他改动：' + str(relative))


def available_port():
    for port in range(6185, 6286):
        with socket.socket() as connection:
            if connection.connect_ex(('127.0.0.1', port)) != 0:
                return port
    raise RuntimeError('没有可用的本机面板端口')


def download_checked(asset, cache):
    if cache.exists() and digest(cache) == asset['sha256']:
        return
    partial = cache.with_suffix('.part')
    for attempt in range(3):
        try:
            print('正在下载并校验组件…', flush=True)
            with urllib.request.urlopen(asset['url'], timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            if digest(partial) != asset['sha256']:
                raise ValueError('下载校验失败')
            os.replace(partial, cache)
            return
        except Exception:
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2)


def prepare_dashboard(root, asset, force=False):
    marker = root / 'runtime/app/data/.installer-dashboard-sha256'
    if not force and marker.exists() and marker.read_text().strip() == asset['sha256']:
        return
    cache = root / 'runtime/cache/downloads' / (asset['sha256'] + '.zip')
    cache.parent.mkdir(parents=True, exist_ok=True)
    download_checked(asset, cache)
    data = root / 'runtime/app/data'
    with ZipFile(cache) as archive:
        for info in archive.infolist():
            path = safe_member(info.filename)
            if path.parts[0] != 'dist' or info.is_dir():
                continue
            file = (data / info.filename).resolve()
            if not file.is_relative_to(data.resolve()):
                raise ValueError('管理面板解压越界')
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(archive.read(info))
    marker.write_text(asset['sha256'], encoding='ascii')


def download_plugins(root, lock):
    for plugin in lock['plugins']:
        target = root / 'runtime/vendor' / plugin['directory']
        marker = target / '.installer-source-sha256'
        if marker.exists():
            if marker.read_text().strip() != plugin['sha256']:
                raise ValueError('上游插件版本变更需要先进行迁移验收')
            continue
        if target.exists():
            raise ValueError('上游插件目录已有未登记的内容')
        cache = root / 'runtime/cache/downloads' / (plugin['sha256'] + '.zip')
        cache.parent.mkdir(parents=True, exist_ok=True)
        download_checked(plugin, cache)
        with ZipFile(cache) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            for info in members:
                path = safe_member(info.filename)
                relative = Path(*path.parts[1:])
                file = (target / relative).resolve()
                if not file.is_relative_to(target.resolve()):
                    raise ValueError('上游插件归档越界')
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(archive.read(info))
        marker.write_text(plugin['sha256'], encoding='ascii')


def copy_own_plugins(root):
    for source in (root / 'plugins').rglob('*'):
        if source.is_file() and '__pycache__' not in source.parts:
            target = root / 'runtime/app/data/plugins' / source.relative_to(root / 'plugins')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def remove_owned_file(root, name):
    target = (root / safe_member(name)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('程序文件路径越界')
    target.unlink(missing_ok=True)
    if name.startswith('plugins/'):
        installed = (root / 'runtime/app/data/plugins' / Path(name).relative_to('plugins')).resolve()
        if not installed.is_relative_to((root / 'runtime/app/data/plugins').resolve()):
            raise ValueError('插件文件路径越界')
        installed.unlink(missing_ok=True)


def restore_code(root, backup, current_files):
    manifest = read_payload(backup / 'code.zip')
    # Delete only files owned by this attempted release and absent from the old one.
    for name in set(current_files) - set(manifest['files']):
        remove_owned_file(root, name)
    extract_payload(backup / 'code.zip', root)
    write_json(root / 'runtime/installation.local.json', json.loads((backup / 'installation.json').read_text()))
    state = json.loads((backup / 'state.json').read_text())
    write_json(root / 'runtime' / STATE_NAME, state)
    copy_own_plugins(root)
    # The shell lives in generated dashboard files, outside the program manifest.
    # Restore the pinned dashboard too, so rolling back cannot leave a new shell
    # pointing at plugin pages which the previous release does not contain.
    lock = json.loads((root / 'installer/installer-lock.json').read_text(encoding='utf-8'))
    if lock.get('dashboard', {}).get('sha256'):
        prepare_dashboard(root, lock['dashboard'], True)
        if (root / 'scripts/apply_panel_layout.py').is_file():
            run_script(root, Path(sys.executable), 'scripts/apply_panel_layout.py')
    return state


def deploy(root, payload, prefix):
    root = validate_root(root)
    prefix = Path(prefix).resolve()
    if not prefix.is_relative_to((root / 'runtime/envs').resolve()) or not (prefix / 'python.exe').exists():
        raise ValueError('运行环境必须位于所选安装目录内')
    manifest = read_payload(payload)
    runtime = root / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with FileLock(str(runtime / 'deployment.lock'), timeout=10), FileLock(str(runtime / 'service.lock'), timeout=150):
        state_path = runtime / STATE_NAME
        old = json.loads(state_path.read_text()) if state_path.exists() else None
        pending_path = runtime / 'installation-in-progress.local.json'
        pending = json.loads(pending_path.read_text()) if pending_path.exists() else None
        reinstall = bool(old and (runtime / 'uninstalled.local.json').exists())
        if old and old['data_format'] != manifest['data_format']:
            raise ValueError('数据格式发生变化，需要专门的迁移安装包')
        if old and not reinstall:
            check_owned_files(root, old)
        elif reinstall:
            check_owned_files(root, old, allow_missing=True)
        elif not old:
            if pending and (pending.get('product') != 'ai-friend' or pending.get('version') != manifest['version']):
                raise ValueError('请先完成之前未成功的安装，或选择新目录')
            for name in manifest['files']:
                existing = root / name
                if existing.exists() and not (pending and pending['files'].get(name) == digest(existing)):
                    raise ValueError('安装目录已有同名文件，请另选独立目录：' + name)
        if old:
            for name in set(manifest['files']) - set(old['files']):
                if (root / name).exists():
                    raise ValueError('新版程序与目录中的其他文件重名，未覆盖：' + name)
        backup = runtime / 'upgrades' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        previous_service = service_module(root) if old and not reinstall else None
        was_running = bool(previous_service and previous_service.managed_process())
        if previous_service:
            previous_service.run_action('stop')
        code_switched = False
        try:
            if old and not reinstall:
                backup.mkdir(parents=True)
                (backup / 'installation.json').write_bytes((runtime / 'installation.local.json').read_bytes())
                write_json(backup / 'state.json', old)
                with ZipFile(backup / 'code.zip', 'w', ZIP_DEFLATED) as archive:
                    for name in old['files']:
                        archive.write(root / name, name)
                    archive.writestr('package-manifest.json', json.dumps({**old, 'product': 'ai-friend', 'format': 1}))
                run_script(root, previous_service.PYTHON, 'scripts/native_backup.py', '_export', '--output', backup / 'native')
            if not old:
                write_json(pending_path, manifest)
            code_switched = True
            if old:
                for name in set(old['files']) - set(manifest['files']):
                    remove_owned_file(root, name)
            extract_payload(payload, root)
            settings_path = runtime / 'installation.local.json'
            settings = json.loads(settings_path.read_text()) if settings_path.exists() else {'port': available_port()}
            settings.update(environment=prefix.relative_to(runtime).as_posix(), version=manifest['version'], product='ai-friend')
            write_json(runtime / 'installation.local.json', settings)
            lock = json.loads((root / 'installer/installer-lock.json').read_text())
            download_plugins(root, lock)
            prepare_dashboard(root, lock['dashboard'])
            copy_own_plugins(root)
            run_script(root, prefix / 'python.exe', 'scripts/initialize_installation.py', '--upgrade' if old else '--first-install')
            new_service = service_module(root)
            new_service.run_action('start', open_browser=False)
            if not old:
                run_script(root, prefix / 'python.exe', 'scripts/initialize_installation.py', '--configure-online')
            if not new_service.ready():
                raise RuntimeError('安装后健康检查未通过')
            previous_version = (old.get('rollback') if old['version'] == manifest['version'] else str(backup)) if old and not reinstall else None
            new_state = {**manifest, 'environment': settings['environment'], 'rollback': previous_version}
            write_json(state_path, new_state)
            pending_path.unlink(missing_ok=True)
            (runtime / 'uninstalled.local.json').unlink(missing_ok=True)
            print('安装部署完成；用户数据保存在所选目录的 runtime 中。', flush=True)
        except Exception:
            if (root / 'scripts/service.py').exists() and (runtime / 'installation.local.json').exists():
                service_module(root).run_action('stop')
            if old and code_switched and (backup / 'code.zip').exists():
                restore_code(root, backup, manifest['files'])
            if was_running:
                service_module(root).run_action('start', open_browser=False)
            raise


def rollback(root):
    root = validate_root(root)
    runtime = root / 'runtime'
    with FileLock(str(runtime / 'deployment.lock'), timeout=10), FileLock(str(runtime / 'service.lock'), timeout=150):
        current = json.loads((runtime / STATE_NAME).read_text())
        if not current.get('rollback'):
            raise ValueError('没有上一程序版本可恢复')
        backup = Path(current['rollback']).resolve()
        if not backup.is_relative_to((runtime / 'upgrades').resolve()):
            raise ValueError('版本备份目录不正确')
        read_payload(backup / 'code.zip')
        for name in ['state.json', 'installation.json']:
            json.loads((backup / name).read_text(encoding='utf-8'))
        check_owned_files(root, current)
        service_module(root).run_action('stop')
        restored = restore_code(root, backup, current['files'])
        service_module(root).run_action('start', open_browser=False)
        refresh_windows_version(root, restored['version'])
        print('已恢复上一程序版本 ' + restored['version'] + '，现有用户数据保留。')


def refresh_windows_version(root, version):
    if os.name != 'nt':
        return
    import winreg
    try:
        path = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
            if Path(winreg.QueryValueEx(key, 'InstallLocation')[0]).resolve() == root.resolve():
                winreg.SetValueEx(key, 'DisplayVersion', 0, winreg.REG_SZ, version)
    except FileNotFoundError:
        pass
    except OSError:
        print('系统应用列表版本未能更新，请以维护窗口显示为准。')


def uninstall_program(root):
    root = validate_root(root)
    runtime = root / 'runtime'
    with FileLock(str(runtime / 'deployment.lock'), timeout=10), FileLock(str(runtime / 'service.lock'), timeout=150):
        state = json.loads((runtime / STATE_NAME).read_text(encoding='utf-8'))
        if state.get('product') != 'ai-friend':
            raise ValueError('安装登记不正确')
        for name in state['files']:
            if not is_program_member(safe_member(name)) or not (root / name).resolve().is_relative_to(root):
                raise ValueError('卸载文件路径不正确')
        check_owned_files(root, state)
        service_module(root).run_action('stop')
        write_json(runtime / 'uninstalled.local.json', {'product': 'ai-friend'})
        for name in state['files']:
            (root / name).unlink(missing_ok=True)
        directories = {parent for name in state['files'] for parent in (root / name).parents if parent != root and parent.is_relative_to(root)}
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        print('程序已移除，runtime 用户数据完整保留。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--prefix', type=Path)
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--uninstall-program', action='store_true')
    args = parser.parse_args()
    if args.uninstall_program:
        uninstall_program(args.root)
    elif args.rollback:
        rollback(args.root)
    else:
        deploy(args.root, args.payload, args.prefix)
