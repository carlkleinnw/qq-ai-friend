"""Discover saved QQ adapters and bind new ones using AstrBot's native managers."""
import asyncio
from copy import deepcopy
import hashlib

QQ_TYPES = {'qq_official', 'qq_official_webhook'}


class BotRegistry:
    def __init__(self, plugin):
        self.plugin = plugin
        self.lock = asyncio.Lock()
        self.errors = {}

    def targets(self):
        context = self.plugin.context
        old = {b['bot_id']: b for b in self.plugin.config.get('bots', [])}
        result = []
        for platform in context.get_config().get('platform', []):
            if platform.get('type') not in QQ_TYPES or not platform.get('id'):
                continue
            bot_id = platform['id']
            name = platform.get('name') or old.get(bot_id, {}).get('name') or bot_id
            connected = False
            try:
                adapter = context.get_platform_inst(bot_id)
                robot = adapter.client.robot if adapter else None
                if robot:
                    name = robot.name or name
                    connected = bool(platform.get('enable', True))
            except (AttributeError, RuntimeError):
                pass  # robot metadata is populated after QQ's READY event.
            result.append({'bot_id': bot_id, 'name': name, 'enabled': platform.get('enable', True),
                           'connected': connected, 'error': self.errors.get(bot_id, '')})
        return result

    async def reconcile(self):
        async with self.lock:
            for bot in self.targets():
                try:
                    await self.ensure_route(bot)
                    await self.ensure_companion(bot)
                    self.errors.pop(bot['bot_id'], None)
                except Exception:
                    self.plugin.logger.exception('机器人独立人设绑定未完成：%s', bot['bot_id'])
                    self.errors[bot['bot_id']] = '机器人配置同步未完成，请查看本机日志后重试。'

    async def ensure_companion(self, bot):
        """Use the pinned companion plugin's own config-creation operation.

        Without this adapter, its enabled multi-persona mode falls back to the
        primary persona for newly added native IDs. No relationship data is copied.
        """
        if not bot['enabled']:
            return
        lookup = getattr(self.plugin.context, 'get_registered_star', None)
        metadata = lookup('astrbot_plugin_private_companion') if lookup else None
        companion = metadata.star_cls if metadata and metadata.activated else None
        if not companion or not getattr(companion, 'enable_multi_persona_mode', False):
            return
        pid = self.plugin.target_persona(bot['bot_id'])
        if pid == companion._primary_persona_id():
            return
        ids = companion._configured_multi_persona_ids()
        if pid not in ids:
            # Keep configuration storage under the companion plugin's schema;
            # its own operation below owns profile creation and persistence.
            basic = companion.config['basic_config']
            old_ids = deepcopy(basic.get('multi_persona_ids', []))
            basic['multi_persona_ids'] = [*ids, pid]
            try:
                companion.config.save_config()
            except Exception:
                basic['multi_persona_ids'] = old_ids
                raise
            companion.multi_persona_ids = [*ids, pid]
        if not companion._persona_config_exists(pid):
            result = await companion._create_persona_config_async(
                pid, bot_name=bot['name'], mode='copy', source_persona_id=companion._primary_persona_id())
            if not result.get('ok'):
                raise ValueError('陪伴插件独立人格配置尚未建立。')

    async def ensure_route(self, bot):
        context = self.plugin.context
        acm = context.astrbot_config_mgr
        bot_id = bot['bot_id']
        route = bot_id + '::'
        routes = acm.ucr.umop_to_conf_id
        if routes.get(route) in acm.confs:
            return  # Never replace an existing user's routing or persona.
        # AstrBotConfig carries a process lock; clone its mapping, not the object.
        cfg = deepcopy(dict(context.get_config(f'{bot_id}:FriendMessage:persona-editor')))
        runner = cfg.get('agent_runner', {})
        if runner.get('runner_type') != 'local':
            raise ValueError('机器人使用外部 Agent，请通过原生配置管理人设。')
        base_id = runner.get('config', {}).get('persona', {}).get('persona_id') or 'default'
        base = await context.persona_manager.get_persona(base_id)
        pid = 'bot-' + hashlib.sha256(bot_id.encode()).hexdigest()[:12]
        created_persona = False
        created_conf = None
        old_routes = None
        try:
            try:
                await context.persona_manager.get_persona(pid)
            except ValueError:
                await context.persona_manager.create_persona(
                    pid, base.system_prompt, tools=deepcopy(base.tools), skills=deepcopy(base.skills),
                    begin_dialogs=deepcopy(base.begin_dialogs), custom_error_message=base.custom_error_message)
                created_persona = True
            # Reuse an unfinished binding after restart instead of making duplicate profiles.
            conf_id = next((key for key, value in acm.confs.items() if key != 'default' and
                            value.get('agent_runner', {}).get('config', {}).get('persona', {}).get('persona_id') == pid), None)
            if not conf_id:
                for key in ('platform', 'provider', 'provider_sources', 'dashboard'):
                    cfg.pop(key, None)
                cfg['agent_runner']['config'].setdefault('persona', {})['persona_id'] = pid
                created_conf = conf_id = await acm.create_conf(cfg, name=bot['name'])
            # Same operation used by the native ConfigProfileService. A saved
            # route alone cannot receive messages without its native scheduler.
            await context.reload_pipeline_scheduler(conf_id)
            # Profile/persona I/O yields to native dashboard edits. Merge the
            # latest routes rather than a snapshot taken before those awaits.
            old_routes = dict(acm.ucr.umop_to_conf_id)
            if old_routes.get(route) in acm.confs:
                return
            # Keep per-session rules ahead of the new bot-wide default, followed
            # by existing fallback rules. Other bots retain their relative order.
            specific = {k: v for k, v in old_routes.items() if k.split(':', 1)[0] == bot_id and k != route}
            remainder = {k: v for k, v in old_routes.items() if k not in specific and k != route}
            await acm.ucr.update_routing_data({**specific, route: conf_id, **remainder})
        except Exception:
            if old_routes is not None:
                acm.ucr.umop_to_conf_id = old_routes
            if created_conf:
                await acm.delete_conf(created_conf)
            if created_persona:
                await context.persona_manager.delete_persona(pid)
            raise
