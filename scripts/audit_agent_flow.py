"""Native configuration and Agent UI round trip using two disabled test bots."""
import json,sys,uuid,subprocess,os
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
BASE='/api/v1/plugins/extensions/astrbot_plugin_persona_studio/'

def main():
    cred=json.loads((ROOT/'runtime/dashboard-login.local.json').read_text('utf-8-sig'))
    created=[];profiles=[];personas=[];checks={};tag='agent-audit-'+uuid.uuid4().hex[:8]
    with httpx.Client(base_url='http://127.0.0.1:6185',trust_env=False,timeout=35) as c:
        def api(method,path,**kw):
            r=c.request(method,path,**kw);r.raise_for_status();d=r.json()
            if d.get('status')=='error':raise RuntimeError('Agent audit operation failed: '+path)
            return d.get('data',d)
        a=api('POST','/api/v1/auth/login',json={'username':cred['username'],'password':cred['initial_password']});c.headers['Authorization']='Bearer '+a['token']
        before_bots=api('GET','/api/v1/bots')['bots'];before_models=api('GET','/api/v1/provider-sources')['provider_sources']
        try:
            for i in range(2):
                bid=tag+'-'+str(i)
                api('POST','/api/v1/bots',json={'config':{'id':bid,'type':'qq_official','enable':False,'appid':str(960000000+i),'secret':''}});created.append(bid)
                state=api('GET',BASE+'state',params={'bot_id':bid});profiles.append(state['binding']['config_id']);personas.append(state['current']['persona_id'])
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='msedge',headless=True);page=browser.new_page();page.set_default_timeout(15000)
                page.goto('http://127.0.0.1:6185');page.locator('input[type=text]').fill(cred['username']);page.locator('input[type=password]').fill(cred['initial_password']);page.get_by_role('button',name='登录',exact=True).click();page.locator('#friend-home-bot').wait_for()
                page.goto('http://127.0.0.1:6185/#/plugin-view/astrbot_plugin_persona_studio/agent?bot_id='+created[0]);f=page.frame_locator('iframe');expect(f.locator('#save')).to_be_enabled()
                f.locator('#runner').select_option('dify');f.locator('[data-field=dify_api_base]').fill('https://example.invalid/v1');f.locator('[data-field=dify_api_key]').fill('audit-only-secret');f.locator('[data-field=variables]').fill('{"audit":"isolated"}');f.locator('#save').click();expect(f.locator('#status')).to_contain_text('已保存并加载')
                saved=api('GET',BASE+'control-state',params={'bot_id':created[0]});checks['agent_native_save']=saved['runner_type']=='dify' and saved['agent_fields']['variables']=={'audit':'isolated'}
                checks['saved_secret_not_returned']='audit-only-secret' not in json.dumps(saved)
                page.reload();f=page.frame_locator('iframe');expect(f.locator('#runner')).to_have_value('dify');expect(f.locator('[data-field=variables]')).to_have_value('{\n  "audit": "isolated"\n}');checks['refresh_keeps_agent_fields']=True
                f.locator('#runner').select_option('coze');f.locator('#runner').select_option('dify');expect(f.locator('[data-field=variables]')).to_have_value('{\n  "audit": "isolated"\n}');checks['switch_back_restores_fields']=True
                f.locator('#runner').select_option('local');f.locator('#save').click();expect(f.locator('#status')).to_contain_text('已保存并加载')
                state=api('GET',BASE+'control-state',params={'bot_id':created[0]});checks['local_runner_restores_native_persona']=state['persona_id']==personas[0]
                checks['other_bot_keeps_local_runner']=api('GET',BASE+'control-state',params={'bot_id':created[1]})['runner_type']=='local'
                browser.close()
        finally:
            for bid in created:api('DELETE','/api/v1/bots/by-id',params={'bot_id':bid})
            for bid in created:api('DELETE','/api/v1/config-routes/'+bid+'::')
            for cid in profiles:api('DELETE','/api/v1/config-profiles/'+cid)
            for pid in personas:api('DELETE','/api/v1/personas/by-id',params={'persona_id':pid})
            cleanup="""import asyncio,hashlib,sys
from astrbot.core import sp
async def main():
 for bid in sys.argv[1:]:
  assert bid.startswith('agent-audit-')
  await sp.global_remove('ai_friend.agent_profiles.'+hashlib.sha256((bid+'::').encode()).hexdigest())
 await sp.close()
asyncio.run(main())
"""
            env=os.environ.copy();env['ASTRBOT_ROOT']=str(ROOT/'runtime/app')
            subprocess.run([sys.executable,'-c',cleanup,*created],cwd=ROOT/'runtime/app',env=env,check=True,stdout=subprocess.DEVNULL,timeout=30)
            checks['existing_connections_and_model_keys_preserved']=api('GET','/api/v1/bots')['bots']==before_bots and api('GET','/api/v1/provider-sources')['provider_sources']==before_models
        out=ROOT/'verification/plugin-memory-audit';(out/'agent-flow.json').write_text(json.dumps(checks,indent=2),encoding='utf-8');print(json.dumps(checks));assert all(checks.values())

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
