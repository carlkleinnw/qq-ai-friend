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
let botListSignature = '';
let polling = false;
let qqEditorEnabled = false;
let selectedBotId = null;
let bindingState = null;
let loadSequence = 0;

function renderBinding(binding) {
  const pending = bindingState?.config_id === binding?.config_id && bindingState?.persona_id === binding?.persona_id ? $('bound-persona').value : '';
  bindingState = binding;
  const choices = binding?.choices || [];
  $('bound-persona').replaceChildren(new Option('请选择人设', ''), ...choices.map(p => new Option(p.name + ' · ' + p.persona_id, p.persona_id)));
  const selected = pending || binding?.persona_id;
  $('bound-persona').value = choices.some(p => p.persona_id === selected) ? selected : '';
  const botName = $('bot').selectedOptions[0]?.textContent || '当前机器人';
  const name = choices.find(p => p.persona_id === binding?.persona_id)?.name;
  $('binding-state').textContent = binding?.message || `${botName} → ${name || binding?.persona_id || '尚未绑定人设'}`;
  $('binding-help').textContent = binding?.shared ? '当前人设被其他配置共用。点击“保存绑定”会建立独立副本，再编辑不会影响其他机器人。' : '保存后用于该机器人的默认聊天。单独设置过的会话仍按自己的规则处理。';
  $('bound-persona').disabled = busy || !binding?.editable;
  $('save-binding').disabled = busy || !binding?.editable;
}
function updateQQAccess(data) {
  qqEditorEnabled = data.qq_editor_enabled === true;
  $('qq-editor-enabled').checked = qqEditorEnabled;
  $('qq-access-state').textContent = qqEditorEnabled ? '已开启：可直接在 QQ 私聊中编辑，修改后仍需确认保存。' : '已关闭：QQ 只能查看人设列表，不能编辑或应用人设。';
}
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
  $('fields').disabled = value || !current;
  for (const id of ['save', 'load-preset', 'sync-qq', 'qq-editor-enabled', 'reload']) $(id).disabled = value || !current;
  $('bot').disabled = value;
  $('bound-persona').disabled = value || !bindingState?.editable;
  $('save-binding').disabled = value || !bindingState?.editable;
  $('save').textContent = value ? '处理中…' : '保存修改';
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
  const sequence = ++loadSequence;
  dismiss();
  selectedBotId = botId;
  current = null; bindingState = null;
  setBusy(true);
  fill('', ''); $('tools-list').replaceChildren();
  $('model-state').textContent = ''; $('binding').textContent = '';
  $('bound-persona').replaceChildren(); $('binding-state').textContent = '正在读取当前机器人的绑定…';
  updateQQAccess({qq_editor_enabled: false});
  status('正在读取所选机器人的人设…');
  try {
    const data = await call(bridge.apiGet('state', {bot_id: botId}));
    if (sequence !== loadSequence) return;
    current = data.current || null;
    parent.postMessage({type: 'ai-friend-bot-selected', botId}, '*');
    updateBots(data.bots, botId);
    renderBinding(data.binding);
    $('external-change').hidden = true;
    updatePresets(data.presets, $('preset').value);
    if (!current) {
      status(data.binding?.message || '尚未设置人设，请选择人设并保存绑定。');
      return;
    }
    availableTools = data.tools || [];
    renderTools();
    $('model-state').textContent = data.model_ready ? '已有启用的模型；工具能否执行还取决于模型支持与插件连接。' :
      '当前没有启用的聊天模型，QQ 聊天和工具调用暂不可用。请点击“配置和启用模型”保存有效密钥并启用模型。';
    updateQQAccess(data);
    $('bot').value = current.bot_id;
    $('binding').textContent = `原生人格：${current.persona_id}`;
    fill(current.bio, current.prompt);
    status('正在编辑当前好友的人设，修改后点击“保存修改”。');
  } catch (error) {
    if (current) $('bot').value = current.bot_id;
    status(`读取失败：${String(error.message || error).slice(0, 220)}`, true);
  } finally { if (sequence === loadSequence) setBusy(false); }
}

$('save-binding').onclick = () => guard(async () => {
  if (busy || !bindingState?.editable || !$('bound-persona').value) return;
  const botId = selectedBotId;
  const body = {bot_id: botId, persona_id: $('bound-persona').value,
    expected_persona_id: bindingState.persona_id, config_id: bindingState.config_id};
  setBusy(true);
  status('正在保存机器人与人设绑定…');
  try {
    const result = await call(bridge.apiPost('bind-persona', body), 30000);
    await load(botId);
    status(result.copied ? '绑定已保存，已载入当前机器人的独立人设副本。' : '绑定已保存，已自动载入对应人设。');
  } catch (error) { status(`绑定未能确认：${error.message}。请重新读取后核对。`, true); }
  finally { setBusy(false); }
});
function updateBots(items, selected = current?.bot_id || $('bot').value) {
  const signature = JSON.stringify(items);
  if (signature !== botListSignature) {
    $('bot').replaceChildren(...items.map((bot) => new Option(
      bot.name + (!bot.enabled ? '（已停用）' : bot.connected ? '' : '（连接中）'), bot.bot_id)));
    botListSignature = signature;
  }
  for (const option of [...$('bot').options]) {
    if (option.dataset.removed && !(current && changed() && option.value === current.bot_id)) option.remove();
  }
  if (items.some((bot) => bot.bot_id === selected)) $('bot').value = selected;
  else if (current && changed()) {
    if (![...$('bot').options].some((option) => option.value === current.bot_id)) {
      const removed = new Option('已移除的机器人（草稿已保留）', current.bot_id);
      removed.disabled = true; removed.dataset.removed = 'true'; $('bot').add(removed);
    }
    $('bot').value = current.bot_id;
  }
  const bot = items.find((bot) => bot.bot_id === $('bot').value);
  $('bot-state').textContent = bot?.error || (bot ? (!bot.enabled ? '已停用，可编辑已保存的人设' : bot.connected ? 'QQ 已连接' : '正在等待 QQ 连接') : '尚未接入 QQ 机器人');
}
async function refreshState(manual = false) {
  if (busy || polling || $('custom-dialog').open || $('delete-dialog').open) return;
  if (!manual && document.hidden) return;
  polling = true;
  try {
    const requestedBot = selectedBotId;
    const requestedRevision = current?.revision;
    const data = await call(bridge.apiGet('state', requestedBot ? {bot_id: requestedBot} : {}));
    if (busy || selectedBotId !== requestedBot || current?.revision !== requestedRevision ||
        $('custom-dialog').open || $('delete-dialog').open) return;
    const dirty = changed();
    if (data.current && !current) { await load(requestedBot); return; }
    if (!data.current && current) {
      if (dirty) $('external-change').hidden = false;
      else await load(requestedBot);
      return;
    }
    if (!dirty && data.binding) renderBinding(data.binding);
    if (data.current) updateQQAccess(data);
    updateBots(data.bots);
    if (JSON.stringify(data.presets) !== JSON.stringify(presets)) updatePresets(data.presets, $('preset').value);
    if (data.current && current && (data.current.revision !== current.revision ||
        data.current.persona_id !== current.persona_id)) {
      if (dirty) $('external-change').hidden = false;
      else {
        current = data.current; availableTools = data.tools || [];
        renderTools(); fill(current.bio, current.prompt);
        $('binding').textContent = `原生人格：${current.persona_id}`;
        $('external-change').hidden = true;
        status('已同步 QQ 或其他页面保存的人设。');
      }
    } else if (!data.current && (!current || !data.bots.some((b) => b.bot_id === current.bot_id))) {
      if (dirty) { $('external-change').hidden = false; status('机器人已移除，草稿已保留。请选择其他机器人或重新接入。', true); }
      else {
        current = null; setBusy(false); $('fields').disabled = true;
        if (data.bots.length) await load(data.bots[0].bot_id);
        else status('尚未接入机器人。请点击“接入与管理 QQ 机器人”，完成官方绑定并保存。');
      }
    }
    if (manual && current) status('机器人和人设列表已刷新。');
  } catch (error) { if (manual) status(`刷新失败：${error.message}`, true); }
  finally { polling = false; }
}
$('refresh-bots').onclick = () => refreshState(true);
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
    const names = {memory_companion_recall: '回忆相关记忆', memory_companion_query: '查找记忆',
      memory_companion_remember: '保存记忆', memory_companion_core_memory: '核心记忆',
      memory_companion_discover_sources: '查找记忆来源', memory_companion_sources: '查看记忆来源',
      memory_companion_events: '查看记忆事件', memory_companion_navigate: '浏览记忆',
      memory_companion_note_create: '新建记忆笔记', memory_companion_note_read: '读取记忆笔记',
      memory_companion_note_delete: '删除记忆笔记', future_task: '定时提醒',
      send_message_to_user: '发送消息', get_group_message_history: '查看群聊记录', astr_kb_search: '查询知识库'};
    const text = document.createElement('span');
    const title = names[tool.name] || (/搜索|search/.test(tool.name) ? '联网搜索' : tool.name);
    text.textContent = title + (tool.active ? '' : '（已停用或未加载）');
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
$('qq-editor-enabled').onchange = async () => {
  if (busy || !current) return;
  const botId = current.bot_id;
  const enabled = $('qq-editor-enabled').checked;
  setBusy(true);
  try {
    const result = await call(bridge.apiPost('authorize-qq', {bot_id: botId, enabled}));
    updateQQAccess({qq_editor_enabled: result.enabled});
    status(result.enabled ? '已开启这个机器人的 QQ 人设编辑。可在 QQ 发送 /自定义人设 内容，再发送 /确认人设。' : '已关闭这个机器人的 QQ 人设编辑，待确认的 QQ 草稿已取消。网页仍可编辑。');
  } catch (error) {
    $('qq-editor-enabled').checked = qqEditorEnabled;
    $('qq-access-state').textContent = '保存结果未确认，正在重新读取…';
    try { updateQQAccess(await call(bridge.apiGet('state', {bot_id: botId}))); }
    catch { $('qq-access-state').textContent = '无法确认开关状态，请点击“重新读取已保存内容”核对。'; }
    status(`开关保存未确认：${error.message}`, true);
  }
  finally { setBusy(false); }
};
$('load-preset').onclick = () => guard(() => {
  const preset = presets.find((p) => p.id === $('preset').value);
  if (preset) {
    fill(preset.bio, preset.prompt);
    status('预设已载入草稿，可以修改简介和详细人设；保存后生效。');
    $('prompt').focus();
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
  updateBots(data.bots);
  updatePresets(data.presets);
  // Plugin Views have an opaque origin: use messages without weakening the sandbox.
  const requested = await new Promise(resolve => {
    const receive = (event) => {
      if (event.source !== parent || event.data?.type !== 'ai-friend-bot-context') return;
      clearTimeout(timer); window.removeEventListener('message', receive);
      resolve(typeof event.data.botId === 'string' ? event.data.botId : null);
    };
    const timer = setTimeout(() => { window.removeEventListener('message', receive); resolve(null); }, 400);
    window.addEventListener('message', receive);
    parent.postMessage({type: 'ai-friend-bot-request'}, '*');
  });
  if (data.bots.length) await load(data.bots.find(b => b.bot_id === requested)?.bot_id || data.bots[0].bot_id);
  else status('尚未接入机器人。请点击“接入与管理 QQ 机器人”，完成官方绑定并保存。');
  setInterval(() => refreshState(), 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshState(); });
} catch (error) {
  status(`无法连接人设面板，请刷新或重新登录。${String(error.message || error).slice(0, 150)}`, true);
}
