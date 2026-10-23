"""Thin native Plugin View adapter; persona routing and persistence stay upstream."""
import asyncio
import json
import uuid
from copy import deepcopy
from pathlib import Path

from astrbot.api.star import Star, Context
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.web import request, json_response, error_response
from astrbot.dashboard.services.persona_service import PersonaService

from .persona_form import pack, unpack, revision
from .qq_commands import QQPersonaCommands, ALIASES
from .qq_menu import merge_persona_menu
from .bot_registry import BotRegistry
from .connections import connection_summary
from .binding import PersonaBinding
from .control import QQControl

PLUGIN = 'astrbot_plugin_persona_studio'


class PersonaStudio(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.lock = asyncio.Lock()
        self.presets = json.loads((Path(__file__).parent / 'presets.json').read_text(encoding='utf-8'))
        self.qq_commands = QQPersonaCommands(self)
        self.registry = BotRegistry(self)
        self.binding = PersonaBinding(self)
        self.control = QQControl(self)
        self._sync_task = None
        self._menu_versions = {}
        for endpoint, handler, method in [('state', self.state, 'GET'), ('save', self.save, 'POST'),
                                          ('connections', self.connections, 'GET'),
                                          ('bot-identities', self.bot_identities, 'GET'),
                                          ('bind-persona', self.bind_persona, 'POST'),
                                          ('control-state', self.control_state, 'GET'),
                                          ('control-persona', self.control_persona, 'GET'),
                                          ('control-save', self.control_save, 'POST'),
                                          ('control-test-model', self.control_test_model, 'POST'),
                                          ('control-identity', self.control_identity, 'POST'),
                                          ('control-connection', self.control_connection, 'POST'),
                                          ('qq-menu', self.qq_menu, 'POST'), ('presets', self.create_preset, 'POST'),
                                          ('update-preset', self.update_preset, 'POST'),
                                          ('delete-preset', self.delete_preset, 'POST'),
                                          ('authorize-qq', self.authorize_qq, 'POST')]:
            context.register_web_api(f'/{PLUGIN}/{endpoint}', handler, [method], 'AI好友人设编辑')

    @filter.command('人设', alias=ALIASES, priority=100000)
    async def qq_persona_command(self, event: AstrMessageEvent):
        """在授权的 QQ 私聊中选择、自定义、预览和确认人设。"""
        event.should_call_llm(False)
        yield event.plain_result(await self.qq_commands.execute(event)).use_t2i(False)
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=99999)
    async def qq_persona_custom_input(self, event: AstrMessageEvent):
        if event.get_platform_id() in self.registry.errors:
            reply = '这个机器人的独立配置尚未同步完成，请在本机好友人设页面刷新并核对连接状态。'
        else:
            reply = await self.qq_commands.consume_custom(event)
        if reply is None:
            return
        event.should_call_llm(False)
        yield event.plain_result(reply).use_t2i(False)
        event.stop_event()

    def targets(self):
        return self.registry.targets()

    @filter.on_llm_request(priority=-10000)
    async def observe_request(self, event: AstrMessageEvent, req):
        try: await self.control.observe(event,'request',request=req)
        except Exception: self.logger.exception('读取实际请求状态失败')

    @filter.on_llm_response(priority=-10000)
    async def observe_response(self, event: AstrMessageEvent, response):
        try: await self.control.observe(event,'response',response=response)
        except Exception: self.logger.exception('读取实际回复状态失败')

    @filter.after_message_sent(priority=-10000)
    async def observe_sent(self, event: AstrMessageEvent):
        try: await self.control.observe(event,'send')
        except Exception: self.logger.exception('读取发送状态失败')

    async def control_state(self):
        try:
            return json_response(await self.control.read(request.query.get('bot_id'),request.query.get('umo')))
        except ValueError as exc: return error_response(str(exc))
        except Exception:
            self.logger.exception('读取 QQ 机器人与好友配置失败')
            return error_response('无法读取实际配置，请刷新后重试。',status_code=500)

    async def bot_identities(self):
        try:
            return json_response({'bots': self.targets()})
        except Exception:
            return error_response('无法读取 QQ 身份和连接状态，请稍后重试。', status_code=500)

    async def control_operation(self, operation):
        try: return json_response(await operation(await request.json(default={})))
        except ValueError as exc: return error_response(str(exc))
        except Exception:
            self.logger.exception('QQ 机器人管理操作失败')
            return error_response('操作未能确认，请重新读取状态并核对；不要重复发送消息。',status_code=500)

    async def control_save(self):
        return await self.control_operation(self.control.save)

    async def control_test_model(self):
        body = await request.json(default={})
        if not isinstance(body, dict):
            return error_response('测试参数格式不正确。')
        provider = next((p for p in self.context.get_all_providers() if p.meta().id == body.get('provider_id')), None)
        if provider is None:
            return error_response('模型未启用或不存在，请重新读取模型列表。')
        try:
            await asyncio.wait_for(provider.test(), timeout=60)
        except Exception:
            # Upstream exceptions can contain provider credentials or request headers.
            return error_response('模型测试失败或超时，请核对服务地址、密钥、额度和网络。测试不会向 QQ 发送消息。')
        return json_response({'note': '所选模型测试成功；这不代表 QQ 收发已验证。'})

    async def control_persona(self):
        try:
            persona=await self.context.persona_manager.get_persona(request.query.get('persona_id'))
            return json_response({'persona_id':persona.persona_id,'prompt':persona.system_prompt})
        except ValueError as exc: return error_response(str(exc))

    async def control_identity(self):
        try:
            return json_response(await self.control.identity(await request.json(default={})))
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            return error_response('名称与头像保存未能确认，请保留草稿并重新读取核对。未提交 QQ 平台资料修改。', status_code=500)

    async def control_connection(self):
        return await self.control_operation(self.control.connection)

    async def reconcile_bots(self):
        await self.registry.reconcile()

    async def initialize(self):
        self._sync_task = asyncio.create_task(self.watch_bots())

    async def terminate(self):
        if self._sync_task:
            self._sync_task.cancel()
            await asyncio.gather(self._sync_task, return_exceptions=True)

    @filter.on_platform_loaded()
    async def platform_loaded(self):
        await self.reconcile_bots()

    @filter.on_astrbot_loaded()
    async def astrbot_loaded(self):
        await self.reconcile_bots()

    async def watch_bots(self):
        while True:
            try:
                await self.reconcile_bots()
                fingerprint = revision(await self.get_presets())
                for bot in self.targets():
                    if bot['connected'] and self._menu_versions.get(bot['bot_id']) != fingerprint:
                        try:
                            await asyncio.wait_for(self.publish_qq_menu(bot['bot_id']), timeout=12)
                            self._menu_versions[bot['bot_id']] = fingerprint
                        except Exception:
                            self.logger.exception('QQ 菜单尚未同步：%s', bot['bot_id'])
            except Exception:
                self.logger.exception('自动同步机器人或 QQ 菜单未完成，将稍后重试')
            await asyncio.sleep(30)

    def tool_catalog(self):
        manager = self.context.get_llm_tool_manager()
        return {t.name: t for t in [*manager.func_list, *manager.iter_builtin_tools()]}

    async def get_presets(self):
        references = self.config.get('custom_presets', [])
        hidden = set(self.config.get('hidden_presets', []))
        overridden = {r['id'] for r in references}
        result = [{**p, 'revision': revision(p)} for p in self.presets
                  if p['id'] not in hidden and p['id'] not in overridden]
        indexed = set()
        for reference in references:
            indexed.add(reference['persona_id'])
            if reference['id'] in hidden:
                continue
            try:
                persona = await self.context.persona_manager.get_persona(reference['persona_id'])
            except ValueError:
                self.logger.warning('自定义预设对应的原生人格已删除，已跳过该索引。')
                continue
            bio, prompt = unpack(persona.system_prompt)
            result.append({'id': reference['id'], 'name': reference['name'],
                           'bio': bio, 'prompt': prompt, 'summary': '自定义预设，可预览后选择。',
                           'revision': revision({'name': reference['name'], 'persona': PersonaService.serialize_persona(persona)})})
        # Existing personas created in AstrBot's own editor remain selectable here.
        bound = set()
        for bot in self.targets():
            try:
                bound.add(self.target_persona(bot['bot_id']))
            except ValueError:
                pass
        for persona in await self.context.persona_manager.get_all_personas():
            pid = persona.persona_id
            key = 'native-' + pid
            if pid == 'default' or pid in indexed or pid in bound or key in hidden:
                continue
            bio, prompt = unpack(persona.system_prompt)
            result.append({'id': key, 'name': pid, 'bio': bio, 'prompt': prompt,
                           'summary': '来自原生人格库。',
                           'revision': revision(PersonaService.serialize_persona(persona))})
        return result

    async def sync_menus(self):
        async def sync(bot):
            try:
                await asyncio.wait_for(self.publish_qq_menu(bot['bot_id']), timeout=10)
                return None
            except Exception:
                self.logger.exception('预设已保存，QQ 菜单同步尚未完成')
                return bot.get('name', bot['bot_id'])
        return [name for name in await asyncio.gather(*(sync(b) for b in self.targets() if b['enabled'])) if name]

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('请给人设取一个名字。')
        name = name.strip()
        if (any(ord(c) < 32 for c in name) or
            sum(2 if ord(c) > 127 else 1 for c in name) > 14):
            raise ValueError('名称最多七个汉字或十四个英文字母，不能包含换行。')
        return name

    async def save_preset(self, body):
        if not isinstance(body, dict):
            raise ValueError('预设内容格式不正确。')
        name = self.validate_name(body.get('name'))
        prompt = pack(body.get('bio'), body.get('prompt'))
        async with self.lock:
            presets = await self.get_presets()
            if any(p['name'] == name for p in presets):
                raise ValueError('已有同名预设，请换个名字。')
            suffix = uuid.uuid4().hex
            reference = {'id': 'custom-' + suffix, 'name': name, 'persona_id': 'preset-' + suffix}
            old = list(self.config.get('custom_presets', []))
            # A reusable preset inherits the explicitly selected robot's capabilities.
            # Never silently create a persona with all tools disabled.
            base = await self.context.persona_manager.get_persona(self.target_persona(body.get('bot_id')))
            await self.context.persona_manager.create_persona(reference['persona_id'], prompt,
                                                              tools=deepcopy(base.tools), skills=deepcopy(base.skills))
            try:
                self.config['custom_presets'] = [*old, reference]
                self.config.save_config()
            except Exception:
                self.config['custom_presets'] = old
                await self.context.persona_manager.delete_persona(reference['persona_id'])
                raise
        sync_errors = await self.sync_menus()
        return {'preset_id': reference['id'], 'presets': await self.get_presets(), 'menu_sync_errors': sync_errors}

    async def change_preset(self, body, delete=False):
        if not isinstance(body, dict):
            raise ValueError('预设内容格式不正确。')
        async with self.lock:
            presets = await self.get_presets()
            item = next((p for p in presets if p['id'] == body.get('preset_id')), None)
            if item is None or item['revision'] != body.get('revision'):
                raise ValueError('预设已改变，请重新读取列表后再操作。')
            old_refs = deepcopy(self.config.get('custom_presets', []))
            old_hidden = list(self.config.get('hidden_presets', []))
            ref = next((r for r in old_refs if r['id'] == item['id']), None)
            native = None
            created = False
            try:
                if delete:
                    # Soft delete preserves already bound conversations and allows recovery.
                    self.config['hidden_presets'] = [*old_hidden, item['id']]
                else:
                    name = self.validate_name(body.get('name'))
                    if any(p['name'] == name and p['id'] != item['id'] for p in presets):
                        raise ValueError('已有同名预设，请换个名字。')
                    prompt = pack(body.get('bio'), body.get('prompt'))
                    if not ref:
                        if item['id'].startswith('native-'):
                            pid = item['id'][7:]
                        else:
                            pid = 'preset-' + uuid.uuid4().hex
                            base = await self.context.persona_manager.get_persona(self.target_persona(body.get('bot_id')))
                            await self.context.persona_manager.create_persona(pid, prompt, tools=deepcopy(base.tools), skills=deepcopy(base.skills))
                            created = True
                        ref = {'id': item['id'], 'name': name, 'persona_id': pid}
                    if not created:
                        native = await self.context.persona_manager.get_persona(ref['persona_id'])
                        await self.context.persona_manager.update_persona(ref['persona_id'], system_prompt=prompt)
                    self.config['custom_presets'] = [r for r in old_refs if r['id'] != item['id']] + [{**ref, 'name': name}]
                self.config.save_config()
            except Exception:
                self.config['custom_presets'] = old_refs
                self.config['hidden_presets'] = old_hidden
                if created:
                    await self.context.persona_manager.delete_persona(ref['persona_id'] if ref else pid)
                elif native is not None:
                    await self.context.persona_manager.update_persona(native.persona_id, system_prompt=native.system_prompt)
                raise
        return {'presets': await self.get_presets(), 'preset_id': item['id'],
                'menu_sync_errors': await self.sync_menus()}

    async def update_preset(self):
        return await self.preset_operation(False)

    async def delete_preset(self):
        return await self.preset_operation(True)

    async def preset_operation(self, delete):
        try:
            return json_response(await self.change_preset(await request.json(default={}), delete))
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('预设修改未完成')
            return error_response('操作未能确认，请保留草稿并重新读取列表核对。', status_code=500)

    async def authorize_qq(self):
        try:
            body = await request.json(default={})
            if (not isinstance(body, dict) or not isinstance(body.get('bot_id'), str)
                    or type(body.get('enabled')) is not bool):
                raise ValueError('请刷新好友人设页面，使用“允许 QQ 编辑人设”开关。')
            bot_id, enabled = body['bot_id'], body['enabled']
            if not any(b['bot_id'] == bot_id for b in self.targets()):
                raise ValueError('未找到该机器人，请刷新页面后重试。')
            # Same lock order as QQ confirmation: command lock, then form lock.
            async with self.qq_commands.lock:
                async with self.lock:
                    existed = 'qq_editor_enabled_bots' in self.config
                    old = list(self.config.get('qq_editor_enabled_bots', []))
                    updated = [bid for bid in old if bid != bot_id]
                    if enabled:
                        updated.append(bot_id)
                    self.config['qq_editor_enabled_bots'] = updated
                    try:
                        self.config.save_config()
                    except Exception:
                        if existed:
                            self.config['qq_editor_enabled_bots'] = old
                        else:
                            self.config.pop('qq_editor_enabled_bots', None)
                        raise
                if not enabled:
                    for drafts in (self.qq_commands.pending, self.qq_commands.waiting_custom):
                        for key in list(drafts):
                            if key[0].split(':', 1)[0] == bot_id:
                                drafts.pop(key)
            return json_response({'bot_id': bot_id, 'enabled': enabled})
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('QQ 人设编辑开关保存失败')
            return error_response('开关未能保存，请刷新页面核对后重试。', status_code=500)

    async def create_preset(self):
        try:
            return json_response(await self.save_preset(await request.json(default={})))
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('保存自定义预设失败')
            return error_response('预设保存未能确认，请重新读取预设列表后核对。', status_code=500)

    async def publish_qq_menu(self, bot_id):
        from botpy.http import Route
        if not any(b['bot_id'] == bot_id for b in self.targets()):
            raise ValueError('请先同步 QQ 机器人，再安装人设菜单。')
        platform = next((p for p in self.context.get_config().get('platform', [])
                         if p.get('id') == bot_id and p.get('enable', True) and p.get('type') == 'qq_official'), None)
        adapter = self.context.get_platform_inst(bot_id) if platform else None
        if adapter is None:
            raise ValueError('这个 QQ 机器人尚未运行，请先启用并连接。')
        async with self.lock:
            http = adapter.client.api._http
            current = await http.request(Route('GET', '/v2/menu'))
            # Fresh QQ bots return {"menu": {}} without a version field.
            if (not isinstance(current, dict) or 'menu' not in current or
                (current['menu'] is not None and not isinstance(current['menu'], dict))):
                raise ValueError('未能确认 QQ 当前菜单，未执行覆盖。')
            desired = merge_persona_menu(current.get('menu'), await self.get_presets())
            if desired == current.get('menu'):
                return {'changed': False, 'version': current.get('version')}
            result = await http.request(Route('PUT', '/v2/menu'), json={'menu': desired})
            if not isinstance(result, dict) or 'version' not in result:
                raise ValueError('QQ 菜单保存结果未能确认，请重新打开聊天核对。')
            return {'changed': True, 'version': result['version']}

    async def qq_menu(self):
        try:
            body = await request.json(default={})
            result = await self.publish_qq_menu(body.get('bot_id'))
            return json_response({'status': 'ok', 'data': result})
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('QQ 人设菜单配置未完成')
            return error_response('QQ 菜单设置未完成，请检查机器人连接与官方菜单接口权限，原人设未修改。', status_code=500)

    def target_persona(self, bot_id):
        if not any(b['bot_id'] == bot_id for b in self.targets()):
            raise ValueError('未找到该机器人，请刷新页面或检查机器人配置。')
        cfg = self.context.get_config(f'{bot_id}:FriendMessage:persona-editor')
        runner = cfg.get('agent_runner', {})
        if runner.get('runner_type') != 'local':
            raise ValueError('这个机器人未使用原生人格，请在原生配置中查看。')
        persona_id = runner.get('config', {}).get('persona', {}).get('persona_id')
        if not persona_id:
            raise ValueError('请先在原生配置中绑定机器人默认人格。')
        return persona_id

    async def snapshot(self, bot_id):
        persona_id = self.target_persona(bot_id)
        persona = await self.context.persona_manager.get_persona(persona_id)
        native = PersonaService.serialize_persona(persona)
        bio, prompt = unpack(native['system_prompt'])
        return {'bot_id': bot_id, 'persona_id': persona_id, 'bio': bio, 'prompt': prompt,
                'revision': revision(native), 'tools': native['tools']}

    async def state(self):
        try:
            await self.reconcile_bots()
            bot_id = request.query.get('bot_id')
            data = {'bots': self.targets(), 'presets': await self.get_presets()}
            if bot_id and any(b['bot_id'] == bot_id for b in data['bots']):
                data['binding'] = await self.binding.describe(bot_id)
                data['current'] = await self.snapshot(bot_id) if data['binding'].get('available') else None
                data['tools'] = [{'name': t.name, 'description': t.description, 'active': t.active}
                                 for t in self.tool_catalog().values()]
                data['model_ready'] = bool(self.context.get_all_providers())
                data['qq_editor_enabled'] = bot_id in self.config.get('qq_editor_enabled_bots', [])
                data['qq_authorized'] = data['qq_editor_enabled']
            return json_response(data)
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('读取人设失败')
            return error_response('读取失败，请刷新页面；若持续失败，请查看本机日志。', status_code=500)

    async def bind_persona(self):
        try:
            result = await self.binding.save(await request.json(default={}))
            return json_response(result)
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('保存机器人与人设绑定失败')
            return error_response('绑定未能确认，请重新读取并核对配置。', status_code=500)

    async def connections(self):
        try:
            bot_id = request.query.get('bot_id')
            bots = self.targets()
            if bot_id and not any(b['bot_id'] == bot_id for b in bots):
                raise ValueError('未找到该 QQ 机器人，请重新选择。')
            result = await connection_summary(self.context, bot_id)
            result['qq'] = {'connected': sum(bool(b['enabled'] and b['connected']) for b in bots), 'total': len(bots)}
            return json_response(result)
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('读取连接状态失败')
            return error_response('无法读取连接状态，请刷新重试。', status_code=500)

    async def save_form(self, body):
        if not isinstance(body, dict):
            raise ValueError('保存内容格式不正确。')
        prompt = pack(body.get('bio'), body.get('prompt'))
        async with self.lock:
            current = await self.snapshot(body.get('bot_id'))
            if body.get('persona_id') != current['persona_id'] or body.get('revision') != current['revision']:
                raise ValueError('人设已在别处修改或绑定已改变。请先保留草稿，再重新读取。')
            config_id, _ = self.binding.profile(current['bot_id'])
            if self.binding.shared(current['persona_id'], config_id):
                raise ValueError('该人设仍被其他配置共用。请先点击“保存绑定”建立独立副本，再编辑。')
            # Never silently edit a persona shared by multiple enabled robots.
            platforms = self.context.get_config().get('platform', [])
            for platform in platforms:
                other_id = platform.get('id')
                if not platform.get('enable', True) or other_id == current['bot_id']:
                    continue
                cfg = self.context.get_config(f'{other_id}:FriendMessage:persona-editor')
                other = cfg.get('agent_runner', {}).get('config', {}).get('persona', {}).get('persona_id')
                if other == current['persona_id']:
                    raise ValueError('该人格被其他机器人共用。请先在原生人格与配置页面复制并独立绑定，再编辑。')
            # Omitted fields preserve tools, skills, example dialogue and error replies.
            native = await self.context.persona_manager.get_persona(current['persona_id'])
            # HTML textareas normalize CRLF. An unchanged form must preserve the
            # stored bytes, including when only the tool selection was changed.
            normalize = lambda text: text.replace('\r\n', '\n').replace('\r', '\n')
            if normalize(native.system_prompt) == normalize(prompt):
                prompt = native.system_prompt
            changes = {'system_prompt': prompt}
            if 'tools' in body:
                tools = body['tools']
                if tools is not None:
                    if not isinstance(tools, list) or any(not isinstance(t, str) for t in tools):
                        raise ValueError('工具选择格式不正确。')
                    allowed = set(self.tool_catalog())
                    allowed.update(current['tools'] or [])
                    if any(t not in allowed for t in tools):
                        raise ValueError('工具列表已改变，请重新读取后选择。')
                    tools = list(dict.fromkeys(tools))
                changes['tools'] = tools
            await self.context.persona_manager.update_persona(persona_id=current['persona_id'], **changes)
            return await self.snapshot(current['bot_id'])

    async def save(self):
        try:
            return json_response(await self.save_form(await request.json(default={})))
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('保存人设失败')
            return error_response('保存未能确认，请保留草稿并重新读取后核对。', status_code=500)
