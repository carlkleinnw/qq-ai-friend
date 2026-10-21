"""Checked source packages; runtime data can never be installed as program files."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ALLOWED = {'scripts', 'plugins', 'config', 'docs', 'installer'}


def is_program_member(member):
    return (member.parts[0] in ALLOWED or member.as_posix() == 'AI好友.exe'
            or (len(member.parts) == 1 and member.suffix in {'.md', '.txt', '.yml', '.json', '.cmd'}))


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def safe_member(name):
    path = PurePosixPath(name)
    if not name or not path.parts or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts:
        raise ValueError('安装包包含不安全路径')
    return path


def read_payload(path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(n.casefold() for n in names)) or archive.testzip():
            raise ValueError('安装包损坏或文件重名')
        manifest = json.loads(archive.read('package-manifest.json'))
        if manifest.get('product') != 'ai-friend' or manifest.get('format') != 1:
            raise ValueError('不是本程序支持的安装包')
        if set(names) != {'package-manifest.json', *manifest['files']}:
            raise ValueError('安装包清单不完整')
        for name, expected in manifest['files'].items():
            member = safe_member(name)
            if not is_program_member(member):
                raise ValueError('安装包试图写入用户数据目录')
            info = archive.getinfo(name)
            if info.file_size > 50 * 1024 ** 2 or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('安装包文件大小或类型不受支持')
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError('安装包文件校验失败')
        return manifest


def extract_payload(path, destination):
    manifest = read_payload(path)
    destination = Path(destination).resolve()
    with ZipFile(path) as archive:
        for name in manifest['files']:
            target = (destination / name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('解压目录越界')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    return manifest
