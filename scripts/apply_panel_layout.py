"""Install the presentation layer without rebuilding AstrBot or touching user data."""
from datetime import datetime
from pathlib import Path
import argparse
import shutil

ROOT = Path(__file__).resolve().parents[1]
MARKER_START = '<!-- AI-Friend panel start -->'
MARKER_END = '<!-- AI-Friend panel end -->'
SHELL_ASSETS = ['friend-native-bots.js', 'friend-panel.js', 'friend-panel.css']


def apply(root=ROOT, restore=False, include_plugin_code=False):
    root = Path(root).resolve()
    dist = root / 'runtime/app/data/dist'
    index = dist / 'index.html'
    if not index.is_file():
        raise RuntimeError('找不到已安装的网页面板，请先完成安装。')
    source = index.read_text(encoding='utf-8')
    if MARKER_START in source:
        if source.count(MARKER_START) != 1 or source.count(MARKER_END) != 1:
            raise RuntimeError('面板标记异常，未覆盖任何文件。')
        start = source.index(MARKER_START)
        end = source.index(MARKER_END) + len(MARKER_END)
        if source[end:end + 1] == '\n':
            end += 1
        source = source[:start] + source[end:]
    if '</head>' not in source:
        raise RuntimeError('面板缺少 head 结束标记，未覆盖任何文件。')
    targets = []
    if not restore:
        targets.extend((root / 'installer/dashboard' / name, dist / 'assets' / name)
                       for name in SHELL_ASSETS)
        editor = Path('plugins/astrbot_plugin_persona_studio/views/editor')
        targets.extend((root / editor / name, root / 'runtime/app/data' / editor / name)
                       for name in ['index.html', 'style.css', 'app.js'])
        views = Path('plugins/astrbot_plugin_persona_studio/views')
        for page in ('manage', 'model', 'qq', 'agent'):
            if (root / views / page).exists():
                targets.append((root / views / page / 'index.html', root / 'runtime/app/data' / views / page / 'index.html'))
                targets.extend((root / views / 'manage' / name, root / 'runtime/app/data' / views / page / name)
                               for name in ['style.css', 'app.js'])
        if include_plugin_code:
            plugin = Path('plugins/astrbot_plugin_persona_studio')
            targets.extend((root / plugin / name, root / 'runtime/app/data' / plugin / name)
                           for name in ['main.py', 'bot_registry.py', 'binding.py', 'connections.py', 'control.py', 'profile_images.py', '_conf_schema.json'])
        # Validate all sources before writing any installed file.
        for origin, _ in targets:
            if not origin.is_file():
                raise RuntimeError('缺少页面源文件：' + str(origin))
        assets = [(name, (root / 'installer/dashboard' / name).read_bytes())
                  for name in SHELL_ASSETS]
        import hashlib
        version = hashlib.sha256(b''.join(data for _, data in assets)).hexdigest()[:12]
        block = (MARKER_START + '\n'
                 f'<link rel="stylesheet" href="/assets/friend-panel.css?v={version}">\n'
                 f'<script defer src="/assets/friend-native-bots.js?v={version}"></script>\n'
                 f'<script defer src="/assets/friend-panel.js?v={version}"></script>\n' + MARKER_END)
        source = source.replace('</head>', block + '\n</head>', 1)
    changed = [(origin.read_bytes(), target) for origin, target in targets
               if not target.exists() or origin.read_bytes() != target.read_bytes()]
    if source != index.read_text(encoding='utf-8'):
        changed.append((source.encode('utf-8'), index))
    if not changed:
        return None
    if shutil.disk_usage(root).free < 20 * 1024 ** 2:
        raise RuntimeError('安装盘可用空间不足，未修改文件。')
    backup = root / 'runtime/backups/panel-layout' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for _, target in changed:
        if target.exists():
            saved = backup / target.relative_to(root)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    for content, target in changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.panel-tmp')
        temporary.write_bytes(content)
        temporary.replace(target)
    return backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-original-shell', action='store_true', help='移除简洁外壳，保留原生面板')
    parser.add_argument('--include-plugin-code', action='store_true', help='同步本轮绑定与状态接口；需先停止服务，更新后启动')
    args = parser.parse_args()
    result = apply(restore=args.restore_original_shell, include_plugin_code=args.include_plugin_code)
    print('页面已更新，刷新浏览器即可。备份：' + str(result) if result else '页面已经是当前版本。')
