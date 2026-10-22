"""Exercise the installed UI and native APIs; delete only this run's temporary preset."""
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:6185'
PLUGIN = 'astrbot_plugin_persona_studio'
BASE = '/api/v1/plugins/extensions/' + PLUGIN + '/'


def main():
    credentials = json.loads((ROOT / 'runtime/dashboard-login.local.json').read_text())
    output = ROOT / 'verification'
    output.mkdir(exist_ok=True)
    checks = {}
    errors = []
    with httpx.Client(base_url=URL, trust_env=False, timeout=40) as client:
        checks['anonymous_access_denied'] = client.get(BASE + 'state').status_code == 401
        auth = client.post('/api/v1/auth/login', json={
            'username': credentials['username'], 'password': credentials['initial_password']}).json()
        assert auth['status'] == 'ok'
        client.headers['Authorization'] = 'Bearer ' + auth['data']['token']
        initial = client.get(BASE + 'state').json()
        assert initial['bots'], 'No QQ robot configured'
        bot_id = initial['bots'][0]['bot_id']
        original = client.get(BASE + 'state', params={'bot_id': bot_id}).json()['current']
        existing = {p['id'] for p in initial['presets']}
        test_id = None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.set_default_timeout(20000)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(URL)
                page.locator('input[type=text]').fill(credentials['username'])
                page.locator('input[type=password]').fill(credentials['initial_password'])
                page.get_by_role('button', name='登录', exact=True).click()
                page.wait_for_url('**/#/data/statistics')
                page.goto(URL + '/#/plugin-view/' + PLUGIN + '/editor')
                frame = page.frame_locator('iframe')
                frame.locator('#save').wait_for(state='visible')
                frame.locator('#custom').click()
                frame.locator('#custom-name').fill('验收临时')
                frame.locator('#custom-bio').fill('临时验收简介')
                frame.locator('#custom-prompt').fill('这是临时验收预设，测试后删除。')
                frame.locator('#custom-next').click()
                assert frame.locator('#custom-review').is_visible()
                frame.locator('#custom-next').click()
                frame.locator('#custom-dialog').wait_for(state='hidden', timeout=40000)
                created = client.get(BASE + 'state').json()['presets']
                item = next(p for p in created if p['id'] not in existing)
                test_id = item['id']
                checks['browser_create_persists_native'] = item['name'] == '验收临时'
                page.reload()
                frame = page.frame_locator('iframe')
                frame.locator('#preset').select_option(test_id)
                checks['browser_reload_retains_preset'] = frame.locator('#preset').input_value() == test_id
                frame.locator('#edit-preset').click()
                assert frame.locator('#custom-name').input_value() == '验收临时'
                frame.locator('#custom-name').fill('验收改名')
                frame.locator('#custom-prompt').fill('修改后的临时验收内容。')
                frame.locator('#custom-next').click()
                frame.locator('#custom-next').click()
                frame.locator('#custom-dialog').wait_for(state='hidden', timeout=40000)
                item = next(p for p in client.get(BASE + 'state').json()['presets'] if p['id'] == test_id)
                checks['browser_edit_keeps_id'] = item['name'] == '验收改名' and item['prompt'] == '修改后的临时验收内容。'
                frame.locator('#preset-search').fill('验收改名')
                checks['browser_search_filters'] = frame.locator('#preset option').count() == 1
                frame.locator('#load-preset').click()
                checks['load_is_draft_only'] = client.get(BASE + 'state', params={'bot_id': bot_id}).json()['current'] == original
                # Capture only the generated test draft, never the user's original prompt.
                page.screenshot(path=str(output / 'persona-repair-desktop.png'), full_page=True)
                frame.locator('#reload').click()
                frame.locator('#confirm-yes').click()
                page.wait_for_timeout(400)
                # Save the original text/tool selection unchanged through the real UI.
                frame.locator('#save').click()
                frame.locator('#status').filter(has_text='已保存，后续新消息').wait_for()
                saved = client.get(BASE + 'state', params={'bot_id': bot_id}).json()['current']
                checks['browser_save_preserves_text_and_tools'] = all(saved[k] == original[k] for k in ('bio', 'prompt', 'tools', 'persona_id'))
                page.set_viewport_size({'width': 390, 'height': 844})
                frame.locator('#preset-search').fill('验收改名')
                frame.locator('#load-preset').click()
                page.screenshot(path=str(output / 'persona-repair-mobile.png'), full_page=True)
                checks['mobile_no_horizontal_overflow'] = frame.locator('body').evaluate(
                    '(body) => body.scrollWidth <= innerWidth + 1')
                frame.locator('#reload').click()
                frame.locator('#confirm-yes').click()
                frame.locator('#status').filter(has_text='已读取当前人设').wait_for()
                frame.locator('#preset-search').fill('验收改名')
                frame.locator('#delete-preset').click()
                frame.locator('#delete-confirm').click()
                frame.locator('#delete-dialog').wait_for(state='hidden', timeout=40000)
                checks['browser_delete_removes_preset'] = test_id not in {p['id'] for p in client.get(BASE + 'state').json()['presets']}
                checks['browser_no_script_errors'] = not errors
                browser.close()
            result = client.post(BASE + 'authorize-qq', json={'umo': 'unknown:GroupMessage:user'}).json()
            checks['reject_invalid_qq_authorization'] = result.get('status') == 'error'
            sync = client.post(BASE + 'qq-menu', json={'bot_id': bot_id}).json()
            checks['official_qq_menu_confirmed'] = sync.get('status') == 'ok'
            checks['enabled_chat_model_loaded'] = client.get(BASE + 'state', params={'bot_id': bot_id}).json()['model_ready']
        finally:
            # Remove only the fixture created above; keep all original personas/config.
            if test_id:
                endpoint = '/api/v1/plugins/' + PLUGIN + '/config'
                cfg = client.get(endpoint).json()['data']['config']
                ref = next((r for r in cfg.get('custom_presets', []) if r['id'] == test_id), None)
                cfg['custom_presets'] = [r for r in cfg.get('custom_presets', []) if r['id'] != test_id]
                cfg['hidden_presets'] = [i for i in cfg.get('hidden_presets', []) if i != test_id]
                result = client.put(endpoint, json={'config': cfg}).json()
                assert result['status'] == 'ok'
                if ref:
                    result = client.delete('/api/v1/personas/by-id', params={'persona_id': ref['persona_id']}).json()
                    assert result['status'] == 'ok'
                client.post('/api/v1/plugins/' + PLUGIN + '/reload', json={}).raise_for_status()
                client.post(BASE + 'qq-menu', json={'bot_id': bot_id}).raise_for_status()
            final = client.get(BASE + 'state').json()
            checks['original_library_retained'] = {p['id'] for p in final['presets']} == existing
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
              'script_errors': errors, 'phone_qq_receipt_verified': False,
              'note': 'QQ API acknowledgement is not a phone-client acceptance test.'}
    (output / 'persona-repair-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert checks and all(checks.values()), 'A persona acceptance check failed'


if __name__ == '__main__':
    main()
