"""Install our thin native Plugin View without changing any existing persona."""
import json
import shutil
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = 'astrbot_plugin_persona_studio'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qq-editor-session', action='append', default=[], help='Deprecated; use the per-robot switch in the persona page.')
    args = parser.parse_args()
    if args.qq_editor_session:
        parser.error('请在好友人设页面选择机器人并打开“允许 QQ 编辑人设”，不再使用私聊 UMO 授权。')
    if shutil.disk_usage(ROOT).free < 100 * 1024 ** 2:
        raise RuntimeError('E drive has insufficient free space.')
    source = ROOT / 'plugins' / NAME
    target = ROOT / 'runtime/app/data/plugins' / NAME
    files = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    for path in files:
        destination = target / path.relative_to(source)
        if destination.exists() and destination.read_bytes() != path.read_bytes():
            raise RuntimeError('Installed plugin differs; preserve local edits before updating: ' + destination.name)
    for path in files:
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    config_path = ROOT / 'runtime/app/data/config' / (NAME + '_config.json')
    if not config_path.exists():
        state = json.loads((ROOT / 'runtime/multibot.local.json').read_text(encoding='utf-8'))
        bots = [{'bot_id': state['first_bot_id'], 'name': '大肥鱼'}]
        if state.get('second_bot_id'):
            bots.append({'bot_id': state['second_bot_id'], 'name': 'GPT大人'})
        config_path.write_text(json.dumps({'bots': bots}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Native persona editor installed. Existing prompts and bot configuration preserved; restart the service to load it.')


if __name__ == '__main__':
    main()
