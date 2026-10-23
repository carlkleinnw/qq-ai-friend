"""Read-only inventory: report capabilities without exporting credentials or chat text."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    credentials=json.loads((ROOT/'runtime/dashboard-login.local.json').read_text('utf-8-sig'))
    with httpx.Client(base_url='http://127.0.0.1:6185',trust_env=False,timeout=30) as c:
        def get(path,**kwargs):
            r=c.get(path,**kwargs);r.raise_for_status();d=r.json()
            if d.get('status')=='error':raise RuntimeError('Read-only audit failed: '+path)
            return d.get('data',d)
        a=c.post('/api/v1/auth/login',json={'username':credentials['username'],'password':credentials['initial_password']}).json()['data']
        c.headers['Authorization']='Bearer '+a['token']
        plugins=[{k:p.get(k) for k in ['name','version','activated','reserved','pages','support_platforms']} for p in get('/api/v1/plugins')]
        failed=get('/api/v1/plugins/failed')
        base='/api/v1/plugins/extensions/astrbot_plugin_persona_studio/'
        bots=[]
        for b in get(base+'bot-identities')['bots']:
            state=get(base+'control-state',params={'bot_id':b['bot_id']})
            cfg=get('/api/v1/config-profiles/'+state['config_id'])['config']
            # Do not export session IDs, friend IDs, prompts, message bodies, or keys.
            bots.append({'name':b['name'],'appid':b['appid'],'bot_id':b['bot_id'],'connection_status':b['connection_status'],
                'persona_id':state['persona_id'],'config_id':state['config_id'],'runner_type':state['runner_type'],
                'provider_configured':bool(state['provider_id']),'friend_sessions':len(state['sessions']),
                'plugins':cfg.get('plugin_set',['*']),'session_enabled':state['session_enabled'],'llm_enabled':state['llm_enabled']})
        stats=get('/api/v1/plugins/extensions/astrbot_plugin_memory_companion/page/stats')['stats']
        coord=get('/api/v1/plugins/extensions/astrbot_plugin_memory_companion/page/coordination/status')['status']
        config=json.loads((ROOT/'runtime/app/data/config/astrbot_plugin_memory_companion_config.json').read_text('utf-8-sig'))
        conversations=get('/api/v1/conversations',params={'include_history':False})
        result={'checked_at':datetime.now(timezone.utc).isoformat(),'plugins':plugins,'failed_plugins_count':len(failed.get('failed_plugins',[])) if isinstance(failed,dict) else len(failed),
            'bots':bots,'conversation_list_readable':isinstance(conversations.get('conversations'),list),'memory':{'total_records_including_internal':stats['total_memories'],'timeline_events':stats['timeline_events'],
                'coordination_health':coord['health'],'bridge_health':coord['bridge']['health'],'scope_control':config['scope_control'],
                'embedding_enabled':config['retrieval']['embedding_enabled'],'acl_rules':stats['acl_rules']},'model_called':False,'qq_sent':False}
    out=ROOT/'verification/plugin-memory-audit';out.mkdir(parents=True,exist_ok=True)
    (out/'inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
