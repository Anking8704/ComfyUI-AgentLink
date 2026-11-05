// Edge cases of reattaching to a running reply: never two streams at once, no event handled twice,
// an older AgentLink without /agentlink/events ends cleanly, and "still answering" (409) follows the earlier reply.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const src = fs.readFileSync('web/agentlink.js', 'utf8');
const sse = (event) => `data: ${JSON.stringify(event)}\n\n`;
const tick = () => new Promise((r) => setImmediate(r));

function panel(fetchImpl) {
  const log = { requests: [], handled: [], ran: [], notes: [] };
  const ctx = { TextDecoder, AbortController, URL, setTimeout: (fn) => setImmediate(fn), document: { visibilityState: 'visible' },
    el: () => ({}), t: (x) => x, newId: () => 'new', request: async () => ({}), canvasSummary: () => ({ name: 'w', nodes: 0, types: [] }),
    PAGE_TOOLS: { run_canvas: async () => ({}) },
    fetch: (url, init) => { log.requests.push({ url, body: JSON.parse(init.body) }); return fetchImpl(url, init); } };
  vm.createContext(ctx);
  vm.runInContext(src.slice(src.indexOf('class AgentLinkPanel'), src.indexOf('\nfunction describeCall')) + '\nthis.Panel=AgentLinkPanel;', ctx);
  const p = Object.create(ctx.Panel.prototype);
  Object.assign(p, { session: 's', busy: false, input: { value: 'hi', placeholder: '' }, config: { base_url: 'u', model: 'm' }, lastSeq: 0, turnOpen: false,
    items: [], steps: new Map(), generations: new Map(), attachments: [], renderAttachments() {}, autosize() {}, persist() {}, closeOpenSteps() {},
    push(item) { if (item.k === 'note') log.notes.push(item.text); }, setBusy(v) { this.busy = v; },
    handle(e) { log.handled.push(e.seq); if (e.type === 'tool_call' && ctx.PAGE_TOOLS[e.name] && !e.answered) log.ran.push(e.id); } });
  return { p, log };
}
function controlledStream() {
  const queue = [], waiters = [];
  const reader = { cancel: async () => {}, read: () => queue.length ? Promise.resolve(queue.shift()) : new Promise((r) => waiters.push(r)) };
  const give = (item) => (waiters.length ? waiters.shift()(item) : queue.push(item));
  return { response: { ok: true, status: 200, headers: { get: () => 'text/event-stream' }, body: { getReader: () => reader } },
    send: (event) => give({ done: false, value: Buffer.from(sse(event)) }), end: () => give({ done: true }) };
}

(async () => {
  // 1. While the chat stream is still open, coming back to the tab must not open a second one.
  {
    const live = controlledStream();
    const { p, log } = panel(async (url) => (url === '/agentlink/chat' ? live.response : assert.fail('second stream opened')));
    const sending = p.send();
    await tick();
    live.send({ type: 'tool_call', id: 'c1', name: 'run_canvas', seq: 1 });
    await tick();
    await p.resume(); // visibilitychange / online while attached
    live.send({ type: 'tool_call', id: 'c1', name: 'run_canvas', seq: 1 }); // a duplicate delivery is ignored too
    live.send({ type: 'done', stopped: false, seq: 2 });
    live.end();
    await sending;
    assert.deepEqual(log.requests.map((r) => r.url), ['/agentlink/chat']);
    assert.deepEqual(log.ran, ['c1']);
    assert.deepEqual(log.handled, [1, 2]);
    assert.equal(p.busy, false);
  }
  // 2. A computer still running an older AgentLink (no /agentlink/events) ends the wait instead of spinning forever.
  {
    const first = controlledStream();
    const { p, log } = panel(async (url) => (url === '/agentlink/chat' ? first.response : { ok: false, status: 405, headers: { get: () => 'text/plain' } }));
    const sending = p.send();
    await tick();
    first.send({ type: 'text', text: 'partial', seq: 1 });
    first.end(); // the connection drops without "done"
    await sending;
    for (let i = 0; i < 20 && (p.resuming || p.busy); i++) await tick();
    assert.equal(p.busy, false);
    assert.equal(p.turnOpen, false);
    assert.deepEqual(log.notes, ['lostReply']);
  }
  // 3. "Still answering" (409): the page follows the earlier reply instead of reporting an error.
  {
    const resumed = controlledStream();
    const { p, log } = panel(async (url) => (url === '/agentlink/chat'
      ? { ok: false, status: 409, headers: { get: () => 'application/json' }, json: async () => ({ error: 'busy' }) } : resumed.response));
    const sending = p.send();
    await sending;
    for (let i = 0; i < 10; i++) await tick();
    resumed.send({ type: 'text', text: 'earlier reply', seq: 1 });
    resumed.send({ type: 'done', stopped: false, seq: 2 });
    resumed.end();
    for (let i = 0; i < 20 && p.busy; i++) await tick();
    assert.deepEqual(log.requests.map((r) => r.url), ['/agentlink/chat', '/agentlink/events']);
    assert.equal(log.requests[1].body.after, 0);
    assert.deepEqual(log.notes, ['stillAnswering']);
    assert.deepEqual(log.handled, [1, 2]);
    assert.equal(p.busy, false);
  }
  console.log('resume edge cases (single stream, duplicates, old backend, still answering) passed');
})().catch((e) => { console.error(e); process.exitCode = 1; });
