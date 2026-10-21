"""Thin native Plugin View adapter; persona routing and persistence stay upstream."""
import asyncio
import json
import uuid
from pathlib import Path

from astrbot.api.star import Star, Context
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.web import request, json_response, error_response
from astrbot.dashboard.services.persona_service import PersonaService

from .persona_form import pack, unpack, revision
from .qq_commands import QQPersonaCommands, ALIASES
from .qq_menu import merge_persona_menu

PLUGIN = 'astrbot_plugin_persona_studio'


class PersonaStudio(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.lock = asyncio.Lock()
        self.presets = json.loads((Path(__file__).parent / 'presets.json').read_text(encoding='utf-8'))
        self.qq_commands = QQPersonaCommands(self)
        for endpoint, handler, method in [('state', self.state, 'GET'), ('save', self.save, 'POST'),
                                          ('qq-menu', self.qq_menu, 'POST'), ('presets', self.create_preset, 'POST')]:
            context.register_web_api(f'/{PLUGIN}/{endpoint}', handler, [method], 'AI好友人设编辑')

    @filter.command('人设', alias=ALIASES, priority=100000)
    async def qq_persona_command(self, event: AstrMessageEvent):
        """在授权的 QQ 私聊中选择、自定义、预览和确认人设。"""
        event.should_call_llm(False)
        yield event.plain_result(await self.qq_commands.execute(event)).use_t2i(False)
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=99999)
    async def qq_persona_custom_input(self, event: AstrMessageEvent):
        reply = await self.qq_commands.consume_custom(event)
        if reply is None:
            return
        event.should_call_llm(False)
        yield event.plain_result(reply).use_t2i(False)
        event.stop_event()

    def targets(self):
        return self.config.get('bots', [])

    async def get_presets(self):
        result = list(self.presets)
        for reference in self.config.get('custom_presets', []):
            try:
                persona = await self.context.persona_manager.get_persona(reference['persona_id'])
            except ValueError:
                self.logger.warning('自定义预设对应的原生人格已删除，已跳过该索引。')
                continue
            bio, prompt = unpack(persona.system_prompt)
            result.append({'id': reference['id'], 'name': reference['name'],
                           'bio': bio, 'prompt': prompt, 'summary': '自定义预设，可预览后选择。'})
        return result

    async def save_preset(self, body):
        if not isinstance(body, dict):
            raise ValueError('预设内容格式不正确。')
        name = body.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('请给人设取一个名字。')
        name = name.strip()
        if (any(ord(c) < 32 for c in name) or
            sum(2 if ord(c) > 127 else 1 for c in name) > 14):
            raise ValueError('名称最多七个汉字或十四个英文字母，不能包含换行。')
        prompt = pack(body.get('bio'), body.get('prompt'))
        async with self.lock:
            presets = await self.get_presets()
            if any(p['name'] == name for p in presets):
                raise ValueError('已有同名预设，请换个名字。')
            suffix = uuid.uuid4().hex
            reference = {'id': 'custom-' + suffix, 'name': name, 'persona_id': 'preset-' + suffix}
            old = list(self.config.get('custom_presets', []))
            await self.context.persona_manager.create_persona(reference['persona_id'], prompt, tools=[], skills=[])
            try:
                self.config['custom_presets'] = [*old, reference]
                self.config.save_config()
            except Exception:
                self.config['custom_presets'] = old
                await self.context.persona_manager.delete_persona(reference['persona_id'])
                raise
        sync_errors = []
        for bot in self.targets():
            try:
                await asyncio.wait_for(self.publish_qq_menu(bot['bot_id']), timeout=15)
            except Exception:
                self.logger.exception('预设已保存，QQ 菜单同步尚未完成')
                sync_errors.append(bot.get('name', bot['bot_id']))
        return {'preset_id': reference['id'], 'presets': await self.get_presets(), 'menu_sync_errors': sync_errors}

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
                'revision': revision(native)}

    async def state(self):
        try:
            bot_id = request.query.get('bot_id')
            data = {'bots': self.targets(), 'presets': await self.get_presets()}
            if bot_id:
                data['current'] = await self.snapshot(bot_id)
            return json_response(data)
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('读取人设失败')
            return error_response('读取失败，请刷新页面；若持续失败，请查看本机日志。', status_code=500)

    async def save_form(self, body):
        if not isinstance(body, dict):
            raise ValueError('保存内容格式不正确。')
        prompt = pack(body.get('bio'), body.get('prompt'))
        async with self.lock:
            current = await self.snapshot(body.get('bot_id'))
            if body.get('persona_id') != current['persona_id'] or body.get('revision') != current['revision']:
                raise ValueError('人设已在别处修改或绑定已改变。请先保留草稿，再重新读取。')
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
            await self.context.persona_manager.update_persona(persona_id=current['persona_id'], system_prompt=prompt)
            return await self.snapshot(current['bot_id'])

    async def save(self):
        try:
            return json_response(await self.save_form(await request.json(default={})))
        except ValueError as exc:
            return error_response(str(exc))
        except Exception:
            self.logger.exception('保存人设失败')
            return error_response('保存未能确认，请保留草稿并重新读取后核对。', status_code=500)
