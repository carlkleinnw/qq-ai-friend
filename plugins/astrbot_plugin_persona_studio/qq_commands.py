"""QQ command adapter over the same native persona form used by the web page."""
import asyncio
import time

from .persona_form import pack

ALIASES = {'自定义人设', '确认人设', '取消人设', '当前人设', 'presets', 'setpersona',
           'confirmpersona', 'cancelpersona', 'currentpersona', '预设人设', '自选人设', '人设列表', '人设设置'}
CANONICAL = {'presets': '人设', 'setpersona': '自定义人设', 'confirmpersona': '确认人设',
             'cancelpersona': '取消人设', 'currentpersona': '当前人设',
             '预设人设': '人设', '自选人设': '人设', '人设列表': '人设', '人设设置': '人设'}


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
        if scope.split(':', 1)[0] != bot_id:
            raise ValueError('消息来源不一致，未执行修改。')
        return scope, bot_id

    def authorize(self, event):
        scope, bot_id = self.source(event)
        if not any(b['bot_id'] == bot_id for b in self.plugin.targets()):
            raise ValueError('未找到这个机器人的人设配置。请在维护窗口先点“同步 QQ 机器人”，再发 /sid 并通过“授权 QQ 私聊”授权自己。')
        self.plugin.target_persona(bot_id)
        allowed = scope in self.plugin.config.get('qq_editor_sessions', [])
        # Full private UMO is scoped to one bot; also check the actual sender.
        if not event.is_admin() and not (allowed and scope.rsplit(':', 1)[-1] == str(event.get_sender_id())):
            raise ValueError('这个私聊尚未获得人设编辑权限。请在本机插件配置中授权此私聊，或使用管理员账号；可发 /sid 查看会话来源。')
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
                    '查看：/当前人设\n确认：/确认人设\n取消：/取消人设\n'
                    '先预览，确认后保存。修改与网页同步，不更新 QQ 公开简介。\n'
                    '首次设置：维护窗口“同步 QQ 机器人”，然后发 /sid 并通过“授权 QQ 私聊”授权自己；列表可直接查看，保存需授权。')
            if command == '自定义人设' and not content:
                try:
                    self.authorize(event)
                except ValueError:
                    return ('请在指令后填写内容，例如：/自定义人设 你是一位温柔细心的 AI 好友，说话简短自然。\n'
                            '先预览，再确认保存；尚未授权时请从维护窗口完成 QQ 同步与私聊授权。')
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
                        await self.plugin.save_form(pending['form'])
                    except ValueError:
                        self.pending.pop(key, None)
                        return '未保存：人设、绑定或共享状态已改变。请重新选择预设或发送自定义内容，再确认。'
                    self.pending.pop(key, None)
                    return (f'已保存“{pending["label"]}”，与网页端同步，只修改这个机器人的默认人设。\n'
                            '音色、模型和长期记忆保持原样；后续新消息生效。可发送 /new 开始新对话。')
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
                pack('', text)
            except ValueError as exc:
                return str(exc)
            self.waiting_custom.pop(key, None)
            self.pending[key] = {'expires': time.monotonic() + 600, 'label': '自定义人设',
                                 'form': {**waiting['form'], 'bio': '', 'prompt': text}}
            return ('待确认：自定义人设\n' + self.preview('', text) +
                    '\n\n当前人设尚未改变。请从“人设设置”点击“确认保存”或“取消修改”。')

    @staticmethod
    def preview(bio, prompt):
        text = ('简介：' + bio + '\n\n' if bio else '') + prompt
        return text if len(text) <= 1200 else text[:1200] + '\n（预览已截短，确认时仍保存完整内容。）'
