"""Verify local profile management and truthful QQ capabilities without platform writes."""
from io import BytesIO
import json
from pathlib import Path
import uuid
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:6185'
BASE='/api/v1/plugins/extensions/astrbot_plugin_persona_studio/'

def main():
 out=ROOT/'verification/qq-profile';out.mkdir(exist_ok=True);checks={};created=[];profiles=[];personas=[];errors=[]
 credentials=json.loads((ROOT/'runtime/dashboard-login.local.json').read_text(encoding='utf-8'))
 with httpx.Client(base_url=URL,trust_env=False,timeout=35) as client:
  def api(method,path,**kwargs):
   response=client.request(method,path,**kwargs);response.raise_for_status();result=response.json()
   if result.get('status')=='error':raise RuntimeError('Profile API operation failed')
   return result.get('data',result)
  auth=api('POST','/api/v1/auth/login',json={'username':credentials['username'],'password':credentials['initial_password']});client.headers['Authorization']='Bearer '+auth['token']
  before=api('GET','/api/v1/bots')['bots'];before_models=api('GET','/api/v1/provider-sources')['provider_sources']
  suffix=uuid.uuid4().hex[:8]
  try:
   for index in range(2):
    bid='profile-check-'+suffix+'-'+str(index);api('POST','/api/v1/bots',json={'config':{'id':bid,'type':'qq_official','enable':False,'appid':str(970000000+index),'secret':'temporary-profile-secret'}});created.append(bid)
    state=api('GET',BASE+'state',params={'bot_id':bid});profiles.append(state['binding']['config_id']);personas.append(state['current']['persona_id'])
   with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(URL);page.locator('input[type=text]').fill(credentials['username']);page.locator('input[type=password]').fill(credentials['initial_password']);page.get_by_role('button',name='登录',exact=True).click();page.locator('#friend-home-bot').wait_for()
    page.goto(URL+'/#/platforms?bot_id='+created[0]);panel=page.locator('.friend-native-profile');expect(panel).to_have_attribute('data-bot-id',created[0]);expect(panel.locator('[data-profile-id]')).to_contain_text('970000000')
    expect(panel.get_by_role('link',name='打开 QQ 开放平台管理')).to_have_attribute('href','https://q.qq.com/');expect(panel.get_by_role('link',name='在 QQ 官方页面创建或绑定机器人')).to_have_attribute('href','https://q.qq.com/qqbot/openclaw/login.html');checks['official_management_and_creation_entries']=True
    panel.locator('.friend-web-only > summary').click();panel.locator('[data-local-name]').fill('网页头像验收A')
    stream=BytesIO();Image.new('RGB',(40,40),'navy').save(stream,'PNG');payload={'name':'avatar.png','mimeType':'image/png','buffer':stream.getvalue()}
    panel.locator('[data-avatar-file]').set_input_files(payload);expect(panel.locator('[data-result]')).to_contain_text('尚未保存');checks['upload_previews_before_save']=panel.locator('[data-local-preview]').get_attribute('src').startswith('data:image/png')
    panel.locator('[data-save]').click();expect(panel.locator('[data-result]')).to_contain_text('已保存，仅网页显示');expect(page.locator('.bot-editor__title')).to_have_text('网页头像验收A');checks['local_save_truthfully_labeled']=True
    saved=next(b for b in api('GET',BASE+'bot-identities')['bots'] if b['bot_id']==created[0]);checks['saved_image_is_sanitized_png']=saved['local_avatar_data'].startswith('data:image/png;base64,') and saved['avatar_source']=='local';checks['appid_instance_and_credentials_unchanged']=api('GET','/api/v1/bots/by-id',params={'bot_id':created[0]})['bot']['secret']=='temporary-profile-secret'
    page.reload();panel=page.locator('.friend-native-profile');expect(panel.locator('[data-local-name]')).to_have_value('网页头像验收A');expect(page.locator('.bot-editor__title')).to_have_text('网页头像验收A');checks['profile_and_uploaded_avatar_survive_refresh']=page.locator('.bot-editor__icon').get_attribute('src')==saved['avatar']
    page.locator('.bot-list-item[data-friend-bot-id="'+created[1]+'"] .bot-list-item__main').click();panel=page.locator('.friend-native-profile');expect(panel).to_have_attribute('data-bot-id',created[1]);expect(panel.locator('[data-local-name]')).to_have_value('');checks['switch_to_other_robot_has_no_profile_leak']=True
    page.locator('.bot-list-item[data-friend-bot-id="'+created[0]+'"] .bot-list-item__main').click();panel=page.locator('.friend-native-profile');expect(panel).to_have_attribute('data-bot-id',created[0]);panel.locator('.friend-web-only > summary').click();expect(panel.locator('[data-local-name]')).to_have_value('网页头像验收A')
    panel.locator('[data-local-name]').fill('保留失败草稿');page.route('**/astrbot_plugin_persona_studio/control-identity',lambda route:route.fulfill(status=500,json={'status':'error','message':'模拟保存失败'}));panel.locator('[data-save]').click();expect(panel.locator('[data-result]')).to_contain_text('保存失败，草稿已保留');expect(panel.locator('[data-local-name]')).to_have_value('保留失败草稿');checks['failed_save_keeps_draft_and_reports_failure']=True;page.unroute('**/astrbot_plugin_persona_studio/control-identity')
    page.once('dialog',lambda dialog:dialog.accept());page.reload();panel=page.locator('.friend-native-profile');expect(panel.locator('[data-local-name]')).to_have_value('网页头像验收A')
    panel.locator('[data-sync]').click();expect(panel.locator('[data-result]')).to_contain_text('资料读取失败');expect(page.locator('.bot-editor__title')).to_have_text('网页头像验收A');checks['unavailable_qq_read_is_not_reported_as_sync_success']=True
    panel.locator('.friend-web-only > summary').click();panel.locator('[data-remove-avatar]').click();panel.locator('[data-save]').click();expect(panel.locator('[data-result]')).to_contain_text('已保存，仅网页显示');now=next(b for b in api('GET',BASE+'bot-identities')['bots'] if b['bot_id']==created[0]);checks['explicit_avatar_removal_is_saved']=not now['local_avatar_data']
    # Clear only the temporary local-display record before native test cleanup.
    api('POST',BASE+'control-identity',json={'bot_id':created[0],'appid':'970000000','local_name':'','local_avatar':'','clear_avatar':True,'web_override':False})
    page.goto(URL+'/#/platforms?bot_id='+before[0]['id']);panel=page.locator('.friend-native-profile');expect(panel).to_have_attribute('data-bot-id',before[0]['id']);panel.locator('[data-sync]').click();expect(panel.locator('[data-result]')).to_contain_text('已从 QQ 读取当前公开资料');checks['real_qq_profile_get_readonly_succeeds']=True
    page.screenshot(path=str(out/'profile-desktop.png'));page.set_viewport_size({'width':390,'height':844});expect(page.locator('.v-main')).to_have_css('padding-left','0px');checks['mobile_no_horizontal_overflow']=page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(out/'profile-mobile.png'));browser.close()
  finally:
   for bid in created:api('DELETE','/api/v1/bots/by-id',params={'bot_id':bid})
   for bid in created:api('DELETE','/api/v1/config-routes/'+bid+'::')
   for cid in profiles:api('DELETE','/api/v1/config-profiles/'+cid)
   for pid in personas:api('DELETE','/api/v1/personas/by-id',params={'persona_id':pid})
   checks['existing_qq_connections_and_keys_unchanged']=api('GET','/api/v1/bots')['bots']==before
   checks['existing_model_configs_and_keys_unchanged']=api('GET','/api/v1/provider-sources')['provider_sources']==before_models
  checks['no_browser_script_errors']=not errors
  report={'checks':checks,'real_qq_profile_read':True,'qq_platform_profile_write':False,'qq_platform_create_or_delete_tested':False,'qq_messages_sent':False}
  (out/'checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));assert all(checks.values())
if __name__=='__main__':main()
