const $ = (id) => document.getElementById(id);
const bridge = window.AstrBotPluginView;
let current = null;
let presets = [];
let pendingAction = null;
let busy = false;
let customBase = null;
let customReview = false;
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
async function call(operation, timeout = 20000) {
  let timer;
  try {
    const result = await Promise.race([operation, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('等待超时，请保留草稿并重新读取，核对是否已保存。')), timeout);
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
$('custom').onclick = () => {
  if (!current || busy) return;
  customBase = {...current};
  $('custom-name').value = '';
  $('custom-bio').value = '';
  $('custom-prompt').value = '';
  $('custom-bot').textContent = '预设可以重复使用，保存后仍需选择并确认才会应用。';
  $('custom-status').textContent = '';
  customStep(false);
  $('custom-dialog').showModal();
  $('custom-name').focus();
};
function customStep(review) {
  customReview = review;
  $('custom-inputs').hidden = review;
  $('custom-review').hidden = !review;
  $('custom-back').hidden = !review;
  $('custom-next').textContent = review ? '保存到预设' : '预览人设';
}
function closeCustom() {
  if (busy) return;
  $('custom-dialog').close();
  customBase = null;
  $('custom').focus();
}
$('custom-cancel').onclick = closeCustom;
$('custom-dialog').oncancel = (event) => {
  event.preventDefault();
  closeCustom();
};
$('custom-back').onclick = () => { customStep(false); $('custom-prompt').focus(); };
$('custom-form').onsubmit = async (event) => {
  event.preventDefault();
  if (busy || !customBase) return;
  const name = $('custom-name').value.trim();
  const bio = $('custom-bio').value;
  const prompt = $('custom-prompt').value;
  if (!name || [...name].reduce((size, char) => size + (char.codePointAt(0) > 127 ? 2 : 1), 0) > 14) {
    $('custom-status').textContent = '请填写名称，最多七个汉字或十四个英文字母。';
    $('custom-name').focus();
    return;
  }
  if (!bio.trim() && !prompt.trim()) {
    $('custom-status').textContent = '请至少填写简介或详细人设。';
    $('custom-prompt').focus();
    return;
  }
  if (!customReview) {
    $('custom-status').textContent = '';
    $('custom-preview-text').textContent = `名称：${name}\n\n` + (bio ? `简介：${bio}\n\n` : '') + prompt;
    customStep(true);
    $('custom-next').focus();
    return;
  }
  setBusy(true);
  $('custom-fields').disabled = true;
  $('custom-status').textContent = '正在保存预设并同步 QQ 菜单…';
  try {
    const result = await call(bridge.apiPost('presets', {name, bio, prompt}), 90000);
    updatePresets(result.presets, result.preset_id);
    $('custom-dialog').close();
    customBase = null;
    status(result.menu_sync_errors?.length ?
      '预设已保存，QQ 菜单同步尚未完成；可从维护窗口重试“同步 QQ 机器人”。当前人设未切换。' :
      '已加入预设并同步 QQ 菜单。重新打开 QQ 私聊可查看；选择并确认后才会应用。');
  } catch (error) {
    $('custom-status').textContent = `保存未确认，内容已保留。${String(error.message || error).slice(0, 180)}`;
  } finally {
    $('custom-fields').disabled = false;
    setBusy(false);
    if (!$('custom-dialog').open) $('custom').focus();
  }
};
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
function updatePresets(items, selected) {
  presets = items;
  $('preset').replaceChildren(...items.map((p) => new Option(p.name, p.id)));
  if (selected) $('preset').value = selected;
  $('preset').onchange();
}
window.addEventListener('beforeunload', (event) => {
  if (changed() || ($('custom-dialog').open && ($('custom-name').value || $('custom-bio').value || $('custom-prompt').value))) {
    event.preventDefault(); event.returnValue = '';
  }
});
try {
  await bridge.ready();
  const data = await call(bridge.apiGet('state'));
  for (const bot of data.bots) $('bot').add(new Option(bot.name, bot.bot_id));
  updatePresets(data.presets);
  if (data.bots.length) await load(data.bots[0].bot_id);
  else status('尚未配置可编辑的机器人。请先在面板扫码保存 QQ，再到“维护与更新”点击“同步 QQ 机器人”。');
} catch (error) {
  status(`无法连接人设面板，请刷新或重新登录。${String(error.message || error).slice(0, 150)}`, true);
}
