"""Whitelisted configuration status; no credentials or network probes."""


async def connection_summary(context, bot_id=None):
    umo = f'{bot_id}:FriendMessage:persona-editor' if bot_id else None
    config = context.get_config(umo)
    runner = config.get('agent_runner', {})
    kind = runner.get('runner_type', 'local')
    settings = runner.get('config', {})
    profile_id = context.astrbot_config_mgr.ucr.get_conf_id_for_umop(umo) if umo else None
    agent = {'type': kind, 'status': 'local', 'tested': False}
    model = {'id': '', 'status': 'unconfigured', 'tested': False}
    if kind == 'local':
        model_id = settings.get('model', {}).get('provider_id', '')
        provider = context.get_provider_by_id(model_id) if model_id else await context.get_using_provider_async(umo)
        model['id'] = model_id or (provider.meta().id if provider else '')
        model['status'] = ('disabled' if not config.get('provider_settings', {}).get('enable', True)
                           else 'configured' if provider else 'unavailable' if model_id else 'unconfigured')
    else:
        required = {'dify': ('dify_api_key', 'dify_api_base'),
                    'coze': ('coze_api_key', 'bot_id', 'coze_api_base'),
                    'dashscope': ('dashscope_api_key', 'dashscope_app_id'),
                    'deerflow': ('deerflow_api_base',)}.get(kind)
        agent['status'] = ('configured' if all(settings.get(key) for key in required) else 'incomplete') if required else 'unsupported'
        model['status'] = 'external'
    return {'config_id': profile_id or 'default', 'model': model, 'agent': agent}
