/* 生成剧场：和编剧聊天、上传 txt/md、贴网址；轮询不剧透的生成进度，完成后显示案件卡片并开局。
   侧边栏列出这个浏览器里的历次对话，新对话不覆盖旧的，各段对话的生成都在后台接着查。 */
(() => {
  const {
    h, icon, hydrateIcons, toast, confirmDialog, typeText, tidy, api, store, chats, ApiError,
  } = window.KS;

  const $ = (id) => document.getElementById(id);
  const el = {
    studio: $('studio'), thread: $('thread'), messages: $('messages'), newChat: $('btn-new'),
    suggest: $('suggest'), composer: $('composer'), attachments: $('attachments'), fileInput: $('file-input'),
    say: $('say'), send: $('btn-send'), note: $('composer-note'),
    sidebar: $('sidebar'), chatList: $('chat-list'), history: $('btn-history'), scrim: $('scrim'), sideNew: $('btn-side-new'),
  };

  const { LIMITS, URL_PATTERN, STARTERS, writer } = chats;
  const POLL_MS = 1500;
  const PLACEHOLDER = '海龟汤、小说、网址或一句想法';
  // 编剧只问一次改编方式，这几句是他给的选项
  const STRATEGY_REPLIES = ['没看过答案', '看过答案', '全新', '直接开始'];

  // 当前打开的对话，结构见 chats.js；job.after 是任务开始时的消息条数，卡片画在这条消息后面
  let session = null;
  let attachments = [];
  let busy = false;
  let pollTimer = null;
  let polling = false;

  function save() {
    chats.put(session);
    renderSidebar();
  }

  // ---------- 小工具 ----------

  const userCount = () => (session ? session.messages.filter((m) => m.role === 'me').length : 0);
  const runningJob = () => (session ? chats.runningJob(session) : undefined);
  const keepBottom = () => { el.thread.scrollTop = el.thread.scrollHeight; };
  const sizeText = (bytes) => (bytes < 1024 ? `${bytes} B` : `${Math.ceil(bytes / 1024)} KB`);
  const seal = () => h('span', { class: 'writer-seal', 'aria-hidden': 'true' }, '编');
  const { clock } = chats;

  function hostOf(url) {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  // ---------- 对话 ----------

  function fileChip(name, size) {
    return h('span', { class: 'file-chip' }, icon('file'), h('span', null, name), size === undefined ? null : h('small', null, sizeText(size)));
  }

  function messageNode(msg, { enter = false, text = msg.text } = {}) {
    if (msg.role === 'me') {
      return h('div', { class: `msg me${enter ? ' enter' : ''}` },
        h('div', { class: 'bubble' },
          msg.text ? h('p', null, msg.text) : null,
          msg.files.length ? h('div', { class: 'bubble-files' }, msg.files.map((name) => fileChip(name))) : null));
    }
    return h('div', { class: `msg writer${enter ? ' enter' : ''}` }, seal(),
      h('div', { class: 'bubble' }, h('span', { class: 'who' }, '编剧'), h('p', null, text)));
  }

  function typingNode() {
    return h('div', { class: 'msg writer typing-msg enter' }, seal(),
      h('div', { class: 'bubble' },
        h('span', { class: 'who' }, '编剧'),
        h('span', { class: 'typing', role: 'img', 'aria-label': '编剧正在回复' }, h('i'), h('i'), h('i')),
        h('span', { class: 'slow' })));
  }

  // ---------- 生成任务卡片 ----------

  const elapsedText = (job) => `${job.quality === 'fine' ? '精修中' : '快速生成中'} · ${clock(Date.now() - job.startedAt)}`;

  function stepsNode(job) {
    return h('ol', { class: 'job-steps' }, job.steps.map((step, i) => {
      const now = i === job.steps.length - 1;
      return h('li', { class: now ? 'now' : null }, now ? h('span', { class: 'spinner', 'aria-hidden': 'true' }) : icon('check'), step);
    }));
  }

  function tipNode(job) {
    return job.offline
      ? h('p', { class: 'job-tip warn' }, '和服务器的连接断了，正在重试……')
      : h('p', { class: 'job-tip' }, '离开这个页面不影响生成，回来还能看到进度。');
  }

  function runningNode(job, cls) {
    return h('article', { class: cls, dataset: { job: job.id } },
      h('div', { class: 'job-head' }, seal(),
        h('div', null, h('b', null, '正在生成剧场'), h('small', { class: 'job-clock' }, elapsedText(job)))),
      stepsNode(job),
      tipNode(job));
  }

  function doneNode(job, cls) {
    const story = job.story || {};
    const start = h('button', { class: 'btn btn-lg btn-primary', type: 'button' }, '开始调查');
    start.addEventListener('click', () => startGame(job.storyId, start));
    return h('article', { class: cls, dataset: { job: job.id } },
      h('div', { class: 'case-stamp', 'aria-hidden': 'true' }, '新案'),
      job.error ? null : h('p', { class: 'job-ready' }, icon('check'), job.progress),
      h('div', { class: 'case-meta' },
        h('span', { class: 'tag tag-blue' }, '生成案件'),
        story.characters ? h('span', { class: 'meta-item' }, icon('users'), `${story.characters} 位角色`) : null,
        h('span', { class: 'meta-item' }, icon('clock'), `用时 ${clock(job.endedAt - job.startedAt)}`)),
      h('h3', null, story.title || '新案件'),
      story.intro ? h('blockquote', { class: 'soup paper' }, tidy(story.intro)) : null,
      job.error ? h('p', { class: 'job-warn' }, icon('alert'), h('span', null, job.error)) : null,
      h('div', { class: 'job-actions' }, start));
  }

  // 只有最近一次生成的失败卡片带按钮，之后又生成过就不再提供重试
  function failedNode(job, cls) {
    let action = null;
    if (job === session.jobs.at(-1)) {
      action = job.lost
        ? h('button', { class: 'btn btn-primary', type: 'button', onclick: () => newChat() }, icon('plus'), '新建对话')
        : h('button', { class: 'btn btn-primary', type: 'button', onclick: () => send(job.quality === 'fine' ? '精修' : '快速') }, icon('retry'), '重新生成');
    }
    return h('article', { class: cls, dataset: { job: job.id } },
      h('div', { class: 'job-head' }, seal(),
        h('div', null, h('b', null, job.progress || '本次生成未完成'), h('small', null, `用时 ${clock(job.endedAt - job.startedAt)}`))),
      h('p', { class: 'job-tip' }, job.error || '生成没有完成，请重试。'),
      action ? h('div', { class: 'job-actions' }, action) : null);
  }

  function jobNode(job, enter = false) {
    const cls = `job ${job.status}${enter ? ' enter' : ''}`;
    if (job.status === 'running') return runningNode(job, cls);
    if (job.status === 'done') return doneNode(job, cls);
    return failedNode(job, cls);
  }

  // 生成中只换步骤和提示，卡片不重画，呼吸动画不会每次轮询都从头开始
  function refreshRunning(job) {
    const node = el.messages.querySelector(`[data-job="${job.id}"]`);
    if (!node) return;
    if (node.querySelectorAll('.job-steps li').length !== job.steps.length) node.querySelector('.job-steps').replaceWith(stepsNode(job));
    node.querySelector('.job-tip').replaceWith(tipNode(job));
  }

  function finishJob(job) {
    el.messages.querySelector(`[data-job="${job.id}"]`)?.replaceWith(jobNode(job, true));
    keepBottom();
    renderSuggest();
    syncControls();
  }

  // 查所有对话里还在生成的任务：当前对话更新卡片，其他对话只更新侧边栏。查完还有在生成的就继续排下一轮
  async function pollAll() {
    polling = true;
    let offline = false;
    const others = chats.list().filter((c) => c.chatId !== (session && session.chatId) && chats.runningJob(c));
    for (const chat of [session, ...others]) {
      const job = chat && chats.runningJob(chat);
      if (!job) continue;
      if (!(await chats.checkJob(job))) offline = true;
      // 等待期间可能切换了对话；当前对话用内存里的 session 存，避免拿旧对象覆盖
      if (chat === session) {
        save();
        if (job.status === 'running') refreshRunning(job);
        else finishJob(job);
      } else if (!session || chat.chatId !== session.chatId) {
        chats.put(chat);
        renderSidebar();
      }
    }
    polling = false;
    pollTimer = null;
    const more = runningJob() || chats.list().some((c) => chats.runningJob(c));
    if (more) pollTimer = setTimeout(pollAll, offline ? POLL_MS * 3 : POLL_MS);
  }

  function startPolling() {
    if (polling || pollTimer) return;
    pollAll();
  }

  // ---------- 渲染 ----------

  function renderMessages() {
    const nodes = [];
    session.messages.forEach((msg, i) => {
      nodes.push(messageNode(msg));
      for (const job of session.jobs) if (job.after === i + 1) nodes.push(jobNode(job));
    });
    el.messages.replaceChildren(...nodes);
  }

  function chip(label, onclick, sends) {
    return h('button', { class: sends ? 'send' : null, type: 'button', onclick }, sends ? null : icon('plus'), label);
  }

  function renderSuggest() {
    let chips = [];
    if (session && !busy && !runningJob()) {
      const lastJob = session.jobs.at(-1);
      const endsWithReply = session.messages.at(-1).role === 'writer' && !(lastJob && lastJob.after === session.messages.length);
      if (!userCount()) chips = STARTERS.map((s) => chip(s.label, () => fill(s.text), false));
      else if (endsWithReply) {
        const qualityQuestion = /快速(?:（约 3 分钟）)?还是精修/.test(session.messages.at(-1).text);
        const replies = qualityQuestion ? ['快速', '精修'] : STRATEGY_REPLIES;
        chips = replies.map((t) => chip(t, () => send(t), true));
      }
    }
    el.suggest.replaceChildren(...chips);
  }

  function renderAttachments() {
    el.attachments.replaceChildren(...attachments.map((file, i) => h('li', { class: 'file-chip' },
      icon('file'), h('span', null, file.name), h('small', null, sizeText(file.size)),
      h('button', {
        type: 'button',
        'aria-label': `移除 ${file.name}`,
        onclick: () => {
          attachments.splice(i, 1);
          renderAttachments();
          syncControls();
        },
      }, icon('close')))));
  }

  function renderNote() {
    const urls = el.say.value.match(URL_PATTERN) || [];
    el.note.classList.toggle('warn', urls.length > LIMITS.urls);
    if (urls.length > LIMITS.urls) el.note.textContent = `每次最多读取 ${LIMITS.urls} 个网址，请分几次发。`;
    else if (urls.length) el.note.replaceChildren('发送后编剧会读取网页正文：', h('b', null, urls.map(hostOf).join('、')));
    else el.note.textContent = '可上传 txt、md 文件（每个 256 KB 内），网址会自动读取正文。';
  }

  function syncControls() {
    const running = Boolean(runningJob());
    el.say.disabled = !session || running;
    el.say.placeholder = running ? '编剧在布置现场，稍等' : PLACEHOLDER;
    el.fileInput.disabled = !session || running;
    el.composer.classList.toggle('locked', !session || running);
    el.send.disabled = !session || busy || running || (!el.say.value.trim() && !attachments.length);
    el.newChat.disabled = busy;
  }

  function renderAll() {
    renderMessages();
    renderAttachments();
    renderNote();
    renderSuggest();
    syncControls();
    keepBottom();
  }

  function autosize() {
    el.say.style.height = 'auto';
    el.say.style.height = `${Math.min(el.say.scrollHeight, 200)}px`;
  }

  function fill(text) {
    el.say.value = text;
    autosize();
    renderNote();
    syncControls();
    el.say.focus();
    el.say.setSelectionRange(text.length, text.length);
  }

  // ---------- 附件 ----------

  function addFiles(list) {
    if (!session || runningJob()) return;
    chats.addFiles(list, attachments);
    renderAttachments();
    syncControls();
  }

  // ---------- 发消息、建对话 ----------

  async function send(preset) {
    const fromComposer = preset === undefined;
    const text = (fromComposer ? el.say.value : preset).trim();
    const files = fromComposer ? [...attachments] : [];
    if (!session || busy || runningJob() || (!text && !files.length)) return;
    if ((text.match(URL_PATTERN) || []).length > LIMITS.urls) {
      toast(`每次最多读取 ${LIMITS.urls} 个网址，请分几次发。`, 'error');
      return;
    }
    const form = new FormData();
    form.append('text', text);
    for (const file of files) form.append('files', file, file.name);
    const msg = { role: 'me', text, files: files.map((f) => f.name) };
    if (fromComposer) {
      el.say.value = '';
      attachments = [];
      renderAttachments();
      autosize();
      renderNote();
    }

    busy = true;
    const mine = messageNode(msg, { enter: true });
    const typing = typingNode();
    el.messages.append(mine, typing);
    renderSuggest();
    syncControls();
    keepBottom();
    const slow = typing.querySelector('.slow');
    const reading = files.length > 0 || (text.match(URL_PATTERN) || []).length > 0;
    const timers = [
      setTimeout(() => { slow.textContent = reading ? '编剧在读素材，想想怎么改编……' : '编剧在想怎么接话……'; }, 6000),
      setTimeout(() => { slow.textContent = '这次有点慢，再等等。'; }, 25000),
    ];

    let result;
    try {
      result = await writer.send(session.chatId, form);
    } catch (error) {
      timers.forEach(clearTimeout);
      mine.remove();
      typing.remove();
      busy = false;
      // 发送失败把内容放回输入框；等待期间玩家已经输入了新内容就不覆盖
      if (fromComposer && !el.say.value && !attachments.length) {
        el.say.value = text;
        attachments = files;
        renderAttachments();
        autosize();
        renderNote();
      }
      renderSuggest();
      syncControls();
      await handleError(error);
      return;
    }
    timers.forEach(clearTimeout);
    typing.remove();

    session.messages.push(msg, { role: 'writer', text: result.reply });
    let job = null;
    if (result.job && !session.jobs.some((j) => j.id === result.job.id)) {
      job = chats.newJob(result.job, session.messages.length);
      session.jobs.push(job);
      for (const actions of el.messages.querySelectorAll('.job.failed .job-actions')) actions.remove();
    }
    save();
    const reply = messageNode(session.messages.at(-1), { enter: true, text: '' });
    el.messages.append(reply);
    await typeText(reply.querySelector('p'), result.reply, { onFrame: keepBottom });
    if (job) {
      el.messages.append(jobNode(job, true));
      keepBottom();
      startPolling();
    }
    busy = false;
    renderSuggest();
    syncControls();
    keepBottom();
    if (!job) el.say.focus({ preventScroll: true });
  }

  async function newChat() {
    busy = true;
    syncControls();
    let chat;
    try {
      chat = await writer.newChat();
    } catch (error) {
      busy = false;
      if (!(error instanceof ApiError)) throw error;
      if (session) toast(`没能新建对话：${error.message}`, 'error', 6000);
      else {
        el.messages.replaceChildren(h('div', { class: 'thread-error' },
          h('span', null, `编剧暂时联系不上：${error.message}`),
          h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => newChat() }, icon('retry'), '重试')));
      }
      syncControls();
      return false;
    }
    const now = Date.now();
    session = { chatId: chat.chat_id, createdAt: now, updatedAt: now, messages: [{ role: 'writer', text: chat.reply }], jobs: [] };
    chats.setCurrent(session.chatId);
    busy = false;
    save();
    renderAll();
    return true;
  }

  // 旧对话留在侧边栏；当前对话还没聊过就不再新建
  async function resetChat() {
    if (busy) return;
    closeSidebar();
    if (session && !userCount()) {
      el.say.focus();
      return;
    }
    if (await newChat()) el.say.focus();
  }

  function openChat(chatId) {
    closeSidebar();
    if (busy || (session && session.chatId === chatId)) return;
    const chat = chats.get(chatId);
    if (!chat) return;
    session = chat;
    chats.setCurrent(chatId);
    attachments = [];
    el.say.value = '';
    autosize();
    renderAll();
    renderSidebar();
    startPolling();
  }

  // ---------- 侧边栏 ----------

  function chatStatus(chat) {
    const job = chat.jobs.at(-1);
    if (!job) return null;
    if (job.status === 'running') return h('span', { class: 'chat-state running' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), '生成中');
    if (job.status === 'done') return h('span', { class: 'chat-state done' }, icon('check'), '已生成');
    return h('span', { class: 'chat-state failed' }, icon('alert'), '未完成');
  }

  function renderSidebar() {
    const items = chats.list().filter((c) => chats.hasTalk(c) || (session && c.chatId === session.chatId));
    el.chatList.replaceChildren(...items.map((chat) => {
      const active = session && chat.chatId === session.chatId;
      return h('li', null, h('button', {
        class: `chat-item${active ? ' active' : ''}`,
        type: 'button',
        'aria-current': active ? 'true' : null,
        onclick: () => openChat(chat.chatId),
      },
      h('span', { class: 'chat-title' }, chats.title(chat)),
      h('span', { class: 'chat-meta' },
        chatStatus(chat),
        h('span', { class: 'chat-time' }, chats.ago(chat.updatedAt)))));
    }));
  }

  function openSidebar() {
    el.sidebar.classList.add('open');
    el.scrim.hidden = false;
    el.history.setAttribute('aria-expanded', 'true');
  }

  function closeSidebar() {
    el.sidebar.classList.remove('open');
    el.scrim.hidden = true;
    el.history.setAttribute('aria-expanded', 'false');
  }

  async function handleError(error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 404) {
      const again = await confirmDialog({
        title: '这段对话已失效',
        text: `${error.message}服务器重启后，进行中的对话会被清空。新建对话后可以接着发。`,
        ok: '新建对话',
        cancel: '回到首页',
      });
      if (again) await newChat();
      else location.href = '/';
      return;
    }
    toast(error.message, 'error', 6500);
  }

  async function startGame(storyId, button) {
    const label = button.textContent;
    button.disabled = true;
    button.textContent = '正在布置现场……';
    let game;
    try {
      game = await api.newGame(storyId);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      button.disabled = false;
      button.textContent = label;
      toast(`没能开局：${error.message}`, 'error', 6000);
      return;
    }
    const state = store.create(game, storyId);
    store.save(state);
    location.assign(`/game.html?g=${encodeURIComponent(state.gameId)}`);
  }

  // ---------- 事件 ----------

  el.composer.addEventListener('submit', (event) => {
    event.preventDefault();
    send();
  });
  el.say.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    send();
  });
  el.say.addEventListener('input', () => {
    autosize();
    renderNote();
    syncControls();
  });
  el.say.addEventListener('paste', (event) => {
    const files = [...(event.clipboardData ? event.clipboardData.files : [])];
    if (!files.length) return;
    event.preventDefault();
    addFiles(files);
  });
  el.fileInput.addEventListener('change', () => {
    addFiles([...el.fileInput.files]);
    el.fileInput.value = '';
  });

  // 文件拖到页面任何地方都算上传
  const dragsFiles = (event) => event.dataTransfer && [...event.dataTransfer.types].includes('Files');
  el.studio.addEventListener('dragover', (event) => {
    if (!dragsFiles(event)) return;
    event.preventDefault();
    el.composer.classList.add('dragging');
  });
  el.studio.addEventListener('dragleave', (event) => {
    if (!el.studio.contains(event.relatedTarget)) el.composer.classList.remove('dragging');
  });
  el.studio.addEventListener('drop', (event) => {
    if (!dragsFiles(event)) return;
    event.preventDefault();
    el.composer.classList.remove('dragging');
    addFiles([...event.dataTransfer.files]);
  });

  el.newChat.addEventListener('click', () => resetChat());
  el.sideNew.addEventListener('click', () => resetChat());
  el.history.addEventListener('click', () => (el.sidebar.classList.contains('open') ? closeSidebar() : openSidebar()));
  el.scrim.addEventListener('click', closeSidebar);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && el.sidebar.classList.contains('open')) closeSidebar();
  });
  // 首页或另一个标签页更新了记录时，刷新侧边栏
  window.addEventListener('storage', (event) => {
    if (event.key === 'kanshan:studio:chats') renderSidebar();
  });

  // 建议、附件出现、手机键盘弹起让对话区变矮，或进度卡片变长时，原本停在底部的继续贴着底部
  let atBottom = true;
  el.thread.addEventListener('scroll', () => {
    atBottom = el.thread.scrollHeight - el.thread.scrollTop - el.thread.clientHeight < 24;
  }, { passive: true });
  const pin = new ResizeObserver(() => {
    if (atBottom) keepBottom();
  });
  pin.observe(el.thread);
  pin.observe(el.messages);

  setInterval(() => {
    const job = runningJob();
    const node = job && el.messages.querySelector(`[data-job="${job.id}"] .job-clock`);
    if (node) node.textContent = elapsedText(job);
  }, 1000);

  // 从游戏页按返回键回来时，浏览器可能直接恢复旧页面，重新读取本地记录和进度
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) location.reload();
  });

  // ---------- 开始 ----------

  hydrateIcons();
  renderNote();
  syncControls();
  // 首页的生成中行和「新建剧场」都带 ?chat=<id> 打开对应对话；出题页留下的旧链接还带 ?mode=，一并去掉
  const saved = chats.get(new URLSearchParams(location.search).get('chat')) || chats.get(chats.current());
  if (location.search) history.replaceState(null, '', location.pathname);
  if (!saved) newChat();
  else {
    session = saved;
    chats.setCurrent(saved.chatId);
    renderAll();
  }
  renderSidebar();
  startPolling();
})();
