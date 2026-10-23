"""QQ command adapter over the same native persona form used by the web page."""
import asyncio
import time

from .persona_form import pack

ALIASES = {'自定义人设', '确认人设', '取消人设', '当前人设', 'presets', 'setpersona',
           'confirmpersona', 'cancelpersona', 'currentpersona', '预设人设', '自选人设', '人设列表', '人设设置'}
CANONICAL = {'presets': '人设', 'setpersona': '自定义人设', 'confirmpersona': '确认人设',
             'cancelpersona': '取消人设', 'currentpersona': '当前人设',
             '预设人设': '人设', '自选人设': '人设', '人设列表': '人设', '人设设置': '人设'}
LIBRARY_COMMANDS = {'newpersona': '新建人设', 'editpersona': '编辑人设',
                    'renamepersona': '重命名人设', 'deletepersona': '删除人设', 'showpersona': '查看人设'}
CANONICAL.update(LIBRARY_COMMANDS)
ALIASES.update(LIBRARY_COMMANDS)
ALIASES.update(LIBRARY_COMMANDS.values())


class QQPersonaCommands:
    def __init__(self, plugin):
        self.plugin = plugin
        self.pending = {}
        self.waiting_custom = {}
        self.lock = asyncio.Lock()

    def source(self, event):
        if not event.is_private_chat():
            raise ValueError('请在与机器人的 QQ 私聊中设置人设，群聊中不执行修改。')
        scope = str(event.unified_msg_origin)
        bot_id = event.get_platform_id()
        if scope != f'{bot_id}:FriendMessage:{event.get_sender_id()}':
            raise ValueError('消息来源不一致，未执行修改。')
        return scope, bot_id

    def authorize(self, event):
        scope, bot_id = self.source(event)
        if not any(b['bot_id'] == bot_id for b in self.plugin.targets()):
            raise ValueError('未找到这个机器人的人设配置。请在本机好友人设页面刷新机器人。')
        self.plugin.target_persona(bot_id)
        if bot_id not in self.plugin.config.get('qq_editor_enabled_bots', []):
            raise ValueError('这个机器人的 QQ 人设编辑开关已关闭。请在电脑“好友人设”页面选择这个机器人，打开“允许 QQ 编辑人设”开关后重试。')
        return scope, bot_id

    async def execute(self, event):
        try:
            scope, bot_id = self.source(event)
            parts = event.get_message_str().strip().lstrip('/／').split(maxsplit=1)
            command = CANONICAL.get(parts[0], parts[0]) if parts else '人设'
            content = parts[1].strip() if len(parts) > 1 else ''
            presets = await self.plugin.get_presets()
            # Public preset/help text must not depend on a newly scanned bot
            # already having a native route or an authorized editor session.
            # Current persona, drafts and all writes still pass authorization.
            if command == '人设' and content in ('', '列表', '帮助'):
                lines = ['可选预设：'] + [f'{i}. {p["name"]}：{p["summary"]}' for i, p in enumerate(presets, 1)]
                return '\n'.join(lines) + ('\n\n选择：/人设 5 或 /人设 体贴甜蜜女友\n'
                    '自定义：/自定义人设 你希望的背景、性格和说话方式\n'
                    '新建到人设库：/新建人设 名称 | 人设内容\n'
                    '查看库内人设：/查看人设 名称或编号\n'
                    '编辑：/编辑人设 名称 | 新内容\n'
                    '改名：/重命名人设 旧名 | 新名\n删除：/删除人设 名称\n'
                    '查看：/当前人设\n确认：/确认人设\n取消：/取消人设\n'
                    '先预览，确认后保存。修改与网页同步，不更新 QQ 公开简介。\n'
                    '首次设置：电脑“好友人设”页面选择这个机器人，打开“允许 QQ 编辑人设”开关。无需复制会话标识；列表随时可查看。')
            if command == '自定义人设' and not content:
                try:
                    self.authorize(event)
                except ValueError:
                    return ('请在指令后填写内容，例如：/自定义人设 你是一位温柔细心的 AI 好友，说话简短自然。\n'
                            '先预览，再确认保存；请先在电脑“好友人设”页面打开这个机器人的“允许 QQ 编辑人设”开关。')
                async with self.lock:
                    key = (scope, str(event.get_sender_id()))
                    self.pending.pop(key, None)
                    now = time.monotonic()
                    self.waiting_custom = {k: v for k, v in self.waiting_custom.items() if v['expires'] > now}
                    self.waiting_custom[key] = {'expires': now + 600, 'form': await self.plugin.snapshot(bot_id)}
                return ('请直接发送你希望的人设描述，作为下一条文字消息，例如“温柔细心，说话简短自然”。\n'
                        '我会先给你预览，再通过“人设设置 → 确认保存”应用。当前人设尚未改变。\n'
                        '十分钟内有效；“取消修改”可退出，发送其他斜杠指令也会退出输入。')
            scope, bot_id = self.authorize(event)
            key = (scope, str(event.get_sender_id()))
            async with self.lock:
                self.authorize(event)  # Recheck after a concurrent switch change.
                now = time.monotonic()
                self.pending = {k: v for k, v in self.pending.items() if v['expires'] > now}
                self.waiting_custom.pop(key, None)
                if command == '取消人设':
                    self.pending.pop(key, None)
                    return '已取消人设草稿，当前人设未因取消而改变。'
                if command == '确认人设':
                    pending = self.pending.get(key)
                    if not pending:
                        return '没有待确认的人设，或草稿已过期。请先发 /人设 选择预设，或发 /自定义人设 内容。'
                    try:
                        action = pending.get('action', 'apply')
                        if action == 'create':
                            result = await self.plugin.save_preset(pending['form'])
                        elif action in ('update', 'delete'):
                            result = await self.plugin.change_preset(pending['form'], delete=action == 'delete')
                        else:
                            await self.plugin.save_form(pending['form'])
                    except ValueError as exc:
                        self.pending.pop(key, None)
                        return f'未保存：{exc} 请重新读取并操作。'
                    self.pending.pop(key, None)
                    if action != 'apply':
                        verb = {'create': '已创建', 'update': '已更新', 'delete': '已删除'}[action]
                        warning = 'QQ 菜单同步尚未完成，可从网页重试。' if result.get('menu_sync_errors') else 'QQ 菜单接口已确认。'
                        return f'{verb}人设“{pending["label"]}”，网页人设库已同步。{warning}\n当前已应用人设保留；要切换请发 /人设 名称，再确认。'
                    return (f'已保存“{pending["label"]}”，与网页端同步，只修改这个机器人的默认人设。\n'
                            '音色、模型和长期记忆保持原样；后续新消息生效。可发送 /new 开始新对话。')
                if command in LIBRARY_COMMANDS.values():
                    return await self.library_draft(command, content, presets, bot_id, key, now)
                current = await self.plugin.snapshot(bot_id)
                if command == '当前人设':
                    title = next((p['name'] for p in presets
                                  if p['bio'] == current['bio'] and p['prompt'] == current['prompt']), '自定义 / 已编辑人设')
                    return f'当前默认人设：{title}\n' + self.preview(current['bio'], current['prompt'])
                if command == '人设':
                    preset = None
                    if content.isascii() and content.isdigit() and len(content) < 4:
                        index = int(content) - 1
                        if 0 <= index < len(presets):
                            preset = presets[index]
                    else:
                        preset = next((p for p in presets if content in (p['id'], p['name'])), None)
                    if not preset:
                        return '未找到这个预设，请发 /人设 查看编号和名称。当前人设未修改。'
                    bio, prompt, label = preset['bio'], preset['prompt'], preset['name']
                elif command == '自定义人设':
                    bio, prompt, label = '', content, '自定义人设'
                else:
                    return '请发 /人设 查看用法。'
                pack(bio, prompt)  # Same validation as the web form, before creating a draft.
                self.pending[key] = {'expires': now + 600, 'label': label,
                                     'form': {**current, 'bio': bio, 'prompt': prompt}}
                return (f'待确认：{label}\n' + self.preview(bio, prompt) +
                        '\n\n当前人设尚未改变。10 分钟内发送 /确认人设 保存，或 /取消人设 放弃。'
                        '\n保存会替换这个机器人的默认人设，共用该默认人设的会话会一起生效；不改变音色和长期记忆。')
        except ValueError as exc:
            return str(exc)
        except Exception:
            self.plugin.logger.exception('QQ 人设指令未完成')
            return '操作未能确认，请到本机人设页面核对当前内容后再操作。'

    @staticmethod
    def find_preset(content, presets):
        # Exact ID/name wins over numeric positions, so a persona named "6" is reachable.
        item = next((p for p in presets if content in (p['id'], p['name'])), None)
        if item is None and content.isascii() and content.isdigit() and len(content) < 4:
            index = int(content) - 1
            if 0 <= index < len(presets):
                item = presets[index]
        return item

    async def library_draft(self, command, content, presets, bot_id, key, now):
        if not content:
            return ('人设库管理用法：\n/新建人设 名称 | 人设内容\n/查看人设 名称\n'
                    '/编辑人设 名称 | 新内容\n/重命名人设 旧名 | 新名\n/删除人设 名称\n'
                    '名称也可以用 /人设 列表中的编号或完整标识。修改均先预览，再 /确认人设。')
        target, separator, value = content.partition('|')
        target, value = target.strip(), value.strip()
        if command == '新建人设':
            self.plugin.validate_name(target)
            if not separator:
                self.pending.pop(key, None)
                self.waiting_custom[key] = {'expires': now + 600, 'action': 'create',
                                            'form': {'bot_id': bot_id, 'name': target, 'bio': ''}}
                return f'请直接发送“{target}”的人设内容，下一条文字将生成预览。确认后保存到人设库，当前人设保留。'
            if any(p['name'] == target for p in presets):
                raise ValueError('已有同名预设，请换个名字。')
            body = {'bot_id': bot_id, 'name': target, 'bio': '', 'prompt': value}
            action, label = 'create', target
        else:
            item = self.find_preset(target, presets)
            if item is None:
                raise ValueError('未找到这个预设，请发 /人设 查看编号和名称。')
            if command == '查看人设':
                return f'人设：{item["name"]}\n标识：{item["id"]}\n' + self.preview(item['bio'], item['prompt'])
            body = {**item, 'preset_id': item['id'], 'bot_id': bot_id}
            action, label = 'update', item['name']
            if command == '删除人设':
                action = 'delete'
            elif not separator or not value:
                raise ValueError(f'请用 /{command} 名称 | 新内容（改名时填写新名字）。')
            elif command == '编辑人设':
                body['prompt'] = value
            elif command == '重命名人设':
                body['name'] = label = value
        if action != 'delete':
            self.plugin.validate_name(body['name'])
            pack(body['bio'], body['prompt'])
        self.pending[key] = {'expires': now + 600, 'action': action, 'label': label, 'form': body}
        preview = '删除后从 QQ 和网页人设库移除，已应用人设和聊天记录保留。' if action == 'delete' else self.preview(body['bio'], body['prompt'])
        return f'待确认：{command}“{label}”\n{preview}\n\n当前人设保留。10 分钟内 /确认人设 保存到人设库，或 /取消人设 放弃。'

    async def consume_custom(self, event):
        key = (str(event.unified_msg_origin), str(event.get_sender_id()))
        async with self.lock:
            waiting = self.waiting_custom.get(key)
            if not waiting:
                return None
            text = event.get_message_str().strip()
            raw = getattr(getattr(event, 'message_obj', None), 'message_str', text).lstrip()
            parsed = getattr(event, 'get_extra', lambda key, default=None: default)('parsed_params', None)
            if (waiting['expires'] <= time.monotonic() or raw.startswith(('/', '／')) or
                parsed is not None):
                self.waiting_custom.pop(key, None)
                return None
            if not text:
                return '请发送文字描述，或从人设设置中取消修改。'
            try:
                self.authorize(event)
                if waiting.get('action') == 'create':
                    self.plugin.validate_name(waiting['form']['name'])
                pack('', text)
            except ValueError as exc:
                return str(exc)
            self.waiting_custom.pop(key, None)
            self.pending[key] = {'expires': time.monotonic() + 600,
                                 'action': waiting.get('action', 'apply'),
                                 'label': waiting['form'].get('name', '自定义人设'),
                                 'form': {**waiting['form'], 'bio': '', 'prompt': text}}
            label = waiting['form'].get('name', '自定义人设')
            return (f'待确认：{label}\n' + self.preview('', text) +
                    '\n\n当前人设尚未改变。请从“人设设置”点击“确认保存”或“取消修改”。')

    @staticmethod
    def preview(bio, prompt):
        text = ('简介：' + bio + '\n\n' if bio else '') + prompt
        return text if len(text) <= 1200 else text[:1200] + '\n（预览已截短，确认时仍保存完整内容。）'
