"""Install a harmless ZIP through the real dashboard, exercise it, then uninstall."""
import io
import json
import shutil
import sys
import uuid
import zipfile
import hashlib
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
FIXTURE='''from types import SimpleNamespace
from astrbot.api.star import Star
from astrbot.api.event import filter
from astrbot.api.web import json_response
from astrbot.core.star.star_handler import star_handlers_registry, EventType
from astrbot.core.star.star import star_map

class AuditProbe(Star):
    def __init__(self, context, config):
        super().__init__(context)
        self.config=config
        context.register_web_api('/__NAME__/probe',self.probe,['GET'],'Temporary local audit')

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def harmless_message_hook(self,event):
        if getattr(event,'audit_only',False):
            event.probe_result=self.config.get('marker','default')

    async def probe(self):
        rows=[]
        for platform in self.context.get_config().get('platform',[]):
            if platform.get('type')!='qq_official':continue
            bot=platform['id']
            cfg=self.context.get_config(bot+':FriendMessage:audit-only')
            plugins=cfg.get('plugin_set',['*'])
            handlers=star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent,plugins_name=plugins)
            requests=star_handlers_registry.get_handlers_by_event_type(EventType.OnLLMRequestEvent,plugins_name=plugins)
            rows.append({'bot':bot,'plugin_set':plugins,'message_plugins':sorted({star_map[h.handler_module_path].name for h in handlers}), 'request_plugins':sorted({star_map[h.handler_module_path].name for h in requests})})
        handlers=star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent,plugins_name=['__NAME__'])
        owned=[h for h in handlers if star_map[h.handler_module_path].name=='__NAME__']
        ev=SimpleNamespace(audit_only=True)
        for h in owned:
            await h.handler(ev)
        excluded=star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent,plugins_name=[])
        hello=[]
        for h in star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent,plugins_name=['helloworld']):
            if star_map[h.handler_module_path].name=='helloworld':
                synthetic=SimpleNamespace(get_sender_name=lambda:'audit-only',message_str='/helloworld',get_messages=lambda:[],plain_result=lambda text:text)
                async for result in h.handler(synthetic):
                    hello.append(result)
        return json_response({'marker':getattr(ev,'probe_result',None),'called':len(owned),'excluded':not any(star_map[h.handler_module_path].name=='__NAME__' for h in excluded),'scopes':rows,'third_party_result':hello})
'''

def main():
    assert shutil.disk_usage(ROOT).free>100*1024*1024
    name='astrbot_plugin_audit_'+uuid.uuid4().hex[:8]
    cred=json.loads((ROOT/'runtime/dashboard-login.local.json').read_text('utf-8-sig'))
    checks={}; out=ROOT/'verification/plugin-memory-audit';out.mkdir(parents=True,exist_ok=True)
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr(name+'/main.py',FIXTURE.replace('__NAME__',name))
        z.writestr(name+'/metadata.yaml',f'name: {name}\nauthor: local-audit\ndesc: No-network temporary probe\nversion: 0.0.1\n')
        z.writestr(name+'/_conf_schema.json',json.dumps({'marker':{'type':'string','description':'Test marker','default':'audit-default'}}))
    with httpx.Client(base_url='http://127.0.0.1:6185',trust_env=False,timeout=60) as c:
        def api(method,path,**kwargs):
            r=c.request(method,path,**kwargs);r.raise_for_status();d=r.json()
            if d.get('status')=='error':raise RuntimeError('Audit operation failed: '+path)
            return d.get('data',d)
        a=api('POST','/api/v1/auth/login',json={'username':cred['username'],'password':cred['initial_password']});c.headers['Authorization']='Bearer '+a['token']
        before={p['name']:p['activated'] for p in api('GET','/api/v1/plugins')}
        hello_installed=False;network={}
        try:
            assert 'helloworld' not in before,'Existing helloworld belongs to the user; refusing replacement'
            try:
                api('POST','/api/v1/plugins/install/github',json={'repository':'https://github.com/Soulter/helloworld'})
                network['native_github_install']='passed'
            except (RuntimeError,httpx.HTTPError):
                network['native_github_install']='failed: inherited proxy download connection; direct download tested separately'
                # The reviewed upstream template has no dependencies or external actions.
                with httpx.Client(trust_env=False,timeout=30,follow_redirects=True) as direct:
                    downloaded=direct.get('https://api.github.com/repos/Soulter/helloworld/zipball/0c0d52b')
                    downloaded.raise_for_status()
                network['reviewed_archive_sha256']=hashlib.sha256(downloaded.content).hexdigest()
                api('POST','/api/v1/plugins/install/upload',files={'file':('helloworld-audit.zip',downloaded.content,'application/zip')})
            hello_installed=True
            checks['third_party_download_install_and_load']=any(p['name']=='helloworld' and p['activated'] for p in api('GET','/api/v1/plugins'))
            api('POST','/api/v1/plugins/install/upload',files={'file':(name+'.zip',archive.getvalue(),'application/zip')})
            checks['zip_installed_discovered_loaded']=any(p['name']==name and p['activated'] for p in api('GET','/api/v1/plugins'))
            probe=api('GET','/api/v1/plugins/extensions/'+name+'/probe')
            checks['real_registered_message_hook_called']=probe['marker']=='audit-default' and probe['called']==1
            checks['scope_exclusion_blocks_hook']=probe['excluded']
            checks['third_party_command_generates_expected_reply_without_send']=len(probe['third_party_result'])==1 and 'audit-only' in probe['third_party_result'][0] and '/helloworld' in probe['third_party_result'][0]
            scopes=probe['scopes']
            api('PUT','/api/v1/plugins/config',json={'plugin_id':name,'config':{'marker':'audit-saved'}})
            probe=api('GET','/api/v1/plugins/extensions/'+name+'/probe')
            checks['saved_configuration_used_by_hook']=probe['marker']=='audit-saved'
            api('PATCH','/api/v1/plugins/'+name+'/enabled',json={'enabled':False})
            checks['disabled_list_state']=not next(p for p in api('GET','/api/v1/plugins') if p['name']==name)['activated']
            disabled=c.get('/api/v1/plugins/extensions/'+name+'/probe')
            # Disabled routes should be gone. If retained, the native registry must still block its hook.
            d=disabled.json()
            checks['disabled_hook_not_callable']=d.get('status')=='error' or d.get('called')==0
            api('PATCH','/api/v1/plugins/'+name+'/enabled',json={'enabled':True})
            probe=api('GET','/api/v1/plugins/extensions/'+name+'/probe')
            checks['reenabled_hook_and_saved_config']=probe['marker']=='audit-saved' and probe['called']==1
            api('POST','/api/v1/plugins/'+name+'/reload')
            checks['reload_keeps_saved_config']=api('GET','/api/v1/plugins/extensions/'+name+'/probe')['marker']=='audit-saved'
        finally:
            installed=api('GET','/api/v1/plugins')
            if any(p['name']==name for p in installed):
                api('DELETE','/api/v1/plugins/by-id',params={'plugin_id':name},json={'delete_config':True,'delete_data':True})
            if hello_installed:
                api('DELETE','/api/v1/plugins/by-id',params={'plugin_id':'helloworld'},json={'delete_config':True,'delete_data':True})
            checks['uninstalled_no_discovery_or_directory']=not any(p['name']==name for p in api('GET','/api/v1/plugins')) and not (ROOT/'runtime/app/data/plugins'/name).exists()
            checks['uninstalled_route_removed']=c.get('/api/v1/plugins/extensions/'+name+'/probe').json().get('status')=='error'
            checks['original_plugin_enable_states_preserved']={p['name']:p['activated'] for p in api('GET','/api/v1/plugins')}==before
        result={'checks':checks,'network':network,'scopes':scopes,'qq_messages_sent':False,'paid_services_called':False,'install_transport':'native ZIP upload and GitHub install' if network.get('native_github_install')=='passed' else 'ZIP upload passed; GitHub failure recorded separately','third_party_repository':'https://github.com/Soulter/helloworld'}
        (out/'external-install.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2));assert all(checks.values())

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
