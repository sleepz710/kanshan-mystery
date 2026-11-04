/* 首页：16:9 游戏标题画面。标题、从已有剧场游玩、新建剧场三个视图共用一幅夜山画面，后两个记在 hash 上
   （#cases、#new），浏览器后退回上一个视图。带 ?story=<id> 时直接开局。 */
(() => {
  const { h, icon, api, store, chats, toast, ApiError } = window.KS;
  const DESIGN_W = 1600;
  const DESIGN_H = 900;
  const POLL_MS = 3000;
  // 失败的生成在「我的剧场」留半天，之后只在编剧页的对话记录里看得到
  const FAILED_KEEP_MS = 12 * 3600 * 1000;
  const SOUND_KEY = 'kanshan:sound';
  const PROVIDERS = { deepseek: 'DeepSeek', openai: 'OpenAI' };
  const VIEWS = { '#cases': 'cases', '#new': 'new' };

  const $ = (id) => document.getElementById(id);
  const body = document.body;
  const shelves = $('shelves');
  const launch = $('launch');

  // 标题画面左下的菜单：main 是主菜单，start 是点「开始探案」后换上的子菜单
  let menu = 'main';
  // 案件列表；还没加载出来或加载失败时是 null
  let stories = null;
  let pollTimer = null;

  // ---------- 画面 ----------

  // 夜山画面铺满窗口不留黑边；界面按窗口高度等比缩放，标题贴左上、菜单贴左下，宽度随窗口比例伸缩
  function fit() {
    const scale = innerHeight / DESIGN_H;
    const style = document.documentElement.style;
    style.setProperty('--fit', scale);
    style.setProperty('--cover', Math.max(innerWidth / DESIGN_W, scale));
    style.setProperty('--ui-w', `${innerWidth / scale}px`);
    body.classList.add('fitted');
  }

  function paintScene() {
    const stars = [];
    for (let i = 0; i < 46; i++) {
      const r = 1 + (i % 3) * 0.8;
      stars.push(h('i', {
        class: 'star',
        style: {
          left: `${(i * 397 + 53) % 1600}px`, top: `${24 + ((i * 151) % 360)}px`,
          width: `${r}px`, height: `${r}px`, 'animation-delay': `${((i * 7) % 9) * 0.45}s`,
        },
      }));
    }
    $('stars').replaceChildren(...stars);
    // 灯笼沿一条二次贝塞尔曲线从山脚排到谜案馆门口
    const [p0, p1, p2] = [[360, 846], [820, 700], [1060, 556]];
    const n = 15;
    const lamps = [];
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1);
      const at = (k) => Math.round((1 - t) ** 2 * p0[k] + 2 * (1 - t) * t * p1[k] + t ** 2 * p2[k]);
      lamps.push(h('i', { class: 'lamp', style: { left: `${at(0)}px`, top: `${at(1)}px`, 'animation-delay': `${(i * 0.24).toFixed(2)}s` } }));
    }
    $('lamps').replaceChildren(...lamps);
  }

  // ---------- 声音 ----------

  const sound = (() => {
    let prefs = { music: true, sfx: true };
    try {
      prefs = { ...prefs, ...JSON.parse(localStorage.getItem(SOUND_KEY)) };
    } catch {
      // 读不到本地存储（隐私模式）或记录坏了，用默认的全开
    }
    const bgm = new Audio('/assets/audio/bgm.mp3');
    bgm.loop = true;
    bgm.volume = 0.3;
    let ctx = null;

    // 浏览器要等玩家先点一下或按个键才肯出声
    function afterGesture(fn) {
      const once = () => {
        removeEventListener('pointerdown', once, true);
        removeEventListener('keydown', once, true);
        fn();
      };
      addEventListener('pointerdown', once, true);
      addEventListener('keydown', once, true);
    }

    function playMusic() {
      if (!prefs.music) return;
      bgm.play().catch((error) => {
        if (error.name === 'NotAllowedError') afterGesture(playMusic);
        // 曲子还没放进 frontend/assets/audio/ 时不显示音乐开关
        else if (error.name === 'NotSupportedError') $('toggle-music').hidden = true;
        // 关音乐打断了还没开始的播放
        else if (error.name !== 'AbortError') throw error;
      });
    }

    // 菜单音效用 Web Audio 现合成：[频率, 起点, 时长, 音量]。移动一声轻响，确认两声上行，返回两声下行
    const TONES = {
      move: [[880, 0, 0.07, 0.025]],
      confirm: [[660, 0, 0.12, 0.05], [990, 0.07, 0.2, 0.05]],
      back: [[660, 0, 0.1, 0.045], [440, 0.06, 0.18, 0.045]],
    };

    function sfx(name) {
      if (!prefs.sfx || !navigator.userActivation.hasBeenActive) return;
      ctx = ctx || new AudioContext();
      if (ctx.state === 'suspended') ctx.resume();
      const now = ctx.currentTime;
      for (const [freq, delay, length, peak] of TONES[name]) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, now + delay);
        gain.gain.exponentialRampToValueAtTime(peak, now + delay + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + length);
        osc.connect(gain).connect(ctx.destination);
        osc.start(now + delay);
        osc.stop(now + delay + length + 0.02);
      }
    }

    function render() {
      for (const [key, id] of [['music', 'toggle-music'], ['sfx', 'toggle-sfx']]) {
        $(id).setAttribute('aria-pressed', String(prefs[key]));
        $(id).querySelector('b').textContent = prefs[key] ? '开' : '关';
      }
    }

    function toggle(key) {
      prefs[key] = !prefs[key];
      try {
        localStorage.setItem(SOUND_KEY, JSON.stringify(prefs));
      } catch {
        // 存不下时开关只在这一页有效
      }
      render();
      if (key === 'music') {
        if (prefs.music) playMusic();
        else bgm.pause();
      } else sfx('confirm');
    }

    $('toggle-music').addEventListener('click', () => toggle('music'));
    $('toggle-sfx').addEventListener('click', () => toggle('sfx'));
    render();
    return { sfx, playMusic };
  })();

  // ---------- 视图与菜单 ----------

  const viewOf = () => VIEWS[location.hash] || 'title';

  // 当前能用方向键选的项：标题画面是左下的菜单，从已有剧场游玩是案件行加「返回」
  function items() {
    const view = viewOf();
    const root = view === 'title' ? $(`menu-${menu}`) : $(`view-${view}`);
    return [...root.querySelectorAll('.item, .row')].filter((item) => !item.hidden);
  }

  // 选中项只有一个，焦点跟着它，回车就是确认它
  function select(item, { quiet = false, scroll = false } = {}) {
    for (const other of document.querySelectorAll('.item.on, .row.on')) if (other !== item) other.classList.remove('on');
    if (!item.classList.contains('on')) {
      item.classList.add('on');
      if (!quiet) sound.sfx('move');
    }
    if (document.activeElement !== item) item.focus({ preventScroll: true });
    if (scroll) item.scrollIntoView({ block: 'nearest' });
  }

  function move(step) {
    const list = items();
    if (!list.length) return;
    const index = list.findIndex((item) => item.classList.contains('on'));
    const next = index < 0 ? (step > 0 ? 0 : list.length - 1) : (index + step + list.length) % list.length;
    select(list[next], { scroll: true });
  }

  function setMenu(name, pick = '[data-default]') {
    menu = name;
    $('menu-main').hidden = name !== 'main';
    $('menu-start').hidden = name !== 'start';
    select($(`menu-${name}`).querySelector(pick), { quiet: true });
  }

  function render() {
    const view = viewOf();
    const left = body.dataset.view;
    body.dataset.view = view;
    for (const name of ['title', 'cases', 'new']) $(`view-${name}`).hidden = name !== view;
    if (view === 'title') {
      renderContinue();
      // 从两个视图回来时停在「开始探案」的子菜单，选中刚才进去的那一项
      if (left !== 'title') setMenu('start', `[data-view="${left}"]`);
      else setMenu(menu);
    } else if (view === 'cases') renderShelves();
    else $('material').focus();
  }

  function go(view) {
    history.pushState({ from: 'title' }, '', `#${view}`);
    render();
  }

  function back() {
    sound.sfx('back');
    if (viewOf() === 'title') {
      setMenu('main', '#item-start');
      return;
    }
    // 从标题画面点进来的后退一步；直接打开 #cases、#new 的换成标题画面
    if (history.state && history.state.from === 'title') history.back();
    else {
      history.replaceState(null, '', location.pathname);
      render();
    }
  }

  function renderContinue() {
    const last = store.last();
    const item = $('item-continue');
    item.hidden = !last || last.finished;
    if (item.hidden) return;
    item.href = `/game.html?g=${encodeURIComponent(last.gameId)}`;
    $('continue-meta').textContent = `${last.title} · 第 ${last.turns} 回合`;
  }

  // 「模型设置」「退出」只在桌面版有：设置接口由桌面版挂载，它注入的脚本会设 KANSHAN_DESKTOP；退出由窗口注入的 pywebview 提供
  async function loadSettings() {
    if (!window.KANSHAN_DESKTOP) return;
    const response = await fetch('/api/settings');
    if (!response.ok) throw new Error(`模型设置读取失败（${response.status}）`);
    const settings = await response.json();
    const meta = $('settings-meta');
    meta.textContent = `${PROVIDERS[settings.provider] || settings.provider} · key ${settings.has_key ? '已填写' : '未填写'}`;
    meta.classList.toggle('warn', !settings.configured);
    $('item-settings').hidden = false;
  }

  function showQuit() {
    const bridge = window.pywebview && window.pywebview.api;
    $('item-quit').hidden = !(bridge && typeof bridge.quit === 'function');
  }

  // ---------- 开局 ----------

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

  // ---------- 从已有剧场游玩 ----------

  const mark = () => h('span', { class: 'mark' });

  // 每个案件最近的一局，没结束的才算数
  function openGames() {
    const latest = new Map();
    for (const game of store.list().sort((a, b) => a.updatedAt - b.updatedAt)) latest.set(game.storyId, game);
    for (const [storyId, game] of latest) if (game.finished) latest.delete(storyId);
    return latest;
  }

  // 有没查完的一局就接着查，否则开新局
  function storyRow(story, game) {
    const progress = game && game.turns ? ` · 调查到第 ${game.turns} 回合` : '';
    const children = [
      mark(),
      h('span', { class: 'name' }, story.title),
      h('span', { class: 'info' },
        story.checked === false ? h('span', { class: 'check-badge' }, '检查未全部通过') : null,
        `${story.characters} 位角色${progress}`),
    ];
    const props = { class: 'row', dataset: { key: `story:${story.id}` } };
    return game
      ? h('a', { ...props, href: `/game.html?g=${encodeURIComponent(game.gameId)}` }, children)
      : h('button', { ...props, type: 'button', onclick: () => startGame(story.id) }, children);
  }

  // 这个浏览器里正在生成、或刚失败的剧场
  function pendingChats() {
    return chats.list().filter((chat) => {
      const job = chat.jobs.at(-1);
      return job && (job.status === 'running' || (job.status === 'failed' && Date.now() - job.endedAt < FAILED_KEEP_MS));
    });
  }

  const stepText = (job) => (job.offline ? '和服务器的连接断了，正在重试' : (job.steps.at(-1) || '编剧正在布置现场'));
  const clockText = (job) => `· ${job.quality === 'fine' ? '精修中' : '快速生成中'} · ${chats.clock(Date.now() - job.startedAt)}`;

  function genRow(chat) {
    const job = chat.jobs.at(-1);
    const running = job.status === 'running';
    return h('a', {
      class: `row ${job.status}`,
      href: `/studio/?chat=${encodeURIComponent(chat.chatId)}`,
      title: running ? null : (job.error || '生成没有完成，请回到对话重试。'),
      dataset: { key: `chat:${chat.chatId}`, chat: chat.chatId },
    },
    mark(),
    h('span', { class: 'name' }, chats.title(chat)),
    running
      ? h('span', { class: 'info' },
        h('span', { class: 'dots', 'aria-hidden': 'true' }, h('i', { class: 'gen-dot' }), h('i', { class: 'gen-dot' }), h('i', { class: 'gen-dot' })),
        h('span', { class: 'gen-step' }, stepText(job)),
        h('span', { class: 'gen-clock' }, clockText(job)))
      : h('span', { class: 'info' }, '生成没有完成 · 回到对话'));
  }

  function inviteRow() {
    return h('a', {
      class: 'row', href: '#new', dataset: { key: 'invite' },
      onclick: (event) => {
        event.preventDefault();
        history.replaceState(history.state, '', '#new');
        render();
      },
    }, mark(), h('span', { class: 'name' }, '新建剧场'), h('span', { class: 'info' }, '把素材交给编剧，改编成一桩新案子'));
  }

  const shelf = (title, rows) => h('section', { class: 'shelf' }, h('h2', null, title), rows);

  // 重画时保留选中的那一行，生成完自动刷新也不会把键盘选中弄丢
  function renderShelves() {
    if (!stories) return;
    const games = openGames();
    const official = stories.filter((story) => story.source === 'official');
    const generated = stories.filter((story) => story.source === 'generated')
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    const mine = [...pendingChats().map(genRow), ...generated.map((story) => storyRow(story, games.get(story.id)))];
    const picked = shelves.querySelector('.row.on');
    const focused = picked && document.activeElement === picked;
    shelves.replaceChildren(...[
      official.length ? shelf('馆藏案件', official.map((story) => storyRow(story, games.get(story.id)))) : null,
      shelf('我的剧场', mine.length ? mine : [inviteRow()]),
    ].filter(Boolean));
    const again = picked && [...shelves.querySelectorAll('.row')].find((row) => row.dataset.key === picked.dataset.key);
    if (!again) return;
    again.classList.add('on');
    if (focused) again.focus({ preventScroll: true });
  }

  // 生成中的行原地更新用时和进度，不重建节点
  function refreshRunning() {
    for (const row of shelves.querySelectorAll('.row.running')) {
      const job = chats.get(row.dataset.chat).jobs.at(-1);
      row.querySelector('.gen-step').textContent = stepText(job);
      row.querySelector('.gen-clock').textContent = clockText(job);
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
    if (stories && running !== shelves.querySelectorAll('.row.running').length) changed = true;
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
      stories = null;
      shelves.replaceChildren(h('div', { class: 'shelf-state' },
        h('span', null, `案件列表没加载出来：${error.message}`),
        h('button', { class: 'chip', type: 'button', onclick: loadStories }, '重试')));
      shelves.removeAttribute('aria-busy');
      return;
    }
    shelves.removeAttribute('aria-busy');
    renderShelves();
  }

  // ---------- 新建剧场 ----------

  const form = $('new-form');
  const material = $('material');
  const fileInput = $('file-input');
  const goButton = $('btn-go');
  const goNote = $('go-note');
  let files = [];
  let sending = false;
  let slowTimers = [];

  const urlsIn = (text) => text.match(chats.URL_PATTERN) || [];
  const sizeText = (bytes) => (bytes < 1024 ? `${bytes} B` : `${Math.ceil(bytes / 1024)} KB`);

  function hostOf(url) {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  function renderAttachments() {
    $('attachments').replaceChildren(...files.map((file, i) => h('li', { class: 'attachment' },
      h('span', null, file.name),
      h('small', null, sizeText(file.size)),
      h('button', {
        type: 'button',
        'aria-label': `移除 ${file.name}`,
        onclick: () => {
          files.splice(i, 1);
          renderAttachments();
        },
      }, icon('close')))));
  }

  function renderNote() {
    const urls = urlsIn(material.value);
    const note = $('material-note');
    note.classList.toggle('warn', urls.length > chats.LIMITS.urls);
    if (urls.length > chats.LIMITS.urls) note.textContent = `每次最多读取 ${chats.LIMITS.urls} 个网址`;
    else if (urls.length) note.textContent = `会读取 ${urls.map(hostOf).join('、')} 的正文`;
    else note.textContent = '网址会自动读取正文';
  }

  function addFiles(list) {
    if (sending) return;
    chats.addFiles(list, files);
    renderAttachments();
  }

  function fillMaterial(text) {
    material.value = text;
    renderNote();
    material.focus();
    material.setSelectionRange(text.length, text.length);
  }

  function setSending(on, reading = false) {
    sending = on;
    form.classList.toggle('sending', on);
    goButton.disabled = on;
    material.readOnly = on;
    goButton.textContent = on ? '正在交给编剧……' : '交给编剧';
    slowTimers.forEach(clearTimeout);
    slowTimers = [];
    if (!on) {
      goNote.replaceChildren('编剧会问你要快速还是精修', h('br'), '生成完会出现在「我的剧场」');
      return;
    }
    goNote.textContent = '编剧在看你的素材';
    slowTimers = [
      setTimeout(() => { goNote.textContent = reading ? '编剧在读素材，想想怎么改编……' : '编剧在想怎么接话……'; }, 6000),
      setTimeout(() => { goNote.textContent = '这次有点慢，再等等。'; }, 25000),
    ];
  }

  // 新建一段编剧对话，素材和附件作为第一条消息发出，再到编剧页接着聊
  async function handOver(event) {
    event.preventDefault();
    if (sending) return;
    const text = material.value.trim();
    if (!text && !files.length) {
      toast('先写几句素材，或者上传一个 txt / md 文件。');
      material.focus();
      return;
    }
    const urls = urlsIn(text).length;
    if (urls > chats.LIMITS.urls) {
      toast(`每次最多读取 ${chats.LIMITS.urls} 个网址，请分几次发。`, 'error');
      return;
    }
    const data = new FormData();
    data.append('text', text);
    for (const file of files) data.append('files', file, file.name);
    setSending(true, files.length > 0 || urls > 0);
    let chat;
    let result;
    try {
      chat = await chats.writer.newChat();
      result = await chats.writer.send(chat.chat_id, data);
    } catch (error) {
      setSending(false);
      if (!(error instanceof ApiError)) throw error;
      toast(`没能交给编剧：${error.message}`, 'error', 6500);
      return;
    }
    chats.begin(chat, { role: 'me', text, files: files.map((file) => file.name) }, result);
    material.value = '';
    files = [];
    renderAttachments();
    renderNote();
    location.assign(`/studio/?chat=${encodeURIComponent(chat.chat_id)}`);
  }

  $('starters').replaceChildren(...chats.STARTERS.map((starter) => h('button', {
    class: 'chip', type: 'button', onclick: () => fillMaterial(starter.text),
  }, starter.label)));
  form.addEventListener('submit', handOver);
  material.addEventListener('input', renderNote);
  material.addEventListener('paste', (event) => {
    const pasted = [...(event.clipboardData ? event.clipboardData.files : [])];
    if (!pasted.length) return;
    event.preventDefault();
    addFiles(pasted);
  });
  $('btn-upload').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    addFiles([...fileInput.files]);
    fileInput.value = '';
  });
  // 文件拖到这个视图任何地方都算上传
  const dragsFiles = (event) => event.dataTransfer && [...event.dataTransfer.types].includes('Files');
  $('view-new').addEventListener('dragover', (event) => {
    if (dragsFiles(event)) event.preventDefault();
  });
  $('view-new').addEventListener('drop', (event) => {
    if (!dragsFiles(event)) return;
    event.preventDefault();
    addFiles([...event.dataTransfer.files]);
  });

  // ---------- 事件 ----------

  $('item-start').addEventListener('click', () => setMenu('start'));
  for (const link of document.querySelectorAll('#menu-start [data-view]')) {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      go(link.dataset.view);
    });
  }
  for (const button of document.querySelectorAll('[data-back]')) button.addEventListener('click', back);
  $('item-quit').addEventListener('click', () => window.pywebview.api.quit());
  addEventListener('pywebviewready', showQuit);
  addEventListener('popstate', render);
  addEventListener('resize', fit);

  document.addEventListener('click', (event) => {
    if (event.target.closest('.item:not([data-back]), .row, .chip, .go')) sound.sfx('confirm');
  });

  document.addEventListener('keydown', (event) => {
    if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey || !launch.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      if (viewOf() !== 'title' || menu === 'start') back();
      return;
    }
    // 新建剧场里方向键和回车留给输入框
    if (viewOf() === 'new') return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      move(event.key === 'ArrowDown' ? 1 : -1);
    } else if (event.key === 'Enter' && !event.target.closest('a, button')) {
      const current = items().find((item) => item.classList.contains('on'));
      if (!current) return;
      event.preventDefault();
      current.click();
    }
  });

  // 鼠标移到哪一项就选中哪一项。只认真的移动：键盘滚动列表时停着不动的鼠标不抢选中
  let pointerAt = '';
  document.addEventListener('pointermove', (event) => {
    const at = `${event.screenX},${event.screenY}`;
    if (at === pointerAt) return;
    pointerAt = at;
    const item = event.target.closest('.item, .row');
    if (item && viewOf() !== 'new' && items().includes(item)) select(item);
  });
  document.addEventListener('focusin', (event) => {
    const item = event.target.closest('.item, .row');
    if (item && viewOf() !== 'new' && items().includes(item)) select(item);
  });

  // 从游戏页按返回键回到首页时，浏览器可能直接恢复旧页面，要收起等待层、刷新续局和案件
  addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    launch.hidden = true;
    setSending(false);
    render();
    sound.playMusic();
    loadStories();
    if (!pollTimer && chats.list().some(chats.runningJob)) pollPending();
  });

  setInterval(refreshRunning, 1000);

  // ---------- 开始 ----------

  paintScene();
  fit();
  renderNote();
  shelves.replaceChildren(h('div', { class: 'shelf-state' }, '正在打开档案柜……'));
  render();
  showQuit();
  sound.playMusic();
  loadSettings();
  const storyId = new URLSearchParams(location.search).get('story');
  if (storyId) startGame(storyId, { replace: true });
  loadStories().then(() => {
    if (!pollTimer && chats.list().some(chats.runningJob)) pollPending();
  });
})();
