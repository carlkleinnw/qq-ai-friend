"""Thin native Plugin View adapter; persona routing and persistence stay upstream."""
import asyncio
import json
from pathlib import Path

from astrbot.api.star import Star, Context
from astrbot.api.web import request, json_response, error_response
from astrbot.dashboard.services.persona_service import PersonaService

from .persona_form import pack, unpack, revision

PLUGIN = 'astrbot_plugin_persona_studio'


class PersonaStudio(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.lock = asyncio.Lock()
        self.presets = json.loads((Path(__file__).parent / 'presets.json').read_text(encoding='utf-8'))
        for endpoint, handler, method in [('state', self.state, 'GET'), ('save', self.save, 'POST')]:
            context.register_web_api(f'/{PLUGIN}/{endpoint}', handler, [method], 'AI好友人设编辑')

    def targets(self):
        return self.config.get('bots', [])

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
            data = {'bots': self.targets(), 'presets': self.presets}
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
