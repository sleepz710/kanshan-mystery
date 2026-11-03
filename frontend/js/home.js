/* 首页：馆藏案件、我的剧场、大家生成的三组目录，继续上一局；带 ?story=<id> 时直接开局。 */
(() => {
  const { h, icon, hydrateIcons, tidy, api, store, chats, toast, ApiError } = window.KS;
  const POLL_MS = 3000;
  // 失败的生成在首页留半天，之后只在编剧页的对话记录里看得到
  const FAILED_KEEP_MS = 12 * 3600 * 1000;
  // 「大家生成的」默认列这么多，其余折叠
  const OTHERS_SHOWN = 6;
  let pollTimer = null;
  let stories = [];
  let othersOpen = false;
  const shelves = document.getElementById('shelves');
  const launch = document.getElementById('launch');

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
      h('a', { class: 'btn btn-blue btn-sm', href: `/game.html?g=${encodeURIComponent(last.gameId)}` }, '继续')));
  }

  function shelf(id, title, note, action, rows) {
    return h('section', { class: 'shelf', id },
      h('div', { class: 'shelf-head' },
        h('h2', null, title),
        note ? h('span', { class: 'shelf-note' }, note) : null,
        action),
      h('ol', { class: 'case-list' }, rows.map((row) => h('li', null, row))));
  }

  function storyRow(story, label) {
    return h('button', { class: 'case-row', type: 'button', onclick: () => startGame(story.id) },
      h('span', { class: 'row-title' }, story.title),
      h('span', { class: 'row-desc' }, tidy(story.intro)),
      h('span', { class: 'row-meta' }, label ? `${label} · ` : null, `${story.characters} 位角色`),
      icon('arrow', 'row-go'));
  }

  // 这个浏览器里正在生成、或刚失败的剧场
  function pendingChats() {
    return chats.list().filter((chat) => {
      const job = chat.jobs.at(-1);
      return job && (job.status === 'running' || (job.status === 'failed' && Date.now() - job.endedAt < FAILED_KEEP_MS));
    });
  }

  const stepText = (job) => (job.offline ? '和服务器的连接断了，正在重试……' : (job.steps.at(-1) || '编剧正在布置现场'));

  function genRow(chat) {
    const job = chat.jobs.at(-1);
    const running = job.status === 'running';
    const error = job.error || '生成没有完成，请回到对话重试。';
    return h('a', { class: `case-row gen-row ${job.status}`, href: `/studio/?chat=${encodeURIComponent(chat.chatId)}`, dataset: { chat: chat.chatId } },
      h('span', { class: 'row-title' }, chats.title(chat)),
      running
        ? h('span', { class: 'row-desc' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), h('span', { class: 'gen-step' }, stepText(job)))
        : h('span', { class: 'row-desc', title: error }, error),
      h('span', { class: 'row-meta' },
        chat.mode === 'share' ? '出题给朋友 · ' : null,
        running ? h('span', { class: 'gen-clock' }, chats.clock(Date.now() - job.startedAt)) : '回到对话'),
      icon('arrow', 'row-go'));
  }

  // 这个浏览器生成完的案件，按生成完的时间从新到旧；案件列表里已经没有的不列
  function mineDone() {
    const byId = new Map(stories.map((story) => [story.id, story]));
    const done = chats.list()
      .flatMap((chat) => chat.jobs.filter((job) => job.status === 'done' && byId.has(job.storyId)))
      .sort((a, b) => b.endedAt - a.endedAt);
    const seen = new Set();
    return done.filter((job) => !seen.has(job.storyId) && seen.add(job.storyId))
      .map((job) => ({ story: byId.get(job.storyId), share: job.mode === 'share' }));
  }

  function inviteRow() {
    return h('a', { class: 'case-row invite', href: '/studio/' },
      h('span', { class: 'row-title' }, '新建剧场'),
      h('span', { class: 'row-desc' }, '把一碗海龟汤、一段小说、一个网址，或者一句「我想玩一个发生在……的案子」交给编剧，几分钟后开一局新的。'),
      h('span', { class: 'row-meta' }, '和编剧聊聊'),
      icon('arrow', 'row-go'));
  }

  function mineShelf(mine) {
    const rows = [
      ...pendingChats().map(genRow),
      ...mine.map(({ story, share }) => storyRow(story, share ? '出题给朋友' : null)),
    ];
    const action = rows.length ? h('a', { class: 'shelf-action', href: '/studio/' }, icon('plus'), '新建剧场') : null;
    return shelf('shelf-mine', '我的剧场', '这台浏览器里生成的', action, rows.length ? rows : [inviteRow()]);
  }

  function othersShelf(mineIds) {
    const others = stories.filter((story) => story.source !== 'official' && !mineIds.has(story.id));
    if (!others.length) return null;
    const shown = othersOpen ? others : others.slice(0, OTHERS_SHOWN);
    const section = shelf('shelf-others', '大家生成的', `${others.length} 个`, null, shown.map((story) => storyRow(story)));
    const rest = others.length - OTHERS_SHOWN;
    if (rest > 0) {
      section.append(h('button', {
        class: 'shelf-more', type: 'button', 'aria-expanded': String(othersOpen),
        onclick: () => { othersOpen = !othersOpen; renderShelves(); },
      }, othersOpen ? '收起' : `再看 ${rest} 个`));
    }
    return section;
  }

  function renderShelves() {
    const official = stories.filter((story) => story.source === 'official');
    const mine = mineDone();
    shelves.replaceChildren(...[
      official.length ? shelf('shelf-official', '馆藏案件', '制作组编写', null, official.map((story) => storyRow(story))) : null,
      mineShelf(mine),
      othersShelf(new Set(mine.map(({ story }) => story.id))),
    ].filter(Boolean));
  }

  // 生成中的行原地更新用时和进度，不重建节点，鼠标悬停的高亮不会闪
  function refreshRunning() {
    for (const row of shelves.querySelectorAll('.gen-row.running')) {
      const job = chats.get(row.dataset.chat)?.jobs.at(-1);
      if (!job) continue;
      row.querySelector('.gen-clock').textContent = chats.clock(Date.now() - job.startedAt);
      row.querySelector('.gen-step').textContent = stepText(job);
    }
  }

  // 首页也替编剧页查进度：生成完就重新拉案件列表，新案件出现在「我的剧场」
  async function pollPending() {
    pollTimer = null;
    let changed = false;
    for (const chat of chats.list()) {
      const job = chats.runningJob(chat);
      if (!job) continue;
      await chats.checkJob(job);
      chats.put(chat);
      if (job.status !== 'running') changed = true;
    }
    // 编剧页在别的标签页里收尾的生成，这里只看得出生成中的行数对不上
    const running = chats.list().filter(chats.runningJob).length;
    if (running !== shelves.querySelectorAll('.gen-row.running').length) changed = true;
    if (changed) await loadStories();
    else refreshRunning();
    if (running) pollTimer = setTimeout(pollPending, POLL_MS);
  }

  async function loadStories() {
    shelves.setAttribute('aria-busy', 'true');
    try {
      stories = await api.stories();
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      shelves.replaceChildren(h('div', { class: 'case-error' },
        h('span', null, `案件列表没加载出来：${error.message}`),
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: loadStories }, icon('retry'), '重试')));
      shelves.removeAttribute('aria-busy');
      return;
    }
    renderShelves();
    shelves.removeAttribute('aria-busy');
  }

  // 从游戏页按返回键回到首页时，浏览器可能直接恢复旧页面，要收起等待层并刷新续局和案件
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    launch.hidden = true;
    renderResume();
    loadStories();
    if (!pollTimer && chats.list().some(chats.runningJob)) pollPending();
  });

  setInterval(refreshRunning, 1000);

  hydrateIcons();
  const storyId = new URLSearchParams(location.search).get('story');
  if (storyId) startGame(storyId, { replace: true });
  renderResume();
  loadStories().then(() => {
    if (!pollTimer && chats.list().some(chats.runningJob)) pollPending();
  });
})();
