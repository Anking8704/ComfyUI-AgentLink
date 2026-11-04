// Native graph edits stay on the page. No executable prompt or replacement workflow is needed.
const clone = value => JSON.parse(JSON.stringify(value));
const object = value => value && typeof value === 'object' && !Array.isArray(value);

export function createCanvasEditor({ getGraph, getWorkflow, createNode, isValidConnection, onChanged = () => {}, canvas, historyLimit = 20 }) {
  let serial = 0;
  const inspections = new Map(), histories = new Map();
  const workflowIds = new WeakMap();
  let nextWorkflow = 0;
  function context() {
    const graph = getGraph();
    if (!graph?.serialize || !graph?.configure) throw new Error('Canvas graph is unavailable');
    if (graph.isRootGraph === false || graph._subgraph_node || (graph.rootGraph && graph.rootGraph !== graph)) throw new Error('Subgraph targets are unsupported; return to the root canvas');
    const workflow = getWorkflow() ?? graph;
    if (typeof workflow === 'object' && !workflowIds.has(workflow)) workflowIds.set(workflow, ++nextWorkflow);
    const key = `${typeof workflow === 'object' ? workflowIds.get(workflow) : workflow}:${workflow.filename ?? ''}`;
    return { graph, workflow, key, state: clone(graph.serialize()) };
  }
  function fingerprint(state) { return JSON.stringify(state); }
  function inspect(c) {
    const target = `canvas-${++serial}`;
    inspections.set(target, {graph:c.graph, key:c.key, state:fingerprint(c.state)});
    while (inspections.size > 100) inspections.delete(inspections.keys().next().value);
    return target;
  }
  function checked(target) {
    const c = context(), previous = inspections.get(target);
    if (!previous || previous.graph !== c.graph || previous.key !== c.key || previous.state !== fingerprint(c.state)) throw new Error('Canvas target is stale or the workflow changed. Call read_canvas again before editing');
    return c;
  }
  function nodeMap(graph) { return new Map((graph._nodes ?? graph.nodes ?? []).map(n => [String(n.id), n])); }
  function supported(node) {
    if (node.isSubgraphNode?.() || node.subgraph || node.type === 'graph/subgraph') throw new Error('Editing subgraph nodes is unsupported');
    return node;
  }
  function slot(node, field, name) {
    if (typeof name !== 'string') throw new Error('Socket names must be strings from read_canvas/get_node_schema');
    const slots = node[field] ?? [], found = slots.map((s,i) => s.name === name ? i : -1).filter(i => i >= 0);
    if (found.length !== 1) throw new Error(`${node.type}: unknown or ambiguous ${field} socket ${name}. Available: ${slots.map(s=>s.name).join(', ')}`);
    return found[0];
  }
  function widgetValue(node, name, value, connected = false) {
    const matches = (node.widgets ?? []).filter(w => w.name === name);
    if (matches.length !== 1) throw new Error(`${node.type}: unknown or ambiguous widget ${name}`);
    if (connected) throw new Error(`${name}: this input is connected; disconnect it or change the source node`);
    const w = matches[0], options = typeof w.options?.values === 'function' ? w.options.values() : w.options?.values;
    if (Array.isArray(options) && !options.includes(value)) throw new Error(`${name}: invalid option. Use get_node_schema or list_models`);
    if (w.type === 'number' || typeof w.value === 'number') {
      if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${name}: needs a finite number`);
      if (w.options?.min != null && value < w.options.min || w.options?.max != null && value > w.options.max) throw new Error(`${name}: value is outside the widget range`);
      if ((w.type === 'INT' || w.options?.precision === 0) && !Number.isInteger(value)) throw new Error(`${name}: needs an integer`);
    } else if (typeof w.value === 'boolean' && typeof value !== 'boolean') throw new Error(`${name}: needs a boolean`);
    else if (typeof w.value === 'string' && typeof value !== 'string') throw new Error(`${name}: needs a string`);
    else if (value === undefined || value === null || typeof value === 'object') throw new Error(`${name}: unsupported widget value`);
    return w;
  }
  function read() {
    const c = context();
    const nodes = [...nodeMap(c.graph).values()].map(n => ({
      id:String(n.id), class_type:n.type, title:n.title, mode:n.mode, position:Array.from(n.pos ?? []),
      values:Object.fromEntries((n.widgets ?? []).map(w => [w.name, w.value])),
      inputs:(n.inputs ?? []).map(s => ({name:s.name, type:s.type, link:s.link ?? null})),
      outputs:(n.outputs ?? []).map(s => ({name:s.name, type:s.type})),
      connections:Object.fromEntries((n.inputs ?? []).filter(s=>s.link!=null).map(s=>{
        const l = c.graph.getLink?.(s.link) ?? c.graph.links?.get?.(s.link) ?? c.graph.links?.[s.link];
        return [s.name, l ? {node:String(l.origin_id), output:c.graph.getNodeById(l.origin_id)?.outputs?.[l.origin_slot]?.name, slot:l.origin_slot} : {link:s.link}];
      })), unsupported:!!(n.isSubgraphNode?.() || n.subgraph),
    }));
    return {workflow:c.workflow.filename ?? 'untitled', target:inspect(c), nodes};
  }
  function changed(c) {
    c.graph.setDirtyCanvas?.(true, true);
    onChanged();
    c.state = clone(c.graph.serialize());
  }
  function beginChange(graph) {
    graph.beforeChange?.();
    let ended = false;
    return () => {
      if (ended) return;
      // Mark before invoking: a throwing native hook must not be fired twice.
      ended = true;
      graph.afterChange?.();
    };
  }
  function restore(c, state, endChange) {
    try { c.graph.configure(clone(state)); }
    finally { endChange(); }
    c.graph.setDirtyCanvas?.(true, true);
    onChanged();
  }
  function patch({target, operations}) {
    const c = checked(target);
    if (!Array.isArray(operations) || !operations.length || operations.length > 100) throw new Error('operations must contain 1–100 graph operations');
    const nodes = nodeMap(c.graph), planned = [], aliases = Object.create(null);
    const sourceLinks = new Map([...nodes].map(([id,n])=>[id,new Map((n.inputs??[]).filter(s=>s.link!=null).map(s=>{
      const l=c.graph.getLink?.(s.link) ?? c.graph.links?.get?.(s.link) ?? c.graph.links?.[s.link];
      return [s.name,String(l?.origin_id)];
    }))]));
    const connected = new Map([...nodes].map(([id,n])=>[id,new Set((n.inputs??[]).filter(s=>s.link!=null).map(s=>s.name))]));
    function resolve(ref) {
      const n = nodes.get(String(ref));
      if (!n) throw new Error(`No node/reference ${ref}; read_canvas again for node ids`);
      return supported(n);
    }
    // Validate every operation first. Temporary nodes have not entered the user's graph.
    for (const op of operations) {
      if (!object(op)) throw new Error('Each operation must be an object');
      if (op.op === 'add_node') {
        if (typeof op.ref !== 'string' || !/^[A-Za-z_][\w-]{0,63}$/.test(op.ref) || nodes.has(op.ref) || Object.hasOwn(aliases, op.ref)) throw new Error(`Duplicate or invalid node reference ${op.ref}`);
        if (typeof op.class_type !== 'string') throw new Error('class_type is required');
        const n = createNode(op.class_type);
        if (!n) throw new Error(`Unknown node type ${op.class_type}; use search_nodes`);
        supported(n);
        if (op.widgets !== undefined && !object(op.widgets)) throw new Error('widgets must be an object');
        for (const [name,value] of Object.entries(op.widgets ?? {})) widgetValue(n,name,value);
        if (op.position !== undefined && (!Array.isArray(op.position) || op.position.length !== 2 || !op.position.every(Number.isFinite))) throw new Error('position must be [x, y]');
        const near = op.near !== undefined ? resolve(op.near) : [...nodes.values()].at(-1);
        n.pos = op.position ?? [Number(near?.pos?.[0] ?? 0) + Number(near?.size?.[0] ?? 160) + 60, Number(near?.pos?.[1] ?? 0) + 80];
        nodes.set(op.ref,n);connected.set(op.ref,new Set());sourceLinks.set(op.ref,new Map());aliases[op.ref]=null;
        planned.push({op,n});
      } else if (op.op === 'remove_node') {
        const n = resolve(op.node);
        for(const [id,links] of sourceLinks)for(const [input,source] of links)if(source===String(op.node)){connected.get(id)?.delete(input);links.delete(input);}
        nodes.delete(String(op.node));connected.delete(String(op.node));sourceLinks.delete(String(op.node));planned.push({op,n});
      } else if (op.op === 'set_widget') {
        const n = resolve(op.node);widgetValue(n,op.widget,op.value,connected.get(String(op.node)).has(op.widget));planned.push({op,n});
      } else if (op.op === 'connect') {
        const from = resolve(op.from), to = resolve(op.to), output = slot(from,'outputs',op.output), input = slot(to,'inputs',op.input);
        const a=from.outputs[output].type,b=to.inputs[input].type;
        if (from === to || !(isValidConnection ? isValidConnection(a,b) : a === b || a === '*' || b === '*')) throw new Error(`Incompatible socket types ${a} → ${b}`);
        connected.get(String(op.to)).add(op.input);sourceLinks.get(String(op.to)).set(op.input,String(op.from));planned.push({op,from,to,output,input});
      } else if (op.op === 'disconnect') {
        const n=resolve(op.node),input=slot(n,'inputs',op.input);
        connected.get(String(op.node)).delete(op.input);sourceLinks.get(String(op.node)).delete(op.input);planned.push({op,n,input});
      } else throw new Error(`Unknown operation ${op.op}`);
    }
    // The JS execution is synchronous: the user cannot switch tabs between this check and mutation.
    checked(target);
    const endChange = beginChange(c.graph);
    try {
      for (const p of planned) {
        const {op,n}=p;
        if (op.op === 'add_node') {
          c.graph.add(n);aliases[op.ref]=String(n.id);
          if (n.graph !== c.graph) throw new Error('Native graph rejected add_node');
          for (const [name,value] of Object.entries(op.widgets ?? {})) {
            const w=widgetValue(n,name,value);w.value=value;w.callback?.(value,typeof canvas === 'function' ? canvas() : canvas,n);
          }
        } else if (op.op === 'remove_node') c.graph.remove(n);
        else if (op.op === 'set_widget') {
          const w=widgetValue(n,op.widget,op.value,n.inputs?.some(s=>s.name===op.widget&&s.link!=null));w.value=op.value;w.callback?.(op.value,typeof canvas === 'function' ? canvas() : canvas,n);
        } else if (op.op === 'disconnect') {
          if (n.disconnectInput(slot(n,'inputs',op.input)) === false) throw new Error('Native graph rejected disconnect');
        } else if (op.op === 'connect') {
          const link=p.from.connect(slot(p.from,'outputs',op.output),p.to,slot(p.to,'inputs',op.input));
          if (!link) throw new Error('Native graph rejected connection; this custom node may require manual wiring');
        }
      }
      endChange();
      changed(c);
    } catch (error) {
      try { restore(c,c.state,endChange); }
      catch (rollback) { throw new Error(`Patch failed: ${error.message}; rollback failed: ${rollback.message}. Restore your workflow from a saved copy`); }
      throw new Error(`Patch rolled back: ${error.message}`);
    }
    // changed() has captured the resulting state; the original inspected snapshot is the undo boundary.
    const history=histories.get(c.key)??[];
    history.push({before:JSON.parse(inspections.get(target).state),after:fingerprint(c.state),graph:c.graph});
    if(history.length>historyLimit)history.shift();histories.set(c.key,history);
    return {applied:operations.length,aliases,target:inspect(c),undo_available:history.length};
  }
  function undo({target}) {
    const c=checked(target),history=histories.get(c.key),entry=history?.at(-1);
    if (!entry) throw new Error('No AgentLink edit to undo on this workflow');
    if(entry.graph!==c.graph || entry.after!==fingerprint(c.state)) throw new Error('Canvas changed after the edit (possibly manual changes); undo refused to preserve them');
    const before=clone(c.state),endChange=beginChange(c.graph);
    try {c.graph.configure(clone(entry.before));endChange();changed(c);history.pop();}
    catch(error){
      try {restore(c,before,endChange);}
      catch(rollback){throw new Error(`Undo failed: ${error.message}; rollback failed: ${rollback.message}. Restore your workflow from a saved copy`);}
      throw new Error(`Undo failed (edited state restored): ${error.message}`);
    }
    return {undone:true,target:inspect(c),undo_available:history.length};
  }
  return {read,patch,undo};
}
