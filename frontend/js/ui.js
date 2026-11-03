/* 公共界面工具：建节点、图标、头像、提示条、确认框、打字效果。挂在 window.KS 上，各页面共用。 */
(() => {
  const KS = (window.KS = window.KS || {});
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const AVATAR_DIR = '/assets/avatars/';
  // 依次对应招牌案件四人头像的底色，生成剧本按角色顺序取色
  const PALETTE = ['#6f9fd8', '#e8954a', '#6fa385', '#8b7bc8', '#d27a98', '#5fb0b0'];

  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key === 'style') for (const [prop, v] of Object.entries(value)) el.style.setProperty(prop, v);
      else if (key === 'dataset') Object.assign(el.dataset, value);
      else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : String(child));
    }
    return el;
  }

  const ICONS = {
    send: '<path d="M21 3 10 14"/><path d="m21 3-7 18-4-7-7-4z"/>',
    evidence: '<path d="M4 6.5A1.5 1.5 0 0 1 5.5 5H9l2 2h7.5A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z"/><path d="M9 13h6"/>',
    chat: '<path d="M20 12a8 8 0 0 1-11.7 7.1L4 20l1-4.1A8 8 0 1 1 20 12z"/>',
    clue: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    events: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1.2"/><circle cx="4.5" cy="12" r="1.2"/><circle cx="4.5" cy="18" r="1.2"/>',
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    gavel: '<path d="m14 13-7.5 7.5a2.1 2.1 0 0 1-3-3L11 10"/><path d="m16 16 6-6M8 8l6-6M9 7l8 8M21 11l-8-8"/>',
    question: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.6"/><path d="M12 17h.01"/>',
    back: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    users: '<path d="M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20"/><circle cx="10" cy="8" r="3.5"/><path d="M20 20v-1.5a3.5 3.5 0 0 0-2.5-3.4M15.5 4.6a3.5 3.5 0 0 1 0 6.8"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.3.3.5.7.5 1.1v.5h6V15c0-.4.2-.8.5-1.1A6 6 0 0 0 12 3z"/>',
    retry: '<path d="M3 12a9 9 0 0 1 15.4-6.4L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.4 6.4L3 16"/><path d="M3 21v-5h5"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    home: '<path d="M4 11 12 4l8 7"/><path d="M6 10v10h12V10"/>',
    swords: '<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="m13 19 6-6M16 16l4 4M19 21l2-2"/><path d="M9.5 17.5 21 6V3h-3L6.5 14.5"/><path d="m11 19-6-6M8 16l-4 4M5 21l-2-2"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    shield: '<path d="M12 3 4.5 6v6c0 4.4 3.2 8.2 7.5 9 4.3-.8 7.5-4.6 7.5-9V6z"/><path d="m9 12 2 2 4-4"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
  };

  function icon(name, cls) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', cls ? `icon ${cls}` : 'icon');
    svg.innerHTML = ICONS[name];
    return svg;
  }

  // HTML 里写 <i data-icon="send"></i>，页面加载后换成 SVG
  function hydrateIcons(root = document) {
    for (const el of root.querySelectorAll('i[data-icon]')) el.replaceWith(icon(el.dataset.icon, el.className));
  }

  function hue(text) {
    let n = 7;
    for (const ch of text) n = (n * 31 + ch.codePointAt(0)) % 360;
    return n;
  }

  // 小林、阿凯这类称呼取后一个字，其余取姓
  function initial(name) {
    const nickname = name.match(/^[小阿老](.)$/);
    return nickname ? nickname[1] : name.slice(0, 1);
  }

  // 剧本里的头像文件不存在时（生成的剧本常见）退回姓名首字；记住缺的文件，重画时不再请求
  const missingAvatars = new Set();
  function avatar(person, size = 44) {
    const el = h('span', { class: 'avatar', style: { '--size': `${size}px` } });
    if (person === 'kanshan') {
      el.classList.add('seal');
      el.append(h('img', { src: '/assets/logo.svg', alt: '' }));
      return el;
    }
    const fallback = () => {
      el.classList.add('mono');
      el.style.setProperty('--hue', hue(person.id));
      el.replaceChildren(initial(person.name));
    };
    if (!person.avatar || missingAvatars.has(person.avatar)) {
      fallback();
      return el;
    }
    const img = h('img', { src: AVATAR_DIR + encodeURIComponent(person.avatar), alt: '', decoding: 'async' });
    img.addEventListener('error', () => {
      missingAvatars.add(person.avatar);
      fallback();
    }, { once: true });
    el.append(img);
    return el;
  }

  function accent(characters, id) {
    const index = characters.findIndex((c) => c.id === id);
    return PALETTE[(index < 0 ? 0 : index) % PALETTE.length];
  }

  function trustMeter(value, max = 3) {
    const meter = h('span', { class: 'trust', role: 'img', 'aria-label': `信任度 ${value}/${max}` });
    for (let i = 0; i < max; i += 1) meter.append(h('i', { class: i < value ? 'on' : null }));
    return meter;
  }

  function toast(message, kind = 'info', timeout = 4200) {
    let box = document.querySelector('.toasts');
    if (!box) {
      box = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' });
      document.body.append(box);
    }
    const name = { error: 'alert', success: 'check' }[kind] || 'bulb';
    const el = h('div', { class: `toast ${kind}` }, icon(name), h('span', null, message));
    box.append(el);
    setTimeout(() => {
      el.classList.add('leaving');
      el.addEventListener('animationend', () => el.remove(), { once: true });
    }, timeout);
  }

  function confirmDialog({ title, text, ok = '确定', cancel = '取消' }) {
    return new Promise((resolve) => {
      const dlg = h('dialog', { class: 'modal confirm' },
        h('div', { class: 'modal-head' }, h('h2', null, title)),
        h('div', { class: 'modal-body' }, h('p', { class: 'confirm-text' }, text)),
        h('div', { class: 'modal-foot' },
          cancel ? h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => dlg.close('cancel') }, cancel) : null,
          h('button', { class: 'btn btn-primary', type: 'button', onclick: () => dlg.close('ok') }, ok)));
      dlg.addEventListener('close', () => {
        resolve(dlg.returnValue === 'ok');
        dlg.remove();
      });
      document.body.append(dlg);
      dlg.showModal();
    });
  }

  // 点弹窗外的遮罩关闭；按下和松开都在遮罩上才算，避免拖选文字时误关
  let pressedOn = null;
  document.addEventListener('pointerdown', (event) => { pressedOn = event.target; });
  document.addEventListener('click', (event) => {
    const target = event.target;
    if (target instanceof HTMLDialogElement && target.classList.contains('modal')
      && !target.hasAttribute('data-sticky') && pressedOn === target) target.close();
  });

  const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // 逐字显示；点一下文字直接显示全文。onFrame 每次更新后调用，用来让对话区跟着滚动。
  // 页面在后台时浏览器暂停动画帧，这时直接显示全文，免得回合演出卡住
  function typeText(el, text, { cps = 42, maxMs = 1800, onFrame } = {}) {
    const chars = Array.from(text);
    if (reducedMotion() || document.hidden || chars.length < 4) {
      el.textContent = text;
      if (onFrame) onFrame();
      return Promise.resolve();
    }
    const duration = Math.min(maxMs, (chars.length / cps) * 1000);
    const start = performance.now();
    return new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        document.removeEventListener('visibilitychange', finish);
        el.textContent = text;
        if (onFrame) onFrame();
        resolve();
      };
      el.addEventListener('click', finish, { once: true });
      document.addEventListener('visibilitychange', finish);
      // 用定时器按经过的时间推进：浏览器不出动画帧时定时器照样会走
      const tick = () => {
        if (done) return;
        const count = Math.ceil(chars.length * Math.min(1, (performance.now() - start) / duration));
        el.textContent = chars.slice(0, count).join('');
        if (onFrame) onFrame();
        if (count >= chars.length) finish();
        else setTimeout(tick, 30);
      };
      tick();
    });
  }

  const fmtTime = (ts) => new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

  // 剧本 YAML 的折行写法会在两个汉字之间留下空格，显示前去掉；「8 月 20 日」这类数字旁的空格保留。
  // 只用于展示文字，结局题选项要原样提交，不能经过这里
  const CJK = '[\\u3000-\\u303f\\u4e00-\\u9fff\\uff00-\\uffef]';
  const CJK_GAP = new RegExp(`(${CJK})\\s+(?=${CJK})`, 'g');
  const tidy = (text) => text.replace(CJK_GAP, '$1');

  Object.assign(KS, { h, icon, hydrateIcons, avatar, accent, trustMeter, toast, confirmDialog, reducedMotion, sleep, typeText, fmtTime, tidy });
})();
