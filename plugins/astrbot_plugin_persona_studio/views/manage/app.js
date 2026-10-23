const $ = id => document.getElementById(id);
const bridge = window.AstrBotPluginView;
let current = null, bots = [], busy = false, baseline = '', sequence = 0, pending = null, section = '', personaReadFailed=false;
const agentDefaults={dify:{dify_api_base:'https://api.dify.ai/v1',dify_api_type:'chat',dify_query_input_key:'astrbot_text_query',dify_workflow_output_key:'astrbot_wf_output',timeout:60},coze:{coze_api_base:'https://api.coze.cn',auto_save_history:true,timeout:60},dashscope:{dashscope_app_type:'agent',timeout:60},deerflow:{deerflow_api_base:'http://127.0.0.1:2026',deerflow_assistant_id:'lead_agent',timeout:300}};
const agentFields = {
  dify: [['dify_api_base','服务地址','url'],['dify_api_key','API Key','password'],['dify_api_type','应用类型（chat / agent / workflow）','text'],['dify_query_input_key','问题输入字段','text'],['dify_workflow_output_key','工作流输出字段','text'],['timeout','超时（秒）','number']],
  coze: [['coze_api_base','服务地址','url'],['coze_api_key','API Key','password'],['bot_id','Coze Bot ID','text'],['auto_save_history','保存 Coze 历史','checkbox'],['timeout','超时（秒）','number']],
  dashscope: [['dashscope_api_key','API Key','password'],['dashscope_app_id','应用 ID','text'],['dashscope_app_type','应用类型','text'],['timeout','超时（秒）','number']],
  deerflow: [['deerflow_api_base','服务地址','url'],['deerflow_api_key','API Key（服务要求时填写）','password'],['deerflow_assistant_id','助手 ID','text'],['deerflow_model_name','模型名称','text'],['timeout','超时（秒）','number']]
};
function status(text, error=false) { $('status').textContent=text; $('status').dataset.error=String(error); }
function form() {
  const fields={};
  for(const input of $('agent-fields').querySelectorAll('input')) fields[input.dataset.field]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;
  return {runner_type:$('runner').value,provider_id:$('provider').value,persona_id:$('persona-id').value,prompt:$('prompt').value,
    session_enabled:$('session-enabled').checked,llm_enabled:$('llm-enabled').checked,agent_fields:fields};
}
const dirty = () => !!current && JSON.stringify(form())!==baseline;
function dirtyLabel() { $('dirty').textContent=dirty()?'有未保存的修改':'未修改'; }
function setBusy(value) {
  busy=value; $('chat-fields').disabled=value||!current; $('qq-fields').disabled=value||!current;
  for(const id of ['robot','session','sync-identity','save-identity','refresh']) $(id).disabled=value||(!current&&id!=='robot'&&id!=='refresh');
  $('save').textContent=value?'处理中…':'保存当前范围的配置';
  $('save').disabled=value||!current||personaReadFailed;
}
function guard(action) { if(!dirty()) return action(); pending=action; $('guard').hidden=false; $('keep').focus(); }
$('keep').onclick=()=>{pending=null;$('guard').hidden=true;};
$('discard').onclick=()=>{const action=pending;pending=null;$('guard').hidden=true;action?.();};
function showAgent(kind, values={}, secrets={}) {
  values={...(agentDefaults[kind]||{}),...values};
  $('agent-fields').replaceChildren();
  for(const [key,label,type] of agentFields[kind]||[]) {
    const wrapper=document.createElement('label');wrapper.textContent=label;
    const input=document.createElement('input');input.type=type;input.dataset.field=key;input.autocomplete='off';
    if(type==='password') input.placeholder=secrets[key]?'已保存，留空保留':'尚未填写';
    else if(type==='checkbox') { input.checked=values[key]===true;wrapper.className='check'; }
    else input.value=values[key]??(key==='timeout'?60:'');
    if(type==='number') { input.min='1';input.max='600'; }
    wrapper.append(input);$('agent-fields').append(wrapper);
  }
  const local=kind==='local';$('provider').disabled=!local;$('persona-id').disabled=!local;$('prompt').disabled=!local;
  $('provider-note').textContent=local?'保存后用于当前选择的机器人或好友会话。':'外部 Agent 使用它自身的模型与人设。';
}
function identity(bot) {
  $('robot-name').textContent=bot.name;
  $('identity-meta').textContent=`AppID ${bot.appid} · 本机实例 ${bot.bot_id} · ${bot.name_source==='qq'?'名称来自 QQ 接口':bot.name_source==='qq_cache'?'名称来自该 AppID 的 QQ 资料缓存':'名称是本机显示信息，尚未取得 QQ 资料'}`;
  if(!bot.avatar)$('identity-meta').textContent+=' · 暂无可显示的 QQ 头像，可填写本机备用头像';
  const slot=$('avatar-slot');slot.hidden=!bot.avatar;
  if(bot.avatar) {
    let avatar=slot.querySelector('img');
    if(!avatar) {avatar=document.createElement('img');avatar.alt='QQ 机器人头像';avatar.referrerPolicy='no-referrer';avatar.onerror=()=>{slot.hidden=true;};slot.append(avatar);}
    if(avatar.getAttribute('src')!==bot.avatar)avatar.src=bot.avatar;
  } else slot.replaceChildren();
  $('socket-state').textContent=({connected:'QQ 已连接',connecting:'正在连接 QQ',disabled:'机器人已停用',unknown:'当前接入方式无法确认持续在线状态'})[bot.connection_status]||'连接状态未知';
  if(bot.identity_conflict) $('socket-state').textContent+='；AppID 重复，需先消除重复接入';
}
function results(data) {
  const applied=data.apply_result;
  $('applied').textContent=applied&&applied.revision===data.revision?applied.note:applied?'实际配置已变化，请核对当前内容后保存。':'已读取原生实际配置；尚未在本页保存。';
  const message=data.last_message;
  $('observed').textContent=message?`${message.note} ${message.reply_preview?`最近回复：${message.reply_preview}`:''}`:data.umo?'尚未观察到这个会话的新请求。保存后在 QQ 发一句话，可在这里核对。':'选择一个好友会话可查看最近消息处理状态。';
}
async function load(botId,umo=null) {
  const request=++sequence;current=null;baseline='';personaReadFailed=false;setBusy(true);$('guard').hidden=true;
  $('prompt').value='';$('persona-id').replaceChildren();$('provider').replaceChildren();$('agent-fields').replaceChildren();
  $('applied').textContent='正在读取…';$('observed').textContent='';status('正在读取所选范围的实际配置…');
  try {
    const data=await bridge.apiGet('control-state',{bot_id:botId,...(umo?{umo}:{})});
    if(data.status==='error') throw new Error(data.message);
    if(request!==sequence) return;
    current=data;$('robot').value=data.bot.bot_id;
    $('session').replaceChildren(new Option('机器人默认设置（所有未单独配置的会话）',''),...data.sessions.map(row=>{
      const label=row.display_name||row.auto_name;
      return new Option((label&&label!==row.umo&&!label.startsWith(data.bot.bot_id+':')?label:'QQ 好友')+' · '+row.umo.split(':').slice(2).join(':').slice(-10),row.umo);
    }));
    $('session').value=data.umo||''; identity(data.bot);
    $('scope-note').textContent=data.umo?`当前只管理：${data.bot.name} → ${$('session').selectedOptions[0].textContent}。修改只用于这个好友与该机器人的会话。`:`当前管理 ${data.bot.name} 的默认设置。单独配置过的好友会话仍按自己的设置处理。`;
    $('provider').replaceChildren(new Option('请选择已启用的模型',''),...data.providers.map(id=>new Option(id,id)));$('provider').value=data.provider_id||'';
    $('persona-id').replaceChildren(new Option('请选择人设',''),...data.personas.map(p=>new Option(p.name,p.persona_id)));$('persona-id').value=data.persona_id||'';
    $('prompt').value=data.prompt||'';$('persona-source').textContent=`${data.persona_source} · ${data.persona_id||'尚无人设'}`;
    $('runner').value=data.runner_type;showAgent(data.runner_type,data.agent_fields,data.saved_secrets);
    $('llm-enabled').checked=data.llm_enabled;$('session-enabled').checked=data.session_enabled;$('session-enabled-label').hidden=!data.umo;
    $('enabled').checked=data.qq_settings.enable;$('group-c2c').checked=data.qq_settings.enable_group_c2c;
    $('guild-dm').checked=data.qq_settings.enable_guild_direct_message;$('markdown').checked=data.qq_settings.use_markdown;
    $('local-name').value=data.bot.local_name||'';$('local-avatar').value=data.bot.local_avatar||'';
    results(data);baseline=JSON.stringify(form());dirtyLabel();status('已载入实际配置，修改后保存才会生效。');
    parent.postMessage({type:'ai-friend-bot-selected',botId:data.bot.bot_id},'*');
    parent.postMessage({type:'ai-friend-session-selected',botId:data.bot.bot_id,umo:data.umo},'*');
    if(section&&$(section)) { $(section).open=true;$(section).scrollIntoView({block:'start'});section=''; }
  } catch(error) {status('读取失败：'+String(error.message||error),true);}
  finally {if(request===sequence)setBusy(false);}
}
$('robot').onchange=()=>{const chosen=$('robot').value;if(current)$('robot').value=current.bot.bot_id;guard(()=>load(chosen));};
$('session').onchange=()=>{const chosen=$('session').value;if(current)$('session').value=current.umo||'';guard(()=>load($('robot').value,chosen));};
$('chat-form').oninput=dirtyLabel;
$('runner').onchange=()=>{const kind=$('runner').value;showAgent(kind,kind===current?.runner_type?current.agent_fields:{},kind===current?.runner_type?current.saved_secrets:{});dirtyLabel();};
$('persona-id').onchange=async()=>{
  if(!current||!$('persona-id').value)return;
  const request=sequence;const pid=$('persona-id').value;setBusy(true);
  try { const result=await bridge.apiGet('control-persona',{persona_id:pid});if(result.status==='error')throw new Error(result.message);if(sequence===request&&$('persona-id').value===pid){$('prompt').value=result.prompt;personaReadFailed=false;dirtyLabel();} }
  catch(error){personaReadFailed=true;status('人设读取失败，请重新读取实际状态：'+error.message,true);}
  finally{setBusy(false);}
};
$('chat-form').onsubmit=async event=>{
  event.preventDefault();if(!current||busy)return;
  const body={...form(),bot_id:current.bot.bot_id,appid:current.bot.appid,umo:current.umo,revision:current.revision};setBusy(true);status('正在保存并加载当前范围的配置…');
  try {const result=await bridge.apiPost('control-save',body);if(result.status==='error')throw new Error(result.message);await load(body.bot_id,body.umo);status(result.apply_result?.note||'已保存，请在 QQ 发送消息验证实际回复。');}
  catch(error){status('保存未能确认：'+String(error.message||error),true);}
  finally{setBusy(false);}
};
async function action(endpoint,extra={}) {
  if(!current||busy)return;
  const saved=current;setBusy(true);status('正在处理…');
  try {const result=await bridge.apiPost(endpoint,{bot_id:saved.bot.bot_id,appid:saved.bot.appid,...extra});if(result.status==='error')throw new Error(result.message);identity(result.bot);status(result.note||'操作已完成。');$('connection-result').textContent=result.note||'';}
  catch(error){status('操作未能确认：'+String(error.message||error),true);}
  finally{setBusy(false);}
}
$('sync-identity').onclick=()=>action('control-identity',{sync:true});
$('save-identity').onclick=()=>action('control-identity',{local_name:$('local-name').value,local_avatar:$('local-avatar').value});
$('save-connection').onclick=()=>action('control-connection',{enable:$('enabled').checked,enable_group_c2c:$('group-c2c').checked,enable_guild_direct_message:$('guild-dm').checked,use_markdown:$('markdown').checked});
$('reconnect').onclick=()=>action('control-connection');
$('refresh').onclick=()=>guard(()=>load($('robot').value,$('session').value));
window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
try {
  await bridge.ready();const data=await bridge.apiGet('state');if(data.status==='error')throw new Error(data.message);bots=data.bots;
  $('robot').replaceChildren(...bots.map(bot=>new Option(`${bot.name} · AppID ${bot.appid||'未设置'}`,bot.bot_id)));
  const context=await new Promise(resolve=>{
    const listener=event=>{if(event.source!==parent||event.data?.type!=='ai-friend-bot-context')return;clearTimeout(timer);window.removeEventListener('message',listener);resolve(event.data);};
    const timer=setTimeout(()=>{window.removeEventListener('message',listener);resolve({});},600);window.addEventListener('message',listener);parent.postMessage({type:'ai-friend-bot-request'},'*');
  });
  section=context.section||'';const first=bots.find(bot=>bot.bot_id===context.botId)||bots[0];
  if(first)await load(first.bot_id,context.umo||null);else{status('尚未连接 QQ 机器人，请点击顶部“添加机器人 / 高级接入”。');$('robot').disabled=false;}
  setInterval(async()=>{if(!current||busy||document.hidden)return;const saved=current;const request=sequence;try{const data=await bridge.apiGet('control-state',{bot_id:saved.bot.bot_id,...(saved.umo?{umo:saved.umo}:{})});if(request!==sequence||data.status==='error')return;identity(data.bot);results(data);if(data.revision!==saved.revision){if(dirty())status('实际配置已在其他页面改变；草稿保留，请先复制再重新读取。',true);else await load(saved.bot.bot_id,saved.umo);}}catch{/* Explicit refresh reports failures. */}},10000);
}catch(error){status('无法连接管理面板：'+String(error.message||error),true);}
