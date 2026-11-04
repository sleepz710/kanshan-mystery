/* 全站声音：共用开关，整页跳转时保存播放位置，返回缓存页时重新同步。 */
(() => {
  const SOUND_KEY = 'kanshan:sound';
  const POSITION_KEY = 'kanshan:music:position';
  const controls = document.querySelectorAll('#toggle-music, #toggle-sfx');
  const bgm = new Audio('/assets/audio/bgm.mp3');
  bgm.id = 'bgm';
  bgm.hidden = true;
  bgm.preload = 'metadata';
  bgm.loop = true;
  bgm.volume = 0.3;
  document.body.append(bgm);
  let available = false;
  let leaving = false;
  let waitingForGesture = false;
  let ctx = null;

  function readPrefs() {
    try {
      return { music: true, sfx: true, ...JSON.parse(localStorage.getItem(SOUND_KEY)) };
    } catch {
      // 本地记录损坏或存储不可用时，保持默认全开。
      return { music: true, sfx: true };
    }
  }
  let prefs = readPrefs();

  function restorePosition() {
    let position;
    try {
      position = Number(sessionStorage.getItem(POSITION_KEY));
    } catch {
      // 浏览器禁用存储时仍能播放，但不能跨页接续。
      return;
    }
    if (Number.isFinite(position) && position >= 0) bgm.currentTime = position % bgm.duration;
  }

  function render() {
    for (const button of controls) {
      const key = button.id === 'toggle-music' ? 'music' : 'sfx';
      const label = `${prefs[key] ? '关闭' : '开启'}${key === 'music' ? '背景音乐' : '音效'}`;
      button.hidden = key === 'music' && !available;
      button.setAttribute('aria-pressed', String(prefs[key]));
      button.setAttribute('aria-label', label);
      button.title = label;
      const status = button.querySelector('b');
      if (status) status.textContent = prefs[key] ? '开' : '关';
      const slash = button.querySelector('[data-music-off]');
      if (slash) slash.toggleAttribute('hidden', prefs.music);
    }
  }

  function afterGesture() {
    removeEventListener('pointerdown', afterGesture, true);
    removeEventListener('keydown', afterGesture, true);
    waitingForGesture = false;
    playMusic();
  }

  function playMusic() {
    if (!available || !prefs.music || leaving) return;
    bgm.play().catch((error) => {
      if (error.name === 'NotAllowedError') {
        if (waitingForGesture) return;
        waitingForGesture = true;
        addEventListener('pointerdown', afterGesture, true);
        addEventListener('keydown', afterGesture, true);
      } else if (error.name === 'NotSupportedError') {
        available = false;
        render();
      } else if (error.name !== 'AbortError') throw error;
    });
  }

  // 菜单音效：[频率, 起点, 时长, 音量]。
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

  for (const button of controls) button.addEventListener('click', () => {
    const key = button.id === 'toggle-music' ? 'music' : 'sfx';
    prefs[key] = !prefs[key];
    try {
      localStorage.setItem(SOUND_KEY, JSON.stringify(prefs));
    } catch {
      // 存储不可用时，本页开关仍立即生效。
    }
    render();
    if (!prefs.music) bgm.pause();
    else playMusic();
    if (key === 'sfx') sfx('confirm');
  });

  bgm.addEventListener('loadedmetadata', () => {
    available = true;
    restorePosition();
    render();
    playMusic();
  });
  bgm.addEventListener('error', () => {
    available = false;
    render();
  });
  addEventListener('pagehide', () => {
    leaving = true;
    if (available) {
      try {
        sessionStorage.setItem(POSITION_KEY, String(bgm.currentTime));
      } catch {
        // 存储不可用时，下页从头播放。
      }
    }
    bgm.pause();
  });
  addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    leaving = false;
    prefs = readPrefs();
    if (available) restorePosition();
    render();
    if (prefs.music) playMusic();
    else bgm.pause();
  });
  addEventListener('storage', (event) => {
    if (event.storageArea !== localStorage || (event.key !== SOUND_KEY && event.key !== null)) return;
    prefs = readPrefs();
    render();
    if (prefs.music) playMusic();
    else bgm.pause();
  });

  window.KS.sound = { sfx };
  render();
})();
