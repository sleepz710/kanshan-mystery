/* 首页：案件列表、新建剧场入口、生成中的剧场、继续上一局；带 ?story=<id> 时直接开局。 */
(() => {
  const { h, icon, hydrateIcons, tidy, api, store, chats, toast, ApiError } = window.KS;
  const POLL_MS = 3000;
  // 失败的生成在首页留半天，之后只在编剧页的对话记录里看得到
  const FAILED_KEEP_MS = 12 * 3600 * 1000;
  let pollTimer = null;
  const grid = document.getElementById('case-grid');
  const launch = document.getElementById('launch');
  const heroStart = document.getElementById('hero-start');

  async function startGame(storyId, { replace = false } = {}) {
    launch.hidden = false;
    let game;
    try {
      game = await api.newGame(storyId);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      launch.hidden = true;
      if (replace) history.replaceState(null, '', '/');
      toast(`没能开局：${error.message}`, 'error', 6000);
      return;
    }
    const state = store.create(game, storyId);
    store.save(state);
    const url = `/game.html?g=${encodeURIComponent(state.gameId)}`;
    if (replace) location.replace(url);
    else location.assign(url);
  }

  function renderResume() {
    const box = document.getElementById('resume');
    const last = store.last();
    box.replaceChildren();
    if (!last || last.finished) return;
    box.append(h('div', { class: 'resume' },
      h('span', { class: 'resume-icon' }, icon('clock')),
      h('div', { class: 'resume-text' },
        h('b', null, `继续调查「${last.title}」`),
        h('span', null, `第 ${last.turns} 回合 · 已获 ${last.clues.length} 条线索 · 拆穿 ${last.exposed.length} 句谎话`)),
      h('a', { class: 'btn btn-blue', href: `/game.html?g=${encodeURIComponent(last.gameId)}` }, '继续')));
  }

  function caseCard(story, featured) {
    const official = story.source === 'official';
    return h('article', { class: `case-card${featured ? ' featured' : ''}` },
      featured ? h('div', { class: 'case-stamp', 'aria-hidden': 'true' }, '待查') : null,
      h('div', { class: 'case-meta' },
        h('span', { class: `tag ${official ? 'tag-red' : 'tag-blue'}` }, official ? '招牌案件' : '生成案件'),
        h('span', { class: 'meta-item' }, icon('users'), `${story.characters} 位角色`),
        featured ? h('span', { class: 'meta-item' }, icon('clock'), '约 20 分钟') : null),
      h('h3', null, story.title),
      featured ? h('blockquote', { class: 'soup paper' }, tidy(story.intro)) : h('p', { class: 'case-intro' }, tidy(story.intro)),
      h('div', { class: 'case-actions' },
        h('button', {
          class: featured ? 'btn btn-primary btn-lg' : 'btn btn-gold',
          type: 'button',
          onclick: () => startGame(story.id),
        }, '开始调查')));
  }

  function studioCard() {
    return h('a', { class: 'case-card studio-card', href: '/studio/' },
      h('span', { class: 'studio-plus' }, icon('plus')),
      h('h3', null, '新建剧场'),
      h('p', { class: 'case-intro' }, '把一碗海龟汤、一段小说、一个网址，或者一句「我想玩一个发生在……的案子」交给编剧，几分钟后开一局新的。'),
      h('span', { class: 'studio-go' }, '和编剧聊聊', icon('arrow')));
  }

  // 这个浏览器里正在生成、或刚失败的剧场；生成完的已经在案件列表里
  function pendingChats() {
    return chats.list().filter((chat) => {
      const job = chat.jobs.at(-1);
      return job && (job.status === 'running' || (job.status === 'failed' && Date.now() - job.endedAt < FAILED_KEEP_MS));
    });
  }

  function genCard(chat) {
    const job = chat.jobs.at(-1);
    const running = job.status === 'running';
    const share = chat.mode === 'share';
    return h('a', { class: `case-card gen-card ${job.status}`, href: `/studio/?chat=${encodeURIComponent(chat.chatId)}`, dataset: { chat: chat.chatId } },
      h('div', { class: 'case-meta' },
        running
          ? h('span', { class: 'tag tag-gold' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), '生成中')
          : h('span', { class: 'tag tag-red' }, '生成未完成'),
        h('span', { class: 'meta-item' }, share ? '出题给朋友' : '自己玩'),
        running ? h('span', { class: 'meta-item gen-clock' }, icon('clock'), chats.clock(Date.now() - job.startedAt)) : null),
      h('h3', null, chats.title(chat)),
      running
        ? h('p', { class: 'gen-step' }, job.offline ? '和服务器的连接断了，正在重试……' : (job.steps.at(-1) || '编剧正在布置现场'))
        : h('p', { class: 'gen-error' }, job.error || '生成没有完成，请回到对话重试。'),
      h('span', { class: 'studio-go' }, running ? '查看进度' : '回到对话', icon('arrow')));
  }

  function renderPending() {
    const cards = pendingChats().map(genCard);
    for (const old of grid.querySelectorAll('.gen-card')) old.remove();
    grid.querySelector('.studio-card')?.after(...cards);
  }

  // 首页也替编剧页查进度：生成完就重新拉案件列表，新案件出现在列表里
  async function pollPending() {
    pollTimer = null;
    let finished = false;
    for (const chat of chats.list()) {
      const job = chats.runningJob(chat);
      if (!job) continue;
      await chats.checkJob(job);
      chats.put(chat);
      if (job.status !== 'running') finished = true;
    }
    if (finished) await loadStories();
    else renderPending();
    if (chats.list().some(chats.runningJob)) pollTimer = setTimeout(pollPending, POLL_MS);
  }

  async function loadStories() {
    grid.setAttribute('aria-busy', 'true');
    let stories;
    try {
      stories = await api.stories();
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      grid.replaceChildren(h('div', { class: 'case-error' },
        h('span', null, `案件列表没加载出来：${error.message}`),
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: loadStories }, icon('retry'), '重试')));
      grid.removeAttribute('aria-busy');
      return;
    }
    const official = stories.filter((story) => story.source === 'official');
    const generated = stories.filter((story) => story.source !== 'official');
    grid.replaceChildren(
      ...official.map((story, index) => caseCard(story, index === 0)),
      studioCard(),
      ...pendingChats().map(genCard),
      ...generated.map((story) => caseCard(story, false)));
    grid.removeAttribute('aria-busy');
    if (official.length) {
      heroStart.disabled = false;
      heroStart.onclick = () => startGame(official[0].id);
    } else {
      heroStart.hidden = true;
    }
  }

  // 从游戏页按返回键回到首页时，浏览器可能直接恢复旧页面，要收起等待层并刷新续局卡片
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    launch.hidden = true;
    renderResume();
    renderPending();
    if (!pollTimer && chats.list().some(chats.runningJob)) pollPending();
  });

  setInterval(() => {
    for (const node of grid.querySelectorAll('.gen-card.running')) {
      const job = chats.get(node.dataset.chat)?.jobs.at(-1);
      const clock = node.querySelector('.gen-clock');
      if (job && clock) clock.replaceChildren(icon('clock'), chats.clock(Date.now() - job.startedAt));
    }
  }, 1000);

  hydrateIcons();
  const storyId = new URLSearchParams(location.search).get('story');
  if (storyId) startGame(storyId, { replace: true });
  renderResume();
  loadStories().then(() => {
    if (!pollTimer && chats.list().some(chats.runningJob)) pollPending();
  });
})();
