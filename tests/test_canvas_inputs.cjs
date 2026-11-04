const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 const {createCanvasEditor}=await import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync('web/canvas_edit.js','utf8')).toString('base64'));
 const widget={name:'steps',value:20,type:'number'};
 const node={id:1,type:'Sampler',widgets:[widget],inputs:[{name:'steps',link:9}],pos:[0,0]};
 const graph={_nodes:[node],serialize(){return {nodes:[{id:1,widgets_values:[widget.value]}]};},configure(){},getNodeById:()=>node,setDirtyCanvas(){}};
 const editor=createCanvasEditor({getGraph:()=>graph,getWorkflow:()=>graph,createNode:()=>null});
 const ctx={canvasEditor:editor,canvasSummary:()=>({name:'fixture'})};
 vm.createContext(ctx);const src=fs.readFileSync('web/agentlink.js','utf8');
 vm.runInContext(src.slice(src.indexOf('const PAGE_TOOLS ='),src.indexOf('// The Run button'))+'\nthis.tools=PAGE_TOOLS;',ctx);
 const panel={};await ctx.tools.read_canvas({},panel);
 await assert.rejects(ctx.tools.edit_canvas({changes:{'1.steps':30}},panel),/connected/);
 assert.equal(widget.value,20,'linked input must not be reported as edited');
 console.log('linked canvas input regression passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
