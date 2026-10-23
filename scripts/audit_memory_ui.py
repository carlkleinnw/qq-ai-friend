"""Exercise the existing memory UI against an isolated real engine, never real memories."""
import io,json,sys,uuid,zipfile
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect

from service import URL
ROOT=Path(__file__).resolve().parents[1]
CODE='''import asyncio
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from astrbot.api.star import Star,StarTools
from astrbot.api.web import json_response

class MemoryUIAudit(Star):
    def __init__(self,context):
        super().__init__(context)
        real=context.get_registered_star('astrbot_plugin_memory_companion').star_cls
        cfg=deepcopy(dict(real.service.config.raw)) if hasattr(real.service.config,'raw') else {}
        cfg.update(retrieval={'mode':'basic','embedding_enabled':False},memory_summary={'enabled':False})
        self.service=type(real.service)(context=None,config=cfg,plugin_root=real.service.plugin_root,data_dir=StarTools.get_data_dir('__NAME__'))
        self.memory_companion=type(real.memory_companion)(self.service)
        self.page_api=type(real.page_api)(self)
        self.first_stats=True
        for path,handler,methods,desc in self.page_api._route_specs():
            if path=='/stats':handler=self.slow_stats
            context.register_web_api('/__NAME__/page'+path,handler,methods,desc)
        context.register_web_api('/__NAME__/verify',self.verify,['GET'],'Isolated memory verification')
        self.rows=[]
    async def slow_stats(self):
        if self.first_stats:
            self.first_stats=False
            await asyncio.sleep(1.5)
        return await self.page_api.stats()
    async def initialize(self):
        for i,bot in enumerate(['audit-bot-a','audit-bot-b','audit-bot-c']):
            ev=SimpleNamespace(unified_msg_origin=bot+':FriendMessage:audit-ui-only',get_self_id=lambda b=bot:b,get_platform_name=lambda:'qq_official',get_sender_id=lambda:'audit-ui-only',get_group_id=lambda:'',get_message_str=lambda:'审计档案')
            saved=await self.service.tool_remember(ev,'审计档案 唯一UI口令'+str(i),note_type='profile')
            self.rows.append((ev,saved['memory_id']))
    async def verify(self):
        found=[]
        for ev,mid in self.rows:
            ctx=await self.service.identity.resolve_event_context(ev)
            results,_,_=await self.service.search_context_slots('审计档案',ctx,top_k=10)
            found.append({'id':mid,'records':[{'id':r.memory.id,'content':r.memory.content,'session_id':r.memory.session_id} for r in results]})
        return json_response({'rows':found})
    async def terminate(self):
        await self.service.aclose()
'''

def main():
    name='astrbot_plugin_audit_memory_'+uuid.uuid4().hex[:8]
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr(name+'/main.py',CODE.replace('__NAME__',name))
        z.writestr(name+'/metadata.yaml',f'name: {name}\nauthor: local-audit\ndesc: Isolated memory UI check\nversion: 0.0.1\n')
    cred=json.loads((ROOT/'runtime/dashboard-login.local.json').read_text('utf-8-sig'))
    checks={};out=ROOT/'verification/plugin-memory-audit'
    with httpx.Client(base_url=URL,trust_env=False,timeout=35) as c:
        def api(method,path,**kw):
            r=c.request(method,path,**kw);r.raise_for_status();d=r.json()
            if d.get('status')=='error':raise RuntimeError('Memory UI audit API failed: '+path)
            return d.get('data',d)
        auth=api('POST','/api/v1/auth/login',json={'username':cred['username'],'password':cred['initial_password']});c.headers['Authorization']='Bearer '+auth['token']
        base='/api/v1/plugins/extensions/'+name
        original='/api/v1/plugins/extensions/astrbot_plugin_memory_companion/page'
        original_stats=api('GET',original+'/stats')['stats']
        try:
            api('POST','/api/v1/plugins/install/upload',files={'file':(name+'.zip',archive.getvalue(),'application/zip')})
            initial=api('GET',base+'/verify')['rows'];assert len(initial)==3
            mid=initial[0]['id']
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel='msedge',headless=True);page=browser.new_page();page.set_default_timeout(15000)
                def isolated_route(route):
                    response=route.fetch(url=route.request.url.replace(original,base+'/page'))
                    route.fulfill(response=response)
                page.route('**/api/v1/plugins/extensions/astrbot_plugin_memory_companion/page/**',isolated_route)
                page.goto(URL);page.locator('input[type=text]').fill(cred['username']);page.locator('input[type=password]').fill(cred['initial_password']);page.get_by_role('button',name='登录',exact=True).click();page.locator('#friend-home-bot').wait_for()
                page.goto(URL+'/#/plugin-view/astrbot_plugin_memory_companion/记忆面板')
                frame=page.frame_locator('iframe');frame.locator('#globalSearch').fill('审计档案');frame.locator('#globalSearch').press('Enter')
                expect(frame.locator('#railStatus')).to_have_class('rail-status is-ok')
                expect(frame.locator('#viewTitle')).to_have_text('记忆检视');checks['early_search_survives_slow_initialization']=True
                frame.locator('[data-memory="'+mid+'"]').first.click();expect(frame.locator('#editContent')).to_have_value('审计档案 唯一UI口令0')
                checks['existing_memory_panel_opens_correct_scoped_record']=True
                expect(frame.locator('#editVisibility')).to_have_value('private_pair');expect(frame.locator('#editLifecycle')).to_have_value('stable_memory')
                checks['editor_preserves_visibility_and_lifecycle']=True
                frame.locator('#editContent').fill('审计档案 UI已修改');frame.locator('#saveMemoryBtn').click();expect(frame.locator('#drawer')).to_have_attribute('aria-hidden','true')
                rows=api('GET',base+'/verify')['rows'];checks['ui_save_changes_actual_retrieval']=rows[0]['records'][0]['content']=='审计档案 UI已修改'
                checks['ui_save_preserves_other_bots']=rows[1:]==initial[1:]
                page.reload();frame=page.frame_locator('iframe');expect(frame.locator('#railStatus')).to_have_class('rail-status is-ok');frame.locator('body').evaluate('() => new Promise(resolve => { const t=setInterval(()=>{if(state.ready && busyCount===0){clearInterval(t);resolve(true)}},50) })');frame.locator('#globalSearch').fill('审计档案');frame.locator('#globalSearch').press('Enter');frame.locator('[data-memory="'+mid+'"]').first.click();expect(frame.locator('#editContent')).to_have_value('审计档案 UI已修改');checks['ui_refresh_keeps_saved_edit']=True
                frame.locator('#deleteMemoryBtn').click();frame.get_by_role('button',name='删除',exact=True).last.click();expect(frame.locator('#drawer')).to_have_attribute('aria-hidden','true')
                rows=api('GET',base+'/verify')['rows'];checks['ui_delete_removes_actual_retrieval']=not rows[0]['records'];checks['ui_delete_preserves_other_bots']=rows[1:]==initial[1:]
                browser.close()
        finally:
            if any(p['name']==name for p in api('GET','/api/v1/plugins')):
                api('DELETE','/api/v1/plugins/by-id',params={'plugin_id':name},json={'delete_data':True,'delete_config':True})
            stats=api('GET',original+'/stats')['stats']
            checks['production_memory_and_timeline_counts_unchanged']=all(stats[k]==original_stats[k] for k in ['total_memories','timeline_events'])
        (out/'memory-ui.json').write_text(json.dumps(checks,indent=2),encoding='utf-8');print(json.dumps(checks));assert all(checks.values())

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
