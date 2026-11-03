/* 编剧对话记录：浏览器里存多段对话和各自的生成任务。编剧页的侧边栏和首页的生成进度都读这里。 */
(() => {
  const KS = (window.KS = window.KS || {});
  const { api, ApiError, toast } = KS;

  // { chatId, mode, createdAt, updatedAt, messages: [{ role: 'me' | 'writer', text, files }],
  //   jobs: [{ id, mode, after, status, progress, steps, storyId, error, story, startedAt, endedAt, lost }] }
  // 列表按 updatedAt 从新到旧排
  const LIST_KEY = 'kanshan:studio:chats';
  const CURRENT_KEY = 'kanshan:studio:current';
  // 旧版只记一段对话，第一次读取时搬进列表
  const LEGACY_KEY = 'kanshan:studio';
  const OWNER_PREFIX = 'kanshan:owner:';
  const KEEP = 30;
  // 隐私模式等禁用本地存储时退回内存，当前页面照常能用
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

  function parse(raw) {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  const hasTalk = (chat) => chat.messages.some((m) => m.role === 'me');

  function list() {
    const saved = parse(read(LIST_KEY)) || [];
    const legacyRaw = read(LEGACY_KEY);
    if (legacyRaw === null) return saved;
    remove(LEGACY_KEY);
    const legacy = parse(legacyRaw);
    if (!legacy || !legacy.chatId || !Array.isArray(legacy.messages) || !Array.isArray(legacy.jobs)) return saved;
    const now = Date.now();
    const merged = [{ ...legacy, createdAt: now, updatedAt: now }, ...saved.filter((c) => c.chatId !== legacy.chatId)];
    write(LIST_KEY, JSON.stringify(merged));
    write(CURRENT_KEY, legacy.chatId);
    return merged;
  }

  const get = (chatId) => list().find((chat) => chat.chatId === chatId) || null;

  // 存一段对话并排到最前；没聊过的空对话只留这一段，侧边栏不堆空白记录
  function put(chat) {
    const saved = list();
    const stored = saved.find((c) => c.chatId === chat.chatId);
    // 另一个页面（比如首页）先记下了任务结果，这边内存里还是生成中时，以已结束的为准
    if (stored) {
      for (const job of chat.jobs) {
        const finished = stored.jobs.find((j) => j.id === job.id && j.status !== 'running');
        if (finished && job.status === 'running') Object.assign(job, finished);
      }
    }
    chat.updatedAt = Date.now();
    const rest = saved.filter((c) => c.chatId !== chat.chatId && hasTalk(c));
    write(LIST_KEY, JSON.stringify([chat, ...rest].slice(0, KEEP)));
  }

  const current = () => read(CURRENT_KEY);
  const setCurrent = (chatId) => write(CURRENT_KEY, chatId);

  // 生成完用案件标题，否则用第一句话
  function title(chat) {
    const done = [...chat.jobs].reverse().find((j) => j.status === 'done' && j.story && j.story.title);
    if (done) return done.story.title;
    const first = chat.messages.find((m) => m.role === 'me');
    if (!first) return '新对话';
    const text = (first.text || first.files[0] || '').replace(/\s+/g, ' ').replace(/^汤面[:：]\s*/, '');
    return text.length > 24 ? `${text.slice(0, 24)}…` : text;
  }

  const runningJob = (chat) => chat.jobs.find((j) => j.status === 'running');

  function keepOwnerToken(storyId, token) {
    try {
      localStorage.setItem(OWNER_PREFIX + storyId, token);
    } catch {
      toast('浏览器禁用了本地存储，出题人页面需要的访问令牌没能保存。', 'error', 8000);
    }
  }

  async function storyInfo(storyId) {
    let stories;
    try {
      stories = await api.stories();
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      // 卡片只是少了标题和汤面，开局不受影响
      return null;
    }
    const found = stories.find((s) => s.id === storyId);
    return found ? { title: found.title, intro: found.intro, characters: found.characters } : null;
  }

  // 查一次进度，结果写进 job。连不上服务器时返回 false，job.offline 标为 true，调用方稍后再查
  async function checkJob(job) {
    let data;
    try {
      data = await api.studioJob(job.id);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (error.status !== 404) {
        job.offline = true;
        return false;
      }
      Object.assign(job, {
        status: 'failed', lost: true, offline: false, endedAt: Date.now(),
        progress: '生成任务已丢失', error: '服务器重启过，这次生成没有保存下来。请新建对话再生成一次。',
      });
      return true;
    }
    job.offline = false;
    if (data.status === 'running') {
      if (data.progress && data.progress !== job.steps.at(-1)) job.steps.push(data.progress);
      return true;
    }
    Object.assign(job, { status: data.status, progress: data.progress, storyId: data.story_id, error: data.error, endedAt: Date.now() });
    if (data.status === 'done') {
      if (data.owner_token) keepOwnerToken(data.story_id, data.owner_token);
      job.story = await storyInfo(data.story_id);
    }
    return true;
  }

  function clock(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  function ago(time) {
    const minutes = Math.floor((Date.now() - time) / 60000);
    if (minutes < 1) return '刚刚';
    if (minutes < 60) return `${minutes} 分钟前`;
    if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} 小时前`;
    const date = new Date(time);
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  }

  KS.chats = { list, get, put, current, setCurrent, title, hasTalk, runningJob, checkJob, clock, ago };
})();
