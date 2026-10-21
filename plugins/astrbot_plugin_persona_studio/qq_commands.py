"""QQ command adapter over the same native persona form used by the web page."""
import asyncio
import time

from .persona_form import pack

ALIASES = {'自定义人设', '确认人设', '取消人设', '当前人设', 'presets', 'setpersona',
           'confirmpersona', 'cancelpersona', 'currentpersona'}
CANONICAL = {'presets': '人设', 'setpersona': '自定义人设', 'confirmpersona': '确认人设',
             'cancelpersona': '取消人设', 'currentpersona': '当前人设'}


class QQPersonaCommands:
    def __init__(self, plugin):
        self.plugin = plugin
        self.pending = {}
        self.lock = asyncio.Lock()

    def authorize(self, event):
        if not event.is_private_chat():
            raise ValueError('请在与机器人的 QQ 私聊中设置人设，群聊中不执行修改。')
        scope = str(event.unified_msg_origin)
        bot_id = event.get_platform_id()
        if scope.split(':', 1)[0] != bot_id:
            raise ValueError('消息来源不一致，未执行修改。')
        self.plugin.target_persona(bot_id)
        allowed = scope in self.plugin.config.get('qq_editor_sessions', [])
        # Full private UMO is scoped to one bot; also check the actual sender.
        if not event.is_admin() and not (allowed and scope.rsplit(':', 1)[-1] == str(event.get_sender_id())):
            raise ValueError('这个私聊尚未获得人设编辑权限。请在本机插件配置中授权此私聊，或使用管理员账号；可发 /sid 查看会话来源。')
        return scope, bot_id

    async def execute(self, event):
        try:
            scope, bot_id = self.authorize(event)
            parts = event.get_message_str().strip().lstrip('/／').split(maxsplit=1)
            command = CANONICAL.get(parts[0], parts[0]) if parts else '人设'
            content = parts[1].strip() if len(parts) > 1 else ''
            key = (scope, str(event.get_sender_id()))
            async with self.lock:
                now = time.monotonic()
                self.pending = {k: v for k, v in self.pending.items() if v['expires'] > now}
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
                    title = next((p['name'] for p in self.plugin.presets
                                  if p['bio'] == current['bio'] and p['prompt'] == current['prompt']), '自定义 / 已编辑人设')
                    return f'当前默认人设：{title}\n' + self.preview(current['bio'], current['prompt'])
                if command == '人设' and content in ('', '列表', '帮助'):
                    lines = ['可选预设：'] + [f'{i}. {p["name"]}：{p["summary"]}' for i, p in enumerate(self.plugin.presets, 1)]
                    return '\n'.join(lines) + ('\n\n选择：/人设 5 或 /人设 体贴甜蜜女友\n'
                        '自定义：/自定义人设 你希望的背景、性格和说话方式\n'
                        '查看：/当前人设\n确认：/确认人设\n取消：/取消人设\n'
                        '先预览，确认后保存。修改与网页同步，作用于这个机器人的默认人设；不更新 QQ 公开简介。')
                if command == '人设':
                    preset = None
                    if content.isascii() and content.isdigit() and len(content) < 4:
                        index = int(content) - 1
                        if 0 <= index < len(self.plugin.presets):
                            preset = self.plugin.presets[index]
                    else:
                        preset = next((p for p in self.plugin.presets if content in (p['id'], p['name'])), None)
                    if not preset:
                        return '未找到这个预设，请发 /人设 查看编号和名称。当前人设未修改。'
                    bio, prompt, label = preset['bio'], preset['prompt'], preset['name']
                elif command == '自定义人设':
                    if not content:
                        return '请在指令后填写内容，例如：/自定义人设 你是一位温柔细心的 AI 好友，说话简短自然。'
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
    def preview(bio, prompt):
        text = ('简介：' + bio + '\n\n' if bio else '') + prompt
        return text if len(text) <= 1200 else text[:1200] + '\n（预览已截短，确认时仍保存完整内容。）'
