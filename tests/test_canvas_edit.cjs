// Behavioral fixture mirrors LiteGraph add/remove/connect/disconnect/serialize/configure.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const types = {
 Source: {outputs:[{name:'MODEL',type:'MODEL'},{name:'CLIP',type:'CLIP'}], widgets:[]},
 Lora: {inputs:[{name:'model',type:'MODEL'},{name:'clip',type:'CLIP'}], outputs:[{name:'MODEL',type:'MODEL'},{name:'CLIP',type:'CLIP'}], widgets:[{name:'strength_model',type:'number',value:1,options:{min:-10,max:10}},{name:'lora_name',type:'combo',value:'a',options:{values:['a','b']}}]},
 Sink: {inputs:[{name:'model',type:'MODEL'},{name:'clip',type:'CLIP'}],widgets:[{name:'text',type:'text',value:'cat'}]},
};
function factory(type) {
 if(!types[type])return null;
 const n=JSON.parse(JSON.stringify({type,pos:[12,34],size:[100,60],...types[type]}));
 n.connect=function(out,target,input){
  if(target.reject)throw Error('native connection rejected');
  target.disconnectInput(input);
  const id=++this.graph.last_link_id;
  this.graph.links[id]={id,origin_id:this.id,origin_slot:out,target_id:target.id,target_slot:input,type:this.outputs[out].type};
  target.inputs[input].link=id;
  return this.graph.links[id];
 };
 n.disconnectInput=function(input){const s=this.inputs[input];if(s.link!=null)delete this.graph.links[s.link];s.link=null;return true;};
 return n;
}
class Graph {
 constructor(){this._nodes=[];this.links={};this.last_node_id=0;this.last_link_id=0;this.groups=[{title:'keep',pos:[2,3]}];}
 add(n){n.id=++this.last_node_id;n.graph=this;this._nodes.push(n);}
 remove(n){for(const l of Object.values(this.links))if(l.origin_id===n.id||l.target_id===n.id)this.getNodeById(l.target_id).disconnectInput(l.target_slot);this._nodes=this._nodes.filter(x=>x!==n);}
 getNodeById(id){return this._nodes.find(n=>String(n.id)===String(id));}
 serialize(){return JSON.parse(JSON.stringify({nodes:this._nodes.map(({graph,connect,disconnectInput,...n})=>n),links:this.links,last_node_id:this.last_node_id,last_link_id:this.last_link_id,groups:this.groups,extra:this.extra}));}
 configure(s){this._nodes=s.nodes.map(data=>Object.assign(factory(data.type),data,{graph:this}));this.links=s.links;this.last_node_id=s.last_node_id;this.last_link_id=s.last_link_id;this.groups=s.groups;this.extra=s.extra;}
 setDirtyCanvas(){}
}
(async()=>{
 const {createCanvasEditor}=await import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync('web/canvas_edit.js','utf8')).toString('base64'));
 let graph=new Graph(), workflow={filename:'a'};
 const source=factory('Source'),sink=factory('Sink');graph.add(source);graph.add(sink);source.connect(0,sink,0);
 const e=createCanvasEditor({getGraph:()=>graph,getWorkflow:()=>workflow,createNode:factory,isValidConnection:(a,b)=>a===b});
 const before=graph.serialize(), read=e.read();
 assert.equal(read.nodes.length,2,'incomplete nodes must be readable without graphToPrompt');
 assert.equal(read.nodes[1].inputs[0].name,'model');
 let r=e.patch({target:read.target,operations:[{op:'add_node',ref:'lora',class_type:'Lora',near:'1',widgets:{lora_name:'b',strength_model:0}},{op:'connect',from:'1',output:'MODEL',to:'lora',input:'model'},{op:'connect',from:'lora',output:'MODEL',to:'2',input:'model'},{op:'set_widget',node:'2',widget:'text',value:'dragon'}]});
 assert.equal(graph._nodes.length,3);assert.equal(graph.getNodeById(r.aliases.lora).widgets[0].value,0);
 assert.equal(graph.getNodeById(2).pos[0],12,'unrelated position preserved');
 assert.equal(graph.getNodeById(2).widgets[0].value,'dragon');
 assert.equal(graph.links[graph.getNodeById(2).inputs[0].link].origin_id,Number(r.aliases.lora));
 e.undo({target:r.target});assert.deepEqual(graph.serialize(),before,'one undo restores whole patch');
 const stale=e.read().target;graph.getNodeById(2).pos=[90,90];assert.throws(()=>e.patch({target:stale,operations:[{op:'remove_node',node:'1'}]}),/stale/i);
 const cross=e.read().target;workflow={filename:'b'};assert.throws(()=>e.patch({target:cross,operations:[{op:'remove_node',node:'1'}]}),/workflow|stale/i);
 const t=e.read().target, prior=graph.serialize();
 assert.throws(()=>e.patch({target:t,operations:[{op:'set_widget',node:'2',widget:'text',value:'changed'},{op:'connect',from:'1',output:'MODEL',to:'2',input:'clip'}]}),/type/i);
 assert.deepEqual(graph.serialize(),prior,'prevalidation prevents partial changes');
 graph.getNodeById(2).reject=true;
 const rollback=graph.serialize();
 let beforeHooks=0,afterHooks=0;
 graph.beforeChange=()=>{beforeHooks++;};graph.afterChange=()=>{afterHooks++;};
 assert.throws(()=>e.patch({target:e.read().target,operations:[{op:'set_widget',node:'2',widget:'text',value:'changed'},{op:'connect',from:'1',output:'CLIP',to:'2',input:'clip'}]}),/rejected/);
 assert.deepEqual(graph.serialize(),rollback,'native error rolls back whole transaction');
 assert.equal(afterHooks,beforeHooks,'rollback must close the native change notification');
 graph.afterChange=()=>{afterHooks++;throw Error('after hook failed');};
 const priorAfter=afterHooks;
 assert.throws(()=>e.patch({target:e.read().target,operations:[{op:'set_widget',node:'2',widget:'text',value:'after failure'}]}),/after hook failed/);
 assert.equal(afterHooks,priorAfter+1,'a throwing afterChange must not be called twice');
 assert.deepEqual(graph.serialize(),rollback,'throwing after hook also restores the graph');
 delete graph.beforeChange;delete graph.afterChange;
 delete graph.getNodeById(2).reject;
 graph.afterChange=function(){this.extra={hook:'updated'};};
 const hook=e.patch({target:e.read().target,operations:[{op:'set_widget',node:'2',widget:'text',value:'hook'}]});
 e.patch({target:hook.target,operations:[{op:'set_widget',node:'2',widget:'text',value:'hook2'}]});
 delete graph.afterChange;
 const p=e.patch({target:e.read().target,operations:[{op:'disconnect',node:'2',input:'model'},{op:'remove_node',node:'1'}]});assert.equal(graph._nodes.length,1);assert.equal(graph.getNodeById(2).inputs[0].link,null);
 graph.getNodeById(2).widgets[0].value='manual';assert.throws(()=>e.undo({target:e.read().target}),/manual|changed/i);
 for(const operations of [[{op:'add_node',ref:'x',class_type:'Missing'}],[{op:'add_node',ref:'2',class_type:'Lora'}],[{op:'set_widget',node:'2',widget:'text',value:42}]])assert.throws(()=>e.patch({target:e.read().target,operations}));
 const g2=new Graph(),a=factory('Source'),b=factory('Sink');g2.add(a);g2.add(b);b.inputs.push({name:'text',type:'MODEL'});a.connect(0,b,2);
 const e2=createCanvasEditor({getGraph:()=>g2,getWorkflow:()=>g2,createNode:factory});
 e2.patch({target:e2.read().target,operations:[{op:'remove_node',node:'1'},{op:'set_widget',node:'2',widget:'text',value:'after removal'}]});
 assert.equal(b.widgets[0].value,'after removal');
 const first=e2.patch({target:e2.read().target,operations:[{op:'set_widget',node:'2',widget:'text',value:'first'}]});
 b.pos=[777,888];
 const second=e2.patch({target:e2.read().target,operations:[{op:'set_widget',node:'2',widget:'text',value:'second'}]});
 const undone=e2.undo({target:second.target});
 assert.throws(()=>e2.undo({target:undone.target}),/manual|changed/,'undo must not cross a manual edit boundary');
 const g3=new Graph();g3.add(factory('Sink'));
 const e3=createCanvasEditor({getGraph:()=>g3,getWorkflow:()=>g3,createNode:factory});
 const undoTarget=e3.patch({target:e3.read().target,operations:[{op:'set_widget',node:'1',widget:'text',value:'after'}]}).target;
 const undoBefore=g3.serialize(),configure=g3.configure.bind(g3);
 let configureCount=0,undoBeforeHooks=0,undoAfterHooks=0;
 g3.beforeChange=()=>{undoBeforeHooks++;};g3.afterChange=()=>{undoAfterHooks++;};
 g3.configure=state=>{if(++configureCount===1)throw Error('native restore failed');configure(state);};
 assert.throws(()=>e3.undo({target:undoTarget}),/native restore failed/);
 assert.deepEqual(g3.serialize(),undoBefore,'failed undo restores the edited state');
 assert.equal(undoAfterHooks,undoBeforeHooks,'failed undo balances native notifications');
 const recovered=e3.undo({target:e3.read().target});assert.equal(g3.getNodeById(1).widgets[0].value,'cat','failed undo retains history for retry');
 graph.isRootGraph=false;assert.throws(()=>e.read(),/subgraph/i);
 console.log('canvas transactions: insert/wire/widgets/undo/stale/cross-tab/rollback/validation passed');
})().catch(e=>{console.error(e.message);process.exitCode=1;});

