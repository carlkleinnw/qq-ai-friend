"""Bind the user's scanned QQ bots through existing profile/persona/plugin APIs."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import httpx
from apply_profile import checked
from service import URL

ROOT = Path(__file__).resolve().parents[1]
PERSONA_PLUGIN = '/api/v1/plugins/astrbot_plugin_persona_studio/config'
COMPANION = '/api/v1/plugins/astrbot_plugin_private_companion/config'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-umo')
    args = parser.parse_args()
    credentials = json.loads((ROOT / 'runtime/dashboard-login.local.json').read_text())
    with httpx.Client(base_url=URL, trust_env=False, timeout=90) as client:
        client.headers['Authorization'] = 'Bearer ' + checked(client.post('/api/v1/auth/login', json={
            'username': credentials['username'], 'password': credentials['initial_password']}))['token']
        editor = checked(client.get(PERSONA_PLUGIN))['config']
        if args.authorize_umo:
            parts = args.authorize_umo.strip().split(':')
            if len(parts) != 3 or parts[1] != 'FriendMessage' or not parts[2] or not any(b['bot_id'] == parts[0] for b in editor['bots']):
                raise ValueError('请填写已同步机器人的完整私聊 UMO，不接受群聊或未登记的机器人。')
            editor['qq_editor_sessions'] = list(dict.fromkeys([*editor.get('qq_editor_sessions', []), args.authorize_umo.strip()]))
            checked(client.put(PERSONA_PLUGIN, json={'config': editor}))
            print('该 QQ 私聊已获得人设编辑权限；未授予系统管理员权限。')
            return
        default = checked(client.get('/api/v1/config-profiles/default'))['config']
        bots = [p for p in default.get('platform', []) if p.get('enable', True) and p.get('type') in {'qq_official', 'qq_official_webhook'}]
        if not bots:
            raise ValueError('还没有已保存并启用的 QQ 机器人。请先在面板扫码创建并保存。')
        routes = checked(client.get('/api/v1/config-routes'))['routing']
        personas = {p['persona_id'] for p in checked(client.get('/api/v1/personas'))}
        companion = checked(client.get(COMPANION))['config']
        enabled_personas = list(companion['basic_config'].get('multi_persona_ids', []))
        targets = {b['bot_id']: b for b in editor.get('bots', [])}
        for index, bot in enumerate(bots):
            route = bot['id'] + '::'
            conf_id = routes.get(route)
            if conf_id:
                cfg = checked(client.get('/api/v1/config-profiles/' + conf_id))['config']
                pid = cfg['agent_runner']['config']['persona']['persona_id']
            else:
                pid = 'qq-friend' if index == 0 else 'bot-' + hashlib.sha256(bot['id'].encode()).hexdigest()[:12]
                if pid not in personas:
                    base = checked(client.get('/api/v1/personas/by-id', params={'persona_id': 'qq-friend'}))
                    checked(client.post('/api/v1/personas', json={'persona_id': pid, 'system_prompt': base['system_prompt'],
                        'tools': base['tools'], 'skills': base['skills'], 'custom_error_message': base['custom_error_message']}))
                    personas.add(pid)
                cfg = deepcopy(default)
                for key in ['platform', 'provider', 'provider_sources', 'dashboard']:
                    cfg.pop(key, None)
                cfg['agent_runner']['config']['persona']['persona_id'] = pid
                if index > 0:
                    cfg['provider_tts_settings']['enable'] = False
                conf_id = checked(client.post('/api/v1/config-profiles', json={'name': f'QQ好友 {index + 1}', 'config': cfg}))['conf_id']
                routes = {route: conf_id, **routes}
            enabled_personas.append(pid)
            targets.setdefault(bot['id'], {'bot_id': bot['id'], 'name': f'QQ好友 {index + 1}'})
        checked(client.put('/api/v1/config-routes', json={'routing': routes}))
        companion['basic_config'].update(plugin_specific_persona_id='qq-friend', enable_multi_persona_mode=True,
                                         multi_persona_ids=list(dict.fromkeys(enabled_personas)))
        checked(client.put(COMPANION, json={'config': companion}))
        extension = '/api/plug/astrbot_plugin_private_companion/page/persona'
        for pid in dict.fromkeys(enabled_personas):
            if pid == 'qq-friend':
                continue
            if not client.get(extension + '/config-state', params={'persona_id': pid}).json().get('success'):
                response = client.post(extension + '/config/create', json={'persona_id': pid, 'bot_name': pid, 'mode': 'copy', 'source_persona_id': 'qq-friend'})
                response.raise_for_status()
                if not response.json().get('success'):
                    raise RuntimeError('陪伴人格独立配置尚未建立，请在原生陪伴面板核对。')
        editor['bots'] = list(targets.values())
        checked(client.put(PERSONA_PLUGIN, json={'config': editor}))
        endpoint = '/api/v1/plugins/astrbot_plugin_reliability/config'
        guard = checked(client.get(endpoint))['config']
        guard['bot_ids'] = list(dict.fromkeys([*guard.get('bot_ids', []), *targets]))
        checked(client.put(endpoint, json={'config': guard}))
    print(f'已同步 {len(bots)} 个 QQ 机器人。请先发送 /sid，再在维护窗口授权自己的私聊，即可在 QQ 里选人设。')


if __name__ == '__main__':
    main()
