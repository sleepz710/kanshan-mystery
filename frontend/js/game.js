/* 游戏页：问话、出示证据、拆穿与对质的演出、线索板、事件流、刘看山问答、提交推理。 */
(() => {
  const {
    h, icon, hydrateIcons, avatar, accent, trustMeter, toast, confirmDialog,
    typeText, sleep, reducedMotion, fmtTime, tidy, api, store, ApiError,
  } = window.KS;

  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const state = params.get('g') ? store.load(params.get('g')) : store.last();
  if (!state) {
    location.replace('/');
    return;
  }
  const gameUrl = () => `/game.html?g=${encodeURIComponent(state.gameId)}`;
  const endingUrl = () => `/ending.html?g=${encodeURIComponent(state.gameId)}`;
  if (params.get('g') !== state.gameId) history.replaceState(null, '', gameUrl());

  const el = {
    app: $('app'), game: $('game'), title: $('case-title'), castList: $('cast-list'),
    chatHead: $('chat-head'), statusBar: $('status-bar'), thread: $('thread'), suggest: $('suggest'),
    composer: $('composer'), say: $('say'), send: $('btn-send'), evidenceBtn: $('btn-evidence'),
    board: $('board'), clueGrid: $('clue-grid'), clueCount: $('clue-count'), timeline: $('timeline'), eventsDot: $('events-dot'),
    ksSay: $('ks-say'), ksAsk: $('ks-ask'), ksInput: $('ks-input'), ksSubmit: $('ks-submit'),
    ksPips: $('ks-pips'), ksRule: $('ks-rule'), ksHistory: $('ks-history'),
    tabbar: $('tabbar'), tabClues: $('tab-clues'), tabEvents: $('tab-events'), tabKanshan: $('tab-kanshan'),
    dlgIntro: $('dlg-intro'), introBody: $('intro-body'), introGo: $('intro-go'),
    dlgEvidence: $('dlg-evidence'), evidenceTitle: $('evidence-title'), evidenceList: $('evidence-list'), evidenceGo: $('evidence-go'),
    dlgClue: $('dlg-clue'), clueBody: $('clue-body'),
    dlgAccuse: $('dlg-accuse'), accuseForm: $('accuse-form'), accuseProgress: $('accuse-progress'), accuseGo: $('accuse-go'),
    trustHelp: $('trust-help'),
  };

  const SUGGESTIONS = ['说说你知道的情况', '你和这件事有什么关系？', '那天具体发生了什么？'];
  const QUALITY_WARNING = '检查未全部通过，试玩可能遇到线索或推理问题。';
  const mobile = window.matchMedia('(max-width: 1023px)');
  const rendered = new WeakMap();
  let busy = false;
  let pending = null;
  let evidenceChoice = null;
  let trustHelpAnchor = null;
  let trustHelpPinned = false;
  let trustHelpTimer = null;

  const save = () => store.save(state);
  const person = (id) => state.characters.find((c) => c.id === id);
  const color = (id) => accent(state.characters, id);
  const brokenCount = (id) => state.exposed.filter((e) => e.character === id).length;
  const roundLabel = (round) => (round ? `第 ${round} 回合` : '开局时');
  const keepBottom = () => { el.thread.scrollTop = el.thread.scrollHeight; };
  const currentView = () => el.game.dataset.view;

  function clip(text, max) {
    const chars = Array.from(text);
    return chars.length > max ? `${chars.slice(0, max).join('')}…` : text;
  }

  // 线索卡片按编号稍微歪一点，像钉在板上
  function tilt(id) {
    let n = 0;
    for (const ch of id) n = (n * 17 + ch.charCodeAt(0)) % 9;
    return `${(n - 4) * 0.5}deg`;
  }

  function replay(node, cls) {
    node.classList.remove(cls);
    void node.offsetWidth;
    node.classList.add(cls);
  }

  function scrollThread(smooth = true) {
    el.thread.scrollTo({ top: el.thread.scrollHeight, behavior: smooth && !reducedMotion() ? 'smooth' : 'auto' });
  }

  // 后端拆穿文案形如「周明的说法被拆穿了。已确认：……」
  function splitExposure(text) {
    const at = text.indexOf('已确认：');
    if (at < 0) return [text, ''];
    return [text.slice(0, at).replace(/[。\s]+$/, ''), text.slice(at + 4).trim()];
  }

  // ---------- 渲染 ----------

  function trustHelpButton() {
    return h('button', {
      class: 'trust-help', type: 'button', dataset: { trustHelp: '' },
      'aria-label': '查看信任度说明', 'aria-describedby': 'trust-help', 'aria-expanded': 'false',
    }, icon('question'));
  }

  function positionTrustHelp() {
    if (!trustHelpAnchor) return;
    const rect = trustHelpAnchor.getBoundingClientRect();
    if (!trustHelpAnchor.isConnected || !rect.width || !rect.height) {
      closeTrustHelp();
      return;
    }
    const viewport = window.visualViewport;
    const leftEdge = (viewport?.offsetLeft || 0) + 12;
    const topEdge = (viewport?.offsetTop || 0) + 12;
    const width = viewport?.width || window.innerWidth;
    const height = viewport?.height || window.innerHeight;
    el.trustHelp.style.width = `${Math.min(340, Math.max(0, width - 24))}px`;
    el.trustHelp.style.maxWidth = `${Math.max(0, width - 24)}px`;
    el.trustHelp.style.maxHeight = `${Math.max(0, height - 24)}px`;
    const box = el.trustHelp.getBoundingClientRect();
    const left = Math.max(leftEdge, Math.min(rect.right - box.width, leftEdge + width - 24 - box.width));
    let top = rect.bottom + 8;
    if (top + box.height > topEdge + height - 24) top = rect.top - box.height - 8;
    top = Math.max(topEdge, Math.min(top, topEdge + height - 24 - box.height));
    el.trustHelp.style.left = `${left}px`;
    el.trustHelp.style.top = `${top}px`;
  }

  function openTrustHelp(button) {
    clearTimeout(trustHelpTimer);
    if (trustHelpAnchor !== button) {
      trustHelpAnchor?.setAttribute('aria-expanded', 'false');
      trustHelpPinned = false;
    }
    trustHelpAnchor = button;
    button.setAttribute('aria-expanded', 'true');
    el.trustHelp.hidden = false;
    positionTrustHelp();
  }

  function closeTrustHelp() {
    clearTimeout(trustHelpTimer);
    trustHelpAnchor?.setAttribute('aria-expanded', 'false');
    el.trustHelp.hidden = true;
    trustHelpAnchor = null;
    trustHelpPinned = false;
  }

  function scheduleTrustHelpClose() {
    clearTimeout(trustHelpTimer);
    trustHelpTimer = setTimeout(() => {
      if (!trustHelpPinned && document.activeElement !== trustHelpAnchor) closeTrustHelp();
    }, 120);
  }

  function setStat(name, value, bump = false) {
    const node = document.querySelector(`.stat[data-stat="${name}"]`);
    const number = node.querySelector('b');
    if (number.textContent === String(value)) return;
    number.textContent = value;
    if (bump) replay(node, 'bump');
  }

  function renderTop() {
    el.title.textContent = state.title;
    document.title = `${state.title} · 看山谜案馆`;
    setStat('turns', state.turns);
    setStat('clues', state.clues.length);
    setStat('exposed', state.exposed.length);
  }

  function renderCast() {
    el.castList.replaceChildren(...state.characters.map((c) => {
      const broken = brokenCount(c.id);
      const active = c.id === state.current;
      return h('li', null, h('button', {
        class: `cast-item${active ? ' active' : ''}`, type: 'button', dataset: { id: c.id },
        style: { '--accent': color(c.id) }, 'aria-pressed': String(active),
        onclick: () => selectCharacter(c.id),
      },
      h('span', { class: 'cast-avatar' }, avatar(c, 46),
        broken ? h('span', { class: 'cast-broken', title: `谎话被拆穿 ${broken} 次` }, icon('bolt'), broken > 1 ? broken : null) : null,
        state.unread[c.id] ? h('i', { class: 'dot cast-unread', title: '有新动静' }) : null),
      h('span', { class: 'cast-info' }, h('b', null, c.name), h('small', null, c.profile)),
      trustMeter(state.trust[c.id])));
    }));
  }

  function renderChatHead() {
    closeTrustHelp();
    const c = person(state.current);
    const broken = brokenCount(c.id);
    el.chatHead.style.setProperty('--accent', color(c.id));
    el.chatHead.replaceChildren(
      avatar(c, 42),
      h('div', { class: 'chat-who' }, h('b', null, c.name), h('small', { title: c.profile }, c.profile)),
      h('div', { class: 'chat-trust' },
        broken ? h('span', { class: 'tag tag-red' }, `拆穿 ${broken} 次`) : null,
        h('span', { class: 'trust-label' }, '信任 ', trustMeter(state.trust[c.id]), trustHelpButton())));
  }

  function qualityNote() {
    return state.checked === false
      ? h('p', { class: 'quality-note', role: 'note' }, icon('alert'), h('span', null, QUALITY_WARNING))
      : null;
  }

  function renderStatus() {
    const last = state.verdicts[state.verdicts.length - 1];
    el.statusBar.hidden = !state.finished && !last && state.checked !== false;
    el.statusBar.classList.toggle('done', state.finished);
    el.statusBar.classList.toggle('unchecked', state.checked === false);
    if (state.finished) {
      el.statusBar.replaceChildren(
        h('span', { class: 'grow' }, state.reveal ? '本局已结案，汤底已经揭晓。' : '本局已结案。'),
        h('a', { class: 'btn btn-gold btn-sm', href: endingUrl() }, '查看结局'),
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: restart }, icon('retry'), '重新开一局'));
    } else if (last) {
      el.statusBar.replaceChildren(
        h('span', { class: 'grow' }, `上次推理：${last.ending.title}（答对 ${last.score}/${last.total}）。线索都还在，查到新东西再提交一次。`),
        h('button', { class: 'btn btn-blue btn-sm', type: 'button', onclick: openAccuse }, '再次提交'));
    } else el.statusBar.replaceChildren();
    const warning = qualityNote();
    if (warning) el.statusBar.append(warning);
  }

  function messageNode(msg, owner) {
    switch (msg.k) {
      case 'me':
        return h('div', { class: 'msg me' }, h('div', { class: 'bubble' }, msg.text));
      case 'show':
        return h('div', { class: 'msg me' }, h('button', { class: 'bubble evidence', type: 'button', onclick: () => openClue(msg.clueId) },
          h('small', null, icon('evidence'), '出示证据'), h('b', null, `《${msg.title}》`)));
      case 'them': {
        const c = person(owner);
        return h('div', { class: `msg them${msg.struck ? ' struck' : ''}`, style: { '--accent': color(owner) } },
          avatar(c, 36),
          h('div', { class: 'bubble' }, h('span', { class: 'who' }, c.name), h('p', null, msg.text),
            msg.struck ? h('span', { class: 'lie-mark' }, '已拆穿') : null));
      }
      case 'exposed':
        return h('div', { class: 'card-exposed' },
          h('div', { class: 'mini-stamp', 'aria-hidden': 'true' }, '拆穿'),
          h('div', null, h('b', null, msg.head), msg.fact ? h('p', null, h('span', null, '已确认：'), msg.fact) : null));
      case 'confront': {
        const left = msg.lines[0].speaker;
        return h('div', { class: 'card-confront' },
          h('header', null, icon('swords'), h('b', null, '对质'), h('span', null, msg.text)),
          h('div', { class: 'duel' }, ...msg.lines.map((line) => {
            const c = person(line.speaker);
            return h('div', { class: `duel-line ${line.speaker === left ? 'left' : 'right'}`, style: { '--accent': color(line.speaker) } },
              avatar(c, 40),
              h('div', { class: 'duel-bubble' }, h('span', { class: 'who' }, c.name), h('p', null, line.text)));
          })));
      }
      case 'clues':
        return h('div', { class: 'card-clues' },
          h('span', { class: 'label' }, icon('clue'), `拿到 ${msg.items.length} 条线索`),
          h('div', { class: 'clue-chips' }, ...msg.items.map((item) => h('button', {
            class: 'clue-chip', type: 'button', onclick: () => openClue(item.id),
          }, icon('file'), item.title))));
      case 'hint':
        return h('div', { class: 'msg kanshan' }, avatar('kanshan', 36),
          h('div', { class: 'bubble' }, h('span', { class: 'who' }, '刘看山 · 提示'), h('p', null, msg.text)));
      default:
        throw new Error(`未知的消息类型：${msg.k}`);
    }
  }

  function track(node, msg) {
    rendered.set(msg, node);
    return node;
  }

  function typingNode(cid, showing) {
    const c = person(cid);
    return h('div', { class: 'msg them typing-msg', style: { '--accent': color(cid) } },
      avatar(c, 36),
      h('div', { class: 'bubble' },
        h('span', { class: 'who' }, showing ? `${c.name}正在看证据` : `${c.name}正在回答`),
        h('span', { class: 'typing', role: 'img', 'aria-label': '对方正在回答' }, h('i'), h('i'), h('i')),
        h('span', { class: 'slow' })));
  }

  function emptyProfile(cid) {
    const c = person(cid);
    return h('div', { class: 'thread-empty', style: { '--accent': color(cid) } },
      avatar(c, 88), h('h3', null, c.name), h('p', null, c.profile),
      h('p', { class: 'muted' }, `还没和${c.name}说过话。先问问情况，拿到证据后再当面出示。`));
  }

  function renderThread() {
    const cid = state.current;
    const thread = state.threads[cid];
    const waiting = pending && pending.cid === cid;
    el.thread.replaceChildren();
    if (!thread.length && !waiting) el.thread.append(emptyProfile(cid));
    for (const msg of thread) el.thread.append(track(messageNode(msg, cid), msg));
    if (waiting) el.thread.append(messageNode(pending.msg, cid), typingNode(cid, pending.msg.k === 'show'));
    renderSuggest();
    scrollThread(false);
  }

  function renderSuggest() {
    const empty = !state.threads[state.current].length && !pending && !state.finished;
    el.suggest.replaceChildren(...(empty ? SUGGESTIONS.map((text) => h('button', {
      type: 'button', disabled: busy, onclick: () => talk(text),
    }, text)) : []));
  }

  function shownLabel(clueId) {
    const ids = state.shown[clueId] || [];
    return ids.length ? `已给 ${ids.map((id) => person(id).name).join('、')} 看过` : '';
  }

  function renderClues(freshIds = []) {
    el.clueCount.textContent = state.clues.length;
    if (!state.clues.length) {
      el.clueGrid.replaceChildren(h('div', { class: 'board-empty' }, icon('clue'),
        '还没有线索。', h('br'), '和角色聊聊，他们会交出手里的材料。'));
    } else {
      el.clueGrid.replaceChildren(...[...state.clues].reverse().map((clue) => h('button', {
        class: `clue-card paper${freshIds.includes(clue.id) ? ' enter' : ''}`, type: 'button',
        style: { '--tilt': tilt(clue.id) }, onclick: () => openClue(clue.id),
      },
      clue.fresh ? h('span', { class: 'new' }, '新') : null,
      h('h4', null, clue.title),
      h('p', null, clue.content),
      h('footer', null, shownLabel(clue.id) || roundLabel(clue.round)))));
    }
    renderBadges();
  }

  function logView(entry) {
    switch (entry.type) {
      case 'start': return { cls: 'start', icon: 'file', title: '接手案件', detail: state.title };
      case 'clue': return { cls: 'clue', icon: 'clue', title: `拿到线索《${entry.title}》`, open: entry.id };
      case 'exposed': return { cls: 'exposed', icon: 'bolt', title: entry.head, detail: entry.fact ? `已确认：${entry.fact}` : '' };
      case 'confront': return { cls: 'confront', icon: 'swords', title: '对质', detail: entry.text, lines: entry.lines };
      case 'hint': return { cls: 'hint', icon: 'bulb', title: '刘看山的提示', detail: entry.text };
      case 'ask': return { cls: 'ask', icon: 'question', title: `问刘看山：${entry.q}`, detail: `答：${entry.a}` };
      case 'accuse': return { cls: 'accuse', icon: 'gavel', title: `提交推理：${entry.title}`, detail: `答对 ${entry.score}/${entry.total}` };
      default: throw new Error(`未知的事件类型：${entry.type}`);
    }
  }

  function renderTimeline(freshFrom = Infinity) {
    el.timeline.replaceChildren(...state.log.map((entry, index) => {
      const view = logView(entry);
      return h('li', { class: `tl-item ${view.cls}${index >= freshFrom ? ' enter' : ''}` },
        h('span', { class: 'tl-dot' }, icon(view.icon)),
        h('div', { class: 'tl-body' },
          h('b', null, view.open ? h('button', { class: 'tl-link', type: 'button', onclick: () => openClue(view.open) }, view.title) : view.title),
          view.detail ? h('p', null, view.detail) : null,
          view.lines ? h('div', { class: 'tl-lines' }, ...view.lines.map((line) => h('span', null,
            h('b', null, `${person(line.speaker).name}：`), line.text))) : null,
          h('div', { class: 'tl-meta' }, `${roundLabel(entry.round)} · ${fmtTime(entry.at)}`)));
    }).reverse());
  }

  function answerStamp(answer) {
    const cls = { 是: 'yes', 不是: 'no', 不重要: 'na' }[answer];
    return h('span', { class: `answer ${cls}` }, answer);
  }

  function renderKanshan(flash = false) {
    const hint = state.hints[state.hints.length - 1];
    el.ksSay.replaceChildren(h('span', { class: 'label' }, hint ? `提示 · ${roundLabel(hint.round)}` : '开场白'), hint ? hint.text : state.greeting);
    if (flash) replay(el.ksSay, 'flash');
    el.ksPips.replaceChildren(...Array.from({ length: state.asksTotal }, (_, i) => h('i', { class: i < state.asksLeft ? 'on' : null })));
    el.ksPips.setAttribute('aria-label', `还剩 ${state.asksLeft} 次`);
    el.ksRule.textContent = state.asksLeft
      ? `只答「是」「不是」「不重要」，还剩 ${state.asksLeft} 次。`
      : `${state.asksTotal} 次问答已经用完，接下来靠你自己了。`;
    // 最新的提示已经显示在上面的气泡里，记录里只列更早的
    const entries = state.log.filter((e) => e.type === 'ask' || e.type === 'hint');
    const latestHint = entries.filter((e) => e.type === 'hint').pop();
    el.ksHistory.replaceChildren(...entries.filter((e) => e !== latestHint).reverse().map((e) => (e.type === 'ask'
      ? h('li', { class: 'ks-entry' }, h('span', null, h('span', { class: 'meta' }, `${roundLabel(e.round)} · 你问`), e.q), answerStamp(e.a))
      : h('li', { class: 'ks-entry hint' }, h('span', null, h('span', { class: 'meta' }, `${roundLabel(e.round)} · 提示`), e.text)))));
    syncControls();
  }

  function markSeen() {
    const eventsVisible = mobile.matches ? currentView() === 'events' : el.board.dataset.tab === 'events';
    if (eventsVisible) state.seenLog = state.log.length;
    if (!mobile.matches || currentView() === 'kanshan') state.seenHints = state.hints.length;
  }

  function renderBadges() {
    const fresh = state.clues.filter((c) => c.fresh).length;
    el.tabClues.hidden = !fresh;
    el.tabClues.textContent = fresh;
    const newLog = state.log.length > state.seenLog;
    el.tabEvents.hidden = !newLog;
    el.eventsDot.hidden = !newLog;
    el.tabKanshan.hidden = state.hints.length <= state.seenHints;
  }

  function syncControls() {
    const locked = busy || state.finished;
    el.send.disabled = locked;
    el.evidenceBtn.disabled = locked;
    el.say.disabled = state.finished;
    el.say.placeholder = state.finished ? '本局已结案' : `问${person(state.current).name}……`;
    el.ksInput.disabled = state.finished || state.asksLeft <= 0;
    el.ksSubmit.disabled = locked || state.asksLeft <= 0;
    for (const button of document.querySelectorAll('[data-action="accuse"]')) button.disabled = busy;
    for (const button of el.suggest.querySelectorAll('button')) button.disabled = locked;
    for (const button of el.clueBody.querySelectorAll('.show-to-btn')) button.disabled = locked;
    el.evidenceGo.disabled = locked || !evidenceChoice;
  }

  function renderAll() {
    renderTop();
    renderCast();
    renderChatHead();
    renderStatus();
    renderThread();
    renderClues();
    renderTimeline();
    renderKanshan();
    markSeen();
    renderBadges();
    syncControls();
  }

  // ---------- 切换 ----------

  function selectCharacter(id) {
    if (state.current === id) return;
    state.current = id;
    delete state.unread[id];
    save();
    renderCast();
    renderChatHead();
    renderThread();
    syncControls();
  }

  function setBoardTab(tab) {
    el.board.dataset.tab = tab;
    for (const button of el.board.querySelectorAll('.board-tabs button')) button.setAttribute('aria-selected', String(button.dataset.tab === tab));
    markSeen();
    renderBadges();
  }

  function setView(view) {
    el.game.dataset.view = view;
    for (const button of el.tabbar.querySelectorAll('button')) button.setAttribute('aria-current', String(button.dataset.view === view));
    if (view === 'clues' || view === 'events') setBoardTab(view);
    markSeen();
    renderBadges();
    if (view === 'chat') scrollThread(false);
  }

  // ---------- 回合 ----------

  function setSlow(text) {
    const slow = el.thread.querySelector('.typing-msg .slow');
    if (slow) slow.textContent = text;
  }

  async function talk(raw) {
    const text = raw.trim();
    if (!text || busy || state.finished) return;
    const cid = state.current;
    el.say.value = '';
    autosize();
    const ok = await runTurn(cid, { k: 'me', text }, () => api.talk(state.gameId, cid, text));
    if (!ok && !el.say.value) {
      el.say.value = text;
      autosize();
    }
  }

  async function show(cid, clueId) {
    if (busy || state.finished) return;
    const clue = state.clues.find((c) => c.id === clueId);
    selectCharacter(cid);
    await runTurn(cid, { k: 'show', clueId, title: clue.title }, () => api.show(state.gameId, cid, clueId));
  }

  async function runTurn(cid, playerMsg, call) {
    busy = true;
    pending = { cid, msg: playerMsg };
    syncControls();
    if (mobile.matches) setView('chat');
    if (state.current === cid) {
      el.thread.querySelector('.thread-empty')?.remove();
      el.suggest.replaceChildren();
      el.thread.append(messageNode(playerMsg, cid), typingNode(cid, playerMsg.k === 'show'));
      scrollThread();
    }
    const name = person(cid).name;
    const slowTimers = [
      setTimeout(() => setSlow(`${name}还在想怎么回答……`), 9000),
      setTimeout(() => setSlow('这次有点慢，再等等。'), 25000),
    ];
    let result;
    try {
      result = await call();
    } catch (error) {
      slowTimers.forEach(clearTimeout);
      pending = null;
      busy = false;
      if (state.current === cid) renderThread();
      syncControls();
      await handleError(error);
      return false;
    }
    slowTimers.forEach(clearTimeout);
    pending = null;
    const turn = applyTurn(cid, playerMsg, result);
    el.thread.querySelector('.typing-msg')?.remove();
    await presentTurn(cid, turn);
    busy = false;
    syncControls();
    renderSuggest();
    return true;
  }

  // 拆穿时划掉的那句话：被当面出示证据的角色在这一回合之前说的最后一句
  function lastStatement(owner, limit) {
    const thread = state.threads[owner];
    for (let i = limit - 1; i >= 0; i -= 1) {
      if (thread[i].k === 'them' && !thread[i].struck) return thread[i];
    }
    return null;
  }

  // 先把回合结果写进本地状态并保存，再按顺序演出；演出途中刷新页面也不会丢数据
  function applyTurn(cid, playerMsg, result) {
    state.turns += 1;
    const round = state.turns;
    const at = Date.now();
    const logFrom = state.log.length;
    const thread = state.threads[cid];
    const before = thread.length;
    thread.push(playerMsg);
    const steps = [];

    // 出示证据当场拆穿的谎话排在角色回话之前，对质及其后的拆穿排在回话之后
    let split = 0;
    if (playerMsg.k === 'show') {
      while (split < result.events.length && result.events[split].type === 'exposed') split += 1;
    }
    const addEvent = (event) => {
      if (event.type === 'exposed') {
        const owner = event.character;
        const lieMsg = owner === cid ? lastStatement(cid, before) : null;
        if (lieMsg) lieMsg.struck = true;
        const [head, fact] = splitExposure(tidy(event.text));
        const msg = { k: 'exposed', character: owner, head, fact };
        thread.push(msg);
        if (owner !== cid) {
          state.threads[owner].push({ ...msg });
          state.unread[owner] = true;
        }
        state.exposed.push({ character: owner, lie: event.lie, round });
        state.log.push({ type: 'exposed', round, at, character: owner, head, fact });
        steps.push({ kind: 'exposed', msg, owner, lieMsg });
      } else {
        const lines = event.lines.map((line) => ({ speaker: line.speaker, text: tidy(line.text) }));
        const msg = { k: 'confront', text: tidy(event.text), lines };
        thread.push(msg);
        for (const id of new Set(lines.map((line) => line.speaker))) {
          if (id === cid) continue;
          state.threads[id].push({ ...msg });
          state.unread[id] = true;
        }
        state.log.push({ type: 'confront', round, at, text: msg.text, lines });
        steps.push({ kind: 'confront', msg });
      }
    };
    result.events.slice(0, split).forEach(addEvent);
    const reply = { k: 'them', text: tidy(result.reply) };
    thread.push(reply);
    steps.push({ kind: 'reply', msg: reply });
    result.events.slice(split).forEach(addEvent);

    if (result.new_clues.length) {
      for (const clue of result.new_clues) {
        state.clues.push({ id: clue.id, title: tidy(clue.title), content: tidy(clue.content), round, from: cid, via: playerMsg.k, fresh: true });
        state.log.push({ type: 'clue', round, at, id: clue.id, title: tidy(clue.title) });
      }
      const msg = { k: 'clues', items: result.new_clues.map(({ id, title }) => ({ id, title: tidy(title) })) };
      thread.push(msg);
      steps.push({ kind: 'clues', msg, ids: result.new_clues.map((c) => c.id) });
    }
    if (playerMsg.k === 'show') {
      const shown = (state.shown[playerMsg.clueId] ||= []);
      if (!shown.includes(cid)) shown.push(cid);
    }
    const trustBefore = { ...state.trust };
    Object.assign(state.trust, result.trust);
    if (result.hint) {
      const msg = { k: 'hint', text: tidy(result.hint) };
      thread.push(msg);
      state.hints.push({ text: msg.text, round });
      state.log.push({ type: 'hint', round, at, text: msg.text });
      steps.push({ kind: 'hint', msg });
    }
    save();
    return { steps, trustBefore, logFrom };
  }

  function appendLive(node, msg, cls) {
    track(node, msg);
    if (cls) node.classList.add(cls);
    el.thread.append(node);
    scrollThread();
    return node;
  }

  async function presentTurn(cid, { steps, trustBefore, logFrom }) {
    const here = () => state.current === cid;
    // 逐字显示期间让读屏软件等整段说完再读
    el.thread.setAttribute('aria-busy', 'true');
    for (const step of steps) {
      if (step.kind === 'exposed') {
        await playExposure(step);
        if (step.lieMsg) markStruck(step.lieMsg);
        if (here()) appendLive(messageNode(step.msg, cid), step.msg, 'enter');
        renderCast();
        renderChatHead();
        setStat('exposed', state.exposed.length, true);
        el.castList.querySelector(`.cast-item[data-id="${step.owner}"] .cast-broken`)?.classList.add('pop');
      } else if (step.kind === 'reply') {
        if (!here()) continue;
        const node = appendLive(messageNode(step.msg, cid), step.msg);
        const text = node.querySelector('p');
        text.textContent = '';
        await typeText(text, step.msg.text, { onFrame: keepBottom });
      } else if (step.kind === 'confront') {
        if (!here()) {
          toast(step.msg.text);
          renderCast();
          continue;
        }
        const node = appendLive(messageNode(step.msg, cid), step.msg);
        const lines = [...node.querySelectorAll('.duel-line')];
        const texts = lines.map((line) => line.querySelector('p'));
        const full = texts.map((p) => p.textContent);
        lines.forEach((line, i) => {
          line.classList.add('pending');
          texts[i].textContent = '';
        });
        renderCast();
        for (const [i, line] of lines.entries()) {
          await sleep(reducedMotion() ? 0 : 500);
          line.classList.remove('pending');
          await typeText(texts[i], full[i], { onFrame: keepBottom });
        }
      } else if (step.kind === 'clues') {
        if (here()) appendLive(messageNode(step.msg, cid), step.msg, 'enter');
        renderClues(step.ids);
        setStat('clues', state.clues.length, true);
        if (mobile.matches) replay(el.tabClues, 'bump');
        else replay(el.board, 'glow');
        replay(el.evidenceBtn, 'has-new');
        await sleep(reducedMotion() ? 0 : 450);
      } else if (step.kind === 'hint') {
        await sleep(reducedMotion() ? 0 : 400);
        if (here()) appendLive(messageNode(step.msg, cid), step.msg, 'enter');
        renderKanshan(true);
      }
    }
    el.thread.removeAttribute('aria-busy');
    setStat('turns', state.turns, true);
    renderCast();
    renderChatHead();
    animateTrust(trustBefore);
    renderStatus();
    markSeen();
    renderTimeline(logFrom);
    renderBadges();
    save();
  }

  function animateTrust(before) {
    for (const c of state.characters) {
      const delta = state.trust[c.id] - before[c.id];
      if (!delta) continue;
      const item = el.castList.querySelector(`.cast-item[data-id="${c.id}"]`);
      item.querySelector('.trust').classList.add('bump');
      item.querySelector('.cast-avatar').append(h('span', { class: `trust-float${delta < 0 ? ' down' : ''}` }, `信任 ${delta > 0 ? '+' : ''}${delta}`));
      if (c.id === state.current) el.chatHead.querySelector('.trust').classList.add('bump');
    }
  }

  function markStruck(msg) {
    const node = rendered.get(msg);
    if (!node || !node.isConnected) return;
    node.classList.add('struck');
    node.querySelector('.bubble').append(h('span', { class: 'lie-mark' }, '已拆穿'));
  }

  // ---------- 拆穿特效 ----------

  function stampNode() {
    const wrap = h('div', { class: 'stamp fx-stamp', 'aria-hidden': 'true' });
    wrap.innerHTML = `<svg viewBox="0 0 240 132">
      <defs>
        <filter id="ks-ink" x="-6%" y="-6%" width="112%" height="112%">
          <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7" result="noise"/>
          <feColorMatrix in="noise" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.6 2" result="holes"/>
          <feComposite in="SourceGraphic" in2="holes" operator="in" result="worn"/>
          <feTurbulence type="fractalNoise" baseFrequency=".05" numOctaves="1" seed="3" result="warp"/>
          <feDisplacementMap in="worn" in2="warp" scale="4" xChannelSelector="R" yChannelSelector="G"/>
        </filter>
      </defs>
      <g filter="url(#ks-ink)">
        <rect x="8" y="8" width="224" height="116" rx="14" fill="none" stroke="currentColor" stroke-width="8"/>
        <rect x="21" y="21" width="198" height="90" rx="7" fill="none" stroke="currentColor" stroke-width="3"/>
        <text x="127" y="92" text-anchor="middle" font-size="68" letter-spacing="14" fill="currentColor">拆穿</text>
      </g>
    </svg>`;
    return wrap;
  }

  function inkBurst() {
    const box = h('div', { class: 'ink-burst', 'aria-hidden': 'true' });
    for (let i = 0; i < 14; i += 1) {
      const angle = (i / 14) * Math.PI * 2 + Math.random() * 0.4;
      const distance = 60 + Math.random() * 90;
      box.append(h('i', {
        style: {
          '--dx': `${Math.cos(angle) * distance}px`,
          '--dy': `${Math.sin(angle) * distance * 0.7}px`,
          '--s': `${4 + Math.random() * 10}px`,
          '--d': `${Math.round(Math.random() * 90)}ms`,
        },
      }));
    }
    return box;
  }

  // 点击、回车或空格关闭；开头一小段时间内不响应，避免连点跳过盖章
  function waitDismiss(node, timeout, minDelay) {
    return new Promise((resolve) => {
      const start = performance.now();
      const finish = () => {
        clearTimeout(timer);
        node.removeEventListener('click', onClick);
        document.removeEventListener('keydown', onKey);
        resolve();
      };
      const onClick = () => { if (performance.now() - start >= minDelay) finish(); };
      const onKey = (event) => {
        if (!['Enter', ' ', 'Escape'].includes(event.key)) return;
        event.preventDefault();
        if (performance.now() - start >= minDelay) finish();
      };
      const timer = setTimeout(finish, timeout);
      node.addEventListener('click', onClick);
      document.addEventListener('keydown', onKey);
    });
  }

  async function playExposure(step) {
    const c = person(step.owner);
    const quote = step.lieMsg ? clip(step.lieMsg.text, 64) : '';
    const fx = h('div', { class: 'fx-exposed', role: 'alertdialog', 'aria-modal': 'true', 'aria-label': step.msg.head, tabindex: '-1' },
      h('div', { class: 'fx-vignette' }),
      h('div', { class: 'fx-flash' }),
      h('div', { class: 'fx-stage' },
        h('p', { class: 'fx-title' }, '谎话被拆穿'),
        h('div', { class: 'fx-card paper' },
          h('div', { class: 'fx-who' }, avatar(c, 52), h('div', null, h('b', null, c.name), quote ? '刚才说：' : '一直坚持的说法')),
          quote ? h('blockquote', { class: 'fx-quote' }, h('span', null, `「${quote}」`)) : null,
          stampNode(),
          inkBurst()),
        h('div', { class: 'fx-fact' }, h('h3', null, step.msg.head), step.msg.fact ? h('p', null, h('b', null, '已确认：'), step.msg.fact) : null),
        h('p', { class: 'fx-tip' }, '点击任意处继续')));
    document.body.append(fx);
    fx.focus();
    const shake = reducedMotion() ? null : setTimeout(() => replay(el.app, 'shake'), 720);
    await waitDismiss(fx, 5200, 800);
    clearTimeout(shake);
    fx.classList.add('leaving');
    await sleep(260);
    fx.remove();
    el.app.classList.remove('shake');
  }

  // ---------- 刘看山 ----------

  async function ask(raw) {
    const question = raw.trim();
    if (!question || busy || state.finished || state.asksLeft <= 0) return;
    busy = true;
    syncControls();
    el.ksInput.value = '';
    const waiting = h('li', { class: 'ks-entry' },
      h('span', null, h('span', { class: 'meta' }, '刘看山在想'), question),
      h('span', { class: 'answer wait' }, h('span', { class: 'typing' }, h('i'), h('i'), h('i'))));
    el.ksHistory.prepend(waiting);
    let result;
    try {
      result = await api.ask(state.gameId, question);
    } catch (error) {
      waiting.remove();
      busy = false;
      if (!el.ksInput.value) el.ksInput.value = question;
      if (error instanceof ApiError && error.status === 409 && !error.message.includes('结束')) {
        state.asksLeft = 0;
        save();
        renderKanshan();
      }
      syncControls();
      await handleError(error);
      return;
    }
    state.asksLeft = result.asks_left;
    state.asks.push({ q: question, a: result.answer });
    state.log.push({ type: 'ask', round: state.turns, at: Date.now(), q: question, a: result.answer });
    save();
    busy = false;
    renderKanshan();
    el.ksHistory.querySelector('.answer')?.classList.add('pop');
    markSeen();
    renderTimeline(state.log.length - 1);
    renderBadges();
  }

  // ---------- 弹窗 ----------

  function openIntro() {
    // 检查都通过时 qualityNote() 是 null，replaceChildren 会把它写成文字「null」，先滤掉
    el.introBody.replaceChildren(...[
      h('h2', { class: 'intro-title' }, state.title),
      qualityNote(),
      h('blockquote', { class: 'soup paper' }, state.intro),
      h('p', { class: 'intro-section' }, '相关人员'),
      h('div', { class: 'intro-cast' }, ...state.characters.map((c) => h('div', { class: 'intro-person' },
        avatar(c, 46), h('div', null, h('b', null, c.name), h('small', null, c.profile))))),
      h('div', { class: 'greeting' }, avatar('kanshan', 40), h('div', null, h('b', null, '刘看山'), h('p', null, state.greeting))),
    ].filter(Boolean));
    el.introGo.textContent = state.introSeen ? '继续调查' : '开始调查';
    el.dlgIntro.showModal();
  }

  function openEvidence() {
    if (busy || state.finished) return;
    if (!state.clues.length) {
      toast('还没有线索。先和角色聊聊，他们会交出手里的材料。');
      return;
    }
    const cid = state.current;
    evidenceChoice = null;
    el.evidenceTitle.textContent = `向${person(cid).name}出示证据`;
    el.evidenceList.replaceChildren(...[...state.clues].reverse().map((clue) => h('button', {
      class: 'evi', type: 'button', 'aria-pressed': 'false', dataset: { id: clue.id },
      onclick: () => pickEvidence(clue.id), ondblclick: confirmEvidence,
    },
    h('b', null, clue.title,
      (state.shown[clue.id] || []).includes(cid) ? h('span', { class: 'tag' }, '已出示过') : null,
      clue.fresh ? h('span', { class: 'tag tag-red' }, '新') : null),
    h('span', null, clip(clue.content, 60)))));
    el.evidenceGo.textContent = '选择一条证据';
    syncControls();
    el.dlgEvidence.showModal();
  }

  function pickEvidence(id) {
    evidenceChoice = id;
    for (const button of el.evidenceList.querySelectorAll('.evi')) button.setAttribute('aria-pressed', String(button.dataset.id === id));
    el.evidenceGo.textContent = `出示《${state.clues.find((c) => c.id === id).title}》`;
    syncControls();
  }

  function confirmEvidence() {
    if (!evidenceChoice || busy) return;
    const clueId = evidenceChoice;
    evidenceChoice = null;
    el.dlgEvidence.close();
    show(state.current, clueId);
  }

  function openClue(id) {
    const clue = state.clues.find((c) => c.id === id);
    if (clue.fresh) {
      clue.fresh = false;
      save();
      renderClues();
    }
    const via = clue.via === 'show' ? `向${person(clue.from).name}出示证据时拿到` : `和${person(clue.from).name}交谈时拿到`;
    const shown = state.shown[id] || [];
    el.clueBody.replaceChildren(
      h('article', { class: 'clue-sheet paper' },
        h('h3', null, clue.title), h('p', null, clue.content), h('footer', null, `${roundLabel(clue.round)} · ${via}`)),
      h('div', { class: 'show-to' },
        h('p', null, state.finished ? '本局已结案。' : '拿给谁看？出示一次算一个回合。'),
        h('div', { class: 'show-to-list' }, ...state.characters.map((c) => h('button', {
          class: 'show-to-btn', type: 'button', disabled: busy || state.finished,
          onclick: () => {
            el.dlgClue.close();
            show(c.id, id);
          },
        }, avatar(c, 34), h('span', null, c.name, h('small', null, shown.includes(c.id) ? '已出示过' : '出示')))))));
    el.dlgClue.showModal();
  }

  function openAccuse() {
    if (busy) return;
    if (state.finished) {
      location.href = endingUrl();
      return;
    }
    el.accuseForm.replaceChildren(...state.questions.map((q, index) => h('fieldset', { class: 'q' },
      h('legend', null, h('span', { class: 'q-no' }, index + 1), h('span', null, q.text)),
      h('div', { class: 'opts' }, ...q.options.map((option) => h('label', { class: 'opt' },
        h('input', { type: 'radio', name: q.id, value: option, checked: state.answers[q.id] === option }),
        h('span', null, option)))))));
    updateAccuse();
    el.dlgAccuse.showModal();
  }

  function updateAccuse() {
    const answered = state.questions.filter((q) => state.answers[q.id]).length;
    el.accuseProgress.textContent = `已答 ${answered}/${state.questions.length}`;
    el.accuseGo.disabled = busy || answered < state.questions.length;
  }

  async function submitAccuse() {
    if (busy) return;
    const answers = Object.fromEntries(state.questions.map((q) => [q.id, state.answers[q.id]]));
    busy = true;
    syncControls();
    updateAccuse();
    el.accuseGo.textContent = '正在结案……';
    let verdict;
    try {
      verdict = await api.accuse(state.gameId, answers);
    } catch (error) {
      busy = false;
      el.accuseGo.textContent = '结案';
      syncControls();
      updateAccuse();
      el.dlgAccuse.close();
      await handleError(error);
      return;
    }
    state.verdicts.push({
      ...verdict, ending: { ...verdict.ending, text: tidy(verdict.ending.text) }, answers, at: Date.now(),
      turns: state.turns, asksUsed: state.asksTotal - state.asksLeft,
      clues: state.clues.length, exposed: state.exposed.length,
    });
    state.log.push({ type: 'accuse', round: state.turns, at: Date.now(), title: verdict.ending.title, score: verdict.score, total: verdict.total });
    if (!verdict.ending.retry) state.finished = true;
    save();
    location.href = endingUrl();
  }

  // ---------- 出错与重开 ----------

  async function restart() {
    if (busy) return;
    busy = true;
    syncControls();
    let game;
    try {
      game = await api.newGame(state.storyId);
    } catch (error) {
      busy = false;
      syncControls();
      if (!(error instanceof ApiError)) throw error;
      toast(`没能重新开局：${error.message}`, 'error', 6500);
      return;
    }
    const fresh = store.create(game, state.storyId);
    store.save(fresh);
    location.replace(`/game.html?g=${encodeURIComponent(fresh.gameId)}`);
  }

  async function handleError(error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 404) {
      const again = await confirmDialog({
        title: '这局调查已失效',
        text: `${error.message}服务器重启后，进行中的对局会被清空。可以用同一个案件重新开局。`,
        ok: '重新开局',
        cancel: '回到首页',
      });
      if (again) await restart();
      else location.href = '/';
      return;
    }
    if (error.status === 409 && error.message.includes('结束')) {
      state.finished = true;
      save();
      renderAll();
    }
    toast(error.message, 'error', 6500);
  }

  // ---------- 事件绑定 ----------

  document.addEventListener('pointerover', (event) => {
    const button = event.target.closest('[data-trust-help]');
    if (button && event.pointerType !== 'touch') openTrustHelp(button);
  });
  document.addEventListener('pointerout', (event) => {
    const button = event.target.closest('[data-trust-help]');
    if (button && !button.contains(event.relatedTarget) && !el.trustHelp.contains(event.relatedTarget)) scheduleTrustHelpClose();
  });
  el.trustHelp.addEventListener('pointerenter', () => clearTimeout(trustHelpTimer));
  el.trustHelp.addEventListener('pointerleave', scheduleTrustHelpClose);
  document.addEventListener('focusin', (event) => {
    const button = event.target.closest('[data-trust-help]');
    if (button) openTrustHelp(button);
  });
  document.addEventListener('focusout', (event) => {
    if (event.target.closest('[data-trust-help]') && !trustHelpPinned && !el.trustHelp.contains(event.relatedTarget)) closeTrustHelp();
  });
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-trust-help]');
    if (!button) return;
    if (trustHelpAnchor === button && trustHelpPinned) closeTrustHelp();
    else {
      openTrustHelp(button);
      trustHelpPinned = true;
    }
  });
  document.addEventListener('pointerdown', (event) => {
    if (!event.target.closest('[data-trust-help]') && !el.trustHelp.contains(event.target)) closeTrustHelp();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !el.trustHelp.hidden) {
      event.preventDefault();
      closeTrustHelp();
    }
  });
  window.addEventListener('resize', positionTrustHelp);
  document.addEventListener('scroll', positionTrustHelp, true);
  window.visualViewport?.addEventListener('resize', positionTrustHelp);
  window.visualViewport?.addEventListener('scroll', positionTrustHelp);

  function autosize() {
    el.say.style.height = 'auto';
    el.say.style.height = `${Math.min(el.say.scrollHeight + 2, 140)}px`;
  }

  el.composer.addEventListener('submit', (event) => {
    event.preventDefault();
    talk(el.say.value);
  });
  el.say.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    talk(el.say.value);
  });
  el.say.addEventListener('input', autosize);
  el.evidenceBtn.addEventListener('click', openEvidence);
  el.evidenceGo.addEventListener('click', confirmEvidence);
  el.ksAsk.addEventListener('submit', (event) => {
    event.preventDefault();
    ask(el.ksInput.value);
  });
  el.accuseForm.addEventListener('submit', (event) => event.preventDefault());
  el.accuseForm.addEventListener('change', (event) => {
    state.answers[event.target.name] = event.target.value;
    save();
    updateAccuse();
  });
  el.accuseGo.addEventListener('click', submitAccuse);
  el.introGo.addEventListener('click', () => el.dlgIntro.close());
  el.dlgIntro.addEventListener('close', () => {
    if (state.introSeen) return;
    state.introSeen = true;
    save();
    el.say.focus({ preventScroll: true });
  });
  $('btn-intro').addEventListener('click', openIntro);
  for (const button of document.querySelectorAll('[data-action="accuse"]')) button.addEventListener('click', openAccuse);
  el.tabbar.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-view]');
    if (button) setView(button.dataset.view);
  });
  el.board.querySelector('.board-tabs').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-tab]');
    if (!button) return;
    if (mobile.matches) setView(button.dataset.tab);
    else setBoardTab(button.dataset.tab);
  });
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-close]');
    if (button) button.closest('dialog').close();
  });
  mobile.addEventListener('change', () => {
    closeTrustHelp();
    markSeen();
    renderBadges();
  });
  // 从结局页按返回键回来时，浏览器可能直接恢复旧页面，这里重新读取本地记录
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) location.reload();
  });

  hydrateIcons();
  renderAll();
  if (!state.introSeen && !state.finished) openIntro();
})();
