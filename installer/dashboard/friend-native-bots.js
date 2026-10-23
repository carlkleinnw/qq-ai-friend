/* Decorate the native QQ editor; native fields, payloads and save handlers remain intact. */
(() => {
  'use strict';
  const BASE='/api/v1/plugins/extensions/astrbot_plugin_persona_studio/';
  let records=new Map(), root=null, observer=null, timer=null, failed=false, loading=false, restored=false, queued=false;
  let providerSelecting=false, mobileChoosing=false, pendingRemoval=null;
  function syncProviders(){
    if(location.hash.split('?')[0]!=='#/providers'){providerSelecting=false;return;}
    const list=document.querySelector('.provider-sources-list');
    if(list){
      if(list.querySelector('.provider-source-item--active'))return;
      const rows=[...list.querySelectorAll('.provider-source-item')];
      const saved=localStorage.getItem('friend-selected-provider-source');
      const row=rows.find(r=>r.querySelector('.provider-source-item__title')?.textContent.trim()===saved)||rows[0];
      if(row&&!providerSelecting){providerSelecting=true;row.click();requestAnimationFrame(()=>{providerSelecting=false;});}
      return;
    }
    const select=document.querySelector('.provider-sources-mobile-select');
    if(!select||select.querySelector('.v-select__selection'))return;
    const options=[...document.querySelectorAll('.v-overlay--active .v-list-item')];
    if(options.length){
      const saved=localStorage.getItem('friend-selected-provider-source');
      const row=options.find(r=>r.querySelector('.v-list-item-title')?.textContent.trim()===saved)||options[0];
      if(!providerSelecting){providerSelecting=true;row.click();requestAnimationFrame(()=>{providerSelecting=false;});}
    }else if(!providerSelecting){providerSelecting=true;select.querySelector('.v-field')?.click();requestAnimationFrame(()=>{providerSelecting=false;});}
  }
  const statusText=bot=>bot.identity_conflict?'AppID 重复，身份待核对':({connected:'QQ 已连接',connecting:'QQ 未连接 / 正在连接',disabled:'已停用',unknown:'持续在线状态未知'})[bot.connection_status]||'连接状态未知';
  async function api(endpoint,body) {
    const response=await fetch(BASE+endpoint,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+localStorage.getItem('token'),...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(18000)});
    const data=await response.json().catch(()=>({}));
    if(!response.ok||data.status==='error')throw new Error(response.status===401?'登录已过期，请重新登录。':data.message||'读取或保存失败，请重试。');return data.data||data;
  }
  function putText(node,value){if(node&&node.textContent!==value)node.textContent=value;}
  function avatar(img,bot) {
    if(!img)return;
    if(!img.dataset.friendOriginalSrc)img.dataset.friendOriginalSrc=img.getAttribute('src')||'';
    const value=bot.avatar&&img.dataset.friendFailedAvatar!==bot.avatar?bot.avatar:img.dataset.friendOriginalSrc;
    if(value&&img.getAttribute('src')!==value){img.referrerPolicy='no-referrer';img.src=value;img.alt=bot.name+'的头像';}
    img.onerror=()=>{img.dataset.friendFailedAvatar=bot.avatar||'';img.src=img.dataset.friendOriginalSrc;img.onerror=null;};
  }
  function identify(element,title) {
    if(!element)return null;
    const raw=title?.textContent?.trim();
    // The native row/editor is keyed by this exact instance ID, never by its position or nickname.
    if(raw&&records.has(raw))element.dataset.friendBotId=raw;
    return records.get(element.dataset.friendBotId);
  }
  function identityPanel(editor,bot) {
    let panel=editor.querySelector('.friend-native-profile');
    if(panel&&(panel.dataset.botId!==bot.bot_id||panel.dataset.appid!==bot.appid)){panel.remove();panel=null;}
    if(panel){panel._friendUpdatePlatform?.(bot);return;}
    const body=editor.querySelector('.bot-editor__body');if(!body)return;
    panel=document.createElement('details');panel.open=true;panel.className='friend-native-profile';panel.dataset.botId=bot.bot_id;panel.dataset.appid=bot.appid;
    panel.innerHTML='<summary>QQ 机器人资料管理</summary><section class="friend-platform-profile"><h3>QQ 平台资料</h3><div class="friend-profile-preview"><img data-qq-preview hidden alt="QQ 平台头像" referrerpolicy="no-referrer"><div><strong data-qq-name></strong><p data-profile-id></p></div></div><p>QQ 端名称与头像需要在 QQ 开放平台保存。这里显示当前 QQ 公开资料，并支持修改生效后重新读取；本机接入凭据不具备开放平台管理权限。</p><a href="https://q.qq.com/" target="_blank" rel="noopener noreferrer">打开 QQ 开放平台管理</a><ol><li>登录管理员账号，按下方 AppID 选择当前机器人。</li><li>在基本信息中修改名称、上传头像并按平台提示保存、扫码确认或提交审核。</li><li>审核、发布状态以官方页面为准，生效后点击“从 QQ 重新同步资料”。</li></ol><p>网页无法读取审核进度，不会把本地保存标记为“QQ 已同步”或“待审核”。</p><button type="button" data-sync>从 QQ 重新同步资料</button><p data-read-at></p></section><details class="friend-web-only"><summary>可选：自定义名称与头像（仅网页显示）</summary><div class="friend-native-profile-inputs"><label>名称（仅网页显示）<input data-local-name maxlength="60" autocomplete="off"></label><label>头像地址（HTTPS，可选）<input data-local-avatar type="url" autocomplete="off" placeholder="https://…"></label></div><div class="friend-profile-preview"><img data-local-preview hidden alt="网页头像预览" referrerpolicy="no-referrer"><label>上传更换头像（仅网页显示）<input data-avatar-file type="file" accept="image/png,image/jpeg,image/webp"><small>静态 PNG / JPEG / WebP，最大 2 MB；保存时处理为不超过 512 像素。</small></label></div><button type="button" data-remove-avatar>移除自定义头像</button><label class="friend-profile-toggle"><input type="checkbox" data-web-override>在网页使用自定义名称与头像（仅网页显示）</label><p>不勾选时优先显示 QQ 平台资料，自定义内容只作缺失资料的备用。不会影响 QQ 接入、好友、人设或聊天。</p><button type="button" data-save>保存名称与头像（仅网页显示）</button><span data-draft></span></details><p role="status" aria-live="polite" data-result></p>';
    let pendingAvatar=null,clearAvatar=false,fileLoading=false,saving=false,dirtyProfile=false;
    const name=panel.querySelector('[data-local-name]'),url=panel.querySelector('[data-local-avatar]'),toggle=panel.querySelector('[data-web-override]'),preview=panel.querySelector('[data-local-preview]'),message=panel.querySelector('[data-result]');
    name.value=bot.local_name||'';url.value=bot.local_avatar||'';toggle.checked=bot.web_override===true;
    function showPreview(){const src=pendingAvatar||(!clearAvatar?bot.local_avatar_data:'')||url.value||bot.qq_avatar||bot.avatar;if(src){preview.src=src;preview.hidden=false;}else{preview.removeAttribute('src');preview.hidden=true;}}
    function markDirty(){dirtyProfile=true;putText(panel.querySelector('[data-draft]'),'有未保存的修改');showPreview();}
    panel._friendProfileDirty=()=>dirtyProfile||fileLoading||saving;
    panel._friendUpdatePlatform=current=>{
      putText(panel.querySelector('[data-qq-name]'),current.qq_name||'尚未读取到 QQ 平台名称');putText(panel.querySelector('[data-profile-id]'),'AppID '+current.appid+' · 实例 '+current.bot_id);
      const image=panel.querySelector('[data-qq-preview]');image.hidden=!current.qq_avatar;if(current.qq_avatar)image.src=current.qq_avatar;
      putText(panel.querySelector('[data-read-at]'),current.profile_read_at?'最近读取：'+new Date(current.profile_read_at).toLocaleString():'尚未手动重新同步；当前显示连接资料或已保存缓存。');
    };
    const copy=document.createElement('button');copy.type='button';copy.textContent='复制当前机器人 AppID';copy.onclick=async()=>{try{await navigator.clipboard.writeText(bot.appid);putText(message,'AppID 已复制，请在 QQ 官方管理页面核对同一机器人。');}catch{putText(message,'请复制上方 AppID：'+bot.appid);}};panel.querySelector('.friend-platform-profile').append(copy);
    panel._friendUpdatePlatform(bot);showPreview();
    const operations=document.createElement('details');operations.className='friend-platform-operations';operations.open=true;
    operations.innerHTML='<summary>QQ 平台机器人增删改查</summary><p>本页列表是本机已接入的机器人，不是管理员 QQ 账号下的完整机器人清单。</p><p><a href="https://q.qq.com/qqbot/openclaw/login.html" target="_blank" rel="noopener noreferrer">在 QQ 官方页面创建或绑定机器人</a> · <a href="https://q.qq.com/" target="_blank" rel="noopener noreferrer">查看、修改或管理 QQ 平台机器人</a></p><p>新增接入：使用列表顶部添加入口中的官方 QQ 扫码流程，完成 QQ 授权后保存接入。查询：本页读取已接入机器人的公开资料和连接状态。名称、头像修改：在官方管理页面保存并按要求审核，再重新同步。</p><p>移除本机接入不会注销 QQ 机器人，也不会自动删除好友关系或本地记忆。QQ 平台删除、注销或停用是否可用，以管理员官方页面提供的操作为准；当前未接通公开的远端删除接口，不能在本机操作后宣称 QQ 已删除。</p>';
    panel.querySelector('.friend-platform-profile').append(operations);
    preview.onerror=()=>{preview.hidden=true;putText(message,'头像预览加载失败，请检查图片或地址。');};
    panel.querySelector('[data-qq-preview]').onerror=event=>{event.target.hidden=true;};
    name.oninput=markDirty;url.oninput=markDirty;toggle.onchange=markDirty;
    const fileInput=panel.querySelector('[data-avatar-file]');
    fileInput.onchange=async()=>{
      const file=fileInput.files[0];if(!file)return;
      if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024){putText(message,'请上传 2 MB 以内的静态 PNG、JPEG 或 WebP 图片。');fileInput.value='';return;}
      fileLoading=true;panel.querySelector('[data-save]').disabled=true;
      try{
        const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
        const image=new Image();image.src=data;await image.decode();if(image.width*image.height>16000000)throw new Error();
        pendingAvatar=data;clearAvatar=false;toggle.checked=true;markDirty();putText(message,'头像已预览，尚未保存；保存后仅网页显示。');
      }catch{putText(message,'图片无法读取或尺寸过大，请更换图片。');fileInput.value='';}
      finally{fileLoading=false;panel.querySelector('[data-save]').disabled=false;}
    };
    panel.querySelector('[data-remove-avatar]').onclick=()=>{pendingAvatar=null;clearAvatar=true;url.value='';fileInput.value='';markDirty();putText(message,'已移除头像草稿，点击保存后生效；不会删除 QQ 平台头像。');};
    const run=async(sync)=>{
      if(saving||fileLoading)return;saving=true;
      const controls=panel.querySelectorAll('button,input');controls.forEach(b=>b.disabled=true);putText(message,sync?'正在从 QQ 读取公开资料…':'正在保存网页名称与头像…');
      try{
        const result=await api('control-identity',{bot_id:bot.bot_id,appid:bot.appid,...(sync?{sync:true}:{local_name:name.value,local_avatar:url.value,web_override:toggle.checked,clear_avatar:clearAvatar,...(pendingAvatar?{avatar_data:pendingAvatar}:{})})});
        records.set(bot.bot_id,result.bot);bot=result.bot;failed=false;panel._friendUpdatePlatform(bot);
        if(!sync){pendingAvatar=null;clearAvatar=false;dirtyProfile=false;fileInput.value='';putText(panel.querySelector('[data-draft]'),'已保存，仅网页显示');showPreview();}
        apply();putText(message,result.note||(sync?'已读取 QQ 当前公开资料。':'已保存，仅网页显示。'));
      }catch(error){putText(message,(sync?'资料读取失败：':'保存失败，草稿已保留：')+(error.message||'请稍后重试。'));}
      finally{saving=false;controls.forEach(b=>b.disabled=false);}
    };
    panel.querySelector('[data-sync]').onclick=()=>run(true);panel.querySelector('[data-save]').onclick=()=>run(false);body.prepend(panel);
  }
  function source(bot){
    const name=bot.name_source==='qq'?'名称来自 QQ 平台':bot.name_source==='qq_cache'?'名称来自 QQ 缓存':'名称仅网页显示';
    const image=({qq:'头像来自 QQ 平台',qq_cache:'头像来自 QQ 缓存',local:'头像仅网页显示',unavailable:'未取得头像'})[bot.avatar_source]||'头像来源待确认';
    return name+'；'+image;
  }
  function apply() {
    if(!root?.isConnected)return;
    const create=root.querySelector('.bot-list-panel__head button .v-btn__content');
    if(create)putText(create,'添加 / 绑定机器人');
    for(const button of root.querySelectorAll('.bot-list-item__actions button')){
      button.title='移除本机接入，不注销 QQ 机器人';button.setAttribute('aria-label','移除本机接入');
    }
    if(pendingRemoval){
      for(const content of document.querySelectorAll('.v-overlay--active .v-card-text')){
        if(content.textContent.includes(pendingRemoval)&&!content.querySelector('.friend-removal-note')){
          const note=document.createElement('p');note.className='friend-removal-note';note.textContent='此操作仅移除本机接入，不会注销 QQ 平台机器人，也不会删除本地人设、记忆和聊天记录。QQ 平台账号管理请使用官方入口。';content.append(note);
        }
      }
    }
    for(const selection of root.querySelectorAll('.bot-mobile-selection')){
      const title=selection.querySelector('span');const bot=identify(selection,title);
      if(bot){putText(title,bot.name+' · '+bot.appid);avatar(selection.querySelector('img'),bot);}
    }
    const botMenuOpen=!!root.querySelector('.bot-list-panel__mobile-controls [aria-expanded="true"]');
    for(const option of botMenuOpen?document.querySelectorAll('.v-overlay--active .v-list-item'):[]){
      const title=option.querySelector('.v-list-item-title');const bot=identify(option,title);
      if(bot){putText(title,bot.name);putText(option.querySelector('.v-list-item-subtitle'),statusText(bot)+' · AppID '+bot.appid);avatar(option.querySelector('img.bot-list-icon'),bot);}
    }
    for(const row of root.querySelectorAll('.bot-list-item')) {
      const title=row.querySelector('.bot-list-item__title');const bot=identify(row,title);if(!bot)continue;
      putText(title,bot.name);title.title=bot.bot_id;
      let meta=row.querySelector('.friend-native-appid');if(!meta){meta=document.createElement('div');meta.className='friend-native-appid';row.querySelector('.bot-list-item__copy')?.append(meta);}putText(meta,'AppID '+bot.appid);
      avatar(row.querySelector('.bot-list-icon'),bot);
      const subtitle=row.querySelector('.bot-list-item__subtitle');const label=subtitle?.querySelector('span:not(.bot-list-item__status-dot)');
      putText(label,failed?'状态读取失败，在线待确认':statusText(bot));
      const dot=subtitle?.querySelector('.bot-list-item__status-dot');if(dot)dot.style.backgroundColor=!failed&&bot.connection_status==='connected'?'#28734e':bot.connection_status==='disabled'?'#687786':'#98621c';
    }
    const editor=root.querySelector('.bot-editor');const title=editor?.querySelector('.bot-editor__title');const bot=identify(editor,title);
    if(bot){
      putText(title,bot.name);title.title=bot.bot_id;avatar(editor.querySelector('.bot-editor__icon'),bot);
      const instanceInput=editor.querySelector('.bot-editor__section input[type="text"]');
      if(instanceInput?.value===bot.bot_id){
        instanceInput.readOnly=true;instanceInput.setAttribute('aria-label','接入实例 ID');
        const property=editor.querySelector('.bot-editor__section .property-name');
        const label=property?.querySelector('span')||(!property?.childElementCount?property:null);
        putText(label,'接入实例 ID（非 QQ 名称）');
      }
      let info=editor.querySelector('.friend-native-identity');if(!info){info=document.createElement('div');info.className='friend-native-identity';editor.querySelector('.bot-editor__headline-copy')?.append(info);}
      putText(info,`AppID ${bot.appid} · ${failed?'状态读取失败，在线待确认':statusText(bot)} · ${source(bot)} · 实例 ${bot.bot_id}`);
      const original=editor.querySelector('.bot-editor__subtitle');if(original)original.classList.add('friend-native-adapter-state');
      identityPanel(editor,bot);
      if(restored&&localStorage.getItem('friend-selected-bot')!==bot.bot_id)localStorage.setItem('friend-selected-bot',bot.bot_id);
    }
    if(!restored&&records.size&&root.querySelector('.bot-list-item')) {
      restored=true;
      const params=new URLSearchParams(location.hash.split('?')[1]||'');const wanted=params.get('bot_id')||localStorage.getItem('friend-selected-bot');
      const row=[...root.querySelectorAll('.bot-list-item')].find(r=>r.dataset.friendBotId===wanted);
      if(row&&!row.classList.contains('bot-list-item--active'))row.querySelector('.bot-list-item__main')?.click();
    }else if(!restored&&bot&&root.querySelector('.bot-mobile-selection')){
      const wanted=new URLSearchParams(location.hash.split('?')[1]||'').get('bot_id')||localStorage.getItem('friend-selected-bot');
      if(!wanted||wanted===bot.bot_id||!records.has(wanted)){restored=true;mobileChoosing=false;}
      else{
        const option=[...document.querySelectorAll('.v-overlay--active .v-list-item')].find(r=>r.dataset.friendBotId===wanted);
        if(option){restored=true;mobileChoosing=false;option.click();}
        else if(!mobileChoosing){mobileChoosing=true;root.querySelector('.bot-list-panel__mobile-controls .v-field')?.click();}
      }
    }
  }
  function queue(){if(!queued){queued=true;requestAnimationFrame(()=>{queued=false;apply();});}}
  async function refresh(){
    if(loading||!root)return;loading=true;
    try{const result=await api('bot-identities');records=new Map(result.bots.map(b=>[b.bot_id,b]));failed=false;apply();}
    catch{failed=true;apply();}
    finally{loading=false;}
  }
  function sync(){
    const next=location.hash.split('?')[0]==='#/platforms'?document.querySelector('.platform-page'):null;
    if(next===root)return;
    observer?.disconnect();clearInterval(timer);root=next;restored=false;mobileChoosing=false;
    if(!root)return;
    observer=new MutationObserver(queue);observer.observe(root,{childList:true,subtree:true});
    refresh();timer=setInterval(()=>{if(!document.hidden)refresh();},10000);
  }
  function dirty(){return !!root?.querySelector('.friend-native-profile')?._friendProfileDirty?.()||!!root&&[...root.querySelectorAll('.bot-editor__actions button:not([disabled])')].some(b=>b.textContent.includes('保存'));}
  document.addEventListener('click',event=>{
    const sourceRow=event.target.closest('.provider-source-item');
    const sourceId=sourceRow?.querySelector('.provider-source-item__title')?.textContent.trim();
    if(sourceId)localStorage.setItem('friend-selected-provider-source',sourceId);
    if(!root)return;
    const remove=event.target.closest('.bot-list-item__actions button');
    if(remove)pendingRemoval=remove.closest('.bot-list-item')?.dataset.friendBotId||null;
    const row=event.target.closest('.bot-list-item__main');const anchor=event.target.closest('a[href]');
    const next=row?.closest('.bot-list-item')||event.target.closest('.v-list-item[data-friend-bot-id]');const switching=next&&next.dataset.friendBotId!==root.querySelector('.bot-editor')?.dataset.friendBotId;
    const leaving=anchor&&anchor.hash&&anchor.hash!==location.hash;
    if((switching||leaving)&&dirty()&&!window.confirm('当前机器人的名称、头像或接入配置尚未保存。是否放弃修改并切换？')){event.preventDefault();event.stopImmediatePropagation();return;}
    if(next?.dataset.friendBotId){
      localStorage.setItem('friend-selected-bot',next.dataset.friendBotId);restored=true;
      const params=new URLSearchParams(location.hash.split('?')[1]||'');params.set('bot_id',next.dataset.friendBotId);
      history.replaceState(history.state,'',location.pathname+location.search+'#/platforms?'+params.toString());
    }
  },true);
  window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
  // The native component mounts asynchronously after the route changes.
  new MutationObserver(()=>{if(document.querySelector('.platform-page')!==root)sync();if(root)queue();syncProviders();}).observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener('hashchange',()=>{sync();syncProviders();if(root){restored=false;queue();}});
  window.AIFriendNativeBots={sync};
})();
