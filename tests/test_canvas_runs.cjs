// Delayed conversion/queue responses must not submit or mutate a different workflow/chat.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const src = fs.readFileSync('web/agentlink.js', 'utf8');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };

(async () => {
  const {createCanvasEditor} = await import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync('web/canvas_edit.js', 'utf8')).toString('base64'));
  function setup() {
    const graph = () => ({_nodes:[{id:1,type:'Sampler',widgets:[{name:'seed',value:10,options:{min:0,max:100}},{name:'control_after_generate',value:'increment'}]}],
      serialize() { return {nodes:this._nodes.map(n => ({id:n.id,widgets_values:n.widgets.map(w => w.value)}))}; }, configure() {}});
    const a=graph(), b=graph(); b._nodes[0].widgets[0].value=80;
    let active=a, workflow={filename:'a'};
    const queued=[], tracked=[], cancelled=[], replies=[];
    const editor=createCanvasEditor({getGraph:()=>active,getWorkflow:()=>workflow,createNode:()=>null});
    const ctx={canvasEditor:editor,currentGraph:()=>active,canvasSummary:()=>({name:workflow.filename}),t:key=>key,newId:()=> 'chat-replaced',
      app:{graphToPrompt:async()=>({workflow:workflow.filename,output:{}})},
      api:{queuePrompt:async(_n,prompt)=>{queued.push(prompt);return {prompt_id:'job-'+queued.length};}},
      fetch:async(url)=>{cancelled.push(url);return {ok:true};},request:async(url,body)=>{replies.push({url,body});return {};},crypto:require('node:crypto').webcrypto};
    vm.createContext(ctx);
    vm.runInContext(src.slice(src.indexOf('const PAGE_TOOLS ='),src.indexOf('class AgentLinkPanel'))+'\nthis.tools=PAGE_TOOLS;',ctx);
    vm.runInContext(src.slice(src.indexOf('class AgentLinkPanel'),src.indexOf('\nfunction describeCall'))+'\nthis.Panel=AgentLinkPanel;',ctx);
    const panel=Object.create(ctx.Panel.prototype);
    Object.assign(panel,{session:'chat-a',generations:new Map(),items:[],steps:new Map(),trackGeneration:id=>tracked.push(id),setBusy(){},showWelcome(){},persist(){}});
    panel.canvasTarget=editor.read().target;
    return {ctx,panel,a,b,queued,tracked,cancelled,replies,switchGraph(){active=b;workflow={filename:'b'};}};
  }
  async function check(name, run) { try {await run(); console.log('PASS '+name);} catch(e) {console.error('FAIL '+name+': '+e.message);process.exitCode=1;} }

  await check('switch during prompt conversion prevents queue',async()=>{
    const s=setup(), gate=deferred();s.ctx.app.graphToPrompt=()=>gate.promise;
    const run=s.ctx.tools.run_canvas({count:2},s.panel);s.switchGraph();gate.resolve({workflow:'a',output:{}});
    await assert.rejects(run,/stale|changed|workflow/i);
    assert.equal(s.queued.length,0);assert.equal(s.b._nodes[0].widgets[0].value,80);
  });
  await check('stop during prompt conversion prevents queue',async()=>{
    const s=setup(), gate=deferred();s.ctx.app.graphToPrompt=()=>gate.promise;
    const run=s.ctx.tools.run_canvas({count:2},s.panel);await s.panel.stop();gate.resolve({output:{}});
    await assert.rejects(run,/cancel|stop/i);assert.equal(s.queued.length,0);
  });
  await check('late queue result after new chat is cancelled without seed changes',async()=>{
    const s=setup(), gate=deferred(), entered=deferred();
    s.ctx.api.queuePrompt=async()=>{entered.resolve();return gate.promise;};
    const run=s.ctx.tools.run_canvas({count:2},s.panel);await entered.promise;await s.panel.newChat();
    gate.resolve({prompt_id:'late-job'});await assert.rejects(run,/cancel|chat/i);
    assert.equal(s.tracked.length,0);assert.equal(s.a._nodes[0].widgets[0].value,10);
    assert(s.cancelled.some(url=>url.includes('late-job')&&url.endsWith('/cancel')));
  });
  await check('switch during queue never changes other graph or queues a second job',async()=>{
    const s=setup(), gate=deferred(), entered=deferred();let calls=0;
    s.ctx.api.queuePrompt=async()=>{calls++;entered.resolve();return calls===1?gate.promise:{prompt_id:'unexpected'};};
    const run=s.ctx.tools.run_canvas({count:2},s.panel);await entered.promise;s.switchGraph();gate.resolve({prompt_id:'first'});
    await assert.rejects(run,/stale|changed|workflow/i);
    assert.equal(calls,1);assert.equal(s.b._nodes[0].widgets[0].value,80);
  });
  await check('unchanged graph queues batch and advances seeds',async()=>{
    const s=setup();const result=await s.ctx.tools.run_canvas({count:2},s.panel);
    assert.deepEqual(Array.from(result.prompt_ids),['job-1','job-2']);assert.equal(s.a._nodes[0].widgets[0].value,12);
    assert.equal(s.queued.length,2);assert.equal(s.tracked.length,2);
    // The implicit widget-edit target follows deliberate seed changes.
    s.ctx.canvasEditor.assertCurrent(s.panel.canvasTarget);
  });
  await check('manual edit during conversion prevents queue and preserves value',async()=>{
    const s=setup(), gate=deferred();s.ctx.app.graphToPrompt=()=>gate.promise;
    const run=s.ctx.tools.run_canvas({},s.panel);s.a._nodes[0].widgets[0].value=45;gate.resolve({output:{}});
    await assert.rejects(run,/stale|changed/i);assert.equal(s.queued.length,0);assert.equal(s.a._nodes[0].widgets[0].value,45);
  });
  await check('stop during queue cancels late job and remaining batch',async()=>{
    const s=setup(), gate=deferred(), entered=deferred();let calls=0;
    s.ctx.api.queuePrompt=async()=>{calls++;entered.resolve();return calls===1?gate.promise:{prompt_id:'unexpected'};};
    const run=s.ctx.tools.run_canvas({count:2},s.panel);await entered.promise;await s.panel.stop();gate.resolve({prompt_id:'stopped-job'});
    await assert.rejects(run,/cancel/i);assert.equal(calls,1);assert.equal(s.a._nodes[0].widgets[0].value,10);
    assert(s.cancelled.some(url=>url.includes('stopped-job')&&url.endsWith('/cancel')));
  });
  await check('invalid counts and stale inspected target never queue',async()=>{
    const s=setup();
    for(const count of [0,9,1.5,'2',null]) await assert.rejects(s.ctx.tools.run_canvas({count},s.panel),/count/i);
    s.a._nodes[0].widgets[0].value=22;
    await assert.rejects(s.ctx.tools.run_canvas({},s.panel),/stale|changed/i);assert.equal(s.queued.length,0);
  });
  await check('late edit page call after stop returns an error without mutation',async()=>{
    const s=setup();await s.panel.stop();
    await s.panel.answerPage({id:'edit',name:'edit_canvas',arguments:{changes:{'1.seed':44}}},s.panel.session);
    assert.equal(s.a._nodes[0].widgets[0].value,10);
    assert.match(s.replies.at(-1).body.error,/cancel/i);
  });
  await check('late saved-workflow event after stop cannot replace canvas',async()=>{
    const s=setup(), opened=[];s.ctx.app.loadGraphData=(...args)=>opened.push(args);s.panel.push=()=>{};
    await s.panel.stop();s.panel.handle({type:'open_workflow',name:'late.json',workflow:{}},s.panel.session);
    assert.equal(opened.length,0);
  });
  await check('late saved-workflow event from replaced chat cannot replace canvas',async()=>{
    const s=setup(), opened=[];s.ctx.app.loadGraphData=(...args)=>opened.push(args);s.panel.push=()=>{};
    const old=s.panel.session;await s.panel.newChat();
    s.panel.handle({type:'open_workflow',name:'old.json',workflow:{}},old);assert.equal(opened.length,0);
  });
})().catch(e=>{console.error(e);process.exitCode=1;});
