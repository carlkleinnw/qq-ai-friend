"""Robot-to-persona bindings live in AstrBot's existing config profiles."""
from copy import deepcopy
import uuid


class PersonaBinding:
    def __init__(self, plugin):
        self.plugin = plugin

    def profile(self, bot_id):
        if not isinstance(bot_id, str) or not any(b['bot_id'] == bot_id for b in self.plugin.targets()):
            raise ValueError('未找到该机器人，请刷新列表。')
        manager = self.plugin.context.astrbot_config_mgr
        config_id = manager.ucr.umop_to_conf_id.get(bot_id + '::')
        if not config_id or config_id == 'default' or config_id not in manager.confs:
            raise ValueError('尚未建立机器人独立配置，请在 QQ 连接中设置独立配置。')
        # A profile shared by robot-wide routes cannot be edited as one robot's setting.
        if any(key != bot_id + '::' and value == config_id for key, value in manager.ucr.umop_to_conf_id.items()):
            raise ValueError('该配置被其他连接或会话共用，请先在 QQ 连接中设置独立配置。')
        config = manager.confs[config_id]
        if config.get('agent_runner', {}).get('runner_type', 'local') != 'local':
            raise ValueError('当前使用外部 Agent，人设由该 Agent 管理，请进入 Agent 连接设置。')
        return config_id, config

    def shared(self, persona_id, config_id):
        return any(cid != config_id and cfg.get('agent_runner', {}).get('config', {}).get('persona', {}).get('persona_id') == persona_id
                   for cid, cfg in self.plugin.context.astrbot_config_mgr.confs.items())

    async def describe(self, bot_id):
        personas = await self.plugin.context.persona_manager.get_all_personas()
        names = {ref['persona_id']: ref['name'] for ref in self.plugin.config.get('custom_presets', [])}
        for bot in self.plugin.targets():
            try:
                _, cfg = self.profile(bot['bot_id'])
                pid = cfg.get('agent_runner', {}).get('config', {}).get('persona', {}).get('persona_id')
                if pid:
                    names.setdefault(pid, bot.get('name', bot['bot_id']) + '的人设')
            except ValueError:
                pass
        choices = [{'persona_id': p.persona_id, 'name': names.get(p.persona_id, p.persona_id)} for p in personas]
        result = {'choices': choices, 'editable': False, 'persona_id': None, 'config_id': None}
        try:
            config_id, config = self.profile(bot_id)
            pid = config.get('agent_runner', {}).get('config', {}).get('persona', {}).get('persona_id')
            result.update(config_id=config_id, persona_id=pid, editable=True,
                          available=any(p.persona_id == pid for p in personas),
                          shared=self.shared(pid, config_id))
            if not result['available']:
                result['message'] = '尚未设置可用人设，请选择一个人设并保存绑定。'
        except ValueError as exc:
            result['message'] = str(exc)
        return result

    async def save(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('persona_id'), str) or not body['persona_id']:
            raise ValueError('请选择一个已有的人设。')
        async with self.plugin.lock:
            config_id, config = self.profile(body.get('bot_id'))
            old = deepcopy(config['agent_runner'])
            current_id = old.get('config', {}).get('persona', {}).get('persona_id')
            if body.get('config_id') != config_id or body.get('expected_persona_id') != current_id:
                raise ValueError('绑定已在别处修改，请重新读取后再保存。')
            manager = self.plugin.context.persona_manager
            chosen = await manager.get_persona(body['persona_id'])
            copied = self.shared(chosen.persona_id, config_id)
            target_id = 'bound-' + uuid.uuid4().hex[:16] if copied else chosen.persona_id
            created = False
            writing = False
            try:
                if copied:
                    await manager.create_persona(target_id, chosen.system_prompt, tools=deepcopy(chosen.tools),
                                                 skills=deepcopy(chosen.skills), begin_dialogs=deepcopy(chosen.begin_dialogs),
                                                 custom_error_message=chosen.custom_error_message)
                    created = True
                latest_id, latest_config = self.profile(body['bot_id'])
                if latest_id != config_id or latest_config is not config or config['agent_runner'] != old:
                    # Native configuration writes are outside the plugin's lock.
                    raise ValueError('配置已在别处修改，请重新读取后再绑定。')
                updated = deepcopy(old)
                updated.setdefault('config', {}).setdefault('persona', {})['persona_id'] = target_id
                writing = True
                config['agent_runner'] = updated
                config.save_config()
                await self.plugin.registry.ensure_companion(next(b for b in self.plugin.targets() if b['bot_id'] == body['bot_id']))
                await self.plugin.context.reload_pipeline_scheduler(config_id)
            except Exception:
                if not writing:
                    if created:
                        await manager.delete_persona(target_id)
                    raise
                config['agent_runner'] = old
                try:
                    config.save_config()
                    await self.plugin.context.reload_pipeline_scheduler(config_id)
                except Exception:
                    self.plugin.logger.exception('绑定恢复未完成，请核对原生配置')
                    # Keep a newly created persona if persisted routing may still reference it.
                    raise RuntimeError('绑定保存和恢复未能确认，请到 QQ 连接与配置页面核对。')
                if created:
                    await manager.delete_persona(target_id)
                raise
            return {'bot_id': body['bot_id'], 'config_id': config_id, 'persona_id': target_id, 'copied': copied}
