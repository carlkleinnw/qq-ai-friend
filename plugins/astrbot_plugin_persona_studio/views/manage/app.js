const $ = id => document.getElementById(id);
const bridge = window.AstrBotPluginView;
const pageType = document.body.dataset.page || 'manage';
let current = null, busy = false, baseline = '', sequence = 0, pending = null, cancelPending = null, personaReadFailed = false;
const agentDefaults = {
  dify:{dify_api_base:'https://api.dify.ai/v1',dify_api_type:'chat',dify_query_input_key:'astrbot_text_query',dify_workflow_output_key:'astrbot_wf_output',variables:{},timeout:60},
  coze:{coze_api_base:'https://api.coze.cn',auto_save_history:true,timeout:60},
  dashscope:{dashscope_app_type:'agent',variables:{},rag_options:{pipeline_ids:[],file_ids:[],output_reference:false},timeout:60},
  deerflow:{deerflow_api_base:'http://127.0.0.1:2026',deerflow_assistant_id:'lead_agent',deerflow_max_concurrent_subagents:3,deerflow_recursion_limit:1000,timeout:300}
};
const agentFields = {
  dify:[['dify_api_base','服务地址','url'],['dify_api_key','API Key','password'],['dify_api_type','应用类型（chat / agent / workflow）','text'],['dify_query_input_key','问题输入字段','text'],['dify_workflow_output_key','工作流输出字段','text'],['variables','输入变量（JSON 对象）','json']],
  coze:[['coze_api_base','服务地址','url'],['coze_api_key','API Key','password'],['bot_id','Coze Bot ID','text'],['auto_save_history','保存 Coze 历史','checkbox']],
  dashscope:[['dashscope_api_key','API Key','password'],['dashscope_app_id','应用 ID','text'],['dashscope_app_type','应用类型','text'],['variables','输入变量（JSON 对象）','json'],['rag_options','RAG 选项（JSON 对象）','json']],
  deerflow:[['deerflow_api_base','服务地址','url'],['deerflow_api_key','API Key（可选）','password'],['deerflow_auth_header','认证 Header（可选，留空保留）','password'],['deerflow_assistant_id','助手 ID','text'],['deerflow_model_name','模型名称','text'],['deerflow_thinking_enabled','启用深度思考','checkbox'],['deerflow_plan_mode','启用规划模式','checkbox'],['deerflow_subagent_enabled','启用子助手','checkbox'],['deerflow_max_concurrent_subagents','最大同时运行的子助手数','number'],['deerflow_recursion_limit','递归限制','number']]
};
for (const fields of Object.values(agentFields)) fields.push(['timeout','超时（秒）','number'],['proxy','代理地址（可选）','text']);
function on(id,event,fn) { if($(id)) $(id)[event]=fn; }
function text(id,value) { if($(id)) $(id).textContent=value; }
function status(value,error=false) { text('status',value);$('status').dataset.error=String(error); }
function connectionForm() { return {enable:$('enabled').checked,enable_group_c2c:$('group-c2c').checked,enable_guild_direct_message:$('guild-dm').checked,use_markdown:$('markdown').checked}; }
function identityForm() { return {local_name:$('local-name').value,local_avatar:$('local-avatar').value}; }
function form() {
  if(pageType==='qq')return {...connectionForm(),...identityForm()};
  if(pageType==='model')return {provider_id:$('provider').value};
  if(pageType==='agent') {
    const fields={};
    for(const input of $('agent-fields').querySelectorAll('[data-field]')) {
      // Keep raw JSON in the draft; parse only when saving.
      fields[input.dataset.field]=input.type==='checkbox'?input.checked:input.value;
    }
    return {runner_type:$('runner').value,agent_fields:fields};
  }
  return {persona_id:$('persona-id').value,prompt:$('prompt').value,session_enabled:$('session-enabled').checked,llm_enabled:$('llm-enabled').checked};
}
const dirty=()=>!!current&&JSON.stringify(form())!==baseline;
function dirtyLabel(){text('dirty',dirty()?'有未保存的修改':'未修改');}
function setBusy(value) {
  busy=value;
  for(const id of ['chat-fields','qq-fields']) if($(id))$(id).disabled=value||!current;
  for(const id of ['robot','session','sync-identity','save-identity','refresh','reset-scope','local-name','local-avatar']) if($(id))$(id).disabled=value||(!current&&!['robot','refresh','reset-scope'].includes(id));
  if($('save')) {
    $('save').textContent=value?'处理中…':'保存当前范围的配置';
    $('save').disabled=value||!current||personaReadFailed||(pageType==='model'&&current.runner_type!=='local');
  }
  if($('test-model'))$('test-model').disabled=value||!current||current.runner_type!=='local'||!$('provider').value;
  if(pageType==='model'&&$('provider'))$('provider').disabled=current?.runner_type!=='local';
  if(pageType==='manage')for(const id of ['persona-id','prompt']) if($(id))$(id).disabled=current?.runner_type!=='local';
}
function guard(action,cancel=null) {if(!dirty())return action();pending=action;cancelPending=cancel;$('guard').hidden=false;$('keep').focus();}
on('keep','onclick',()=>{const cancel=cancelPending;pending=null;cancelPending=null;$('guard').hidden=true;cancel?.();});
on('discard','onclick',()=>{const action=pending;pending=null;cancelPending=null;$('guard').hidden=true;action?.();});
function showAgent(kind,values={},secrets={}) {
  values={...(agentDefaults[kind]||{}),...values};$('agent-fields').replaceChildren();
  for(const [key,label,type] of agentFields[kind]||[]) {
    const wrapper=document.createElement('label');wrapper.textContent=label;
    const input=document.createElement(type==='json'?'textarea':'input');input.dataset.field=key;input.dataset.kind=type;input.autocomplete='off';
    if(type==='json'){input.rows=4;input.value=JSON.stringify(values[key]||{},null,2);}
    else {
      input.type=type;
      if(type==='password')input.placeholder=secrets[key]?'已保存，留空保留':'尚未填写';
      else if(type==='checkbox'){input.checked=values[key]===true;wrapper.className='check';}
      else input.value=values[key]??'';
      if(type==='number'){input.min='1';input.max=key==='timeout'?'600':'10000';}
    }
    wrapper.append(input);$('agent-fields').append(wrapper);
  }
}
function identity(bot) {
  text('robot-name',bot.name);
  text('identity-meta',`AppID ${bot.appid} · 本机实例 ${bot.bot_id} · ${bot.name_source==='qq'?'名称来自 QQ 接口':'本机显示信息或该 AppID 的资料缓存'}`);
  const slot=$('avatar-slot');slot.hidden=!bot.avatar;slot.replaceChildren();
  if(bot.avatar){const img=document.createElement('img');img.alt='QQ 机器人头像';img.referrerPolicy='no-referrer';img.src=bot.avatar;img.onerror=()=>{slot.hidden=true;};slot.append(img);}
  text('socket-state',({connected:'QQ 已连接',connecting:'正在连接 QQ',disabled:'机器人已停用',unknown:'当前接入方式无法确认持续在线状态'})[bot.connection_status]||'连接状态未知');
  if(bot.identity_conflict)text('socket-state','AppID 重复，请先消除重复接入');
}
function results(data) {
  const applied=data.apply_result;
  text('applied',applied&&applied.revision===data.revision?applied.note:applied?'实际配置已变化，请核对后保存。':'已读取原生实际配置；尚未在本页保存。');
  const m=data.last_message;
  text('observed',m?`${m.note} ${m.reply_preview?'最近回复：'+m.reply_preview:''}`:data.umo?'尚未观察到这个好友会话的新请求。':'选择好友会话后，可核对最近的实际消息处理状态。');
}
async function load(botId,umo=null) {
  const request=++sequence;current=null;baseline='';personaReadFailed=false;setBusy(true);$('guard').hidden=true;
  text('robot-name','正在读取所选机器人…');text('identity-meta','');text('socket-state','状态待确认');$('avatar-slot').hidden=true;
  // A failed read must leave no editable content from a previous robot.
  for(const id of ['prompt','local-name','local-avatar'])if($(id))$(id).value='';
  for(const id of ['persona-id','provider','agent-fields'])$(id)?.replaceChildren();
  text('applied','正在读取…');text('observed','');status('正在读取所选范围的实际配置…');
  try {
    const data=await bridge.apiGet('control-state',{bot_id:botId,...(umo?{umo}:{})});
    if(data.status==='error')throw new Error(data.message);
    if(request!==sequence)return false;
    current=data;$('robot').value=data.bot.bot_id;
    if($('session')) {
      $('session').replaceChildren(new Option('机器人默认设置（所有未单独配置的会话）',''),...data.sessions.map(row=>new Option((row.display_name||row.auto_name||'QQ 好友')+' · '+row.umo.split(':').slice(2).join(':').slice(-10),row.umo)));
      $('session').value=data.umo||'';
    }
    identity(data.bot);text('scope-note',pageType==='qq'?'接入设置作用于整个机器人。':data.umo?`当前只管理：${data.bot.name} → ${$('session').selectedOptions[0].textContent}`:`当前管理 ${data.bot.name} 的默认设置；好友的单独配置保持优先。`);
    if($('provider')) {
      $('provider').replaceChildren(new Option('请选择已启用的模型',''),...data.providers.map(id=>new Option(id,id)));$('provider').value=data.provider_id||'';
      text('provider-note',data.runner_type==='local'?'保存后进入当前范围的实际聊天流程。':'当前由外部 Agent 管理模型；切换为内置 Agent 后可选择本机模型。');
    }
    if($('persona-id')) {
      $('persona-id').replaceChildren(new Option('请选择人设',''),...data.personas.map(p=>new Option(p.name,p.persona_id)));$('persona-id').value=data.persona_id||'';$('prompt').value=data.prompt||'';
      text('persona-source',data.runner_type==='local'?`${data.persona_source} · ${data.persona_id||'尚无人设'}`:'当前外部 Agent 管理自己的人设，请到 Agent 连接核对。');
      $('llm-enabled').checked=data.llm_enabled;$('session-enabled').checked=data.session_enabled;$('session-enabled-label').hidden=!data.umo;
    }
    if($('runner')){$('runner').value=data.runner_type;showAgent(data.runner_type,data.agent_fields,data.saved_secrets);}
    if(pageType==='qq') {
      for(const [id,key] of [['enabled','enable'],['group-c2c','enable_group_c2c'],['guild-dm','enable_guild_direct_message'],['markdown','use_markdown']])$(id).checked=data.qq_settings[key];
      $('local-name').value=data.bot.local_name||'';$('local-avatar').value=data.bot.local_avatar||'';
    }
    results(data);baseline=JSON.stringify(form());dirtyLabel();status('已载入实际配置，修改后保存才会生效。');
    parent.postMessage({type:'ai-friend-bot-selected',botId:data.bot.bot_id},'*');
    if(pageType!=='qq')parent.postMessage({type:'ai-friend-session-selected',botId:data.bot.bot_id,umo:data.umo},'*');
    return true;
  }catch(error){if(request===sequence){current=null;status('读取失败：'+String(error.message||error),true);}return false;}
  finally{if(request===sequence)setBusy(false);}
}
on('robot','onchange',()=>{const chosen=$('robot').value;if(current)$('robot').value=current.bot.bot_id;guard(()=>load(chosen));});
on('session','onchange',()=>{const chosen=$('session').value;if(current)$('session').value=current.umo||'';guard(()=>load($('robot').value,chosen));});
on('chat-form','oninput',()=>{dirtyLabel();setBusy(busy);});
if(pageType==='qq')document.querySelector('main').addEventListener('input',dirtyLabel);
on('runner','onchange',()=>{const kind=$('runner').value;const saved=current?.agent_profiles?.[kind];showAgent(kind,saved?.fields||{},saved?.saved_secrets||{});dirtyLabel();});
on('persona-id','onchange',async()=>{
  if(!current||!$('persona-id').value)return;
  const request=sequence,pid=$('persona-id').value;setBusy(true);
  try{const r=await bridge.apiGet('control-persona',{persona_id:pid});if(r.status==='error')throw new Error(r.message);if(sequence===request&&$('persona-id').value===pid){$('prompt').value=r.prompt;personaReadFailed=false;dirtyLabel();}}
  catch(error){personaReadFailed=true;status('人设读取失败，请重新读取实际状态。',true);}
  finally{if(sequence===request)setBusy(false);}
});
on('chat-form','onsubmit',async event=>{
  event.preventDefault();if(!current||busy||personaReadFailed)return;
  let body;
  try {
    body={...form(),section:pageType,bot_id:current.bot.bot_id,appid:current.bot.appid,umo:current.umo,revision:current.revision};
    if(pageType==='manage')Object.assign(body,{runner_type:current.runner_type,provider_id:current.provider_id});
    if(pageType==='agent')for(const input of $('agent-fields').querySelectorAll('[data-field]')) {
      if(input.dataset.kind==='json')body.agent_fields[input.dataset.field]=JSON.parse(input.value);
      else if(input.type==='number')body.agent_fields[input.dataset.field]=Number(input.value);
    }
  }catch{status('JSON 格式不正确，请填写有效的 JSON 对象。',true);return;}
  setBusy(true);status('正在保存并加载当前范围的配置…');
  try{const r=await bridge.apiPost('control-save',body);if(r.status==='error')throw new Error(r.message);if(await load(body.bot_id,body.umo))status(r.apply_result?.note||'已保存并加载到聊天流程，实际 QQ 回复待验证。');}
  catch(error){status('保存未能确认：'+String(error.message||error),true);}
  finally{setBusy(false);}
});
async function action(endpoint,extra={}) {
  if(!current||busy)return;const saved=current;setBusy(true);status('正在处理…');
  try {
    const r=await bridge.apiPost(endpoint,{bot_id:saved.bot.bot_id,appid:saved.bot.appid,...(endpoint==='control-connection'?{qq_revision:saved.qq_revision}:{}),...extra});if(r.status==='error')throw new Error(r.message);
    // Preserve unsaved fields from the other operation on the QQ page.
    const before=JSON.parse(baseline);
    if(endpoint==='control-connection'){Object.assign(before,extra);Object.assign(current.qq_settings,extra);current.qq_revision=r.qq_revision;}
    if(endpoint==='control-identity'&&!extra.sync){Object.assign(before,extra);delete before.sync;}
    baseline=JSON.stringify(before);current.bot=r.bot;identity(r.bot);dirtyLabel();status(r.note||'操作已完成。');text('connection-result',r.note||'');
  }catch(error){status('操作未能确认：'+String(error.message||error),true);}
  finally{setBusy(false);}
}
on('sync-identity','onclick',()=>action('control-identity',{sync:true}));
on('save-identity','onclick',()=>action('control-identity',identityForm()));
on('save-connection','onclick',()=>action('control-connection',connectionForm()));
on('reconnect','onclick',()=>action('control-connection'));
on('refresh','onclick',()=>guard(()=>load($('robot').value,$('session')?.value||null)));
on('reset-scope','onclick',()=>guard(()=>load($('robot').value,null)));
on('test-model','onclick',async()=>{
  if(!current||busy)return;const id=$('provider').value;setBusy(true);text('test-result','正在测试所选模型，不会向 QQ 发送消息…');
  try{const r=await bridge.apiPost('control-test-model',{provider_id:id});if(r.status==='error')throw new Error(r.message);text('test-result',r.note);}
  catch(error){text('test-result',error.message||'测试失败，请核对连接参数。');}
  finally{setBusy(false);}
});
window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
// The parent owns hash routing, so ask before it tears down this iframe.
window.addEventListener('message',event=>{
  if(event.source===parent&&event.data?.type==='ai-friend-navigate')guard(()=>parent.postMessage({type:'ai-friend-navigate-approved',href:event.data.href},'*'));
  if(event.source===parent&&event.data?.type==='ai-friend-context-changed') {
    const {botId,umo,previousRoute}=event.data;
    const nextUmo=pageType==='qq'?null:umo||null;
    if(current?.bot.bot_id===botId&&(current.umo||null)===nextUmo)return;
    guard(()=>load(botId,nextUmo),()=>parent.postMessage({type:'ai-friend-navigate-approved',href:previousRoute},'*'));
  }
});
document.addEventListener('click',event=>{
  const a=event.target.closest('a[target="_top"]');if(!a||event.ctrlKey||event.metaKey||event.shiftKey)return;
  const href=a.getAttribute('href');if(!href?.startsWith('/#/'))return;
  event.preventDefault();guard(()=>parent.postMessage({type:'ai-friend-navigate-approved',href:href.slice(1)},'*'));
});
try {
  await bridge.ready();const data=await bridge.apiGet('state');if(data.status==='error')throw new Error(data.message);
  const bots=data.bots;$('robot').replaceChildren(...bots.map(b=>new Option(`${b.name} · AppID ${b.appid||'未设置'}`,b.bot_id)));
  const context=await new Promise(resolve=>{
    const listener=event=>{if(event.source!==parent||event.data?.type!=='ai-friend-bot-context')return;clearTimeout(timer);window.removeEventListener('message',listener);resolve(event.data);};
    const timer=setTimeout(()=>{window.removeEventListener('message',listener);resolve({});},1500);window.addEventListener('message',listener);parent.postMessage({type:'ai-friend-bot-request'},'*');
  });
  const first=context.botId?bots.find(b=>b.bot_id===context.botId):bots[0];
  if(first)await load(first.bot_id,pageType==='qq'?null:context.umo||null);
  else{$('robot').value='';status(bots.length?'所选机器人已不存在，请重新选择；不会自动套用其他机器人的配置。':'尚未配置 QQ 机器人。模型服务可从顶部入口独立管理；QQ 接入请进入扫码添加页面。');setBusy(false);}
  let polling=false;
  setInterval(async()=>{
    if(!current||busy||document.hidden||polling)return;polling=true;const saved=current,request=sequence;
    try{
      const d=await bridge.apiGet('control-state',{bot_id:saved.bot.bot_id,...(saved.umo?{umo:saved.umo}:{})});if(request!==sequence)return;if(d.status==='error')throw new Error();
      identity(d.bot);results(d);
      const changed=d.revision!==saved.revision||(pageType==='qq'&&JSON.stringify(d.qq_settings)!==JSON.stringify(saved.qq_settings));
      if(changed){if(dirty())status('实际配置已在其他页面改变；草稿保留，请先复制再重新读取。',true);else await load(saved.bot.bot_id,saved.umo);}
    }catch{if(request===sequence){text('socket-state','状态更新失败，当前在线状态待确认');status('状态更新失败，当前在线状态可能已过期，请重新读取。',true);}}
    finally{polling=false;}
  },10000);
}catch(error){status('无法连接管理面板：'+String(error.message||error),true);}
