"""Read-only desktop/mobile checks of the final native configuration pages."""
import json
import httpx
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:6185'

def main():
 credentials=json.loads((ROOT/'runtime/dashboard-login.local.json').read_text(encoding='utf-8'));out=ROOT/'verification/native-navigation';checks={};errors=[]
 with httpx.Client(base_url=URL,trust_env=False,timeout=20) as c:
  auth=c.post('/api/v1/auth/login',json={'username':credentials['username'],'password':credentials['initial_password']}).json()['data'];c.headers['Authorization']='Bearer '+auth['token']
  bots=c.get('/api/v1/plugins/extensions/astrbot_plugin_persona_studio/bot-identities').json()['bots'];assert len(bots)>=2,'Requires two connected test robots'
  first,last=bots[0],bots[-1]
 out.mkdir(parents=True,exist_ok=True)
 with sync_playwright() as pw:
  browser=pw.chromium.launch(channel='msedge',headless=True);desktop=browser.new_context(viewport={'width':1440,'height':1000});page=desktop.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(URL);page.locator('input[type=text]').fill(credentials['username']);page.locator('input[type=password]').fill(credentials['initial_password']);page.get_by_role('button',name='登录',exact=True).click();page.locator('#friend-home-bot').wait_for()
  page.locator('.friend-core-nav a[href="#/platforms"]').click();page.get_by_text('接入设置',exact=True).wait_for();expect(page.locator('.bot-list-item__title')).to_have_count(len(bots));expect(page.locator('.bot-editor [aria-label="接入实例 ID"]')).to_have_attribute('readonly','');checks['native_instance_id_cannot_be_mistaken_for_qq_name']=True
  page.locator('.bot-list-item[data-friend-bot-id="'+first['bot_id']+'"] .bot-list-item__main').click();expect(page.locator('.bot-editor__title')).to_have_text(first['name']);page.get_by_text('接入设置',exact=True).wait_for();page.screenshot(path=str(out/'qq-desktop.png'))
  page.locator('.friend-core-nav a[href="#/providers"]').click();page.get_by_text('API Base URL',exact=True).wait_for();page.screenshot(path=str(out/'model-desktop.png'));checks['native_provider_auto_opens_details']=True
  mobile=browser.new_context(viewport={'width':390,'height':844},storage_state=desktop.storage_state());phone=mobile.new_page();phone.set_default_timeout(15000);phone.on('pageerror',lambda e:errors.append(str(e)))
  phone.goto(URL+'/#/platforms?bot_id='+first['bot_id']);expect(phone.locator('.bot-editor__title')).to_have_text(first['name']);phone.get_by_text('接入设置',exact=True).wait_for();expect(phone.locator('.bot-mobile-selection')).to_contain_text(first['name']);checks['mobile_direct_link_restores_real_bot']=True
  phone.reload();expect(phone.locator('.bot-editor__title')).to_have_text(first['name']);checks['mobile_refresh_keeps_real_bot']=True
  phone.locator('.bot-list-panel__mobile-controls .v-field').click();option=phone.locator('.v-overlay--active .v-list-item').filter(has=phone.get_by_text(last['name'],exact=True));option.click();expect(phone.locator('.bot-editor__title')).to_have_text(last['name']);phone.get_by_text('接入设置',exact=True).wait_for();checks['mobile_picker_uses_real_names_and_configs']=True
  checks['qq_mobile_no_overflow']=phone.evaluate('document.documentElement.scrollWidth<=innerWidth+1');phone.screenshot(path=str(out/'qq-mobile.png'))
  phone.goto(URL+'/#/providers');phone.get_by_text('API Base URL',exact=True).wait_for();checks['mobile_model_auto_opens_full_details']=True;checks['model_mobile_no_overflow']=phone.evaluate('document.documentElement.scrollWidth<=innerWidth+1');phone.screenshot(path=str(out/'model-mobile.png'))
  phone.goto(URL+'/#/plugin-view/astrbot_plugin_persona_studio/model');phone.get_by_text('API Base URL',exact=True).wait_for();checks['legacy_model_link_redirects_to_native']=phone.locator('iframe').count()==0
  checks['no_browser_errors']=not errors;browser.close()
 (out/'final-readonly.json').write_text(json.dumps(checks,indent=2),encoding='utf-8');print(json.dumps(checks));assert all(checks.values())
if __name__=='__main__':main()
