/* 桌面入口注入所有页面，共用拖动区与窗口按钮。 */
(() => {
  if (!window.KANSHAN_DESKTOP) return;

  const bar = document.createElement('header');
  bar.className = 'window-bar';
  bar.setAttribute('aria-label', '窗口工具栏');
  bar.innerHTML = `
    <a class="window-home" href="/" aria-label="返回首页" title="返回首页">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg>
      <span>返回首页</span>
    </a>
    <div class="window-drag pywebview-drag-region" title="拖动窗口，双击最大化或还原">
      <span class="window-caption">看山谜案馆</span>
    </div>
    <div class="window-controls">
      <button class="window-button" type="button" data-window="minimize" aria-label="最小化" title="最小化" disabled>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5h10"/></svg>
      </button>
      <button class="window-button" type="button" data-window="toggle_maximize" aria-label="最大化" title="最大化" disabled>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path class="window-maximize" d="M3.5 3.5h9v9h-9z"/><path class="window-restore" d="M5.5 5.5h7v7h-7zM3.5 10.5v-7h7"/></svg>
      </button>
      <button class="window-button window-close" type="button" data-window="quit" aria-label="关闭" title="关闭" disabled>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8"/></svg>
      </button>
    </div>
    <span class="window-error" role="status"></span>`;
  document.body.prepend(bar);

  // 模态弹窗会使外部节点不可交互，工具栏跟随当前弹窗进入顶层。
  function followDialog() {
    const dialogs = [...document.querySelectorAll('dialog:modal')];
    const owner = dialogs.at(-1) || document.body;
    if (bar.parentElement === owner) return;
    if (bar.matches(':popover-open')) bar.hidePopover();
    if (owner === document.body) {
      bar.removeAttribute('popover');
      owner.prepend(bar);
    } else {
      bar.setAttribute('popover', 'manual');
      owner.append(bar);
      bar.showPopover();
    }
  }
  new MutationObserver(followDialog).observe(document.body, {
    subtree: true, childList: true, attributes: true, attributeFilter: ['open'],
  });
  followDialog();

  const maximize = bar.querySelector('[data-window="toggle_maximize"]');
  function showState(maximized) {
    bar.classList.toggle('is-maximized', maximized);
    const label = maximized ? '还原' : '最大化';
    maximize.title = label;
    maximize.setAttribute('aria-label', label);
  }

  async function invoke(method) {
    try {
      return await window.pywebview.api[method]();
    } catch (error) {
      console.error('窗口操作失败', error);
      bar.querySelector('.window-error').textContent = '窗口操作失败，请重试';
    }
  }

  bar.addEventListener('click', (event) => {
    const button = event.target.closest('[data-window]');
    if (button) invoke(button.dataset.window);
  });
  bar.addEventListener('keydown', (event) => event.stopPropagation());
  bar.querySelector('.window-drag').addEventListener('mousedown', (event) => {
    if (event.button !== 0 || !window.pywebview?.api) return;
    event.preventDefault();
    event.stopPropagation();
    invoke(event.detail === 2 ? 'toggle_maximize' : 'start_drag');
  });
  addEventListener('kanshan:window-state', (event) => showState(event.detail.maximized));

  async function ready() {
    for (const button of bar.querySelectorAll('button')) button.disabled = false;
    showState(await invoke('is_maximized'));
  }
  addEventListener('pywebviewready', ready, { once: true });
  if (window.pywebview?.api) ready();
})();
