/* 出题人页面：凭出题时存在浏览器里的 owner_token 读取分享案件的完整剧本，以及朋友们的对局进度。 */
(() => {
  const { h, icon, hydrateIcons, toast, avatar, tidy, fmtTime, ApiError } = window.KS;

  // 生成剧场（frontend/studio）按案件把令牌存在这个键下
  const OWNER_PREFIX = 'kanshan:owner:';
  const REFRESH_MS = 20000;

  const main = document.getElementById('main');
  const storyId = new URLSearchParams(location.search).get('story');

  let story = null;
  let games = [];
  let refreshedAt = 0;
  let refreshError = '';
  let refreshing = false;
  let timer = null;
  let progressBox = null;
  // 剧本里按编号查人物、事实、线索、谎话、事件、结局
  let ref = null;

  // ---------- 接口 ----------

  function readToken() {
    try {
      return localStorage.getItem(OWNER_PREFIX + storyId);
    } catch {
      // 浏览器禁用本地存储时读不到令牌，按「没有令牌」给出说明
      return null;
    }
  }

  function errorMessage(status, data) {
    const detail = data && data.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (status === 401) return '需要体验账号和口令，请刷新页面后输入。';
    if (status >= 500) return '服务暂时不可用，请稍后重试。';
    return `请求失败（${status}），请重试。`;
  }

  // js/api.js 的 request 不带自定义请求头，这里单独发带 X-Owner-Token 的请求
  async function fetchOwner(token) {
    let response;
    try {
      response = await fetch(`/api/stories/${encodeURIComponent(storyId)}/owner`, {
        headers: { 'X-Owner-Token': token },
        cache: 'no-store',
      });
    } catch {
      throw new ApiError(0, '网络连接失败，请检查网络后重试。');
    }
    let data = null;
    if ((response.headers.get('content-type') || '').includes('application/json')) {
      try {
        data = await response.json();
      } catch {
        throw new ApiError(response.status, '服务返回的内容无法读取，请重试。');
      }
    }
    if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, data));
    if (!data || !data.story || typeof data.story !== 'object' || Array.isArray(data.story) || !Array.isArray(data.games)) {
      throw new ApiError(response.status, '服务返回的内容无法读取，请重试。');
    }
    return data;
  }

  // ---------- 剧本索引与条件文字 ----------

  function index(data) {
    const byId = (list) => new Map((list || []).map((item) => [item.id, item]));
    const lies = new Map();
    for (const person of data.characters || []) {
      for (const lie of person.lies || []) lies.set(lie.id, { lie, person });
    }
    return {
      facts: byId(data.facts),
      people: byId(data.characters),
      clues: byId(data.clues),
      events: byId(data.events),
      endings: byId(data.ending && data.ending.endings),
      lies,
    };
  }

  const refChip = (id) => h('code', { class: 'ref' }, id);
  const personName = (id) => (ref.people.get(id) || { name: id }).name;
  const factText = (id) => (ref.facts.has(id) ? tidy(ref.facts.get(id).text) : id);

  function clueName(id) {
    const clue = ref.clues.get(id);
    return clue ? `${id}「${tidy(clue.title)}」` : id;
  }

  function lieName(id) {
    const found = ref.lies.get(id);
    return found ? `${found.person.name}的谎话 ${id}` : `谎话 ${id}`;
  }

  // SPEC 6.1 的条件写法，以及结局的 correct / chose
  function condText(cond) {
    const parts = [];
    for (const [key, value] of Object.entries(cond || {})) {
      if (key === 'trust') parts.push(`信任度 ≥ ${value}`);
      else if (key === 'shown') parts.push(`看过 ${clueName(value)}`);
      else if (key === 'has') parts.push(`玩家拿到 ${clueName(value)}`);
      else if (key === 'exposed') parts.push(`${lieName(value)} 被拆穿`);
      else if (key === 'event') parts.push(`对质 ${value} 发生过`);
      else if (key === 'correct') parts.push(`答对 ${[].concat(value).join('、')}`);
      else if (key === 'chose') for (const [q, option] of Object.entries(value)) parts.push(`${q} 选「${option}」`);
      else parts.push(`${key}: ${JSON.stringify(value)}`);
    }
    return parts.join('，并且') || '无额外条件';
  }

  // ---------- 页面骨架 ----------

  function notice({ kind = 'info', title, text, actions = [] }) {
    stopTimer();
    main.removeAttribute('aria-busy');
    main.replaceChildren(h('section', { class: `notice ${kind}` },
      h('span', { class: 'notice-icon' }, icon(kind === 'error' ? 'alert' : 'shield')),
      h('h1', null, title),
      h('p', null, text),
      actions.length ? h('div', { class: 'notice-actions' }, actions) : null));
  }

  const playLink = (cls = 'btn btn-ghost') => h('a', { class: cls, href: `/?story=${encodeURIComponent(storyId)}` }, icon('arrow'), '去玩这个案子');
  const studioLink = () => h('a', { class: 'btn btn-primary', href: '/studio/?mode=share' }, icon('plus'), '出一道新题');

  function showNoToken() {
    notice({
      title: '这个页面只能在出题的浏览器里打开',
      text: '出题人页面凭生成案件时存在浏览器里的访问令牌打开。请用当初生成这个案子的那台设备、那个浏览器打开链接；换了浏览器、用了无痕窗口或清过网站数据，令牌就不在了。朋友要玩这个案子，请打开分享链接。',
      actions: [playLink(), studioLink()],
    });
  }

  function showError(error) {
    if (error.status === 403) {
      notice({
        kind: 'error',
        title: '访问令牌不对',
        text: `${error.message}浏览器里保存的令牌和这个案子对不上，可能是复制链接时改动了案件编号。`,
        actions: [playLink(), studioLink()],
      });
    } else if (error.status === 404) {
      notice({
        kind: 'error',
        title: '找不到这个案子',
        text: '服务器上没有这个编号的分享案件，可能链接不完整，或者案件已被清理。',
        actions: [studioLink()],
      });
    } else {
      notice({
        kind: 'error',
        title: '剧本没能读出来',
        text: error.message,
        actions: [h('button', { class: 'btn btn-primary', type: 'button', onclick: load }, icon('retry'), '重试')],
      });
    }
  }

  function section(id, title, count, ...body) {
    return h('details', { class: 'block', id, open: true },
      h('summary', null, h('h2', null, title), count === null ? null : h('span', { class: 'count' }, count)),
      h('div', { class: 'block-body' }, body));
  }

  function field(label, ...content) {
    return h('div', { class: 'field' }, h('span', { class: 'field-label' }, label), h('div', { class: 'field-value' }, content));
  }

  // ---------- 案件头部与分享链接 ----------

  async function copy(url, input) {
    try {
      await navigator.clipboard.writeText(url);
      toast('链接已复制，发给朋友就能开局。', 'success');
    } catch {
      input.focus();
      input.select();
      toast('浏览器不让直接复制，链接已经选中，请手动复制。');
    }
  }

  function headNode() {
    const url = `${location.origin}/?story=${encodeURIComponent(storyId)}`;
    const input = h('input', { readonly: true, value: url, 'aria-label': '分享链接', onfocus: (event) => event.target.select() });
    const characters = story.characters || [];
    return h('section', { class: 'case-head' },
      h('div', { class: 'case-meta' },
        h('span', { class: 'tag tag-blue' }, '分享案件'),
        h('span', { class: 'meta-item' }, icon('users'), `${characters.length} 位角色`),
        h('span', { class: 'meta-item' }, icon('clue'), `${(story.clues || []).length} 条线索`)),
      h('h1', null, tidy(story.title || '未命名案件')),
      story.checked === false
        ? h('p', { class: 'warn' }, icon('alert'), h('span', null, '这个剧本没有通过自动检查，朋友可能遇到拿不到的线索或推不出的题，发出前可以先自己试玩。'))
        : null,
      h('blockquote', { class: 'soup paper' }, tidy(story.intro || '')),
      h('div', { class: 'share-box' },
        h('span', { class: 'share-label' }, '分享链接'),
        h('div', { class: 'share-row' }, input,
          h('button', { class: 'btn btn-blue', type: 'button', onclick: () => copy(url, input) }, '复制')),
        h('p', null, '朋友打开链接直接开局，看不到剧本。他们开局后，这一页下方会出现每一局的进度。'),
        h('div', { class: 'share-actions' }, playLink('btn btn-ghost btn-sm'))));
  }

  // ---------- 朋友们的进度 ----------

  // owner 进度只提供线索和拆穿；其他条件无法确认时，不跳过该提示阶段。
  function reached(cond, got, exposed) {
    let known = true;
    for (const [key, value] of Object.entries(cond || {})) {
      if (key === 'has') {
        if (!got.has(value)) return false;
      } else if (key === 'exposed') {
        if (!exposed.has(value)) return false;
      } else known = false;
    }
    return known ? true : null;
  }

  function stuckHint(got, exposed) {
    const hints = (story.kanshan && story.kanshan.hints) || [];
    for (const hint of hints) {
      const done = reached(hint.done, got, exposed);
      if (done === false) return hint;
      if (done === null) return null;
    }
    return null;
  }

  function stat(value, label) {
    return h('span', { class: 'stat' }, h('b', null, value), label);
  }

  function gameNode(game, n) {
    const clues = story.clues || [];
    const got = new Set(game.clues);
    const exposed = new Set(game.exposed);
    const ending = game.ending ? ref.endings.get(game.ending) || { title: game.ending } : null;
    const closed = ending && !ending.retry;
    const status = ending
      ? h('span', { class: `tag ${ending.retry ? 'tag-red' : 'tag-gold'}` }, tidy(ending.title))
      : h('span', { class: 'tag tag-blue' }, h('i', { class: 'live' }), '进行中');
    const stuck = closed ? null : stuckHint(got, exposed);
    return h('article', { class: 'game' },
      h('header', { class: 'game-head' }, h('b', null, `第 ${n} 局`), status),
      h('div', { class: 'game-stats' },
        stat(game.turns, '回合'),
        stat(`${got.size}/${clues.length}`, '线索'),
        stat(`${exposed.size}/${ref.lies.size}`, '拆穿')),
      h('ul', { class: 'clue-chips', 'aria-label': '线索' }, clues.map((clue) => h('li', {
        class: got.has(clue.id) ? 'got' : null,
        title: got.has(clue.id) ? '已拿到' : '还没拿到',
      }, got.has(clue.id) ? icon('check') : null, tidy(clue.title)))),
      exposed.size
        ? h('p', { class: 'game-exposed' }, h('span', null, '拆穿：'), [...exposed].map((id) => lieName(id)).join('、'))
        : null,
      ending && ending.retry ? h('p', { class: 'game-note' }, '结局可以重新调查，朋友可能还在继续查。') : null,
      stuck ? h('p', { class: 'game-stuck' }, icon('bulb'), h('span', null, h('b', null, '下一步提示：'), tidy(stuck.vague))) : null);
  }

  function renderProgress() {
    const list = games.length
      ? h('div', { class: 'games' }, games.map((game, i) => gameNode(game, i + 1)))
      : h('p', { class: 'empty' }, '还没有人开局。把分享链接发给朋友，他们开局后这里会出现进度。');
    const refresh = h('button', { class: 'btn btn-ghost btn-sm', type: 'button', disabled: refreshing, onclick: () => refreshGames(true) },
      refreshing ? h('span', { class: 'spinner sm', 'aria-hidden': 'true' }) : icon('retry'), '刷新');
    progressBox.replaceChildren(
      h('div', { class: 'progress-head' },
        h('h2', null, '朋友们的进度'),
        h('span', { class: 'count' }, `${games.length} 局`),
        h('span', { class: 'updated' }, refreshedAt ? `${fmtTime(refreshedAt)} 更新，每 20 秒自动刷新` : ''),
        refresh),
      ...(refreshError ? [h('p', { class: 'refresh-error', role: 'status' }, `进度更新失败，当前显示上次结果：${refreshError}`)] : []),
      list);
  }

  async function refreshGames(manual) {
    if (refreshing) return;
    const token = readToken();
    if (!token) {
      showNoToken();
      return;
    }
    refreshing = true;
    if (manual) renderProgress();
    try {
      const data = await fetchOwner(token);
      games = data.games;
      refreshedAt = Date.now();
      refreshError = '';
      if (manual) toast('进度已更新。', 'success', 1800);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (error.status === 403 || error.status === 404) {
        refreshing = false;
        showError(error);
        return;
      }
      // 网络或服务暂时出错：保留上次的进度，下一轮再试
      refreshError = error.message;
      if (manual) toast(error.message, 'error');
    }
    refreshing = false;
    renderProgress();
  }

  function stopTimer() {
    clearInterval(timer);
    timer = null;
  }

  function startTimer() {
    stopTimer();
    timer = setInterval(() => {
      if (!document.hidden) refreshGames(false);
    }, REFRESH_MS);
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && timer && Date.now() - refreshedAt > REFRESH_MS) refreshGames(false);
  });

  // ---------- 完整剧本 ----------

  function truthBlock() {
    const end = story.ending || {};
    const lessons = end.lessons || [];
    return section('s-truth', '汤底', null,
      h('div', { class: 'truth paper' }, tidy(end.truth || '')),
      lessons.length ? field('知识点', h('ul', { class: 'bullets' }, lessons.map((text) => h('li', null, tidy(text))))) : null);
  }

  function factsBlock() {
    const facts = story.facts || [];
    return section('s-facts', '事实', facts.length,
      h('ul', { class: 'rows' }, facts.map((fact) => h('li', null, refChip(fact.id), h('span', null, tidy(fact.text))))));
  }

  function personNode(person) {
    const secrets = person.secrets || [];
    const lies = person.lies || [];
    return h('article', { class: 'card person' },
      h('header', { class: 'person-head' },
        avatar(person, 46),
        h('div', { class: 'person-name' },
          h('h3', null, person.name, refChip(person.id)),
          person.profile ? h('p', null, tidy(person.profile)) : null),
        h('span', { class: 'tag' }, `初始信任 ${person.trust_start || 0}`)),
      person.persona ? field('人设', tidy(person.persona)) : null,
      field('知道', h('ul', { class: 'bullets' }, (person.knows || []).map((id) => h('li', null, refChip(id), factText(id))))),
      secrets.length ? field('秘密', h('ul', { class: 'bullets' }, secrets.map((secret) => h('li', null,
        refChip(secret.fact), factText(secret.fact),
        h('small', { class: 'cond' }, `说出条件：${condText(secret.until)}`))))) : null,
      lies.length ? field('谎话', h('ul', { class: 'lies' }, lies.map((lie) => h('li', null,
        h('p', { class: 'claim' }, refChip(lie.id), h('q', null, tidy(lie.claim))),
        h('small', { class: 'cond' }, `拆穿条件：${condText(lie.until)}`),
        lie.admit ? h('small', { class: 'cond' }, `拆穿后承认：${factText(lie.admit)}`) : null)))) : null);
  }

  function peopleBlock() {
    const people = story.characters || [];
    return section('s-people', '人物', people.length, h('div', { class: 'cards' }, people.map(personNode)));
  }

  function cluesBlock() {
    const clues = story.clues || [];
    return section('s-clues', '线索', clues.length, h('div', { class: 'cards' }, clues.map((clue) => {
      const events = [...ref.events.values()].filter((event) => event.unlock.includes(clue.id));
      const from = events.length
        ? `对质 ${events.map((event) => event.id).join('、')} 后拿到`
        : `由${personName(clue.holder)}交出${Object.keys(clue.requires || {}).length ? `，条件：${condText(clue.requires)}` : '，问到就给'}`;
      return h('article', { class: 'card clue' },
        h('h3', null, refChip(clue.id), tidy(clue.title)),
        h('p', null, tidy(clue.content)),
        h('small', { class: 'cond' }, from));
    })));
  }

  function eventsBlock() {
    const events = story.events || [];
    if (!events.length) return null;
    return section('s-events', '对质', events.length, h('div', { class: 'cards' }, events.map((event) => {
      const when = event.when || {};
      const extra = Object.fromEntries(Object.entries(when).filter(([key]) => key !== 'to' && key !== 'shown'));
      const trigger = [
        when.shown ? `把 ${clueName(when.shown)} 出示给${personName(when.to)}` : null,
        Object.keys(extra).length ? condText(extra) : null,
      ].filter(Boolean).join('，并且');
      return h('article', { class: 'card' },
        h('h3', null, refChip(event.id), (event.confront || []).map(personName).join(' 与 '), ' 对质'),
        h('small', { class: 'cond' }, `触发：${trigger}`),
        (event.unlock || []).length ? h('small', { class: 'cond' }, `对质后玩家拿到：${event.unlock.map(clueName).join('、')}`) : null);
    })));
  }

  function hintsBlock() {
    const kanshan = story.kanshan || {};
    const hints = kanshan.hints || [];
    return section('s-hints', '刘看山', hints.length,
      kanshan.greeting ? field('开场白', tidy(kanshan.greeting)) : null,
      h('ol', { class: 'hints' }, hints.map((hint, i) => h('li', { class: 'card' },
        h('h3', null, `第 ${i + 1} 阶段`, h('small', { class: 'cond' }, `完成标志：${condText(hint.done)}`)),
        field('模糊提示', tidy(hint.vague)),
        field('直接提示', tidy(hint.direct))))));
  }

  function questionsBlock() {
    const questions = (story.ending && story.ending.questions) || [];
    return section('s-questions', '结局题', questions.length, h('ol', { class: 'cards' }, questions.map((q) => h('li', { class: 'card' },
      h('h3', null, refChip(q.id), tidy(q.text)),
      h('ul', { class: 'options' }, (q.options || []).map((option) => h('li', { class: option === q.answer ? 'answer' : null },
        option === q.answer ? icon('check') : h('i', { class: 'bullet' }), tidy(option))))))));
  }

  function endingsBlock() {
    const endings = (story.ending && story.ending.endings) || [];
    return section('s-endings', '结局', endings.length, h('div', { class: 'cards' }, endings.map((ending) => h('article', { class: 'card' },
      h('h3', null, refChip(ending.id), tidy(ending.title), ending.retry ? h('span', { class: 'tag tag-red' }, '可重新调查') : null),
      h('small', { class: 'cond' }, Object.keys(ending.when || {}).length ? `触发：${condText(ending.when)}` : '触发：前面的结局都不满足时'),
      h('p', null, tidy(ending.text || ''))))));
  }

  function tocNode() {
    const items = [['s-progress', '进度'], ['s-truth', '汤底'], ['s-people', '人物'], ['s-clues', '线索'],
      (story.events || []).length ? ['s-events', '对质'] : null, ['s-hints', '提示'], ['s-questions', '结局题'], ['s-endings', '结局'], ['s-facts', '事实']];
    return h('nav', { class: 'toc', 'aria-label': '页面目录' },
      items.filter(Boolean).map(([id, label]) => h('a', { href: `#${id}`, onclick: () => {
        const block = document.getElementById(id);
        if (block instanceof HTMLDetailsElement) block.open = true;
      } }, label)));
  }

  function render() {
    progressBox = h('section', { class: 'progress', id: 's-progress' });
    main.removeAttribute('aria-busy');
    main.replaceChildren(
      headNode(),
      tocNode(),
      progressBox,
      h('div', { class: 'script' },
        h('p', { class: 'script-label' }, icon('eye'), '完整剧本（含真相，只给出题人看）'),
        truthBlock(), peopleBlock(), cluesBlock(), eventsBlock(), hintsBlock(), questionsBlock(), endingsBlock(), factsBlock()));
    renderProgress();
    document.title = `${tidy(story.title || '出题人页面')} · 出题人页面`;
  }

  // ---------- 开始 ----------

  async function load() {
    stopTimer();
    if (!storyId) {
      notice({
        kind: 'error',
        title: '链接缺少案件编号',
        text: '出题人页面的地址形如 /share/?story=案件编号，请从生成剧场的案件卡片上点「出题人页面」进来。',
        actions: [studioLink()],
      });
      return;
    }
    const token = readToken();
    if (!token) {
      showNoToken();
      return;
    }
    main.setAttribute('aria-busy', 'true');
    main.replaceChildren(h('div', { class: 'loading' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), '正在读取剧本……'));
    try {
      const data = await fetchOwner(token);
      story = data.story;
      games = data.games;
      refreshedAt = Date.now();
      refreshError = '';
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      showError(error);
      return;
    }
    ref = index(story);
    render();
    startTimer();
  }

  hydrateIcons();
  window.addEventListener('pagehide', stopTimer);
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) load();
  });
  load();
})();
