"""Verify native navigation with isolated disabled bots and an unused model source."""
from copy import deepcopy
import json
from pathlib import Path
import time
import uuid
import httpx
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:6185'
BASE='/api/v1/plugins/extensions/astrbot_plugin_persona_studio/'

def main():
 output=ROOT/'verification/native-navigation';output.mkdir(exist_ok=True)
 credentials=json.loads((ROOT/'runtime/dashboard-login.local.json').read_text(encoding='utf-8'))
 checks={};errors=[];created=[];profiles=[];personas=[];source_id='native-check-'+uuid.uuid4().hex[:8];source_created=False
 with httpx.Client(base_url=URL,trust_env=False,timeout=45) as client:
  def api(method,path,**kwargs):
   response=client.request(method,path,**kwargs);response.raise_for_status();result=response.json()
   if result.get('status')=='error':raise RuntimeError('Native API operation failed')
   return result.get('data',result)
  auth=api('POST','/api/v1/auth/login',json={'username':credentials['username'],'password':credentials['initial_password']});client.headers['Authorization']='Bearer '+auth['token']
  original=api('GET','/api/v1/bots')['bots'];original_sources=api('GET','/api/v1/provider-sources')['provider_sources']
  identities=api('GET',BASE+'bot-identities')['bots']
  checks['qq_identities_have_stable_ids']=all(b['appid'] and b['name_source']=='qq' and b['avatar_source']=='qq' for b in identities)
  expected={b['appid']:b['name'] for b in identities}
  checks['identity_sources_match_qq']=all(b['name_source']=='qq' and b['appid'] for b in identities)
  def wait_saved(path,predicate,params=None):
   for _ in range(40):
    value=api('GET',path,params=params)
    if predicate(value):return value
    time.sleep(.2)
   raise AssertionError('Saved native config did not become observable')
  try:
   for index in range(2):
    bid=source_id+'-bot-'+str(index)
    api('POST','/api/v1/bots',json={'config':{'id':bid,'type':'qq_official','enable':False,'appid':str(980000000+index),'secret':'temporary-test-secret','enable_group_c2c':True,'enable_guild_direct_message':False,'use_markdown':True}});created.append(bid)
    state=api('GET',BASE+'state',params={'bot_id':bid});profiles.append(state['binding']['config_id']);personas.append(state['current']['persona_id'])
   sample=deepcopy(original_sources[0]);sample.update(id=source_id,key=['temporary-test-key'],api_base='https://example.invalid/v1',enable=False)
   api('POST','/api/v1/provider-sources',json={'config':sample});source_created=True
   with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(20000);page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(URL);page.locator('input[type=text]').fill(credentials['username']);page.locator('input[type=password]').fill(credentials['initial_password']);page.get_by_role('button',name='登录',exact=True).click();page.locator('#friend-home-bot').wait_for()
    page.locator('.friend-core-nav a[href="#/platforms"]').click();page.get_by_text('接入设置',exact=True).wait_for();expect(page.locator('iframe')).to_have_count(0);checks['qq_sidebar_opens_native_editor']=True
    for bot in identities:
     row=page.locator('.bot-list-item[data-friend-bot-id="'+bot['bot_id']+'"]');expect(row.locator('.bot-list-item__title')).to_have_text(bot['name']);row.locator('.bot-list-item__main').click();expect(page.locator('.bot-editor__title')).to_have_text(bot['name']);page.get_by_text('接入设置',exact=True).wait_for()
     fields=page.locator('.bot-editor__section').first.locator('input[type=text]');expect(fields.nth(0)).to_have_value(bot['bot_id']);expect(fields.nth(1)).to_have_value(bot['appid']);expect(page.locator('.friend-native-identity')).to_contain_text(bot['appid']);checks[bot['appid']+'_native_fields_match_identity']=True
     assert row.locator('img').get_attribute('src')==bot['avatar'];checks[bot['appid']+'_avatar_matches']=True
    page.reload();expect(page.locator('.bot-editor__title')).to_have_text(identities[-1]['name']);checks['qq_refresh_restores_selected_bot']=True
    page.screenshot(path=str(output/'qq-desktop.png'))
    # Change a real native checkbox on a stopped temporary adapter.
    page.goto(URL+'/#/platforms?bot_id='+created[0]);page.get_by_text('接入设置',exact=True).wait_for();expect(page.locator('.bot-editor')).to_have_attribute('data-friend-bot-id',created[0]);box=page.locator('.bot-editor__section').first.locator('input[type=checkbox]').nth(3);box.uncheck();page.get_by_role('button',name='保存更改',exact=True).click()
    wait_saved('/api/v1/bots/by-id',lambda x:x['bot']['use_markdown'] is False,{'bot_id':created[0]});checks['native_qq_save_persists_correct_bot']=True
    other=api('GET','/api/v1/bots/by-id',params={'bot_id':created[1]})['bot'];checks['native_qq_save_keeps_other_bot']=other['use_markdown'] is True and other['secret']=='temporary-test-secret'
    page.reload();page.get_by_text('接入设置',exact=True).wait_for();expect(page.locator('.bot-editor__section').first.locator('input[type=checkbox]').nth(3)).not_to_be_checked();checks['native_qq_save_survives_refresh']=True
    # Local display metadata uses the identity endpoint and does not rename the native instance.
    details=page.locator('.friend-native-profile');details.evaluate('(el)=>el.open=true');details.locator('.friend-web-only').evaluate('(el)=>el.open=true');details.locator('[data-local-name]').fill('本机验收备注');details.locator('[data-save]').click();expect(details.locator('[data-result]')).to_contain_text('仅网页显示');expect(page.locator('.bot-editor__title')).to_have_text('本机验收备注');checks['local_display_metadata_separate_from_native_id']=api('GET','/api/v1/bots/by-id',params={'bot_id':created[0]})['bot']['id']==created[0]
    api('POST',BASE+'control-identity',json={'bot_id':created[0],'appid':'980000000','local_name':'','local_avatar':''})
    # Native model source UI, including all categories and existing controls.
    page.locator('.friend-core-nav a[href="#/providers"]').click();page.get_by_text('API Base URL',exact=True).wait_for();expect(page.locator('iframe')).to_have_count(0);checks['model_sidebar_opens_native_editor']=True
    for label in ['对话','语音转文字','文字转语音','嵌入','重排序']:expect(page.get_by_text(label,exact=True).first).to_be_visible()
    checks['all_model_categories_present']=True
    for label in ['API Key','API Base URL','获取模型列表','自定义模型']:expect(page.get_by_text(label,exact=True).first).to_be_visible()
    checks['full_model_source_controls_present']=True
    row=page.locator('.provider-source-item').filter(has=page.locator('.provider-source-item__title',has_text=source_id));row.click();expect(page.locator('.page-content input[type=text]').nth(1)).to_have_value(source_id);page.locator('.page-content input[type=number]').first.fill('27');page.locator('.page-content input[type=number]').first.press('Tab');page.get_by_role('button',name='保存配置',exact=True).click()
    saved=wait_saved('/api/v1/provider-sources/by-id',lambda x:(x.get('provider_source',x.get('source',x))).get('timeout')==27,{'source_id':source_id});checks['native_provider_save_persists']=True
    page.reload();page.get_by_text('API Base URL',exact=True).wait_for();expect(page.locator('.page-content input[type=number]').first).to_have_value('27');checks['provider_refresh_restores_source_and_config']=True
    page.get_by_role('button',name='自定义模型',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible();page.keyboard.press('Escape');checks['custom_model_dialog_opens']=True
    page.locator('.friend-core-nav a').filter(has_text='Agent 连接').click();expect(page.frame_locator('iframe').locator('h1')).to_have_text('Agent 连接');checks['agent_sidebar_remains_independent']=True
    browser.close()
  finally:
   if source_created:api('DELETE','/api/v1/provider-sources/by-id',params={'source_id':source_id})
   for bid in created:api('DELETE','/api/v1/bots/by-id',params={'bot_id':bid})
   for bid in created:api('DELETE','/api/v1/config-routes/'+bid+'::')
   for cid in profiles:api('DELETE','/api/v1/config-profiles/'+cid)
   for pid in personas:api('DELETE','/api/v1/personas/by-id',params={'persona_id':pid})
   checks['existing_bot_configs_and_secrets_unchanged']=api('GET','/api/v1/bots')['bots']==original
   checks['existing_model_sources_and_keys_unchanged']=api('GET','/api/v1/provider-sources')['provider_sources']==original_sources
  checks['no_browser_script_errors']=not errors
  report={'checks':checks,'live_qq_message_sent':False,'model_called':False,'browser_error_count':len(errors),'identity_mapping':expected}
  (output/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=True,indent=2));assert all(checks.values())
if __name__=='__main__':main()
