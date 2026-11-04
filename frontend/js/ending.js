/* 结局页：结案报告、评级、重新调查、揭晓汤底与反诈知识点。 */
(() => {
  const { h, icon, hydrateIcons, toast, confirmDialog, tidy, api, store, ApiError } = window.KS;
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const state = params.get('g') ? store.load(params.get('g')) : store.last();
  if (!state) {
    location.replace('/');
    return;
  }
  const gameUrl = `/game.html?g=${encodeURIComponent(state.gameId)}`;
  const verdict = state.verdicts[state.verdicts.length - 1];
  if (!verdict) {
    location.replace(gameUrl);
    return;
  }
  let busy = false;

  function render() {
    document.title = `${verdict.ending.title} · 看山谜案馆`;
    $('back-game').href = gameUrl;
    $('back-game').hidden = state.finished;
    $('report').classList.toggle('solved', !verdict.ending.retry);
    $('case-title').textContent = `「${state.title}」`;
    $('ending-title').textContent = verdict.ending.title;
    const rating = $('rating');
    rating.className = `rating ${verdict.rating}`;
    rating.setAttribute('aria-label', `评级 ${verdict.rating}`);
    rating.replaceChildren(h('b', null, verdict.rating), h('small', null, '评级'));
    $('score').replaceChildren(
      h('span', { class: 'score-big' }, '答对 ', h('b', null, verdict.score), ` / ${verdict.total}`),
      h('span', { class: 'score-meta' },
        h('span', null, icon('chat'), `调查 ${verdict.turns} 回合`),
        h('span', null, icon('question'), `问刘看山 ${verdict.asksUsed} 次`),
        h('span', null, icon('clue'), `线索 ${verdict.clues} 条`),
        h('span', null, icon('bolt'), `拆穿 ${verdict.exposed} 句谎话`)));
    $('ending-text').textContent = verdict.ending.text;
    $('answers').replaceChildren(...state.questions.map((q, index) => {
      const ok = verdict.results[q.id];
      return h('li', { class: ok ? 'ok' : 'bad' },
        h('span', { class: 'mark', role: 'img', 'aria-label': ok ? '答对' : '答错' }, icon(ok ? 'check' : 'close')),
        h('div', null,
          h('p', { class: 'q' }, `${index + 1}. ${q.text}`),
          h('p', { class: 'a' }, `你的答案：${verdict.answers[q.id]}`)));
    }));
    renderActions();
    if (state.reveal) renderTruth(false);
  }

  function renderActions() {
    const box = $('actions');
    if (state.reveal) {
      box.replaceChildren();
      return;
    }
    const retry = verdict.ending.retry;
    const revealButton = h('button', { class: `btn btn-lg ${retry ? 'btn-ghost' : 'btn-primary'}`, type: 'button', onclick: reveal },
      icon('eye'), retry ? '直接揭晓汤底' : '揭晓汤底');
    if (retry) box.replaceChildren(h('a', { class: 'btn btn-primary btn-lg', href: gameUrl }, icon('retry'), '重新调查'), revealButton);
    else box.replaceChildren(revealButton, h('a', { class: 'btn btn-ghost btn-lg', href: '/' }, icon('home'), '回到首页'));
  }

  function renderTruth(animate) {
    const { truth, lessons } = state.reveal;
    const sentences = truth.match(/[^。！？]+[。！？]?/g) || [truth];
    const delay = (seconds) => (animate ? { 'animation-delay': `${seconds}s` } : { animation: 'none' });
    $('truth-text').replaceChildren(...sentences.map((text, i) => h('span', { style: delay(i * 0.35) }, text)));
    $('lessons').replaceChildren(...lessons.map((text, i) => h('li', { style: delay(sentences.length * 0.35 + i * 0.2) }, text)));
    $('lessons-box').hidden = !lessons.length;
    $('after-actions').replaceChildren(
      h('button', { class: 'btn btn-primary btn-lg', type: 'button', onclick: playAgain }, icon('retry'), '再玩一局'),
      h('a',{ class: 'btn btn-ghost btn-lg', href: '/' }, icon('home'), '回到首页'));
    $('truth').hidden = false;
    if (animate) $('truth').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function reveal() {
    if (busy) return;
    if (verdict.ending.retry) {
      const sure = await confirmDialog({
        title: '揭晓汤底？',
        text: '揭晓后本局结束，不能再回去调查。想拿更高的评级，可以先重新调查再提交。',
        ok: '揭晓汤底',
        cancel: '再想想',
      });
      if (!sure) return;
    }
    busy = true;
    let data;
    try {
      data = await api.reveal(state.gameId);
    } catch (error) {
      busy = false;
      if (!(error instanceof ApiError)) throw error;
      const message = error.status === 404 ? '服务器重启后这局已被清空，汤底取不到了。可以再开一局。' : error.message;
      toast(message, 'error', 7000);
      return;
    }
    state.reveal = { truth: tidy(data.truth), lessons: data.lessons.map(tidy) };
    state.finished = true;
    store.save(state);
    busy = false;
    $('back-game').hidden = true;
    renderActions();
    renderTruth(true);
  }

  async function playAgain() {
    if (busy) return;
    busy = true;
    let game;
    try {
      game = await api.newGame(state.storyId);
    } catch (error) {
      busy = false;
      if (!(error instanceof ApiError)) throw error;
      toast(`没能开局：${error.message}`, 'error', 6500);
      return;
    }
    const fresh = store.create(game, state.storyId);
    store.save(fresh);
    location.href = `/game.html?g=${encodeURIComponent(fresh.gameId)}`;
  }

  hydrateIcons();
  render();
})();
