// A reply that keeps running on the computer while the phone's connection drops must be picked up again:
// the page reattaches with the last seq it saw, renders only what it missed, and never reruns an answered page tool.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const src = fs.readFileSync('web/agentlink.js', 'utf8');

function stream(chunks, fail) {
  let i = 0;
  return { ok: true, headers: { get: () => 'text/event-stream' }, body: { getReader: () => ({ cancel: async () => {},
    read: async () => {
      if (i < chunks.length) return { done: false, value: Buffer.from(chunks[i++]) };
      if (fail) throw new TypeError('network connection was lost');
      return { done: true };
    } }) } };
}
const sse = (event) => `data: ${JSON.stringify(event)}\n\n`;

(async () => {
  const requests = [], handled = [], answered = [];
  const ctx = { TextDecoder, AbortController, URL, setTimeout: (fn) => setImmediate(fn), document: { visibilityState: 'visible' },
    el: () => ({}), t: (x) => x, newId: () => 'new', request: async () => ({}), canvasSummary: () => ({ name: 'w', nodes: 0, types: [] }),
    PAGE_TOOLS: { read_canvas: async () => ({}) },
    fetch: async (url, init) => {
      requests.push({ url, body: JSON.parse(init.body) });
      if (url === '/agentlink/chat') return stream([sse({ type: 'tool_call', id: 'c1', name: 'list_models', seq: 1 })], true);
      return stream([sse({ type: 'tool_call', id: 'c2', name: 'read_canvas', seq: 2, answered: true }), sse({ type: 'text', text: 'done', seq: 3 }), sse({ type: 'done', stopped: false, seq: 4 })]);
    } };
  vm.createContext(ctx);
  vm.runInContext(src.slice(src.indexOf('class AgentLinkPanel'), src.indexOf('\nfunction describeCall')) + '\nthis.Panel=AgentLinkPanel;', ctx);
  const p = Object.create(ctx.Panel.prototype);
  Object.assign(p, { session: 's', busy: false, input: { value: 'hi' }, config: { base_url: 'u', model: 'm' }, lastSeq: 0, turnOpen: false,
    items: [], steps: new Map(), generations: new Map(), attachments: [], renderAttachments() {}, autosize() {}, persist() {}, closeOpenSteps() {},
    push() {}, setBusy(v) { this.busy = v; },
    handle(e) { handled.push(e.seq); if (e.type === 'tool_call' && ctx.PAGE_TOOLS[e.name] && !e.answered) answered.push(e.id); } });
  await p.send();
  for (let i = 0; i < 50 && p.turnOpen; i++) await new Promise((r) => setImmediate(r));
  while (p.resuming) await new Promise((r) => setImmediate(r));
  assert.deepEqual(requests.map((r) => r.url), ['/agentlink/chat', '/agentlink/events']);
  assert.equal(requests[1].body.after, 1, 'reattach continues after the last event seen');
  assert.deepEqual(handled, [1, 2, 3, 4], 'every event rendered exactly once');
  assert.deepEqual(answered, [], 'an already answered page tool is not run again');
  assert.equal(p.turnOpen, false);
  assert.equal(p.busy, false);
  console.log('resume after a dropped connection passed');
})().catch((e) => { console.error(e); process.exitCode = 1; });
