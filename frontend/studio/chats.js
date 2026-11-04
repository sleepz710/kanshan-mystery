/* 编剧对话记录：浏览器里存多段对话和各自的生成任务。编剧页的侧边栏和首页的生成进度都读这里。
   编剧接口、附件限制和快捷素材也放在这里，首页「新建剧场」和编剧页共用。 */
(() => {
  const KS = (window.KS = window.KS || {});
  const { api, ApiError, toast } = KS;

  // { chatId, createdAt, updatedAt, messages: [{ role: 'me' | 'writer', text, files }],
  //   jobs: [{ id, quality, after, status, progress, steps, storyId, error, story, startedAt, endedAt, lost }] }
  // 列表按 updatedAt 从新到旧排。出题给朋友取消前的记录还带 mode 字段，已不再读取
  const LIST_KEY = 'kanshan:studio:chats';
  const CURRENT_KEY = 'kanshan:studio:current';
  // 旧版只记一段对话，第一次读取时搬进列表
  const LEGACY_KEY = 'kanshan:studio';
  const KEEP = 30;

  // 与 backend/studio 的限制一致，发送前先提示
  const LIMITS = { files: 5, fileBytes: 256 * 1024, urls: 3 };
  const URL_PATTERN = /https?:\/\/[^\s<>"'，。；）)]+/g;
  const STARTERS = [
    { label: '贴一碗海龟汤', text: '汤面：小周每天准时给楼下的流浪猫喂食。一天夜里他报了警，说是那只猫救了他。\n汤底：那晚猫没有出现，小周绕到楼后去找，看见有人正在撬他家一楼的窗户。' },
    { label: '说一句想法', text: '我想玩一个发生在大雪封山的民宿里的案子，老板的账本不见了。' },
    { label: '改编网页上的故事', text: '请改编这个网页里的故事：https://' },
  ];
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

  // 编剧开始生成时记下的任务；after 是任务开始时的消息条数，编剧页把任务卡片画在这条消息后面
  const newJob = (job, after) => ({
    id: job.id, quality: job.quality || 'fast', after, status: 'running', progress: '', steps: [], startedAt: Date.now(),
  });

  // 首页「新建剧场」交给编剧后，把开场白、第一条消息和编剧的回复存成一段对话，编剧页打开就能接着聊
  function begin(chat, msg, result) {
    const now = Date.now();
    const record = {
      chatId: chat.chat_id, createdAt: now, updatedAt: now,
      messages: [{ role: 'writer', text: chat.reply }, msg, { role: 'writer', text: result.reply }], jobs: [],
    };
    if (result.job) record.jobs.push(newJob(result.job, record.messages.length));
    put(record);
    setCurrent(record.chatId);
  }

  // 按限制把选中的文件加进附件列表，不合要求的弹提示
  function addFiles(list, attached) {
    for (const file of list) {
      const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
      if (ext !== '.txt' && ext !== '.md') toast(`「${file.name}」不是 txt 或 md 文件，其他格式请把文字复制进输入框。`, 'error', 6000);
      else if (file.size > LIMITS.fileBytes) toast(`「${file.name}」超过 256 KB，请只上传要改编的部分。`, 'error', 6000);
      else if (!file.size) toast(`「${file.name}」是空文件。`, 'error');
      else if (attached.some((f) => f.name === file.name)) toast(`「${file.name}」已经在附件里了。`);
      else if (attached.length >= LIMITS.files) {
        toast(`每次最多附 ${LIMITS.files} 个文件。`, 'error');
        break;
      } else attached.push(file);
    }
  }

  // ---------- 编剧接口（SPEC 6.2 生成剧场） ----------

  function errorMessage(status, data) {
    const detail = data && data.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail)) return '提交的内容格式不对，请修改后再试。';
    if (status === 401) return '需要体验账号和口令，请刷新页面后输入。';
    if (status === 413) return '附件太大了，请只上传要改编的部分。';
    if (status >= 500) return '服务暂时不可用，请稍后重试。';
    return `请求失败（${status}），请重试。`;
  }

  // 和 js/api.js 的 request 一样，多支持 multipart 上传
  async function request(method, path, body) {
    const json = body !== undefined && !(body instanceof FormData);
    let response;
    try {
      response = await fetch(path, {
        method,
        headers: json ? { 'Content-Type': 'application/json' } : undefined,
        body: json ? JSON.stringify(body) : body,
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

  const writer = {
    newChat: () => request('POST', '/api/studio/chats', { mode: 'play' }),
    send: (chatId, form) => request('POST', `/api/studio/chats/${encodeURIComponent(chatId)}/messages`, form),
  };

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
    if (data.quality === 'fast' || data.quality === 'fine') job.quality = data.quality;
    if (data.status === 'running') {
      if (data.progress && data.progress !== job.steps.at(-1)) job.steps.push(data.progress);
      return true;
    }
    Object.assign(job, { status: data.status, progress: data.progress, storyId: data.story_id, error: data.error, endedAt: Date.now() });
    if (data.status === 'done') job.story = await storyInfo(data.story_id);
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

  KS.chats = {
    list, get, put, current, setCurrent, title, hasTalk, runningJob, newJob, begin, checkJob, clock, ago,
    LIMITS, URL_PATTERN, STARTERS, addFiles, writer,
  };
})();
