const $ = (id) => document.getElementById(id);
const bridge = window.AstrBotPluginView;
let current = null;
let presets = [];
let pendingAction = null;
let busy = false;
let customBase = null;
let customReview = false;
let editingPreset = null;
let deletingPreset = null;
let availableTools = [];
function selectedTools() {
  if ($('tools-mode').value === 'all') return null;
  if ($('tools-mode').value === 'none') return [];
  const chosen = [...$('tools-list').querySelectorAll('input:checked')].map((input) => input.value);
  const original = current?.tools || [];
  return [...original.filter((name) => chosen.includes(name)), ...chosen.filter((name) => !original.includes(name))];
}
const toolsEqual = (a, b) => a === null || b === null ? a === b : JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
const normalized = (text) => text.replace(/\r\n?/g, '\n');
const changed = () => current && ($('bio').value !== normalized(current.bio) || $('prompt').value !== normalized(current.prompt) || !toolsEqual(selectedTools(), current.tools));
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
  $('fields').disabled = value;
  for (const id of ['save', 'load-preset', 'sync-qq', 'authorize-qq', 'reload']) $(id).disabled = value || !current;
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
    availableTools = data.tools || [];
    renderTools();
    updatePresets(data.presets, $('preset').value);
    $('model-state').textContent = data.model_ready ? '已有启用的模型；工具能否执行还取决于模型支持与插件连接。' :
      '当前没有启用的聊天模型，QQ 聊天和工具调用暂不可用。请点击“配置和启用模型”保存有效密钥并启用模型。';
    $('qq-state').textContent = data.qq_authorized ? '已配置 QQ 私聊编辑授权；可在 QQ 选择后确认保存。' :
      'QQ 编辑尚未授权：在自己的 QQ 私聊发 /sid，粘贴结果并授权后，才能确认保存。';
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
$('preset-search').oninput = () => updatePresets(presets, $('preset').value);
$('refresh-presets').onclick = async () => {
  if (busy) return;
  setBusy(true);
  try { const data = await call(bridge.apiGet('state')); updatePresets(data.presets, $('preset').value); status('已刷新预设列表。'); }
  catch (error) { status(error.message, true); }
  finally { setBusy(false); }
};
function renderTools() {
  const selected = current.tools;
  $('tools-mode').value = selected === null ? 'all' : selected.length ? 'selected' : 'none';
  const tools = [...availableTools];
  for (const name of selected || []) if (!tools.some((t) => t.name === name)) tools.push({name, active: false});
  $('tools-list').replaceChildren(...tools.map((tool) => {
    const label = document.createElement('label'); label.className = 'tool-option';
    const input = document.createElement('input'); input.type = 'checkbox'; input.value = tool.name;
    input.checked = selected === null || selected.includes(tool.name); input.onchange = counts;
    const text = document.createElement('span'); text.textContent = tool.name + (tool.active ? '' : '（已停用或未加载）');
    label.title = tool.description || tool.name; label.append(input, text); return label;
  }));
  $('tools-list').hidden = $('tools-mode').value !== 'selected';
}
$('tools-mode').onchange = () => { $('tools-list').hidden = $('tools-mode').value !== 'selected'; counts(); };
$('sync-qq').onclick = async () => {
  if (busy || !current) return;
  setBusy(true); status('正在同步 QQ 人设菜单…');
  try { await call(bridge.apiPost('qq-menu', {bot_id: current.bot_id}), 25000); status('QQ 菜单接口已确认保存。请关闭再打开手机 QQ 私聊查看菜单。'); }
  catch (error) { status(`QQ 同步未完成：${error.message}。人设仍保存在本机，可稍后重试。`, true); }
  finally { setBusy(false); }
};
$('authorize-qq').onclick = async () => {
  if (busy) return;
  setBusy(true);
  try { await call(bridge.apiPost('authorize-qq', {umo: $('qq-umo').value})); $('qq-state').textContent = '已授权此 QQ 私聊编辑人设。'; status('授权已保存。现在可在 QQ 选择预设并确认保存。'); }
  catch (error) { status(error.message, true); }
  finally { setBusy(false); }
};
$('load-preset').onclick = () => guard(() => {
  const preset = presets.find((p) => p.id === $('preset').value);
  if (preset) {
    fill(preset.bio, preset.prompt);
    status('预设已载入草稿，可以修改简介和详细人设；保存后生效。');
    $('bio').focus();
  }
});
function openPreset(item = null) {
  if (busy) return;
  if (!current) { status('请先同步并选择机器人，预设将继承它的工具权限。', true); return; }
  customBase = {...current}; editingPreset = item ? {...item} : null;
  $('custom-title').textContent = item ? '编辑选中预设' : '新建自定义预设';
  $('custom-name').value = item?.name || '';
  $('custom-bio').value = item?.bio || '';
  $('custom-prompt').value = item?.prompt || '';
  $('custom-bot').textContent = '预设可以重复使用，保存后仍需选择并确认才会应用。';
  $('custom-status').textContent = '';
  customStep(false);
  $('custom-dialog').showModal();
  $('custom-name').focus();
}
$('custom').onclick = () => openPreset();
$('edit-preset').onclick = () => { const item = presets.find((p) => p.id === $('preset').value); if (item) openPreset(item); };
$('delete-preset').onclick = () => {
  if (busy) return;
  deletingPreset = presets.find((p) => p.id === $('preset').value);
  if (!deletingPreset) return;
  $('delete-description').textContent = `确认删除“${deletingPreset.name}”？`;
  $('delete-dialog').showModal(); $('delete-cancel').focus();
};
$('delete-cancel').onclick = () => $('delete-dialog').close();
$('delete-dialog').oncancel = (event) => { if (busy) event.preventDefault(); };
$('delete-confirm').onclick = async () => {
  if (busy || !deletingPreset) return;
  setBusy(true); $('delete-confirm').disabled = true; $('delete-cancel').disabled = true;
  try {
    const result = await call(bridge.apiPost('delete-preset', {preset_id: deletingPreset.id, revision: deletingPreset.revision}), 30000);
    updatePresets(result.presets); $('delete-dialog').close();
    status(result.menu_sync_errors.length ? '已从本机列表删除，QQ 菜单同步未完成，请点击“同步 QQ 人设菜单”重试。' : '已从预设列表移除，QQ 菜单接口已确认。已应用人设保留。');
  } catch (error) { status(`删除未确认：${error.message}`, true); $('delete-dialog').close(); }
  finally { setBusy(false); $('delete-confirm').disabled = false; $('delete-cancel').disabled = false; }
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
    const result = await call(bridge.apiPost(editingPreset ? 'update-preset' : 'presets', {
      name, bio, prompt, bot_id: customBase.bot_id, preset_id: editingPreset?.id, revision: editingPreset?.revision
    }), 30000);
    $('preset-search').value = '';
    updatePresets(result.presets, result.preset_id);
    $('custom-dialog').close();
    customBase = null;
    status(result.menu_sync_errors?.length ?
      '预设已保存，QQ 菜单同步尚未完成；点击“同步 QQ 人设菜单”可重试。点击“载入预设”再“保存人设”应用。' :
      '预设已保存，QQ 菜单接口已确认。点击“载入预设”再“保存人设”应用；QQ 中选择后也需要确认。');
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
    current = await call(bridge.apiPost('save', {...current, bio: $('bio').value, prompt: $('prompt').value, tools: selectedTools()}));
    renderTools();
    fill(current.bio, current.prompt);
    status('已保存，后续新消息使用此人设。想减少旧上下文影响，可在 QQ 发送 /new。');
  } catch (error) {
    status(`保存未确认：${String(error.message || error).slice(0, 220)}。草稿已保留。`, true);
  } finally { setBusy(false); }
};
function updatePresets(items, selected) {
  presets = items;
  const search = $('preset-search').value.trim().toLowerCase();
  const visible = items.filter((p) => `${p.name} ${p.bio} ${p.prompt}`.toLowerCase().includes(search));
  $('preset').replaceChildren(...visible.map((p) => new Option(p.name + (p.summary === '来自原生人格库。' ? '（原生）' : ''), p.id)));
  if (selected && visible.some((p) => p.id === selected)) $('preset').value = selected;
  $('edit-preset').disabled = !visible.length;
  $('delete-preset').disabled = !visible.length;
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
