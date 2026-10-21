"""Prepare a new user's workspace using existing native setup and repair steps."""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

import httpx
import service
from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]


def offline():
    subprocess.run([sys.executable, str(ROOT / 'scripts/init_mvp.py')], check=True)
    for script in ['repair_memory_panel.py', 'repair_tts_timeout.py', 'repair_cron_failure.py', 'repair_backup_coverage.py']:
        subprocess.run([sys.executable, str(ROOT / 'scripts' / script)], check=True)
    for name, config in [('astrbot_plugin_persona_studio', {'bots': [], 'qq_editor_sessions': []}),
                         ('astrbot_plugin_reliability', {'bot_ids': []})]:
        file = ROOT / 'runtime/app/data/config' / (name + '_config.json')
        if not file.exists():
            file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    import imageio_ffmpeg
    tools = ROOT / 'runtime/tools'
    tools.mkdir(exist_ok=True)
    if not (tools / 'ffmpeg.exe').exists():
        shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), tools / 'ffmpeg.exe')


def online():
    file = ROOT / 'runtime/dashboard-login.local.json'
    credentials = json.loads(file.read_text())
    with httpx.Client(base_url=service.URL, trust_env=False, timeout=90) as client:
        client.headers['Authorization'] = 'Bearer ' + checked(client.post('/api/v1/auth/login', json={
            'username': credentials['username'], 'password': credentials['initial_password']}))['token']
        if checked(client.get('/api/v1/auth/setup-status'))['setup_required']:
            password = 'Af!' + secrets.token_urlsafe(20)
            checked(client.post('/api/v1/auth/setup', json={'username': 'ai_friend', 'password': password, 'confirm_password': password}))
            credentials = {'username': 'ai_friend', 'initial_password': password}
            file.write_text(json.dumps(credentials), encoding='utf-8')
    import apply_profile
    apply_profile.main()
    with httpx.Client(base_url=service.URL, trust_env=False, timeout=90) as client:
        client.headers['Authorization'] = 'Bearer ' + checked(client.post('/api/v1/auth/login', json={
            'username': credentials['username'], 'password': credentials['initial_password']}))['token']
        voice = json.loads((ROOT / 'config/dafeiyu-voice.json').read_text(encoding='utf-8'))
        providers = checked(client.get('/api/v1/providers'))
        if isinstance(providers, dict):
            providers = providers.get('providers', [])
        if not any(provider['id'] == voice['id'] for provider in providers):
            checked(client.post('/api/v1/providers', json=voice))
        config = checked(client.get('/api/v1/config-profiles/default'))['config']
        config['provider_tts_settings'].update(enable=True, provider_id=voice['id'], dual_output=True, trigger_probability=1.0)
        checked(client.put('/api/v1/config-profiles/default', json=config))
        persona = checked(client.get('/api/v1/personas/by-id', params={'persona_id': 'qq-friend'}))
        if not persona.get('custom_error_message'):
            checked(client.put('/api/v1/personas/by-id', json={'persona_id': 'qq-friend', 'custom_error_message': '这次没有收到有效回复，请稍后重发；若持续失败，请在本机检查模型设置。'}))
    (ROOT / 'runtime/本机登录说明.txt').write_text('面板：' + service.URL + '\n账号：' + credentials['username'] +
        '\n密码：' + credentials['initial_password'] + '\n密钥请在本机模型提供商页面填写。\n', encoding='utf-8')
    print('新用户初始化完成。请从维护窗口查看本机登录信息，填写自己的 Key 并扫码接入 QQ。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--first-install', action='store_true')
    parser.add_argument('--upgrade', action='store_true')
    parser.add_argument('--configure-online', action='store_true')
    args = parser.parse_args()
    online() if args.configure_online else offline()
