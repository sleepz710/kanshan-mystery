/* 游戏接口（SPEC 6.2）。错误统一抛 KS.ApiError，message 是能直接给玩家看的中文。 */
(() => {
  const KS = (window.KS = window.KS || {});

  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  function errorMessage(status, data) {
    const detail = data && data.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail)) return '提交的内容格式不对，请修改后再试。';
    if (status === 401) return '需要体验账号和口令，请刷新页面后输入。';
    if (status >= 500) return '服务暂时不可用，请稍后重试。';
    return `请求失败（${status}），请重试。`;
  }

  async function request(method, path, body) {
    let response;
    try {
      response = await fetch(path, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
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
    if (data === null) throw new ApiError(response.status, '服务返回的内容无法读取，请重试。');
    return data;
  }

  const game = (id) => `/api/games/${encodeURIComponent(id)}`;

  KS.ApiError = ApiError;
  KS.api = {
    stories: () => request('GET', '/api/stories'),
    newGame: (storyId) => request('POST', '/api/games', { story_id: storyId }),
    talk: (gameId, characterId, text) => request('POST', `${game(gameId)}/talk`, { character_id: characterId, text }),
    show: (gameId, characterId, clueId) => request('POST', `${game(gameId)}/show`, { character_id: characterId, clue_id: clueId }),
    ask: (gameId, question) => request('POST', `${game(gameId)}/ask`, { question }),
    accuse: (gameId, answers) => request('POST', `${game(gameId)}/accuse`, { answers }),
    reveal: (gameId) => request('POST', `${game(gameId)}/reveal`),
  };
})();
