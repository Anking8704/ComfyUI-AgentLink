// A reply still streaming for an old chat must never write into, or reset, the chat that replaced it.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const src = fs.readFileSync('web/agentlink.js', 'utf8');

async function check(fail) {
  let deliver, reject, reads = 0;
  const events = [];
  const ctx = {TextDecoder, AbortController, URL, crypto: require('node:crypto').webcrypto,
    el: () => ({}), t: x => x, request: async () => ({}), canvasSummary: () => ({name: 'w', nodes: 0, types: []}),
    fetch: async () => ({ok: true, body: {getReader: () => ({cancel: async () => {},
      read: () => ++reads === 1 ? new Promise((r, j) => { deliver = r; reject = j; }) : Promise.resolve({done: true})})}})};
  vm.createContext(ctx);
  vm.runInContext(src.slice(src.indexOf('class AgentLinkPanel'), src.indexOf('\nfunction describeCall')) + '\nthis.Panel=AgentLinkPanel;', ctx);
  const p = Object.create(ctx.Panel.prototype);
  Object.assign(p, {session: 'old', canvasTarget:'previous-inspection', busy: false, input: {value: 'hi'}, config: {base_url: 'local', model: 'm'},
    items: [], steps: new Map(), generations: new Map(), attachments: [], renderAttachments() {}, autosize() {}, persist() {}, showWelcome() {}, closeOpenSteps() {},
    push(e) { events.push(e); }, setBusy(v) { this.busy = v; }, handle(e) { events.push(e); }});
  const running = p.send();
  while (!deliver) await new Promise(r => setImmediate(r));
  events.length = 0;
  await p.newChat();
  assert.equal(p.canvasTarget,null,'new chat must require its own canvas inspection');
  assert.equal(p.busy, false, 'new chat must be ready immediately');
  p.busy = true; // A new request has started; the old finally must not clear it.
  if (fail) reject(new Error('old error'));
  else deliver({done: false, value: Buffer.from('data: {"type":"text","text":"old reply"}\n\n')});
  await running;
  assert.equal(events.length, 0, 'old stream must not write to new chat');
  assert.equal(p.busy, true, 'old stream must not reset new request state');
}

(async () => { await check(false); await check(true); console.log('2 frontend isolation cases passed'); })()
  .catch(e => { console.error(e); process.exitCode = 1; });
