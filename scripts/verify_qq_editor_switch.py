"""Verify the installed switch without sending QQ messages or changing personas."""
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:6185'
PLUGIN = 'astrbot_plugin_persona_studio'
BASE = '/api/v1/plugins/extensions/' + PLUGIN + '/'


def main():
    credentials = json.loads((ROOT / 'runtime/dashboard-login.local.json').read_text(encoding='utf-8'))
    output = ROOT / 'verification/qq-editor-switch'
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = {}, []
    with httpx.Client(base_url=URL, trust_env=False, timeout=40) as client:
        checks['anonymous_switch_denied'] = client.post(BASE + 'authorize-qq', json={
            'bot_id': 'unknown', 'enabled': True}).status_code == 401
        auth = client.post('/api/v1/auth/login', json={
            'username': credentials['username'], 'password': credentials['initial_password']}).json()
        assert auth['status'] == 'ok', 'Local login failed'
        client.headers['Authorization'] = 'Bearer ' + auth['data']['token']
        bots = client.get(BASE + 'state').json()['bots']
        assert bots, 'No registered robots'
        before = {b['bot_id']: client.get(BASE + 'state', params={'bot_id': b['bot_id']}).json() for b in bots}
        bot_id = bots[0]['bot_id']

        def access(enabled):
            response = client.post(BASE + 'authorize-qq', json={'bot_id': bot_id, 'enabled': enabled})
            assert response.status_code == 200
            assert response.json()['enabled'] is enabled

        try:
            access(False)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='msedge', headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1050})
                page.set_default_timeout(20000)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(URL)
                page.locator('input[type=text]').fill(credentials['username'])
                page.locator('input[type=password]').fill(credentials['initial_password'])
                page.get_by_role('button', name='登录', exact=True).click()
                page.wait_for_url('**/#/data/statistics')
                page.goto(URL + '/#/plugin-view/' + PLUGIN + '/editor')
                frame = page.frame_locator('iframe')
                toggle = frame.get_by_role('switch', name='允许 QQ 编辑人设')
                expect(toggle).to_be_enabled()
                expect(toggle).not_to_be_checked()
                checks['no_umo_input'] = frame.locator('#qq-umo').count() == 0
                toggle.check()
                expect(frame.locator('#qq-access-state')).to_contain_text('已开启')
                expect(toggle).to_be_enabled()
                checks['click_saves_enabled'] = client.get(BASE + 'state', params={'bot_id': bot_id}).json()['qq_editor_enabled'] is True
                page.reload()
                expect(toggle).to_be_enabled()
                expect(toggle).to_be_checked()
                checks['enabled_survives_page_reload'] = True
                if len(bots) > 1:
                    other = bots[1]['bot_id']
                    frame.locator('#bot').select_option(other)
                    expect(toggle).to_be_enabled()
                    expect(toggle).to_be_checked(checked=before[other]['qq_editor_enabled'])
                    frame.locator('#bot').select_option(bot_id)
                    expect(toggle).to_be_enabled()
                    expect(toggle).to_be_checked()
                    checks['robot_switches_independent'] = True
                toggle.uncheck()
                expect(frame.locator('#qq-access-state')).to_contain_text('已关闭')
                expect(toggle).to_be_enabled()
                page.reload()
                expect(toggle).to_be_enabled()
                expect(toggle).not_to_be_checked()
                checks['disabled_survives_page_reload'] = True
                toggle.check()
                expect(frame.locator('#qq-access-state')).to_contain_text('已开启')
                expect(toggle).to_be_enabled()

                # The parent dashboard performs the authenticated bridge request.
                pattern = '**' + BASE + 'authorize-qq'
                page.route(pattern, lambda route: route.fulfill(status=500, content_type='application/json', body=json.dumps({
                    'status': 'error', 'message': '模拟保存失败'})), times=1)
                toggle.uncheck()
                expect(frame.locator('#status')).to_contain_text('开关保存未确认')
                expect(toggle).to_be_enabled()
                expect(toggle).to_be_checked()
                checks['failed_save_restores_server_state'] = True

                original_prompt = frame.locator('#prompt').input_value()
                frame.locator('#prompt').fill(original_prompt + '\n临时未保存草稿')
                access(False)
                expect(frame.locator('#qq-access-state')).to_contain_text('已关闭', timeout=12000)
                checks['polling_updates_access_without_losing_draft'] = frame.locator('#prompt').input_value().endswith('临时未保存草稿')
                frame.locator('#prompt').fill(original_prompt)
                for width, height, name in [(1440, 1050, 'desktop'), (390, 844, 'mobile')]:
                    page.set_viewport_size({'width': width, 'height': height})
                    toggle.scroll_into_view_if_needed()
                    checks[name + '_no_horizontal_overflow'] = frame.locator('html').evaluate(
                        '(el) => el.scrollWidth <= el.clientWidth + 1')
                    page.screenshot(path=str(output / (name + '.png')))
                checks['browser_no_script_errors'] = not errors
                browser.close()
        finally:
            for bid, original in before.items():
                result = client.post(BASE + 'authorize-qq', json={'bot_id': bid, 'enabled': original['qq_editor_enabled']})
                assert result.status_code == 200, 'Could not restore original switch'
            after = {b['bot_id']: client.get(BASE + 'state', params={'bot_id': b['bot_id']}).json() for b in bots}
            checks['personas_and_tools_unchanged'] = all(after[bid]['current'] == original['current'] for bid, original in before.items())
            checks['library_unchanged'] = all(after[bid]['presets'] == original['presets'] for bid, original in before.items())
            checks['switches_restored_after_test'] = all(after[bid]['qq_editor_enabled'] == original['qq_editor_enabled'] for bid, original in before.items())
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
              'script_error_count': len(errors), 'phone_qq_receipt_verified': False}
    (output / 'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert checks and all(checks.values()), 'Switch verification failed'


if __name__ == '__main__':
    main()
