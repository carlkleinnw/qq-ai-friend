const $ = (id) => document.getElementById(id);
const bridge = window.AstrBotPluginView;
let current = null;
let presets = [];
let pendingAction = null;
let busy = false;
const changed = () => current && ($('bio').value !== current.bio || $('prompt').value !== current.prompt);
function status(message, error = false) {
  $('status').textContent = message;
  $('status').dataset.error = String(error);
}
function counts() {
  $('bio-count').textContent = `${$('bio').value.length} / 1000`;
  $('prompt-count').textContent = `${$('prompt').value.length} / 20000`;
  $('dirty').textContent = changed() ? '有未保存的修改' : '未修改';
}
function fill(bio, prompt) {
  $('bio').value = bio;
  $('prompt').value = prompt;
  counts();
}
function guard(action) {
  if (!changed()) return action();
  pendingAction = action;
  $('confirm').hidden = false;
  $('confirm-no').focus();
}
function dismiss() { $('confirm').hidden = true; pendingAction = null; }
function setBusy(value) {
  busy = value;
  $('fields').disabled = value || !current;
  $('bot').disabled = value;
  $('save').textContent = value ? '处理中…' : '保存人设';
}
async function call(operation) {
  let timer;
  try {
    const result = await Promise.race([operation, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('等待超时，请保留草稿并重新读取，核对是否已保存。')), 20000);
    })]);
    if (result?.status === 'error') throw new Error(result.message);
    return result;
  } finally { clearTimeout(timer); }
}
async function load(botId) {
  dismiss();
  setBusy(true);
  try {
    const data = await call(bridge.apiGet('state', {bot_id: botId}));
    current = data.current;
    $('bot').value = current.bot_id;
    $('binding').textContent = `原生人格：${current.persona_id}`;
    fill(current.bio, current.prompt);
    status('已读取当前人设。修改后需要点击“保存人设”。');
  } catch (error) {
    if (current) $('bot').value = current.bot_id;
    status(`读取失败：${String(error.message || error).slice(0, 220)}`, true);
  } finally { setBusy(false); }
}
$('confirm-no').onclick = () => { dismiss(); $('prompt').focus(); };
$('confirm-yes').onclick = () => { const action = pendingAction; dismiss(); action?.(); };
$('bot').onchange = () => {
  const target = $('bot').value;
  if (current) $('bot').value = current.bot_id;
  guard(() => load(target));
};
$('bio').oninput = counts;
$('prompt').oninput = counts;
$('preset').onchange = () => {
  $('preset-description').textContent = presets.find((p) => p.id === $('preset').value)?.summary || '';
};
$('load-preset').onclick = () => guard(() => {
  const preset = presets.find((p) => p.id === $('preset').value);
  if (preset) {
    fill(preset.bio, preset.prompt);
    status('预设已载入草稿，可以修改简介和详细人设；保存后生效。');
    $('bio').focus();
  }
});
$('custom').onclick = () => guard(() => {
  fill('', '');
  status('开始自定义。可以只填写简介，也可以详细描述背景、性格和说话方式。');
  $('bio').focus();
});
$('reload').onclick = () => guard(() => load(current.bot_id));
$('copy-bio').onclick = async () => {
  try {
    await navigator.clipboard.writeText($('bio').value);
    status('简介已复制，可粘贴到 QQ 的个人简介中。');
  } catch {
    $('bio').focus(); $('bio').select();
    status('浏览器未允许复制，已选中简介，请手动复制。');
  }
};
$('editor').onsubmit = async (event) => {
  event.preventDefault();
  if (busy || !current) return;
  if (!$('bio').value.trim() && !$('prompt').value.trim()) {
    status('请至少填写个人简介或详细人设。', true); $('bio').focus(); return;
  }
  dismiss();
  setBusy(true);
  try {
    current = await call(bridge.apiPost('save', {...current, bio: $('bio').value, prompt: $('prompt').value}));
    fill(current.bio, current.prompt);
    status('已保存，后续新消息使用此人设。想减少旧上下文影响，可在 QQ 发送 /new。');
  } catch (error) {
    status(`保存未确认：${String(error.message || error).slice(0, 220)}。草稿已保留。`, true);
  } finally { setBusy(false); }
};
window.addEventListener('beforeunload', (event) => {
  if (changed()) { event.preventDefault(); event.returnValue = ''; }
});
try {
  await bridge.ready();
  const data = await call(bridge.apiGet('state'));
  presets = data.presets;
  for (const bot of data.bots) $('bot').add(new Option(bot.name, bot.bot_id));
  for (const preset of presets) $('preset').add(new Option(preset.name, preset.id));
  $('preset').onchange();
  if (data.bots.length) await load(data.bots[0].bot_id);
  else status('尚未配置可编辑的机器人，请在本机运行人设安装脚本，或在插件配置中添加机器人。', true);
} catch (error) {
  status(`无法连接人设面板，请刷新或重新登录。${String(error.message || error).slice(0, 150)}`, true);
}
