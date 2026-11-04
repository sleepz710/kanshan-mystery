/* 参考图的最小运行器：把 .dc.html 里的 {{占位}}、<sc-for>、<sc-if> 和 onClick 渲染成普通页面。只用于在浏览器里打开参考图。 */
(() => {
  class DCLogic {
    constructor(props) { this.props = props || {}; this.state = {}; }
    setState(patch) { Object.assign(this.state, patch); render(); }
  }
  let root, template, component;

  const resolve = (path, scope) => {
    path = path.trim();
    if (path === 'true') return true;
    if (path === 'false') return false;
    if (/^-?\d+(\.\d+)?$/.test(path)) return Number(path);
    return path.split('.').reduce((obj, key) => (obj == null ? undefined : obj[key]), scope);
  };
  const fill = (text, scope) => {
    const whole = text.match(/^\s*\{\{([^}]+)\}\}\s*$/);
    if (whole) return resolve(whole[1], scope);
    return text.replace(/\{\{([^}]+)\}\}/g, (_, path) => { const v = resolve(path, scope); return v == null ? '' : String(v); });
  };

  function build(node, scope, out) {
    if (node.nodeType === Node.TEXT_NODE) { out.appendChild(document.createTextNode(String(fill(node.textContent, scope) ?? ''))); return; }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tag = node.localName;
    if (tag === 'sc-for') {
      const list = fill(node.getAttribute('list'), scope) || [];
      const as = node.getAttribute('as');
      list.forEach((item, index) => {
        const inner = Object.assign(Object.create(scope), { [as]: item, $index: index });
        node.childNodes.forEach((child) => build(child, inner, out));
      });
      return;
    }
    if (tag === 'sc-if') {
      if (fill(node.getAttribute('value'), scope)) node.childNodes.forEach((child) => build(child, scope, out));
      return;
    }
    const el = document.createElementNS(node.namespaceURI, tag);
    for (const attr of node.attributes) {
      if (attr.name.startsWith('hint-')) continue;
      const value = fill(attr.value, scope);
      if (attr.name.startsWith('on') && typeof value === 'function') el.addEventListener(attr.name.slice(2), value);
      else el.setAttribute(attr.name, String(value ?? ''));
    }
    node.childNodes.forEach((child) => build(child, scope, el));
    out.appendChild(el);
  }

  function render() {
    const scope = component.renderVals();
    root.replaceChildren();
    template.childNodes.forEach((child) => build(child, scope, root));
  }

  document.addEventListener('DOMContentLoaded', () => {
    const host = document.querySelector('x-dc');
    const helmet = host.querySelector('helmet');
    if (helmet) { document.head.append(...helmet.childNodes); helmet.remove(); }
    template = document.createElement('div');
    template.append(...host.childNodes);
    root = host;
    const source = document.querySelector('script[data-dc-script]').textContent;
    const Component = new Function('DCLogic', `${source}\nreturn Component;`)(DCLogic);
    component = new Component({});
    if (!component.state) component.state = {};
    render();
  });
})();
