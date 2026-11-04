/* 对局记录存在浏览器本地：刷新、关掉页面后还能接着玩。服务器重启后对局会失效，由游戏页提示重开。 */
(() => {
  const KS = (window.KS = window.KS || {});
  const PREFIX = 'kanshan:game:';
  const LAST = 'kanshan:last';
  const KEEP = 6;
  // 隐私模式等禁用本地存储时退回内存：当前页面照常能玩，只是刷新后不能续局
  const memory = new Map();

  function read(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return memory.has(key) ? memory.get(key) : null;
    }
  }

  function write(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      memory.set(key, value);
    }
  }

  function remove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      memory.delete(key);
    }
  }

  function savedKeys() {
    try {
      return Object.keys(localStorage).filter((key) => key.startsWith(PREFIX));
    } catch {
      return [...memory.keys()].filter((key) => key.startsWith(PREFIX));
    }
  }

  function load(gameId) {
    const raw = read(PREFIX + gameId);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      remove(PREFIX + gameId);
      return null;
    }
  }

  // 只留最近几局，避免本地存储越积越多
  function prune() {
    const games = savedKeys().map((key) => ({ key, at: (load(key.slice(PREFIX.length)) || {}).updatedAt || 0 }));
    games.sort((a, b) => b.at - a.at);
    for (const { key } of games.slice(KEEP)) remove(key);
  }

  function create(game, storyId) {
    const { tidy } = KS;
    const ids = game.characters.map((c) => c.id);
    const now = Date.now();
    return {
      gameId: game.game_id,
      storyId,
      title: game.title,
      ...(typeof game.checked === 'boolean' ? { checked: game.checked } : {}),
      intro: tidy(game.intro),
      characters: game.characters.map((c) => ({ ...c, profile: tidy(c.profile) })),
      questions: game.questions,
      greeting: tidy(game.kanshan.greeting),
      asksTotal: game.kanshan.asks_left,
      asksLeft: game.kanshan.asks_left,
      trust: Object.fromEntries(ids.map((id) => [id, 0])),
      current: ids[0],
      threads: Object.fromEntries(ids.map((id) => [id, []])),
      unread: {},
      turns: 0,
      clues: [],
      shown: {},
      exposed: [],
      log: [{ type: 'start', round: 0, at: now }],
      seenLog: 1,
      asks: [],
      hints: [],
      seenHints: 0,
      answers: {},
      verdicts: [],
      reveal: null,
      finished: false,
      introSeen: false,
      createdAt: now,
      updatedAt: now,
    };
  }

  KS.store = {
    create,
    load,
    save(state) {
      state.updatedAt = Date.now();
      write(PREFIX + state.gameId, JSON.stringify(state));
      write(LAST, state.gameId);
      prune();
    },
    last() {
      const id = read(LAST);
      return id ? load(id) : null;
    },
    // 本地留着的所有对局，首页用来显示每个案件调查到第几回合
    list() {
      return savedKeys().map((key) => load(key.slice(PREFIX.length))).filter(Boolean);
    },
    forget(gameId) {
      remove(PREFIX + gameId);
      if (read(LAST) === gameId) remove(LAST);
    },
  };
})();
