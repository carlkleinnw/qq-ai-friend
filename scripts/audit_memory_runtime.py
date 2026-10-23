"""Offline integration audit of the installed engine; never touches production data."""
import asyncio
import json
import sys
import tempfile
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'runtime/app/data/plugins/astrbot_plugin_memory_companion'
sys.path.insert(0, str(PLUGIN / 'tests'))
from package_bootstrap import bootstrap_package
bootstrap_package()
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService
from astrbot_plugin_memory_companion.main import MemoryCompanionPlugin
from astrbot_plugin_memory_companion.page_api import PluginPageApi
from astrbot.api.provider import ProviderRequest

BOTS = [('审计机器人A', 'audit-bot-a'), ('审计机器人B', 'audit-bot-b'), ('审计机器人C', 'audit-bot-c')]

def event(bot, user, text='你记得我之前告诉你的审计口令是什么吗？请回忆审计口令'):
    return SimpleNamespace(unified_msg_origin=f'{bot}:FriendMessage:{user}',
        get_platform_name=lambda: 'qq_official', get_self_id=lambda: bot,
        get_sender_id=lambda: user, get_sender_name=lambda: 'audit-only',
        get_group_id=lambda: '', get_message_str=lambda: text,
        message_obj=SimpleNamespace(message_id='audit-only'),
        private_companion_persona_id='persona-'+bot)

async def run():
    checks = {}
    config = json.loads((ROOT/'runtime/app/data/config/astrbot_plugin_memory_companion_config.json').read_text('utf-8-sig'))
    # No providers, network, production paths, automatic model extraction, or real send sink.
    config['retrieval'].update(mode='basic', embedding_enabled=False)
    config['memory_summary'] = {'enabled': False}
    with tempfile.TemporaryDirectory(prefix='ai-friend-audit-', dir=ROOT/'runtime') as folder:
        def make():
            return MemoryCompanionService(context=None,config=config,plugin_root=PLUGIN,data_dir=Path(folder))
        service = make()
        records = []
        try:
            for i,(name,bot) in enumerate(BOTS):
                for j in range(2):
                    ev=event(bot, 'audit-friend-'+str(j))
                    marker=f'审计口令 紫晶{i}{j} 唯一标记audit-{i}-{j}'
                    saved=await service.tool_remember(ev,marker,note_type='profile')
                    assert saved.get('ok'), saved
                    records.append((name,bot,ev,marker,saved['memory_id']))
            checks['six_distinct_memories_written_through_tool'] = len(records)==6
            for name,bot,ev,marker,mid in records:
                ctx=await service.identity.resolve_event_context(ev)
                results,_,_=await service.search_context_slots('审计口令',ctx,top_k=20)
                found={r.memory.id for r in results}
                checks[f'{name}_{ctx.user_id}_private_isolation']=found=={mid}
                req=ProviderRequest(prompt=ev.get_message_str(),system_prompt='',contexts=[])
                host=MemoryCompanionPlugin.__new__(MemoryCompanionPlugin)
                host.service=service
                await host.on_llm_request(ev,req)
                prompt=str(req.system_prompt)+str(req.prompt)+str(req.contexts)+''.join(getattr(p,'text','') for p in req.extra_user_content_parts)
                checks[f'{name}_{ctx.user_id}_prompt_uses_own_memory']=marker in prompt and all(m not in prompt for _,_,_,m,id2 in records if id2!=mid)
                recalled=await service.tool_recall(ev,'审计口令',top_k=20)
                checks[f'{name}_{ctx.user_id}_recall_tool_isolation']=recalled.get('ok') and {m['id'] for m in recalled['memories']}=={mid}
            # Exercise the same store operations used by the admin page, including cache invalidation.
            name,bot,ev,marker,mid=records[0]
            updated='审计口令 修改后audit-corrected'
            page=PluginPageApi(SimpleNamespace(service=service))
            page._ok=lambda data:data
            async def update_payload():return {'id':mid,'content':updated}
            page._json=update_payload
            assert (await page.memory_update())['updated']
            ctx=await service.identity.resolve_event_context(ev)
            results,_,_=await service.search_context_slots('审计口令',ctx,top_k=20)
            checks['admin_update_invalidates_retrieval_cache']=any(r.memory.content==updated for r in results) and all(r.memory.content!=marker for r in results)
            async def delete_payload():return {'id':mid}
            page._json=delete_payload
            assert (await page.memory_delete())['deleted']
            results,_,_=await service.search_context_slots('审计口令',ctx,top_k=20)
            checks['admin_delete_invalidates_retrieval_cache']=not any(r.memory.id==mid for r in results)
        finally:
            await service.aclose()
        # Reopen in a fresh interpreter as well, so process-local caches cannot
        # account for persistence. Only synthetic event IDs enter this file.
        payload={'config':config,'records':[{'name':name,'bot':bot,'user':ev.get_sender_id(),'id':mid} for name,bot,ev,marker,mid in records]}
        (Path(folder)/'audit-reopen.json').write_text(json.dumps(payload),encoding='utf-8')
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--reopen',folder],check=True,stdout=subprocess.DEVNULL,timeout=40)
        checks.update(json.loads((Path(folder)/'audit-reopen-result.json').read_text('utf-8')))
        service=make()
        try:
            for name,bot,ev,marker,mid in records[1:]:
                # Display names and avatars never enter this stable event identity.
                ev.get_sender_name=lambda: 'renamed-display-only'
                ev.bot_name='audit-renamed-robot'
                ev.bot_avatar='https://example.invalid/audit-avatar.png'
                ctx=await service.identity.resolve_event_context(ev)
                results,_,_=await service.search_context_slots('审计口令',ctx,top_k=20)
                checks[f'{name}_{ctx.user_id}_reopen_persists']= {r.memory.id for r in results}=={mid}
                checks[f'{name}_{ctx.user_id}_display_change_keeps_identity']=ctx.session_id==ev.unified_msg_origin and ctx.bot_id==bot
            checks['deleted_memory_stays_deleted_after_reopen']=await service.store.get_memory(records[0][4]) is None
        finally:
            await service.aclose()
    out=ROOT/'verification/plugin-memory-audit';out.mkdir(parents=True,exist_ok=True)
    (out/'memory-engine.json').write_text(json.dumps({'checks':checks,'production_data_written':False,'model_called':False,'qq_sent':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False,indent=2))
    assert all(checks.values()), 'Memory integration checks failed; see report'

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv)==3 and sys.argv[1]=='--reopen':
        async def reopen():
            folder=Path(sys.argv[2]).resolve()
            if not folder.is_relative_to((ROOT/'runtime').resolve()) or not folder.name.startswith('ai-friend-audit-'):
                raise ValueError('Not an isolated audit directory')
            payload=json.loads((folder/'audit-reopen.json').read_text('utf-8'))
            service=MemoryCompanionService(context=None,config=payload['config'],plugin_root=PLUGIN,data_dir=folder)
            result={}
            try:
                for index,row in enumerate(payload['records']):
                    ctx=await service.identity.resolve_event_context(event(row['bot'],row['user']))
                    found,_,_=await service.search_context_slots('审计口令',ctx,top_k=20)
                    result[row['name']+'_'+row['user']+'_fresh_process_persistence']={r.memory.id for r in found}==({row['id']} if index else set())
            finally:await service.aclose()
            (folder/'audit-reopen-result.json').write_text(json.dumps(result),encoding='utf-8')
        asyncio.run(reopen())
    else:asyncio.run(run())
