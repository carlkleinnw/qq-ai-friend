/* Presentation only: native routes, authentication and data remain AstrBot's. */
(() => {
  'use strict';
  const HOME = '#/welcome?panel=home';
  const MORE = '#/welcome?panel=more';
  const PERSONA = '#/plugin-view/astrbot_plugin_persona_studio/editor';
  const MANAGE = '#/plugin-view/astrbot_plugin_persona_studio/manage';
  const MEMORY = '#/plugin-view/astrbot_plugin_memory_companion/记忆面板';
  const COMPANION = '#/plugin-view/astrbot_plugin_private_companion/companion-panel';
  const nativeLinks = new Map();
  let root, lastRoute = '', requestVersion = 0;
  const paths = [
    '<path d="m3 10 9-7 9 7v10H3Z"/><path d="M9 20v-7h6v7"/>',
    '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    '<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4Z"/><path d="M13 7a3 3 0 0 1 3-3h5v14h-4a4 4 0 0 0-4 3"/>',
    '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>',
    '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
  ];
  const escape = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = (i) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[i]}</svg>`;
  const link = (href, title, description = '') => `<a class="friend-row" href="${escape(href)}"><span><strong>${escape(title)}</strong>${description ? `<small>${escape(description)}</small>` : ''}</span><span aria-hidden="true">→</span></a>`;
  const items = [[HOME, '首页'], [MANAGE, '好友设置'], [MEMORY, '记忆与记录'], ['#/cron', '提醒'], [MORE, '更多']];
  const coreItems = [[MANAGE+'?section=model', '模型配置'], [MANAGE+'?section=qq', 'QQ 连接'], [MANAGE+'?section=agent', 'Agent 连接']];
  let connectionVersion = 0;
  const coreHTML = (compact = false) => coreItems.map(([href, title], i) => `<a class="${compact ? 'friend-core-nav-link' : 'friend-core-link'}" href="${href}"><strong>${title}</strong><small data-connection="${i}">正在读取状态…</small></a>`).join('');

  async function refreshConnections(botId = localStorage.getItem('friend-selected-bot')) {
    const version = ++connectionVersion;
    const labels = () => document.querySelectorAll('[data-connection]');
    labels().forEach(el => { el.textContent = '正在读取状态…'; });
    try {
      const response = await fetch('/api/v1/plugins/extensions/astrbot_plugin_persona_studio/connections' + (botId ? '?bot_id=' + encodeURIComponent(botId) : ''), {
        headers: {Authorization: 'Bearer ' + localStorage.getItem('token')}, signal: AbortSignal.timeout(10000)
      });
      if (!response.ok) throw new Error('读取失败');
      const result = await response.json();
      if (result.status === 'error') throw new Error('读取失败');
      const data = result.data?.model ? result.data : result;
      if (version !== connectionVersion) return;
      const modelStates = {configured: '已配置，未测试', unavailable: '模型未启用或不可用', unconfigured: '尚未选择模型', disabled: '聊天已停用', external: '由外部 Agent 提供'};
      const agentStates = {local: '内置 Agent，无需外部连接', configured: '已配置，未测试连接', incomplete: '尚未配置完整', unsupported: '请在配置页核对'};
      const values = [data.model.id ? `${data.model.id} · ${modelStates[data.model.status]}` : modelStates[data.model.status],
        data.qq.total ? `${data.qq.connected}/${data.qq.total} 个 QQ 机器人已连接` : '尚未连接 QQ 机器人',
        data.agent.type === 'local' ? agentStates.local : `${data.agent.type} · ${agentStates[data.agent.status]}`];
      labels().forEach(el => { el.textContent = values[Number(el.dataset.connection)] || '请进入配置页核对'; });
    } catch {
      if (version === connectionVersion) labels().forEach(el => { el.textContent = '状态读取失败，点击进入配置'; });
    }
  }
  const navHTML = () => items.map(([href, title], i) => `<a href="${href}" data-section="${i}">${icon(i)}<span>${title}</span></a>`).join('');

  async function state(botId) {
    const response = await fetch('/api/v1/plugins/extensions/astrbot_plugin_persona_studio/state' + (botId ? '?bot_id=' + encodeURIComponent(botId) : ''), {
      headers: {Authorization: 'Bearer ' + localStorage.getItem('token')}, signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) throw new Error(response.status === 401 ? '登录已过期，请重新登录。' : '暂时无法读取好友，请稍后重试。');
    const data = await response.json();
    if (data.status === 'error') throw new Error(data.message || '读取失败，请重试。');
    return data.data?.bots ? data.data : data;
  }

  function renderHome() {
    root.innerHTML = `<header class="friend-page-head"><div><h1>你好，今天想调整什么？</h1><p>让你的 AI 好友，更懂你的习惯。</p></div><a class="friend-text-link" href="#/platforms">添加 QQ 机器人</a></header>
      <nav class="friend-core-links" aria-label="核心配置">${coreHTML()}</nav>
      <section class="friend-current" aria-label="当前好友"><div id="friend-home-state" role="status">正在读取好友…</div></section>
      <section class="friend-shortcuts"><div><h2>常用操作</h2><p>人设、记忆和提醒，都在这里。</p></div><div class="friend-shortcut-list">${link(MEMORY, '查看与修改记忆', '查找它记住的内容，纠正不准确的信息')}${link('#/cron', '管理提醒', '查看时间、接收对象，修改或取消提醒')}${link(COMPANION, '主动联系与陪伴', '管理联系人、免打扰和主动消息')}</div></section>
      <p class="friend-footnote">关闭网页后，好友仍会在后台运行。QQ 回复和提醒需要电脑开机并联网。</p>`;
    loadHome();
  }

  async function loadHome(botId) {
    const version = ++requestVersion;
    const box = root.querySelector('#friend-home-state');
    if (!box) return;
    box.setAttribute('aria-busy', 'true');
    try {
      let data = await state(botId);
      if (version !== requestVersion || !box.isConnected) return;
      const bots = data.bots || [];
      if (!bots.length) {
        box.innerHTML = `<h2>先连接你的第一个 QQ 好友</h2><p>准备好聊天服务，再扫码绑定 QQ，就可以开始聊天。</p><div class="friend-inline-actions"><a class="friend-primary" href="#/providers">设置聊天服务</a><a class="friend-secondary" href="#/platforms">连接 QQ 好友</a></div>`;
        return;
      }
      const saved = localStorage.getItem('friend-selected-bot');
      const bot = bots.find(b => b.bot_id === (botId || saved)) || bots[0];
      if (!data.current || data.current.bot_id !== bot.bot_id) data = await state(bot.bot_id);
      if (version !== requestVersion || !box.isConnected) return;
      localStorage.setItem('friend-selected-bot', bot.bot_id);
      refreshConnections(bot.bot_id);
      const connected = bot.enabled && bot.connected;
      box.innerHTML = `<div class="friend-current-top"><label for="friend-home-bot">正在管理的机器人<select id="friend-home-bot">${bots.map(b => `<option value="${escape(b.bot_id)}" ${b.bot_id === bot.bot_id ? 'selected' : ''}>${escape(b.name)}</option>`).join('')}</select></label><span class="friend-status ${connected ? 'is-connected' : ''}">${!bot.enabled ? '已停用' : connected ? 'QQ 已连接' : '等待 QQ 连接'}</span></div>
        <h2>${bot.avatar ? `<img class="friend-bot-avatar" src="${escape(bot.avatar)}" alt="QQ 头像" referrerpolicy="no-referrer">` : ''}${escape(bot.name)}</h2><p>AppID ${escape(bot.appid||'未设置')} · ${bot.name_source==='qq'?'名称来自 QQ':'本机名称或 QQ 资料缓存'}</p>
        <div class="friend-inline-actions"><a class="friend-primary" href="${MANAGE}?bot_id=${encodeURIComponent(bot.bot_id)}">管理机器人与好友</a><button class="friend-secondary" id="friend-test-chat" type="button">测试网页回复</button></div>
        <p class="friend-connection-note">${data.model_ready ? '已有启用的聊天模型，实际回复请通过测试确认。' : '尚未启用聊天模型。请先到“聊天与语音服务”完成设置。'}${bot.error ? ' ' + escape(bot.error) : ''}</p>
        ${!data.model_ready ? '<a class="friend-text-link" href="#/providers">设置聊天与语音服务 →</a>' : ''}`;
      box.querySelector('select').onchange = (e) => loadHome(e.target.value);
      box.querySelector('#friend-test-chat').onclick = () => {
        // Use the native chat switch so the original chat selection flow stays intact.
        const button = document.querySelector('.top-header .mode-switch-btn');
        if (button) button.click();
        else location.hash = '#/chat';
      };
    } catch (error) {
      if (version !== requestVersion || !box.isConnected) return;
      box.innerHTML = `<h2>暂时无法读取好友</h2><p role="alert">${escape(error.message)}</p><button class="friend-secondary" id="friend-home-retry" type="button">重新读取</button>`;
      box.querySelector('button').onclick = () => loadHome(botId);
    } finally { if (version === requestVersion) box.removeAttribute('aria-busy'); }
  }

  function renderMore() {
    const groups = [
      ['连接与服务', [['#/platforms','QQ 好友连接','添加好友、查看连接和接入设置'], ['#/providers','聊天与语音服务','模型、密钥、语音识别和语音回复'], ['#/extension','插件与外部工具','管理已安装的功能和工具连接']]],
      ['陪伴与扩展', [[COMPANION,'陪伴与扩展功能','主动联系、群聊、学习、世界知识与生活观察'], ['#/knowledge-base','知识库','管理供 AI 查阅的资料']]],
      ['维护与高级设置', [['#/data/statistics?details=1','模型用量与运行情况','调用统计、资源占用'], ['#/data/conversations','聊天记录','查看已有会话'], ['#/data/logs','运行日志','查看错误与运行信息'], ['#/data/trace','处理过程','排查一次回复的处理步骤'], ['#/persona','高级人设管理','原生人格库与详细配置'], ['#/config','配置文件','管理机器人独立配置'], ['#/session-management','自定义会话规则','指定会话的人设与配置'], ['#/subagent','多助手协作','原生子代理编排'], ['#/settings','系统设置与维护','外观、安全、网络、备份和系统维护'], ['#/welcome?panel=original','原版欢迎页','版本和原生使用指引']]]
    ];
    const known = new Set(groups.flatMap(([, rows]) => rows.map(([href]) => href.split('?')[0])).concat(items.map(([href]) => href.split('?')[0])));
    const extras = [...nativeLinks].filter(([href]) => !known.has(href.split('?')[0]));
    if (extras.length) groups.push(['其他扩展', extras.map(([href, title]) => [href, title, '保留的原有功能入口'])]);
    root.innerHTML = `<header class="friend-page-head"><div><h1>更多设置</h1><p>不常用的功能，需要时再打开。</p></div></header><div class="friend-settings-groups">${groups.map(([title, rows]) => `<section><h2>${title}</h2>${rows.map(([href, label, desc]) => link(href, label, desc)).join('')}</section>`).join('')}</div><div class="friend-original"><span>熟悉原来的布局？所有原有功能仍然保留。</span><button class="friend-text-link" id="friend-native" type="button">查看原版面板</button></div>`;
    root.querySelector('#friend-native').onclick = () => { sessionStorage.setItem('friend-native', '1'); location.hash = '#/data/statistics'; location.reload(); };
  }

  function sync() {
    const sidebar = document.querySelector('.sidebar-container');
    const main = document.querySelector('.v-main');
    if (!sidebar || !main) {
      document.body.classList.remove('friend-simple');
      document.querySelector('#friend-restore')?.remove();
      document.querySelectorAll('.friend-mobile-nav').forEach(nav => nav.remove());
      root?.remove(); root = null;
      main?.classList.remove('friend-custom-page');
      requestVersion++;
      lastRoute = '';
      return;
    }
    if (sessionStorage.getItem('friend-native') === '1') {
      if (!document.querySelector('#friend-restore')) {
        const button = document.createElement('button'); button.id = 'friend-restore'; button.textContent = '返回简洁面板';
        button.onclick = () => { sessionStorage.removeItem('friend-native'); location.hash = HOME; location.reload(); };
        document.body.append(button);
      }
      return;
    }
    document.body.classList.add('friend-simple');
    if (!sidebar.querySelector('.friend-nav')) {
      sidebar.querySelectorAll('a[href^="#/"]').forEach(a => nativeLinks.set(decodeURI(a.getAttribute('href')), a.textContent.trim()));
      const nav = document.createElement('nav'); nav.className = 'friend-nav'; nav.setAttribute('aria-label', '常用功能'); nav.innerHTML = navHTML(); sidebar.append(nav);
      const coreNav = document.createElement('nav'); coreNav.className = 'friend-core-nav'; coreNav.setAttribute('aria-label', '核心配置'); coreNav.innerHTML = coreHTML(true); sidebar.append(coreNav);
      if (!document.querySelector('.friend-mobile-nav')) {
        const mobile = document.createElement('nav'); mobile.className = 'friend-mobile-nav'; mobile.setAttribute('aria-label', '常用功能'); mobile.innerHTML = navHTML(); document.body.append(mobile);
      }
      const brand = sidebar.querySelector('.dashboard-sidebar-brand-name'); if (brand) brand.textContent = 'AI 好友';
    }
    if (!root || !root.isConnected) { root = document.createElement('div'); root.className = 'friend-workspace'; main.append(root); lastRoute = ''; }
    const hash = decodeURI(location.hash);
    if (!lastRoute && hash === '#/data/statistics') { location.replace(HOME); return; }
    const isHome = hash === HOME || hash === '#/welcome';
    const isMore = hash === MORE;
    main.classList.toggle('friend-custom-page', isHome || isMore);
    root.hidden = !(isHome || isMore);
    let section = isHome ? 0 : hash.startsWith(PERSONA)||hash.startsWith(MANAGE) ? 1 : hash.startsWith(MEMORY) || hash.startsWith('#/data/conversations') ? 2 : hash.startsWith('#/cron') ? 3 : 4;
    document.querySelectorAll('[data-section]').forEach(a => { if (Number(a.dataset.section) === section) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current'); });
    if (hash !== lastRoute) {
      requestVersion++; lastRoute = hash;
      if (isHome) renderHome(); else if (isMore) renderMore();
      refreshConnections();
      document.title = `${items[section][1]} · AI 好友`;
    }
  }
  let queued = false;
  const schedule = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; sync(); }); } };
  // Observe mounts only. Ignore text/style mutations generated by charts and status updates.
  new MutationObserver(mutations => { if (mutations.some(m => [...m.addedNodes, ...m.removedNodes].some(n => n.nodeType === 1 && (n.matches?.('.v-main,.sidebar-container,.v-navigation-drawer') || n.querySelector?.('.v-main,.sidebar-container'))))) schedule(); }).observe(document.documentElement, {childList:true, subtree:true});
  window.addEventListener('hashchange', schedule);
  window.addEventListener('message', (event) => {
    const frame = [...document.querySelectorAll('iframe')].find(f => f.contentWindow === event.source);
    if (!frame || !(decodeURI(location.hash).startsWith(PERSONA)||decodeURI(location.hash).startsWith(MANAGE))) return;
    if (event.data?.type === 'ai-friend-bot-request') {
      const botId = new URLSearchParams(location.hash.split('?')[1] || '').get('bot_id') || localStorage.getItem('friend-selected-bot');
      const params=new URLSearchParams(location.hash.split('?')[1]||'');
      let selected;try{selected=JSON.parse(localStorage.getItem('friend-selected-session')||'null');}catch{}
      frame.contentWindow.postMessage({type: 'ai-friend-bot-context', botId,section:params.get('section'),umo:params.get('umo')||(selected?.botId===botId?selected.umo:null)}, '*');
    } else if (event.data?.type === 'ai-friend-bot-selected' && typeof event.data.botId === 'string') {
      localStorage.setItem('friend-selected-bot', event.data.botId);
      refreshConnections(event.data.botId);
    } else if(event.data?.type==='ai-friend-session-selected'&&typeof event.data.botId==='string') {
      localStorage.setItem('friend-selected-session',JSON.stringify({botId:event.data.botId,umo:event.data.umo||null}));
    }
  });
  window.addEventListener('DOMContentLoaded', schedule);
  schedule();
})();
