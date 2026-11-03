const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const src=fs.readFileSync('web/agentlink.js','utf8');
const widget={name:'steps',value:20,type:'number'};
const node={widgets:[widget],inputs:[{name:'steps',link:9}]};
const ctx={nodeById:()=>node,currentGraph:()=>({setDirtyCanvas(){}}),app:{extensionManager:{}},canvasSummary:()=>({}),applySeedControls(){}};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('const PAGE_TOOLS ='),src.indexOf('// The Run button'))+'\nthis.tools=PAGE_TOOLS;',ctx);
(async()=>{
 await assert.rejects(ctx.tools.edit_canvas({changes:{'1.steps':30}}),/connected/);
 assert.equal(widget.value,20,'linked input must not be reported as edited');
 console.log('linked canvas input regression passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
