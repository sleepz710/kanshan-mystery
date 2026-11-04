// 从实际前端提取 renderSuggest，离线核对新旧档位文案与历史恢复。
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = path.resolve(__dirname, '../../../frontend/studio/studio.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const renderStart = source.indexOf('  function renderSuggest() {');
const renderEnd = source.indexOf('  function renderAttachments()', renderStart);
assert.ok(renderStart >= 0 && renderEnd > renderStart);
const renderFunction = source.slice(renderStart, renderEnd);
const strategyDefinition = source.match(/^  const STRATEGY_REPLIES = .*;$/m)[0];
const oldPrompt = '快速（约 3 分钟）还是精修（约 8 分钟，可以先去玩别的案子）？';
const newPrompt = '快速还是精修？精修会比较两份设计，并增加修订轮次。实际耗时取决于素材和模型。';
const strategyReplies = ['没看过答案', '看过答案', '全新', '直接开始'];
const cases = [];

function checkCase(name, text, expected, options = {}) {
  const sent = [];
  let nodes = [];
  let session = {
    mode: options.mode || 'play', jobs: [],
    messages: [{ role: 'user', text: '我想玩医院题材' }, { role: options.role || 'writer', text }],
  };
  if (options.restored) session = JSON.parse(JSON.stringify(session));
  const context = {
    session, busy: Boolean(options.busy),
    runningJob: () => options.running ? { id: 'running-job' } : null,
    userCount: () => 1,
    STARTERS: [],
    chip: (label, onclick) => ({ label, onclick }),
    send: (label) => sent.push(label),
    fill: () => {},
    el: { suggest: { replaceChildren: (...children) => { nodes = children; } } },
  };
  vm.runInNewContext(`${strategyDefinition}\n${renderFunction}\nrenderSuggest();`, context);
  const labels = Array.from(nodes, (node) => node.label);
  assert.deepEqual(labels, expected, name);
  nodes.forEach((node) => node.onclick());
  assert.deepEqual(sent, expected, `${name} button actions`);
  cases.push({ name, restored: Boolean(options.restored), labels, sent, passed: true });
}

checkCase('old prompt', oldPrompt, ['快速', '精修']);
checkCase('old prompt restored from history', oldPrompt, ['快速', '精修'], { restored: true });
checkCase('new prompt', newPrompt, ['快速', '精修']);
checkCase('new prompt restored from history', newPrompt, ['快速', '精修'], { restored: true });
checkCase('ordinary strategy question', '你看过答案吗？', strategyReplies);
checkCase('ordinary reply mentioning speed', '快速生成后可以讨论精修的方向。', strategyReplies);
checkCase('retained share conversation', '请确认是否开始生成。', ['开始生成'], { mode: 'share' });
checkCase('latest message from user', newPrompt, [], { role: 'user' });
checkCase('busy conversation', newPrompt, [], { busy: true });
checkCase('generation already running', newPrompt, [], { running: true });

const result = {
  tested_utc: new Date().toISOString(),
  mode: 'offline execution of actual renderSuggest with lightweight DOM and send stubs',
  node_version: process.version,
  source_sha256: crypto.createHash('sha256').update(fs.readFileSync(sourcePath)).digest('hex'),
  real_model_calls: 0,
  cases,
};
fs.writeFileSync(path.join(__dirname, 'quality-suggestions.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
console.log(`${cases.length} quality suggestion checks passed`);
