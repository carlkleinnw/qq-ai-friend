"""QQ identities and scoped controls backed by native profiles and session rules."""
from copy import deepcopy
import asyncio
from datetime import datetime, timezone
import hashlib
import uuid
from urllib.parse import urlsplit

from .persona_form import revision

AGENT_FIELDS = {
    'dify': ('dify_api_base', 'dify_api_key', 'dify_api_type', 'dify_query_input_key', 'dify_workflow_output_key', 'variables', 'timeout', 'proxy'),
    'coze': ('coze_api_base', 'coze_api_key', 'bot_id', 'auto_save_history', 'timeout', 'proxy'),
    'dashscope': ('dashscope_api_key', 'dashscope_app_id', 'dashscope_app_type', 'rag_options', 'variables', 'timeout', 'proxy'),
    'deerflow': ('deerflow_api_base', 'deerflow_api_key', 'deerflow_auth_header', 'deerflow_assistant_id', 'deerflow_model_name', 'deerflow_thinking_enabled', 'deerflow_plan_mode', 'deerflow_subagent_enabled', 'deerflow_max_concurrent_subagents', 'deerflow_recursion_limit', 'timeout', 'proxy'),
}


def secret_field(key):
    return 'api_key' in key or key == 'deerflow_auth_header'


class QQControl:
    def __init__(self, plugin, preferences=None):
        self.plugin = plugin
        if preferences is None:
            from astrbot.core import sp
            preferences = sp
        self.sp = preferences
        self.applied = {}
        self.observed = {}

    @staticmethod
    def archive_key(bot_id, umo=None):
        scope = umo or bot_id + '::'
        return 'ai_friend.agent_profiles.' + hashlib.sha256(scope.encode()).hexdigest()

    async def agent_profiles(self, bot_id, umo=None):
        return await self.sp.global_get(self.archive_key(bot_id, umo), {}) or {}

    def robot(self, bot_id, appid=None):
        bot = next((b for b in self.plugin.targets() if b['bot_id'] == bot_id), None)
        if not bot or not bot.get('appid'):
            raise ValueError('找不到已配置 AppID 的 QQ 机器人，请先完成 QQ 接入。')
        if bot.get('identity_conflict'):
            raise ValueError('同一 AppID 存在多个接入实例，请先到原生 QQ 接入设置消除重复连接。')
        if appid is not None and str(appid) != bot['appid']:
            raise ValueError('AppID 已改变，请重新读取机器人身份后再保存。')
        return bot

    async def sessions(self, bot_id):
        from astrbot.dashboard.services.session_management_service import SessionManagementService
        service = SessionManagementService(None, self.plugin.context._db)
        data = await service.list_active_umos()
        return [row for row in data['umo_infos'] if row['umo'].startswith(bot_id + ':FriendMessage:')]

    async def validate_umo(self, bot_id, umo):
        if not umo:
            return None
        if not isinstance(umo, str) or any(c in umo for c in '*?[]') or not umo.startswith(bot_id + ':FriendMessage:'):
            raise ValueError('好友会话不属于当前机器人，或不是有效的私聊会话。')
        if umo not in {row['umo'] for row in await self.sessions(bot_id)}:
            raise ValueError('尚未收到该好友的 QQ 消息，无法绑定未知会话。')
        return umo

    async def _resolved(self, bot_id, umo=None):
        ctx = self.plugin.context
        origin = umo or f'{bot_id}:FriendMessage:panel-default'
        manager = ctx.astrbot_config_mgr
        cid = manager.ucr.get_conf_id_for_umop(origin) or 'default'
        config = ctx.get_config(origin)
        service = await self.sp.session_get(umo, 'session_service_config', {}) or {} if umo else {}
        preference = await self.sp.session_get(umo, 'provider_perf_chat_completion', None) if umo else None
        conversation_id = await ctx.conversation_manager.get_curr_conversation_id(umo) if umo else None
        conv = await ctx.conversation_manager.get_conversation(umo, conversation_id) if conversation_id else None
        conv_pid = getattr(conv, 'persona_id', None)
        pid, _, forced, _ = await ctx.persona_manager.resolve_selected_persona(
            umo=origin, conversation_persona_id=conv_pid, platform_name='qq_official')
        persona_revision = None
        if pid and pid != '[%None]':
            try:
                persona = await ctx.persona_manager.get_persona(pid)
                persona_revision = revision({'prompt': persona.system_prompt, 'tools': persona.tools, 'skills': persona.skills})
            except ValueError:
                pass
        version = revision({'config_id':cid, 'runner': config.get('agent_runner'), 'settings': config.get('provider_settings'),
                            'agent_profiles': await self.agent_profiles(bot_id, umo),
                            'persona_revision': persona_revision,
                            'service': service, 'provider_override': preference, 'conversation_id': conversation_id, 'conversation_persona': conv_pid,
                            'persona_id':pid})
        return {'origin':origin, 'config_id':cid, 'config':config, 'service':service, 'provider_override':preference,
                'conversation_id':conversation_id, 'conversation_persona':conv_pid, 'persona_id':pid, 'forced':forced, 'revision':version}

    async def read(self, bot_id, umo=None):
        bot = self.robot(bot_id)
        umo = await self.validate_umo(bot_id, umo)
        ctx = self.plugin.context
        resolved = await self._resolved(bot_id, umo)
        config = resolved['config']
        runner = config.get('agent_runner', {})
        kind = runner.get('runner_type', 'local')
        settings = runner.get('config', {})
        provider = await ctx.get_using_provider_async(resolved['origin']) if kind == 'local' else None
        pid = resolved['persona_id']
        prompt = ''
        try:
            if kind == 'local' and pid and pid != '[%None]':
                prompt = (await ctx.persona_manager.get_persona(pid)).system_prompt
        except ValueError:
            pass
        fields = {key: settings[key] for key in AGENT_FIELDS.get(kind, ()) if key in settings and not secret_field(key)}
        secrets = {key: bool(settings.get(key)) for key in AGENT_FIELDS.get(kind, ()) if secret_field(key)}
        profiles = deepcopy(await self.agent_profiles(bot_id, umo))
        profiles[kind] = settings
        safe_profiles = {name: {
            'fields': {key: value[key] for key in AGENT_FIELDS.get(name, ()) if key in value and not secret_field(key)},
            'saved_secrets': {key: bool(value.get(key)) for key in AGENT_FIELDS.get(name, ()) if secret_field(key)},
        } for name, value in profiles.items() if name in AGENT_FIELDS}
        choices = await ctx.persona_manager.get_all_personas()
        names={row['persona_id']:row['name'] for row in self.plugin.config.get('custom_presets',[])}
        for item in self.plugin.targets():
            default_config=ctx.get_config(f"{item['bot_id']}:FriendMessage:panel-default")
            default_pid=default_config.get('agent_runner',{}).get('config',{}).get('persona',{}).get('persona_id')
            if default_pid:names.setdefault(default_pid,item['name']+'的人设')
        for cfg_id,cfg in ctx.astrbot_config_mgr.confs.items():
            owned_pid=cfg.get('agent_runner',{}).get('config',{}).get('persona',{}).get('persona_id')
            meta=(getattr(ctx.astrbot_config_mgr,'abconf_data',None) or {}).get(cfg_id,{})
            if owned_pid and owned_pid.startswith('chat-') and meta.get('name'):names.setdefault(owned_pid,meta['name']+'的人设')
        scope = umo or bot_id
        platform = next(p for p in ctx.get_config()['platform'] if p['id']==bot_id)
        return {'bot':bot, 'umo':umo, 'sessions':await self.sessions(bot_id), 'revision':resolved['revision'],
                'config_id':resolved['config_id'], 'conversation_id':resolved['conversation_id'],
                'runner_type':kind, 'agent_fields':fields, 'saved_secrets':secrets,
                'agent_profiles':safe_profiles, 'qq_revision':revision(platform),
                'providers':[p.meta().id for p in ctx.get_all_providers()],
                'provider_id':provider.meta().id if provider else '', 'persona_id':pid, 'prompt':prompt,
                'personas':[{'persona_id':p.persona_id, 'name':names.get(p.persona_id,p.persona_id)} for p in choices],
                'session_enabled':resolved['service'].get('session_enabled', True),
                'llm_enabled':resolved['service'].get('llm_enabled', config.get('provider_settings',{}).get('enable',True)),
                'qq_settings':{key:platform.get(key,True if key in ('enable','use_markdown') else False) for key in ('enable','enable_group_c2c','enable_guild_direct_message','use_markdown')},
                'persona_source':'会话单独设置' if resolved['forced'] or resolved['conversation_persona'] else '机器人默认设置',
                'apply_result':self.applied.get(scope), 'last_message':self.observed.get(umo) if umo else None}

    async def save(self, body):
        from astrbot.core.config.agent_runner import get_agent_runner_config_default
        if not isinstance(body, dict):
            raise ValueError('配置格式不正确。')
        bot_id = body.get('bot_id')
        bot = self.robot(bot_id, body.get('appid'))
        umo = await self.validate_umo(bot_id, body.get('umo'))
        section = body.get('section', 'manage')
        if section not in ('manage', 'model', 'agent'):
            raise ValueError('配置页面类型不正确。')
        kind = body.get('runner_type')
        if section != 'model' and kind not in ('local', *AGENT_FIELDS):
            raise ValueError('请选择受支持的 Agent 类型。')
        for key in ('session_enabled','llm_enabled'):
            if section == 'manage' and type(body.get(key)) is not bool:
                raise ValueError('启停设置必须是开关值。')
        ctx = self.plugin.context
        acm = ctx.astrbot_config_mgr
        async with self.plugin.lock:
            before = await self._resolved(bot_id, umo)
            if before['revision'] != body.get('revision'):
                raise ValueError('配置或当前对话已改变，请重新读取后保存。')
            old_config = before['config']
            old_runner = deepcopy(old_config.get('agent_runner', {}))
            if section == 'model':
                kind = old_runner.get('runner_type', 'local')
                if kind != 'local':
                    raise ValueError('当前使用外部 Agent，请在 Agent 连接切换为内置 Agent 后选择模型。')
            old_profiles = await self.agent_profiles(bot_id, umo)
            profiles = deepcopy(old_profiles)
            runner_settings = deepcopy(old_runner.get('config', {})) if old_runner.get('runner_type') == kind else deepcopy(profiles.get(kind, get_agent_runner_config_default(kind)))
            if old_runner.get('runner_type') != kind:
                profiles[old_runner.get('runner_type', 'local')] = deepcopy(old_runner.get('config', {}))
            target_persona = None
            created_persona = None
            if kind == 'local' and section in ('manage', 'model'):
                provider_id = body.get('provider_id')
                if provider_id not in {p.meta().id for p in ctx.get_all_providers()}:
                    raise ValueError('所选模型未启用或不可用，请先在模型服务配置中启用。')
                if section == 'manage':
                    target_persona = await ctx.persona_manager.get_persona(body.get('persona_id'))
                    prompt = body.get('prompt')
                    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>21000:
                        raise ValueError('请填写不超过 21000 字的人设。')
                runner_settings.setdefault('model', {})['provider_id'] = provider_id
            elif kind != 'local' and section in ('manage', 'agent'):
                supplied = body.get('agent_fields', {})
                if not isinstance(supplied, dict):
                    raise ValueError('Agent 配置格式不正确。')
                for key in AGENT_FIELDS[kind]:
                    if key not in supplied or (secret_field(key) and not supplied[key]):
                        continue
                    value = supplied[key]
                    if key == 'timeout':
                        if type(value) is not int or not 1 <= value <= 600: raise ValueError('超时应为 1 到 600 秒。')
                    elif key in ('auto_save_history','deerflow_thinking_enabled','deerflow_plan_mode','deerflow_subagent_enabled'):
                        if type(value) is not bool: raise ValueError('保存历史应为开关值。')
                    elif key in ('deerflow_max_concurrent_subagents', 'deerflow_recursion_limit'):
                        if type(value) is not int or not 1 <= value <= 10000: raise ValueError('Agent 数量或递归限制应为 1 到 10000 的整数。')
                    elif key in ('variables', 'rag_options'):
                        if not isinstance(value, dict): raise ValueError('变量与 RAG 选项必须为 JSON 对象。')
                    elif not isinstance(value,str) or len(value)>4000:
                        raise ValueError('Agent 字段格式不正确。')
                    if key.endswith('api_base') and urlsplit(value).scheme not in ('http','https'):
                        raise ValueError('Agent 地址必须使用 http 或 https。')
                    runner_settings[key] = value
                if kind == 'dify' and runner_settings.get('dify_api_type') not in ('chat','agent','workflow'):
                    raise ValueError('Dify 应用类型应为 chat、agent 或 workflow。')
            route = umo or bot_id + '::'
            exact_id = acm.ucr.umop_to_conf_id.get(route)
            private_profile = exact_id in acm.confs and exact_id != 'default' and not any(
                other != route and cid == exact_id for other,cid in acm.ucr.umop_to_conf_id.items())
            created_profile = None
            config_id = exact_id if private_profile else None
            config = acm.confs[config_id] if config_id else None
            saved_config = deepcopy(dict(config)) if config is not None else None
            old_routes = None
            wrote_preferences = False
            wrote_profiles = False
            try:
                if target_persona:
                    target_id = target_persona.persona_id
                    # Copy on write: the editor never overwrites a shared template or another chat's persona.
                    shared = any(cid != config_id and cfg.get('agent_runner',{}).get('config',{}).get('persona',{}).get('persona_id') == target_id
                                 for cid,cfg in acm.confs.items())
                    if (body['prompt'].replace('\r\n','\n') != target_persona.system_prompt.replace('\r\n','\n') or shared
                            or target_id != before['persona_id'] or (umo and not private_profile)):
                        target_id = created_persona = 'chat-' + uuid.uuid4().hex[:16]
                        await ctx.persona_manager.create_persona(target_id, body['prompt'], tools=deepcopy(target_persona.tools),
                            skills=deepcopy(target_persona.skills), begin_dialogs=deepcopy(target_persona.begin_dialogs),
                            custom_error_message=target_persona.custom_error_message)
                    runner_settings.setdefault('persona', {})['persona_id'] = target_id
                # Awaiting persona I/O must not allow a stale native-page edit to be overwritten.
                if (await self._resolved(bot_id,umo))['revision'] != before['revision']:
                    raise ValueError('保存期间配置已被其他页面修改，请重新读取。')
                if config is None:
                    value = deepcopy(dict(old_config))
                    for key in ('platform','provider','provider_sources','dashboard'): value.pop(key,None)
                    created_profile = config_id = await acm.create_conf(value, name=bot['name'] + (' · 好友会话' if umo else ' · 默认'))
                    config = acm.confs[config_id]
                config['agent_runner'] = {'runner_type':kind,'config':runner_settings}
                if section == 'manage':
                    config.setdefault('provider_settings',{})['enable'] = body['llm_enabled']
                config.save_config()
                await ctx.reload_pipeline_scheduler(config_id)
                if profiles != old_profiles:
                    wrote_profiles = True
                    await self.sp.global_put(self.archive_key(bot_id, umo), profiles)
                # Publish a session's exact route before broad defaults. Preserve every other route's order.
                old_routes = dict(acm.ucr.umop_to_conf_id)
                routes = {route:config_id, **{key:val for key,val in old_routes.items() if key != route}} if umo else {
                    **{key:val for key,val in old_routes.items() if key.startswith(bot_id+':') and key!=route},
                    route:config_id, **{key:val for key,val in old_routes.items() if not key.startswith(bot_id+':')}}
                await acm.ucr.update_routing_data(routes)
                if umo:
                    wrote_preferences = True
                    service = deepcopy(before['service'])
                    if section == 'manage':
                        service.update(session_enabled=body['session_enabled'],llm_enabled=body['llm_enabled'])
                        if kind == 'local': service['persona_id'] = runner_settings['persona']['persona_id']
                    await self.sp.session_put(umo,'session_service_config',service)
                    if section in ('manage','model'):
                        await self.sp.session_remove(umo,'provider_perf_chat_completion')
                if kind == 'local' and section == 'manage':
                    await self.plugin.registry.ensure_companion(bot, persona_id=runner_settings['persona']['persona_id'])
                after = await self._resolved(bot_id,umo)
                if after['config_id'] != config_id or (target_persona and after['persona_id'] != runner_settings['persona']['persona_id']):
                    raise RuntimeError('保存后的实际会话配置与选择不一致。')
                self.applied[umo or bot_id] = {'saved':True,'pipeline_loaded':True,'revision':after['revision'],
                    'at':datetime.now(timezone.utc).isoformat(),'note':'已保存并加载到聊天流程；QQ 实际回复待验证。'}
            except Exception:
                try:
                    if wrote_profiles:
                        if old_profiles: await self.sp.global_put(self.archive_key(bot_id, umo), old_profiles)
                        else: await self.sp.global_remove(self.archive_key(bot_id, umo))
                    if wrote_preferences:
                        await self.sp.session_put(umo,'session_service_config',before['service'])
                        if before['provider_override'] is None: await self.sp.session_remove(umo,'provider_perf_chat_completion')
                        else: await self.sp.session_put(umo,'provider_perf_chat_completion',before['provider_override'])
                    if old_routes is not None: await acm.ucr.update_routing_data(old_routes)
                    if created_profile: await acm.delete_conf(created_profile)
                    elif config is not None and saved_config is not None:
                        config.clear(); config.update(saved_config); config.save_config()
                        await ctx.reload_pipeline_scheduler(config_id)
                    if created_persona: await ctx.persona_manager.delete_persona(created_persona)
                except Exception:
                    self.plugin.logger.exception('机器人或会话配置恢复未完成')
                    raise RuntimeError('保存失败且恢复未确认，请核对原生配置。')
                raise
        return await self.read(bot_id,umo)

    async def identity(self, body):
        if not isinstance(body, dict):
            raise ValueError('资料格式不正确。')
        bot = self.robot(body.get('bot_id'),body.get('appid'))
        async with self.plugin.lock:
            rows = deepcopy(self.plugin.config.get('identity_records',[]))
            record = next((r for r in rows if str(r.get('appid'))==bot['appid']),None)
            if record is None:
                record={'appid':bot['appid']}; rows.append(record)
            if body.get('sync') is True:
                adapter=self.plugin.context.get_platform_inst(bot['bot_id'])
                if adapter is None or str(getattr(adapter,'appid',''))!=bot['appid']:
                    raise ValueError('该 AppID 尚未加载，无法从 QQ 读取资料。')
                try:
                    user=await asyncio.wait_for(adapter.client.api.me(),timeout=15)
                except Exception:
                    raise ValueError('未能从 QQ 读取资料，请核对连接后重试。未修改 QQ 平台资料。') from None
                if not isinstance(user, dict) or not user.get('username') or not user.get('id'):
                    raise ValueError('QQ 返回的资料不完整，未覆盖已有资料。请稍后重试。')
                record.update(qq_name=user.get('username',''),qq_avatar=user.get('avatar',''),qq_user_id=str(user.get('id','')))
                record['profile_read_at']=datetime.now(timezone.utc).isoformat()
            else:
                name=body.get('local_name',''); avatar=body.get('local_avatar','')
                if not isinstance(name,str) or len(name)>60 or not isinstance(avatar,str) or len(avatar)>2000:
                    raise ValueError('本机备注或头像地址格式不正确。')
                if avatar and urlsplit(avatar).scheme!='https': raise ValueError('头像地址必须使用 https。')
                if 'web_override' in body:
                    if type(body['web_override']) is not bool: raise ValueError('网页显示开关格式不正确。')
                    record['web_override'] = body['web_override']
                if body.get('clear_avatar') is True:
                    record.pop('local_avatar_data', None)
                if body.get('avatar_data'):
                    from .profile_images import normalize_avatar
                    record['local_avatar_data'] = normalize_avatar(body['avatar_data'])
                record.update(local_name=name.strip(),local_avatar=avatar)
                if not any(value for key, value in record.items() if key != 'appid'):
                    rows.remove(record)
            old=deepcopy(self.plugin.config.get('identity_records',[]))
            self.robot(bot['bot_id'], bot['appid'])
            self.plugin.config['identity_records']=rows
            try: self.plugin.config.save_config()
            except Exception:
                self.plugin.config['identity_records']=old
                raise
            if body.get('sync') is True:
                robot=getattr(adapter.client,'robot',None)
                if robot: robot._update(user)
        return {'bot':self.robot(bot['bot_id']), 'note':
                '已从 QQ 读取当前公开资料并更新网页；未修改 QQ 资料，审核状态请到开放平台查看。'
                if body.get('sync') is True else '已保存，仅网页显示；未提交 QQ 修改或审核。'}

    async def connection(self, body):
        bot=self.robot(body.get('bot_id'),body.get('appid'))
        ctx=self.plugin.context
        async with self.plugin.lock:
            global_config=ctx.get_config()
            platform=next(p for p in global_config['platform'] if p['id']==bot['bot_id'])
            if body.get('qq_revision') is not None and body['qq_revision'] != revision(platform):
                raise ValueError('QQ 接入设置已在其他页面改变，请重新读取后保存。')
            old=deepcopy(platform)
            for key in ('enable','enable_group_c2c','enable_guild_direct_message','use_markdown'):
                if key in body:
                    if type(body[key]) is not bool: raise ValueError('连接选项必须是开关值。')
            try:
                platform.update({key:body[key] for key in ('enable','enable_group_c2c','enable_guild_direct_message','use_markdown') if key in body})
                global_config.save_config()
                await ctx.platform_manager.reload(platform)
            except Exception:
                platform.clear();platform.update(old);global_config.save_config()
                try: await ctx.platform_manager.reload(platform)
                except Exception: self.plugin.logger.exception('QQ 连接恢复失败')
                raise
        return {'bot':self.robot(bot['bot_id']), 'qq_revision':revision(platform), 'note':'接入配置已保存，已请求原生适配器重新连接；是否在线请查看实际连接状态。'}

    async def observe(self,event,phase,request=None,response=None):
        bot_id=event.get_platform_id()
        if not any(b['bot_id']==bot_id for b in self.plugin.targets()): return
        umo=str(event.unified_msg_origin)
        message_id=str(getattr(event.message_obj,'message_id',''))
        previous=self.observed.get(umo,{})
        if phase=='request' or previous.get('message_id')!=message_id:
            previous={'message_id':message_id,'at':datetime.now(timezone.utc).isoformat()}
        previous[phase+'_observed']=True
        if request is not None:
            data=await self._resolved(bot_id,umo)
            provider=await self.plugin.context.get_using_provider_async(umo)
            previous.update(config_id=data['config_id'],persona_id=data['persona_id'],revision=data['revision'],
                selected_provider_id=provider.meta().id if provider else None,request_model=getattr(request,'model',None),
                system_prompt_sha256=hashlib.sha256(request.system_prompt.encode()).hexdigest())
        if response is not None:
            previous['reply_preview']=str(getattr(response,'completion_text',''))[:160]
            previous['response_failed']=getattr(response,'role',None)=='err'
        previous['note']='已观察到 QQ 发送流程完成，手机实际收取需确认。' if phase=='send' else '已观察到实际消息处理，等待发送结果。'
        if previous.get('response_failed'):previous['note']='模型处理返回错误，请查看运行日志；不能将此视为连接成功。'
        self.observed[umo]=previous
        if len(self.observed)>300: self.observed.pop(next(iter(self.observed)))
