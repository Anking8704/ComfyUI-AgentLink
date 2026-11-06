import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { createCanvasEditor } from "./canvas_edit.js";
import { qrSvg } from "./qr.js";

const PRESETS = [
  { id: "deepseek", label: "DeepSeek", format: "openai", base_url: "https://api.deepseek.com", vision: false },
  { id: "qwen", label: "通义千问", format: "openai", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", vision: false },
  { id: "kimi", label: "Kimi", format: "openai", base_url: "https://api.moonshot.cn/v1", vision: false },
  { id: "glm", label: "智谱 GLM", format: "openai", base_url: "https://open.bigmodel.cn/api/paas/v4", vision: false },
  { id: "openrouter", label: "OpenRouter", format: "openai", base_url: "https://openrouter.ai/api/v1", vision: true },
  { id: "openai", label: "OpenAI", format: "openai", base_url: "https://api.openai.com/v1", vision: true },
  { id: "anthropic", label: "Claude", format: "anthropic", base_url: "https://api.anthropic.com", vision: true },
  { id: "ollama", label: "Ollama", format: "openai", base_url: "http://127.0.0.1:11434/v1", vision: false },
];

const TEXT = {
  zh: {
    newChat: "新对话", settings: "设置", close: "关闭", send: "发送", stop: "停止", noModel: "未设置模型",
    needSettings: "电脑上还没设置 AI 模型，请先在电脑的 AgentLink 设置里填写", notPairedApi: "这台设备还没和电脑配对，先打开 AI 助手完成配对", stillBusyApi: "AI 还在处理上一条消息",
    placeholder: "想画什么？例如：海边的猫，夕阳，竖图", hint: "Enter 发送 · Shift+Enter 换行",
    welcome: "我会用你画布上的工作流出图", welcomeSub: "改提示词、调参数、点运行，都交给我。先在画布打开一个工作流。",
    suggestions: ["用当前工作流画一只海边的猫", "把提示词换成夜晚的城市，出 2 张", "当前工作流用的是哪个模型？", "我有哪些 LoRA？"],
    attach: "添加参考图（也可粘贴或拖进来）", removeImage: "移除这张图", dropHere: "松开即可添加参考图", uploading: "上传中…",
    tooMany: "最多 4 张参考图", notImage: "只能添加 PNG、JPG 或 WebP 图片", uploadFailed: "参考图上传失败：",
    canvas: "画布", canvasEmpty: "画布是空的", nodes: "{n} 个节点",
    working: "处理中", doneSteps: "完成 {n} 步", failedSteps: "{n} 步，有错误",
    queued: "排队中", running: "生成中", finished: "完成", failed: "失败", stoppedGen: "已中断",
    openFull: "打开原图", download: "下载",
    stopped: "已停止", opened: "已在画布打开 {name}", restored: "已恢复上次的对话",
    provider: "服务商", format: "接口格式", openai: "OpenAI 兼容", anthropic: "Anthropic",
    baseUrl: "API 地址", apiKey: "API Key", keySaved: "已保存 {hint}，留空不修改", keyNone: "本地模型可留空",
    model: "模型名", modelHint: "例如 deepseek-chat", show: "显示", hide: "隐藏",
    vision: "模型能看图", visionNote: "能看图时，它会检查出图结果再决定要不要改",
    nsfw: "允许成人内容", nsfwNote: "只写成年角色；服务商是否照做由对方决定",
    save: "保存", test: "保存并测试", saved: "已保存", testing: "测试中…", ok: "连接成功", failedTest: "失败：",
    keyNote: "Key 只保存在这台电脑上，不会发给网页，也不会写进工作流。",
    phoneTitle: "手机访问", phoneOn: "允许同一 Wi-Fi 下的手机使用", phoneOnNote: "手机第一次打开要输入配对码；Key 不会发到手机上",
    pairCode: "配对码", codeValid: "{m} 分钟内有效，只能用一次", newCode: "换一个配对码", revoke: "让所有手机下线",
    devices: "已配对 {n} 台手机", openOnPhone: "在手机浏览器打开：", noAddress: "没找到这台电脑的局域网地址",
    scanToPair: "用手机相机扫码：自动配对并打开 AgentLink（安卓可选用 ComfyMobile 打开）", hintSendMobile: "点右侧按钮发送", reconnecting: "连接中断，正在重新连接…（电脑上的任务仍在继续）",
    stillAnswering: "电脑上这段对话的上一条回复还在进行，继续显示它的进展；完成后再发送新消息。", lostReply: "连不上电脑，没能继续显示这条回复。回复可能已在电脑上完成，可稍后刷新页面查看。",
    pairTitle: "连接电脑上的 AgentLink", pairSub: "在电脑上打开 AgentLink 设置 → 手机访问，输入那里显示的 6 位配对码。",
    pairButton: "连接", pairFailed: "配对失败：", lanOff: "电脑上还没打开手机访问。在电脑的 AgentLink 设置里打开「手机访问」后再刷新这个页面。",
    phoneSettings: "模型和 Key 只能在电脑上修改。", currentModel: "当前模型",
    mcpTitle: "给外部 agent 用（MCP）", copy: "复制", copied: "已复制",
    remote: "AgentLink 只能在运行 ComfyUI 的这台电脑上使用。请用 http://127.0.0.1:{port} 打开 ComfyUI。",
    steps: {
      read_canvas: "读取画布", edit_canvas: "修改参数", patch_canvas: "原地编辑", undo_canvas: "撤销修改", run_canvas: "提交生成",
      comfy_status: "查看状态", list_models: "查找模型", search_nodes: "搜索节点", get_node_schema: "查看节点选项",
      list_workflows: "查看工作流", read_workflow: "读取工作流", run_workflow: "运行工作流", get_job: "等待结果",
      get_image: "查看图片", upload_image: "上传图片", cancel_job: "取消任务", validate_workflow: "检查工作流",
      save_workflow: "保存工作流", free_memory: "释放内存", show_in_canvas: "在画布打开", describe_image: "反推标签",
    },
  },
  en: {
    newChat: "New chat", settings: "Settings", close: "Close", send: "Send", stop: "Stop", noModel: "No model set",
    needSettings: "No AI model is set yet; set one in AgentLink settings on the computer", notPairedApi: "This device is not paired with the computer yet; open the AI assistant to pair", stillBusyApi: "The AI is still working on the previous message",
    placeholder: "What should I make? e.g. a cat on a beach at sunset", hint: "Enter to send · Shift+Enter for a new line",
    welcome: "I generate with the workflow on your canvas", welcomeSub: "Prompts, parameters, Run — leave them to me. Open a workflow first.",
    suggestions: ["Draw a cat on a beach with the current workflow", "Switch the prompt to a city at night, make 2", "Which model does this workflow use?", "Which LoRAs do I have?"],
    attach: "Add reference images (or paste or drop them)", removeImage: "Remove this image", dropHere: "Drop to add reference images", uploading: "Uploading…",
    tooMany: "Up to 4 reference images", notImage: "Only PNG, JPG or WebP images", uploadFailed: "Reference image upload failed: ",
    canvas: "Canvas", canvasEmpty: "Canvas is empty", nodes: "{n} nodes",
    working: "Working", doneSteps: "{n} steps done", failedSteps: "{n} steps, with errors",
    queued: "Queued", running: "Generating", finished: "Done", failed: "Failed", stoppedGen: "Interrupted",
    openFull: "Open original", download: "Download",
    stopped: "Stopped", opened: "Opened {name} on the canvas", restored: "Restored your last chat",
    provider: "Provider", format: "API format", openai: "OpenAI-compatible", anthropic: "Anthropic",
    baseUrl: "API URL", apiKey: "API key", keySaved: "Saved {hint}; leave empty to keep", keyNone: "Can be empty for local models",
    model: "Model", modelHint: "e.g. gpt-4.1", show: "Show", hide: "Hide",
    vision: "Model can see images", visionNote: "Lets it check results before deciding what to change",
    nsfw: "Allow adult content", nsfwNote: "Adult characters only; whether the provider complies is up to them",
    save: "Save", test: "Save & test", saved: "Saved", testing: "Testing…", ok: "Connected", failedTest: "Failed: ",
    keyNote: "The key stays on this computer. It is never sent to the page or written into workflows.",
    phoneTitle: "Phone access", phoneOn: "Let phones on the same Wi-Fi use AgentLink", phoneOnNote: "A phone enters a pairing code once; the key never reaches it",
    pairCode: "Pairing code", codeValid: "Valid for {m} min, works once", newCode: "New pairing code", revoke: "Sign out all phones",
    devices: "{n} phone(s) paired", openOnPhone: "Open on the phone:", noAddress: "No network address found for this computer",
    scanToPair: "Scan with the phone camera: pairs and opens AgentLink (Android can open it in ComfyMobile)", hintSendMobile: "Tap the button to send", reconnecting: "Connection lost, reconnecting… (the computer keeps working)",
    stillAnswering: "The computer is still answering an earlier message in this chat; following it. Send again when it finishes.", lostReply: "Could not reach the computer to follow this reply. It may have finished there; reload later to check.",
    pairTitle: "Connect to AgentLink on your computer", pairSub: "On the computer, open AgentLink settings → Phone access and enter the 6-digit code shown there.",
    pairButton: "Connect", pairFailed: "Pairing failed: ", lanOff: "Phone access is off. Turn it on in AgentLink settings on the computer, then reload this page.",
    phoneSettings: "The model and key can only be changed on the computer.", currentModel: "Model",
    mcpTitle: "For outside agents (MCP)", copy: "Copy", copied: "Copied",
    remote: "AgentLink only works on the computer running ComfyUI. Open ComfyUI at http://127.0.0.1:{port}.",
    steps: {
      read_canvas: "Read canvas", edit_canvas: "Change parameters", patch_canvas: "Edit graph", undo_canvas: "Undo edit", run_canvas: "Queue generation",
      comfy_status: "Check status", list_models: "Find models", search_nodes: "Search nodes", get_node_schema: "Read node options",
      list_workflows: "List workflows", read_workflow: "Read workflow", run_workflow: "Run workflow", get_job: "Wait for result",
      get_image: "Look at image", upload_image: "Upload image", cancel_job: "Cancel job", validate_workflow: "Check workflow",
      save_workflow: "Save workflow", free_memory: "Free memory", show_in_canvas: "Open on canvas", describe_image: "Tag image",
    },
  },
};

const ICONS = {
  spark: "M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  send: "M12 19V5M5 12l7-7 7 7",
  stop: "M7 7h10v10H7z",
  check: "M5 12l5 5L20 7",
  x: "M6 6l12 12M18 6L6 18",
  chevron: "M9 6l6 6-6 6",
  layers: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5",
  external: "M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  clip: "M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7L10 17.7a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9",
  alert: "M12 8v5M12 16.5v.5M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
};

const CSS = `
.al{--al-bg:var(--comfy-menu-bg,#1d1d20);--al-sf:var(--comfy-input-bg,#26262b);--al-bd:var(--border-color,#36363d);--al-fg:var(--fg-color,#e6e6e6);
--al-mute:var(--descrip-text,#9a9aa3);--al-ac:var(--p-primary-color,#6d7cff);--al-ok:#3ecf8e;--al-bad:#f2555a;
position:relative;display:flex;flex-direction:column;height:100%;background:var(--al-bg);color:var(--al-fg);font-size:13px;line-height:1.55}
.al *{box-sizing:border-box}
.al svg{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.al button{font:inherit;color:inherit;cursor:pointer}
.al :focus-visible{outline:2px solid var(--al-ac);outline-offset:2px}
.al-head{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--al-bd)}
.al-logo{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;background:linear-gradient(135deg,var(--al-ac),#b16cff);color:#fff}
.al-title{font-weight:600;font-size:14px}
.al-badge{min-width:0;flex:1;display:flex;justify-content:flex-start}
.al-badge button{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:1px solid var(--al-bd);background:var(--al-sf);border-radius:999px;padding:2px 10px;font-size:12px;color:var(--al-mute)}
.al-badge button.al-warn{color:#f5b04c;border-color:#f5b04c55}
.al-icon{display:grid;place-items:center;width:32px;height:32px;border-radius:8px;border:0;background:transparent;color:var(--al-mute)}
.al-icon:hover{background:var(--al-sf);color:var(--al-fg)}
.al-feed{flex:1;overflow-y:auto;padding:14px 12px 8px;display:flex;flex-direction:column;gap:10px;scroll-behavior:smooth}
.al-feed>*{flex-shrink:0}
.al-welcome{margin:auto 0;padding:8px 4px;display:flex;flex-direction:column;gap:12px}
.al-welcome h3{margin:0;font-size:15px;font-weight:600}.al-welcome p{margin:0;color:var(--al-mute)}
.al-chips{display:flex;flex-direction:column;gap:6px}
.al-chip{text-align:left;border:1px solid var(--al-bd);background:var(--al-sf);border-radius:10px;padding:8px 10px;transition:border-color .15s,transform .15s}
.al-chip:hover{border-color:var(--al-ac);transform:translateY(-1px)}
.al-user{align-self:flex-end;max-width:88%;background:var(--al-ac);color:#fff;padding:8px 12px;border-radius:14px 14px 4px 14px;white-space:pre-wrap;word-break:break-word}
.al-text{align-self:stretch;word-break:break-word}
.al-text p{margin:0 0 6px}.al-text p:last-child{margin:0}.al-text ul,.al-text ol{margin:4px 0;padding-left:20px}
.al-text code{background:var(--al-sf);padding:1px 5px;border-radius:5px;font-size:12px}
.al-text pre{background:var(--al-sf);padding:8px;border-radius:8px;overflow-x:auto;font-size:12px;margin:6px 0}
.al-card{border:1px solid var(--al-bd);border-radius:12px;background:var(--al-sf);overflow:hidden}
.al-card-h{display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;border:0;background:transparent;text-align:left;color:var(--al-mute);font-size:12px}
.al-card-h .al-chev{transition:transform .15s;margin-left:auto}.al-open>.al-card-h .al-chev{transform:rotate(90deg)}
.al-steps{display:none;padding:2px 10px 8px}.al-open>.al-steps{display:block}
.al-step{display:flex;gap:8px;align-items:flex-start;padding:4px 0}
.al-step-i{margin-top:2px;color:var(--al-mute)}.al-step-ok .al-step-i{color:var(--al-ok)}.al-step-bad .al-step-i{color:var(--al-bad)}
.al-step-main{min-width:0;flex:1}.al-step-l{font-size:12px}.al-step-d{font-size:12px;color:var(--al-mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.al-step-bad .al-step-d{color:var(--al-bad);white-space:normal}
.al-step pre{display:none;margin:4px 0 0;padding:6px;border-radius:6px;background:var(--al-bg);font-size:11px;white-space:pre-wrap;word-break:break-all;max-height:180px;overflow:auto}
.al-step.al-x pre{display:block}.al-step-main{cursor:pointer}
.al-spin{animation:al-spin .9s linear infinite}@keyframes al-spin{to{transform:rotate(360deg)}}
.al-gen{padding:10px;display:flex;flex-direction:column;gap:8px}
.al-gen-top{display:flex;justify-content:space-between;font-size:12px;color:var(--al-mute)}
.al-bar{height:4px;border-radius:4px;background:var(--al-bd);overflow:hidden}.al-bar i{display:block;height:100%;width:0;background:var(--al-ac);transition:width .2s}
.al-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px}
.al-grid img,.al-preview{width:100%;border-radius:8px;display:block;cursor:zoom-in;background:var(--al-bg)}
.al-preview{opacity:.85;cursor:default}
.al-err{display:flex;gap:8px;color:var(--al-bad);border:1px solid #f2555a55;background:#f2555a14;border-radius:10px;padding:8px 10px;word-break:break-word}
.al-note{align-self:center;font-size:12px;color:var(--al-mute)}
.al-compose{padding:8px 12px 12px}
.al-box{border:1px solid var(--al-bd);border-radius:14px;background:var(--al-sf);padding:8px;transition:border-color .15s}
.al-box:focus-within{border-color:var(--al-ac)}
.al-atts{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}.al-atts:empty{display:none}
.al-att{position:relative;width:56px;height:56px;border-radius:8px;overflow:hidden;border:1px solid var(--al-bd);background:var(--al-bg)}
.al-att img{width:100%;height:100%;object-fit:cover;display:block}
.al-att.al-pending img{opacity:.45}
.al-att button{position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;border:0;display:grid;place-items:center;background:#000a;color:#fff;padding:0}
.al-att button svg{width:12px;height:12px}
.al-user-imgs{display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end;margin-bottom:4px}
.al-user-imgs img{width:72px;height:72px;object-fit:cover;border-radius:8px;cursor:zoom-in;display:block}
.al-drop::after{content:attr(data-drop);position:absolute;inset:6px;border:2px dashed var(--al-ac);border-radius:12px;display:grid;place-items:center;
background:color-mix(in srgb,var(--al-bg) 85%,transparent);color:var(--al-fg);font-size:14px;pointer-events:none;z-index:5}
.al-ctx{display:inline-flex;align-items:center;gap:6px;max-width:100%;font-size:12px;color:var(--al-mute);padding:2px 8px;border-radius:999px;background:var(--al-bg);margin-bottom:6px}
.al-ctx span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.al-box textarea:focus-visible{outline:none}
.al-box textarea{width:100%;border:0;outline:0;resize:none;background:transparent;color:var(--al-fg);font:inherit;min-height:22px;max-height:180px;padding:2px 4px}
.al-row{display:flex;align-items:center;gap:8px}
.al-hint{flex:1;font-size:11px;color:var(--al-mute)}
.al-send{display:grid;place-items:center;width:32px;height:32px;border-radius:50%;border:0;background:var(--al-ac);color:#fff}
.al-send:disabled{opacity:.4;cursor:default}.al-send.al-busy{background:var(--al-fg);color:var(--al-bg)}
.al-sheet{position:absolute;inset:0;background:var(--al-bg);display:flex;flex-direction:column;transform:translateX(100%);visibility:hidden;transition:transform .2s ease,visibility .2s}
.al-sheet.al-in{transform:none;visibility:visible}
.al-sheet-body{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:14px}
.al-sec{display:flex;flex-direction:column;gap:8px}.al-sec>b{font-size:12px;color:var(--al-mute);font-weight:600}
.al-presets{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
.al-preset{border:1px solid var(--al-bd);background:var(--al-sf);border-radius:8px;padding:6px 4px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.al-preset.al-on{border-color:var(--al-ac);color:var(--al-ac)}
.al-field{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--al-mute)}
.al-input{display:flex;align-items:center;border:1px solid var(--al-bd);background:var(--al-sf);border-radius:8px}
.al-input:focus-within{border-color:var(--al-ac)}
.al-input input,.al-input select{flex:1;min-width:0;border:0;outline:0;background:transparent;color:var(--al-fg);font:inherit;font-size:13px;padding:7px 9px}
.al-input select option{background:var(--al-bg)}
.al-input .al-icon{width:30px;height:30px}
.al-switch{display:flex;gap:10px;align-items:flex-start;cursor:pointer}
.al-switch input{appearance:none;flex:none;width:34px;height:20px;border-radius:999px;background:var(--al-bd);position:relative;margin:2px 0 0;cursor:pointer;transition:background .15s}
.al-switch input::after{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;transition:transform .15s}
.al-switch input:checked{background:var(--al-ac)}.al-switch input:checked::after{transform:translateX(14px)}
.al-switch small{display:block;color:var(--al-mute);font-size:12px}
.al-btn{border:1px solid var(--al-bd);background:var(--al-sf);border-radius:8px;padding:7px 14px}
.al-btn.al-pri{background:var(--al-ac);border-color:transparent;color:#fff}
.al-status{font-size:12px;color:var(--al-mute);min-height:18px}.al-status.al-good{color:var(--al-ok)}.al-status.al-bad{color:var(--al-bad)}
.al-small{font-size:12px;color:var(--al-mute)}
.al-snip{display:flex;gap:6px;align-items:flex-start}.al-snip code{flex:1;font-size:11px;white-space:pre-wrap;word-break:break-all;background:var(--al-sf);border:1px solid var(--al-bd);padding:6px 8px;border-radius:8px}
.al-light{position:fixed;inset:0;z-index:10000;background:#000c;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:24px}
.al-light img{max-width:100%;max-height:calc(100% - 60px);border-radius:8px}
.al-light .al-row{gap:8px}.al-light .al-btn{display:inline-flex;gap:6px;align-items:center;color:#fff;background:#ffffff1a;border-color:#ffffff33}
.al-float{position:fixed;z-index:1000;min-width:320px;min-height:380px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);resize:both;overflow:hidden;
border-radius:14px;border:1px solid var(--border-color,#36363d);background:var(--comfy-menu-bg,#1d1d20);box-shadow:0 18px 50px rgba(0,0,0,.45),0 2px 8px rgba(0,0,0,.3)}
.al-float[hidden]{display:none}
.al-float>.al{height:100%}
.al-drag{cursor:move;user-select:none;touch-action:none}.al-drag button{cursor:pointer}
.al-launch{position:fixed;z-index:1000;right:24px;bottom:96px;width:48px;height:48px;border-radius:50%;border:0;display:grid;place-items:center;cursor:pointer;color:#fff;
background:linear-gradient(135deg,var(--p-primary-color,#6d7cff),#b16cff);box-shadow:0 8px 24px rgba(0,0,0,.4);transition:transform .15s,box-shadow .15s}
.al-launch:hover{transform:scale(1.06)}.al-launch:focus-visible{outline:2px solid #fff;outline-offset:3px}
.al-launch.al-on{box-shadow:0 0 0 3px var(--comfy-menu-bg,#1d1d20),0 0 0 5px var(--p-primary-color,#6d7cff)}
.al-launch svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
@media (prefers-reduced-motion:reduce){.al-launch{transition:none}}
.al-qr{display:flex;flex-direction:column;gap:6px}.al-qr-img svg{width:176px;height:176px;border-radius:6px;display:block}
.al-code-big{font-size:30px;font-weight:700;letter-spacing:8px;font-variant-numeric:tabular-nums;color:var(--al-fg)}
.al-pair{margin:auto 0;display:flex;flex-direction:column;gap:12px}.al-pair h3{margin:0;font-size:15px}.al-pair p{margin:0;color:var(--al-mute)}
.al-pair input{font-size:24px;letter-spacing:8px;text-align:center;font-variant-numeric:tabular-nums}
/* Phones: the window fills the screen, controls are finger-sized, and nothing drags. */
@media (max-width:640px){
.al-float{left:0!important;top:var(--al-vt,0px)!important;width:100vw!important;height:100vh!important;height:var(--al-vh,100dvh)!important;max-width:none;max-height:none;border-radius:0;border:0;resize:none}
.al-float:not([hidden])~.al-launch{display:none}
.al-head{padding-top:max(10px,env(safe-area-inset-top))}
.al-compose{padding-bottom:max(12px,env(safe-area-inset-bottom))}
.al-drag{cursor:default}
.al-icon{width:42px;height:42px}.al-send{width:42px;height:42px}
.al-box textarea,.al-input input,.al-input select{font-size:16px}
.al-chip{padding:12px}
.al-launch{right:16px;bottom:calc(88px + env(safe-area-inset-bottom));width:56px;height:56px}
.al-presets{grid-template-columns:repeat(3,1fr)}
.al-grid{grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}
}
@media (prefers-reduced-motion:reduce){.al *{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
`;

const STORE_KEY = "agentlink.chat.v2";

const t = (() => {
  let lang;
  return (key, vars = {}) => {
    if (!lang) {
      const locale = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "en";
      lang = String(locale).toLowerCase().startsWith("zh") ? "zh" : "en";
    }
    let value = key.split(".").reduce((o, k) => o?.[k], TEXT[lang]) ?? key;
    if (typeof value === "string") for (const [k, v] of Object.entries(vars)) value = value.replace(`{${k}}`, v);
    return value;
  };
})();

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function icon(name, cls = "") {
  return el("span", { html: `<svg viewBox="0 0 24 24" aria-hidden="true" class="${cls}"><path d="${ICONS[name]}"/></svg>`, style: "display:contents" });
}

function spinner() {
  return el("span", { html: '<svg viewBox="0 0 24 24" aria-hidden="true" class="al-spin"><path d="M12 3a9 9 0 1 0 9 9"/></svg>', style: "display:contents" });
}

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

// crypto.randomUUID only exists on https and localhost pages; a phone opens ComfyUI over plain http.
function newId() {
  return [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Enough Markdown for chat replies: code blocks, inline code, bold, lists, paragraphs.
function markdown(source) {
  const blocks = String(source).split(/```[^\n]*\n?/);
  return blocks.map((block, i) => {
    if (i % 2) return `<pre>${escapeHtml(block.replace(/\n$/, ""))}</pre>`;
    const inline = (s) => escapeHtml(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    const html = [];
    let list = null;
    for (const line of block.split("\n")) {
      const item = line.match(/^\s*(?:[-*]|(\d+)\.)\s+(.*)$/);
      if (item) {
        const tag = item[1] ? "ol" : "ul";
        if (list !== tag) { if (list) html.push(`</${list}>`); html.push(`<${tag}>`); list = tag; }
        html.push(`<li>${inline(item[2])}</li>`);
        continue;
      }
      if (list) { html.push(`</${list}>`); list = null; }
      if (line.trim()) html.push(`<p>${inline(line)}</p>`);
    }
    if (list) html.push(`</${list}>`);
    return html.join("");
  }).join("");
}

// Downscale before sending: the model needs no more than this, and the request stays small.
async function shrink(file, side, quality) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, side / Math.max(bitmap.width, bitmap.height));
  const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvas.toDataURL("image/jpeg", quality);
}

async function asJpegFile(file) {
  const url = await shrink(file, 2048, 0.92);
  const blob = await (await fetch(url)).blob();
  return new File([blob], (file.name || "photo").replace(/\.[^.]*$/, "") + ".jpg", { type: "image/jpeg" });
}

// The original goes into ComfyUI's input folder so a LoadImage node can use it.
async function uploadToComfy(file) {
  const form = new FormData();
  form.append("image", file, file.name || "reference.png");
  form.append("type", "input");
  const response = await api.fetchApi("/upload/image", { method: "POST", body: form });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const result = await response.json();
  return result.subfolder ? `${result.subfolder}/${result.name}` : result.name;
}

function viewUrl(image) {
  return api.apiURL(`/view?${new URLSearchParams({ filename: image.filename, subfolder: image.subfolder || "", type: image.type || "output" })}`);
}

function currentGraph() {
  return app.graph ?? app.rootGraph;
}

function canvasSummary() {
  const graph = currentGraph();
  const nodes = graph?._nodes ?? graph?.nodes ?? [];
  const name = app.extensionManager?.workflow?.activeWorkflow?.filename || document.title.replace(/^\*?\s*|\s*-\s*ComfyUI$/g, "") || "untitled";
  return { name, nodes: nodes.length, types: [...new Set(nodes.map((n) => n.type))] };
}

function nodeById(id) {
  const graph = currentGraph();
  return graph?.getNodeById?.(Number(id)) ?? graph?.getNodeById?.(id);
}

const canvasEditor = createCanvasEditor({
  getGraph: currentGraph,
  getWorkflow: () => app.extensionManager?.workflow?.activeWorkflow,
  createNode: type => (globalThis.LiteGraph ?? globalThis.__COMFY_LITEGRAPH_INSTANCE__)?.createNode(type),
  isValidConnection: (a, b) => {
    const litegraph = globalThis.LiteGraph ?? globalThis.__COMFY_LITEGRAPH_INSTANCE__;
    return litegraph?.isValidConnection?.(a, b) ?? (a === b || a === "*" || b === "*");
  },
  onChanged: () => app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.(),
  canvas: () => app.canvas,
});

// Tools the agent calls through this page, because only the page holds the workflow the user has open.
const PAGE_TOOLS = {
  async read_canvas(_args, panel) {
    const result = canvasEditor.read();
    if (panel) panel.canvasTarget = result.target;
    return { ...result, workflow: canvasSummary().name };
  },

  async patch_canvas(args, panel) {
    const result = canvasEditor.patch(args);
    if (panel) panel.canvasTarget = result.target;
    return result;
  },

  async undo_canvas(args, panel) {
    const result = canvasEditor.undo(args);
    if (panel) panel.canvasTarget = result.target;
    return result;
  },

  async edit_canvas({ changes, target }, panel) {
    if (!changes || typeof changes !== "object" || Array.isArray(changes)) throw new Error('changes must map "node_id.input" to a value');
    const operations = Object.entries(changes).map(([key, value]) => {
      const dot = key.indexOf(".");
      if (dot < 1) throw new Error(`Invalid widget key ${key}; use node_id.widget`);
      return {op: "set_widget", node: key.slice(0, dot), widget: key.slice(dot + 1), value};
    });
    const result = canvasEditor.patch({target: target ?? panel?.canvasTarget, operations});
    if (panel) panel.canvasTarget = result.target;
    return { ...result, applied: Object.entries(changes).map(([key, to]) => ({key, to})), errors: [] };
  },

  async run_canvas({ count = 1, target } = {}, panel) {
    if (!Number.isInteger(count) || count < 1 || count > 8) throw new Error('count must be an integer from 1 to 8');
    const session = panel?.session, epoch = panel?.pageEpoch ?? 0;
    const active = () => !panel || (panel.session === session && (panel.pageEpoch ?? 0) === epoch && !panel.stopped);
    const check = () => {
      if (!active()) throw new Error('Generation cancelled: the chat was stopped or replaced');
      canvasEditor.assertCurrent(target);
    };
    target = target ?? panel?.canvasTarget ?? canvasEditor.read().target;
    const ids = [];
    for (let i = 0; i < count; i++) {
      check();
      const prompt = await app.graphToPrompt();
      check();
      let result;
      try {
        result = await api.queuePrompt(0, prompt);
      } catch (e) {
        const body = e?.response ?? {};
        const nodes = Object.entries(body.node_errors ?? {}).flatMap(([id, n]) =>
          (n.errors ?? []).map((x) => `${id} (${n.class_type}): ${x.message} ${x.details ?? ""}`.trim()));
        throw new Error([body.error?.message ?? e?.message ?? String(e), ...nodes].join("\n"));
      }
      ids.push(result.prompt_id);
      // The queue request may already have reached ComfyUI when stop/new-chat was pressed.
      if (!active()) {
        fetch(`/api/jobs/${encodeURIComponent(result.prompt_id)}/cancel`, { method: 'POST' }).catch(() => {});
        throw new Error(`Generation cancelled: cancellation requested for queued job ${result.prompt_id}`);
      }
      panel?.trackGeneration(result.prompt_id);
      try { check(); }
      catch (e) { throw new Error(`Job ${result.prompt_id} was queued. Remaining batch stopped: ${e.message}`); }
      applySeedControls();
      target = canvasEditor.read().target;
      if (panel) panel.canvasTarget = target;
    }
    return { prompt_ids: ids };
  },
};

// The Run button changes seeds after queueing according to each control_after_generate widget; do the same.
function applySeedControls() {
  for (const node of currentGraph()?._nodes ?? []) {
    const widgets = node.widgets ?? [];
    widgets.forEach((control, i) => {
      if (control.name !== "control_after_generate" || i === 0) return;
      const target = widgets[i - 1];
      const min = target.options?.min ?? 0, max = Math.min(target.options?.max ?? 2 ** 50, 2 ** 50);
      if (control.value === "randomize") target.value = min + Math.floor(Math.random() * (max - min));
      else if (control.value === "increment") target.value = Math.min(max, target.value + 1);
      else if (control.value === "decrement") target.value = Math.max(min, target.value - 1);
      else return;
      target.callback?.(target.value, app.canvas, node);
    });
  }
}

class AgentLinkPanel {
  constructor() {
    this.session = newId();
    this.busy = false;
    this.items = [];
    this.steps = new Map();
    this.generations = new Map();
    this.shownImages = new Set();
    this.root = el("div", { class: "al" });
    this.root.append(this.buildHeader(), this.buildFeed(), this.buildComposer(), this.buildSheet());
    this.lastSeq = 0;
    this.turnOpen = false;
    this.listenToComfy();
    this.restore();
    this.ready = this.init();
    // A phone that slept or switched apps comes back to a reply that kept running on the computer.
    document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && this.resume());
    window.addEventListener("online", () => this.resume());
    setInterval(() => this.root.isConnected && this.updateContext(), 2000);
  }

  async init() {
    this.info = await request("/agentlink/info").catch(() => ({ local: false }));
    if (!this.info.local && !this.info.paired) {
      this.showPairing();
      return;
    }
    this.input.disabled = this.sendButton.disabled = false;
    this.config = await request("/agentlink/config");
    this.updateBadge();
    if (this.turnOpen) this.resume();
    if (this.info.local && (!this.config.base_url || !this.config.model)) this.openSettings();
  }

  showPairing() {
    this.input.disabled = this.sendButton.disabled = true;
    if (!this.info.lan) {
      this.feed.replaceChildren(el("div", { class: "al-err" }, icon("alert"), t("lanOff")));
      return;
    }
    const code = el("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", placeholder: "000000", "aria-label": t("pairCode") });
    const status = el("div", { class: "al-status", role: "status" });
    const submit = async () => {
      try {
        await request("/agentlink/pair", { code: code.value.trim() });
        this.showWelcome();
        await this.init();
      } catch (e) {
        status.textContent = t("pairFailed") + e.message;
        status.className = "al-status al-bad";
      }
    };
    code.addEventListener("keydown", (e) => e.key === "Enter" && submit());
    this.feed.replaceChildren(el("div", { class: "al-pair" }, el("h3", {}, t("pairTitle")), el("p", {}, t("pairSub")),
      el("div", { class: "al-input" }, code), el("button", { class: "al-btn al-pri", onclick: submit }, t("pairButton")), status));
    code.focus();
  }

  buildHeader() {
    this.badge = el("button", { onclick: () => this.openSettings(), title: t("settings") });
    return el("div", { class: "al-head al-drag" },
      el("div", { class: "al-logo" }, icon("spark")),
      el("span", { class: "al-title" }, "AgentLink"),
      el("div", { class: "al-badge" }, this.badge),
      el("button", { class: "al-icon", onclick: () => this.newChat(), title: t("newChat"), "aria-label": t("newChat") }, icon("plus")),
      el("button", { class: "al-icon", onclick: () => this.openSettings(), title: t("settings"), "aria-label": t("settings") }, icon("gear")),
      el("button", { class: "al-icon", onclick: () => this.onClose?.(), title: `${t("close")} (Alt+A)`, "aria-label": t("close") }, icon("minus")));
  }

  updateBadge() {
    const model = this.config?.model;
    this.badge.textContent = model || t("noModel");
    this.badge.classList.toggle("al-warn", !model);
  }

  buildFeed() {
    this.feed = el("div", { class: "al-feed", role: "log", "aria-live": "polite" });
    this.showWelcome();
    return this.feed;
  }

  showWelcome() {
    this.feed.replaceChildren(el("div", { class: "al-welcome" },
      el("h3", {}, t("welcome")), el("p", {}, t("welcomeSub")),
      el("div", { class: "al-chips" }, t("suggestions").map((s) => el("button", { class: "al-chip", onclick: () => { this.input.value = s; this.send(); } }, s)))));
  }

  buildComposer() {
    this.ctx = el("div", { class: "al-ctx" });
    this.attachments = [];
    this.attRow = el("div", { class: "al-atts" });
    this.filePicker = el("input", { type: "file", accept: "image/*", multiple: true, hidden: true,
      onchange: () => { this.addImages([...this.filePicker.files]); this.filePicker.value = ""; } });
    this.input = el("textarea", { rows: 1, placeholder: t("placeholder"), "aria-label": t("placeholder"), enterkeyhint: "send",
      oninput: () => this.autosize(),
      onpaste: (e) => {
        const files = [...(e.clipboardData?.files ?? [])].filter((f) => f.type.startsWith("image/"));
        if (files.length) { e.preventDefault(); this.addImages(files); }
      },
      onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.busy ? null : this.send(); } } });
    this.sendButton = el("button", { class: "al-send", onclick: () => (this.busy ? this.stop() : this.send()), "aria-label": t("send"), title: t("send") }, icon("send"));
    this.updateContext();
    this.acceptDrops();
    const attach = el("button", { class: "al-icon", onclick: () => this.filePicker.click(), title: t("attach"), "aria-label": t("attach") }, icon("clip"));
    return el("div", { class: "al-compose" }, el("div", { class: "al-box" }, this.ctx, this.attRow, this.input, this.filePicker,
      el("div", { class: "al-row" }, attach, el("span", { class: "al-hint" }, matchMedia("(pointer:coarse)").matches ? t("hintSendMobile") : t("hint")), this.sendButton)));
  }

  acceptDrops() {
    // Handled here so ComfyUI does not treat a dropped picture as a workflow to load.
    let depth = 0;
    const hasFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes("Files");
    this.root.dataset.drop = t("dropHere");
    this.root.addEventListener("dragenter", (e) => { if (hasFiles(e)) { e.preventDefault(); depth++; this.root.classList.add("al-drop"); } });
    this.root.addEventListener("dragover", (e) => { if (hasFiles(e)) { e.preventDefault(); e.stopPropagation(); } });
    this.root.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; this.root.classList.remove("al-drop"); } });
    this.root.addEventListener("drop", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      depth = 0;
      this.root.classList.remove("al-drop");
      this.addImages([...e.dataTransfer.files]);
    });
  }

  async addImages(files) {
    for (const file of files) {
      if (!file.type.startsWith("image/")) { this.push({ k: "error", text: t("notImage") }); continue; }
      if (this.attachments.length >= 4) { this.push({ k: "error", text: t("tooMany") }); break; }
      const attachment = { pending: true };
      this.attachments.push(attachment);
      this.renderAttachments();
      try {
        const original = ["image/png", "image/jpeg", "image/webp"].includes(file.type) ? file : await asJpegFile(file);
        const [forModel, thumb, name] = await Promise.all([shrink(original, 1280, 0.9), shrink(original, 160, 0.8), uploadToComfy(original)]);
        Object.assign(attachment, { pending: false, data: forModel.split(",")[1], mime: "image/jpeg", thumb, name });
      } catch (e) {
        this.attachments.splice(this.attachments.indexOf(attachment), 1);
        this.push({ k: "error", text: t("uploadFailed") + (e?.message ?? e) });
      }
      this.renderAttachments();
    }
  }

  renderAttachments() {
    this.attRow.replaceChildren(...this.attachments.map((a) => el("div", { class: `al-att${a.pending ? " al-pending" : ""}`, title: a.name ?? t("uploading") },
      a.thumb ? el("img", { src: a.thumb, alt: a.name ?? "" }) : spinner(),
      el("button", { onclick: () => { this.attachments.splice(this.attachments.indexOf(a), 1); this.renderAttachments(); }, "aria-label": t("removeImage"), title: t("removeImage") }, icon("x")))));
  }

  autosize() {
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight, 180)}px`;
  }

  updateContext() {
    const c = canvasSummary();
    const label = c.nodes ? `${t("canvas")}：${c.name} · ${t("nodes", { n: c.nodes })}` : t("canvasEmpty");
    if (this.ctx.dataset.label !== label) {
      this.ctx.dataset.label = label;
      this.ctx.replaceChildren(icon("layers"), el("span", {}, label));
    }
  }

  // ---------- transcript ----------

  persist() {
    try {
      const items = this.items.slice(-80).map(({ node, bar, preview, ...rest }) => rest);
      localStorage.setItem(STORE_KEY, JSON.stringify({ session: this.session, items, lastSeq: this.lastSeq, turnOpen: this.turnOpen }));
    } catch { /* storage full or blocked: the chat still works */ }
  }

  restore() {
    let saved;
    try { saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch { saved = null; }
    if (!saved?.items?.length) return;
    this.session = saved.session;
    this.lastSeq = saved.lastSeq ?? 0;
    this.turnOpen = !!saved.turnOpen;
    this.feed.replaceChildren();
    for (const item of saved.items) {
      if (item.k === "gen" && !["finished", "failed", "stoppedGen"].includes(item.status)) item.status = "stoppedGen";
      if (item.k === "steps") item.steps.forEach((s) => { if (s.status === "run") s.status = "bad"; });
      this.push(item, false);
    }
    this.push({ k: "note", text: t("restored") }, false);
  }

  push(item, save = true) {
    this.feed.querySelector(".al-welcome")?.remove();
    this.items.push(item);
    item.node = this.render(item);
    this.feed.append(item.node);
    if (item.k === "gen") this.generations.set(item.id, item);
    this.scroll();
    if (save) this.persist();
    return item;
  }

  update(item) {
    const node = this.render(item);
    item.node.replaceWith(node);
    item.node = node;
    this.persist();
  }

  scroll() {
    const nearBottom = this.feed.scrollHeight - this.feed.scrollTop - this.feed.clientHeight < 160;
    if (nearBottom || this.busy) this.feed.scrollTop = this.feed.scrollHeight;
  }

  render(item) {
    switch (item.k) {
      case "user": return el("div", { style: "align-self:flex-end;max-width:88%" },
        item.images?.length ? el("div", { class: "al-user-imgs" }, item.images.map((src) => el("img", { src, alt: "", onclick: () => this.lightbox(src) }))) : null,
        item.text ? el("div", { class: "al-user", style: "max-width:none" }, item.text) : null);
      case "text": return el("div", { class: "al-text", html: markdown(item.text) });
      case "error": return el("div", { class: "al-err", role: "alert" }, icon("alert"), el("span", {}, item.text));
      case "note": return el("div", { class: "al-note" }, item.text);
      case "steps": return this.renderSteps(item);
      case "gen": return this.renderGeneration(item);
      case "images": return el("div", { class: "al-grid" }, item.images.map((src) => this.thumb(src)));
      default: return el("div");
    }
  }

  renderSteps(item) {
    const running = item.steps.some((s) => s.status === "run");
    const bad = item.steps.some((s) => s.status === "bad");
    const title = running ? t("working") : t(bad ? "failedSteps" : "doneSteps", { n: item.steps.length });
    const card = el("div", { class: `al-card${item.open || running ? " al-open" : ""}` },
      el("button", { class: "al-card-h", "aria-expanded": String(!!(item.open || running)), onclick: () => { item.open = !card.classList.contains("al-open"); this.update(item); } },
        running ? spinner() : icon(bad ? "alert" : "check"), el("span", {}, title), icon("chevron", "al-chev")),
      el("div", { class: "al-steps" }, item.steps.map((s) => {
        const row = el("div", { class: `al-step${s.status === "ok" ? " al-step-ok" : s.status === "bad" ? " al-step-bad" : ""}` },
          el("span", { class: "al-step-i" }, s.status === "run" ? spinner() : icon(s.status === "bad" ? "x" : "check")),
          el("div", { class: "al-step-main", onclick: () => row.classList.toggle("al-x") },
            el("div", { class: "al-step-l" }, t(`steps.${s.name}`) === `steps.${s.name}` ? s.name : t(`steps.${s.name}`)),
            s.detail ? el("div", { class: "al-step-d" }, s.detail) : null,
            s.body ? el("pre", {}, s.body) : null));
        return row;
      })));
    return card;
  }

  renderGeneration(item) {
    const pct = item.max ? Math.round((item.value / item.max) * 100) : 0;
    const live = item.status === "queued" || item.status === "running";
    item.bar = el("i", { style: `width:${item.status === "finished" ? 100 : pct}%` });
    item.preview = el("img", { class: "al-preview", alt: "", hidden: !item.previewUrl || !live, src: item.previewUrl || undefined });
    return el("div", { class: "al-card al-gen" },
      el("div", { class: "al-gen-top" }, el("span", { class: "al-row" }, live ? spinner() : icon(item.status === "finished" ? "check" : "alert"), t(item.status)),
        el("span", { class: "al-count" }, live && item.max ? `${item.value}/${item.max}` : "")),
      live ? el("div", { class: "al-bar" }, item.bar) : null,
      live ? item.preview : null,
      item.error ? el("div", { class: "al-small", style: "color:var(--al-bad)" }, item.error) : null,
      item.images.length ? el("div", { class: "al-grid" }, item.images.map((src) => this.thumb(src))) : null);
  }

  thumb(src) {
    return el("img", { src, alt: "", loading: "lazy", onclick: () => this.lightbox(src) });
  }

  lightbox(src) {
    const close = () => { box.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => e.key === "Escape" && close();
    const box = el("div", { class: "al-light", onclick: (e) => e.target === box && close() },
      el("img", { src, alt: "" }),
      el("div", { class: "al-row" },
        el("a", { class: "al-btn", href: src, target: "_blank", rel: "noopener" }, icon("external"), t("openFull")),
        el("a", { class: "al-btn", href: src, download: "" }, icon("download"), t("download")),
        el("button", { class: "al-btn", onclick: close }, icon("x"), t("close"))));
    document.addEventListener("keydown", onKey);
    document.body.append(box);
  }

  // ---------- generation progress from ComfyUI's own events ----------

  trackGeneration(promptId) {
    if (promptId && !this.generations.has(promptId)) this.push({ k: "gen", id: promptId, status: "queued", value: 0, max: 0, images: [] });
  }

  listenToComfy() {
    const gen = (detail) => this.generations.get(detail?.prompt_id);
    api.addEventListener("execution_start", ({ detail }) => {
      this.runningPrompt = detail?.prompt_id;
      const item = gen(detail);
      if (item) { item.status = "running"; this.update(item); }
    });
    api.addEventListener("progress", ({ detail }) => {
      const item = gen(detail) ?? this.generations.get(this.runningPrompt);
      if (!item || item.status === "finished") return;
      if (item.status === "queued") { item.status = "running"; this.update(item); }
      item.value = detail.value; item.max = detail.max;
      if (item.bar) item.bar.style.width = `${Math.round((detail.value / detail.max) * 100)}%`;
      const counter = item.node?.querySelector(".al-count");
      if (counter) counter.textContent = `${detail.value}/${detail.max}`;
    });
    api.addEventListener("b_preview", ({ detail }) => {
      const item = this.generations.get(this.runningPrompt);
      if (!item?.preview || !(detail instanceof Blob)) return;
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      item.previewUrl = URL.createObjectURL(detail);
      item.preview.src = item.previewUrl;
      item.preview.hidden = false;
    });
    api.addEventListener("executed", ({ detail }) => {
      const item = gen(detail);
      const images = detail?.output?.images ?? [];
      if (!item || !images.length) return;
      for (const image of images) {
        const url = viewUrl(image);
        item.images.push(url);
        this.shownImages.add(`${image.filename}|${image.subfolder || ""}`);
      }
      this.update(item);
    });
    api.addEventListener("execution_success", ({ detail }) => this.finishGeneration(detail, "finished"));
    api.addEventListener("execution_error", ({ detail }) => this.finishGeneration(detail, "failed", `${detail?.node_type ?? ""}: ${detail?.exception_message ?? ""}`));
    api.addEventListener("execution_interrupted", ({ detail }) => this.finishGeneration(detail, "stoppedGen"));
  }

  finishGeneration(detail, status, error) {
    const item = this.generations.get(detail?.prompt_id);
    if (!item) return;
    item.status = status;
    if (error) item.error = error;
    if (item.previewUrl) { URL.revokeObjectURL(item.previewUrl); item.previewUrl = null; }
    this.update(item);
  }

  // ---------- settings ----------

  buildSheet() {
    this.sheetBody = el("div", { class: "al-sheet-body" });
    this.sheet = el("div", { class: "al-sheet", "aria-hidden": "true" },
      el("div", { class: "al-head" }, el("span", { class: "al-title", style: "flex:1" }, t("settings")),
        el("button", { class: "al-icon", onclick: () => this.closeSettings(), "aria-label": t("close"), title: t("close") }, icon("x"))),
      this.sheetBody);
    this.sheet.addEventListener("keydown", (e) => e.key === "Escape" && this.closeSettings());
    return this.sheet;
  }

  openSettings() {
    this.renderSettings();
    this.renderPhone();
    this.sheet.classList.add("al-in");
    this.sheet.setAttribute("aria-hidden", "false");
    this.sheet.querySelector("input,select,button")?.focus();
  }

  closeSettings() {
    this.sheet.classList.remove("al-in");
    this.sheet.setAttribute("aria-hidden", "true");
    this.input.focus();
  }

  renderSettings() {
    const c = this.config || {};
    if (!this.info?.local) {
      this.sheetBody.replaceChildren(el("div", { class: "al-sec" }, el("b", {}, t("currentModel")),
        el("div", {}, c.model || t("noModel")), el("div", { class: "al-small" }, t("phoneSettings"))));
      return;
    }
    const field = (label, control, extra) => el("label", { class: "al-field" }, label, el("div", { class: "al-input" }, control, extra));
    const format = el("select", {}, el("option", { value: "openai" }, t("openai")), el("option", { value: "anthropic" }, t("anthropic")));
    format.value = c.format || "openai";
    const baseUrl = el("input", { type: "text", value: c.base_url || "", placeholder: "https://…", spellcheck: "false" });
    const key = el("input", { type: "password", autocomplete: "off", placeholder: c.has_key ? t("keySaved", { hint: c.key_hint }) : t("keyNone") });
    const reveal = el("button", { type: "button", class: "al-icon", title: t("show"), "aria-label": t("show"),
      onclick: () => { key.type = key.type === "password" ? "text" : "password"; } }, icon("eye"));
    const model = el("input", { type: "text", value: c.model || "", placeholder: t("modelHint"), spellcheck: "false" });
    const vision = el("input", { type: "checkbox" });
    vision.checked = c.vision !== false;
    const nsfw = el("input", { type: "checkbox" });
    nsfw.checked = c.nsfw === true;
    const status = el("div", { class: "al-status", role: "status" });
    const presetButtons = PRESETS.map((p) => el("button", { type: "button", class: `al-preset${c.base_url === p.base_url ? " al-on" : ""}`, title: p.base_url,
      onclick: () => {
        format.value = p.format; baseUrl.value = p.base_url; vision.checked = p.vision;
        presetButtons.forEach((b) => b.classList.toggle("al-on", b === presetButtons[PRESETS.indexOf(p)]));
        model.focus();
      } }, p.label));
    const save = async () => {
      this.config = await request("/agentlink/config", { format: format.value, base_url: baseUrl.value, model: model.value, vision: vision.checked, nsfw: nsfw.checked, api_key: key.value });
      key.value = "";
      key.placeholder = this.config.has_key ? t("keySaved", { hint: this.config.key_hint }) : t("keyNone");
      this.updateBadge();
    };
    const setStatus = (text, kind = "") => { status.textContent = text; status.className = `al-status${kind ? ` al-${kind}` : ""}`; };
    const saveButton = el("button", { class: "al-btn", onclick: async () => {
      try { await save(); setStatus(t("saved"), "good"); } catch (e) { setStatus(t("failedTest") + e.message, "bad"); }
    } }, t("save"));
    const testButton = el("button", { class: "al-btn al-pri", onclick: async () => {
      setStatus(t("testing"));
      try {
        await save();
        const r = await request("/agentlink/test", {});
        r.ok ? setStatus(`${t("ok")} · ${r.reply}`, "good") : setStatus(t("failedTest") + r.error, "bad");
      } catch (e) { setStatus(t("failedTest") + e.message, "bad"); }
    } }, t("test"));
    const sw = (input, label, note) => el("label", { class: "al-switch" }, input, el("span", {}, label, el("small", {}, note)));

    const mcpUrl = `${location.protocol}//127.0.0.1:${location.port || (location.protocol === "https:" ? 443 : 80)}${this.info?.mcp_path || "/agentlink/mcp"}`;
    const snippets = [
      ["Claude Code", `claude mcp add --transport http comfyui ${mcpUrl}`],
      ["Codex (config.toml)", `[mcp_servers.comfyui]\nurl = "${mcpUrl}"`],
      ["Cursor / JSON", JSON.stringify({ mcpServers: { comfyui: { url: mcpUrl } } }, null, 2)],
    ];
    this.sheetBody.replaceChildren(
      el("div", { class: "al-sec" }, el("b", {}, t("provider")), el("div", { class: "al-presets" }, presetButtons)),
      el("div", { class: "al-sec" },
        field(t("format"), format), field(t("baseUrl"), baseUrl), field(t("apiKey"), key, reveal), field(t("model"), model)),
      el("div", { class: "al-sec" }, sw(vision, t("vision"), t("visionNote")), sw(nsfw, t("nsfw"), t("nsfwNote"))),
      el("div", { class: "al-sec" }, el("div", { class: "al-row" }, testButton, saveButton), status, el("div", { class: "al-small" }, t("keyNote"))),
      this.phoneBox = el("div", { class: "al-sec" }, el("b", {}, t("phoneTitle"))),
      el("details", { class: "al-sec" }, el("summary", { class: "al-small", style: "cursor:pointer" }, t("mcpTitle")),
        ...snippets.map(([name, text]) => el("div", { class: "al-sec", style: "margin-top:8px;gap:4px" }, el("div", { class: "al-small" }, name),
          el("div", { class: "al-snip" }, el("code", {}, text),
            el("button", { class: "al-icon", title: t("copy"), "aria-label": `${t("copy")} ${name}`, onclick: async (e) => {
              await navigator.clipboard?.writeText(text);
              e.currentTarget.title = t("copied");
            } }, icon("copy")))))));
  }

  async renderPhone(view) {
    const box = this.phoneBox;
    if (!box) return;
    try { view ??= await request("/agentlink/lan"); } catch { return; }
    const change = async (body) => this.renderPhone(await request("/agentlink/lan", body));
    const toggle = el("input", { type: "checkbox", onchange: () => change({ enabled: toggle.checked }) });
    toggle.checked = view.enabled;
    const parts = [el("b", {}, t("phoneTitle")),
      el("label", { class: "al-switch" }, toggle, el("span", {}, t("phoneOn"), el("small", {}, t("phoneOnNote"))))];
    if (view.enabled) {
      const port = location.port ? `:${location.port}` : "";
      parts.push(
        view.code ? el("div", {}, el("div", { class: "al-small" }, t("pairCode")), el("div", { class: "al-code-big" }, view.code),
          el("div", { class: "al-small" }, t("codeValid", { m: Math.max(1, Math.ceil(view.expires_in / 60)) }))) : null,
        view.code && view.addresses.length ? this.pairQr(view, port) : null,
        el("div", { class: "al-small" }, view.addresses.length ? t("openOnPhone") : t("noAddress")),
        ...view.addresses.map((ip) => el("div", { class: "al-snip" }, el("code", {}, `${location.protocol}//${ip}${port}`))),
        el("div", { class: "al-small" }, t("devices", { n: view.devices })),
        el("div", { class: "al-row", style: "flex-wrap:wrap" },
          el("button", { class: "al-btn", onclick: () => change({ new_code: true }) }, t("newCode")),
          view.devices ? el("button", { class: "al-btn", onclick: () => change({ revoke: true }) }, t("revoke")) : null));
    }
    box.replaceChildren(...parts.filter(Boolean));
  }

  /** A QR code of the pairing link, so a phone pairs by pointing its camera at the screen instead of typing. */
  pairQr(view, port) {
    // Prefer a typical home-network address; VPN and WSL adapters often use other ranges.
    const address = view.addresses.find((a) => /^(192\.168\.|10\.)/.test(a)) ?? view.addresses[0];
    const link = `${location.protocol}//${address}${port}/agentlink/pair?code=${view.code}&next=${encodeURIComponent("/?agentlink=open")}`;
    let svg;
    try { svg = qrSvg(link, 4); } catch { return null; }
    return el("div", { class: "al-qr" }, el("div", { class: "al-small" }, t("scanToPair")), el("div", { class: "al-qr-img", html: svg }),
      el("div", { class: "al-snip" }, el("code", {}, link)));
  }

  // ---------- chat ----------

  setBusy(busy) {
    this.busy = busy;
    globalThis.dispatchEvent?.(new CustomEvent("agentlink:busy", { detail: { busy, session: this.session } }));
    this.sendButton.classList.toggle("al-busy", busy);
    this.sendButton.replaceChildren(icon(busy ? "stop" : "send"));
    this.sendButton.setAttribute("aria-label", busy ? t("stop") : t("send"));
    this.sendButton.title = busy ? t("stop") : t("send");
  }

  async newChat() {
    const previousSession = this.session;
    this.session = newId();
    this.pageEpoch = (this.pageEpoch ?? 0) + 1;
    this.stopped = false;
    this.canvasTarget = null;
    this.lastSeq = 0;
    this.turnOpen = false;
    this.resumeController?.abort();
    this.controller?.abort();
    this.controller = null;
    this.setBusy(false);
    request("/agentlink/reset", { session: previousSession }).catch(() => {});
    this.items = [];
    this.steps.clear();
    this.generations.clear();
    this.showWelcome();
    this.persist();
  }

  async stop() {
    this.pageEpoch = (this.pageEpoch ?? 0) + 1;
    this.stopped = true;
    // Stopping the chat also stops the images it queued; the user pressed stop to stop all of it.
    for (const item of this.generations.values()) {
      if (item.status === "queued" || item.status === "running") fetch(`/api/jobs/${item.id}/cancel`, { method: "POST" }).catch(() => {});
    }
    await request("/agentlink/stop", { session: this.session }).catch(() => {});
  }

  async send() {
    const text = this.input.value.trim();
    const ready = this.attachments.filter((a) => !a.pending);
    if ((!text && !ready.length) || this.busy || this.attachments.some((a) => a.pending)) return;
    if (!this.config?.base_url || !this.config?.model) { this.openSettings(); return; }
    this.input.value = "";
    this.autosize();
    const images = ready.map(({ data, mime, name }) => ({ data, mime, name }));
    this.push({ k: "user", text, images: ready.map((a) => a.thumb) });
    this.attachments = [];
    this.renderAttachments();
    this.setBusy(true);
    this.stopped = false;
    const session = this.session;
    const controller = new AbortController();
    this.controller = controller;
    // A new turn starts at seq 0; saved now, so a reload before its first event does not skip any of it.
    this.lastSeq = 0;
    this.turnOpen = true;
    this.persist();
    let started = false;
    try {
      const response = await fetch("/agentlink/chat", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ session, text, images, canvas: canvasSummary() }) });
      if (response.status === 409) {
        // The computer is still answering an earlier message of this chat (sent before a dropped connection): follow it.
        started = true;
        this.push({ k: "note", text: t("stillAnswering") });
        this.lastSeq = 0;
        return;
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      started = true;
      await this.consume(response, session);
    } catch (e) {
      // Once the turn has started on the computer, a dropped connection is resumed rather than reported.
      if (session === this.session && !started) {
        this.turnOpen = false;
        if (e.name !== "AbortError") this.push({ k: "error", text: e.message });
      }
    } finally {
      if (session === this.session) {
        this.controller = null;
        if (this.turnOpen) this.resume(started ? 1000 : 0);
        else { this.setBusy(false); this.closeOpenSteps(); this.persist(); }
      }
    }
  }

  /** Reads a chat event stream; returns when it ends. Seq numbers let a later reattach continue where this stopped. */
  async consume(response, session) {
    this.attached = true;
    try {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (session !== this.session) { await reader.cancel(); return; }
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (!chunk.startsWith("data: ")) continue;
          const event = JSON.parse(chunk.slice(6));
          if (event.seq) {
            if (event.seq <= this.lastSeq) continue; // already shown (and, for page tools, already run)
            this.lastSeq = event.seq;
          }
          if (event.type === "done") this.turnOpen = false;
          this.handle(event, session);
          if (event.type === "done") this.persist();
        }
      }
    } finally {
      this.attached = false;
    }
  }

  /** Reattaches to a reply that is still running on the computer (after sleep, app switch, network loss or reload). */
  async resume(delay = 0) {
    // One stream at a time: a second one would show every event twice and could run a canvas action twice.
    if (!this.turnOpen || this.resuming || this.attached) return;
    this.resuming = true;
    const session = this.session;
    const controller = new AbortController();
    this.resumeController = controller;
    this.setBusy(true);
    const placeholder = this.input.placeholder;
    if (delay) this.input.placeholder = t("reconnecting");
    let gaveUp = false;
    try {
      let attempt = 0;
      for (let wait = delay; this.turnOpen && session === this.session; attempt++, wait = Math.min(10000, (wait || 1000) * 2)) {
        if (attempt >= 40) { gaveUp = true; break; }
        if (wait) await new Promise((r) => setTimeout(r, wait));
        if (session !== this.session || controller.signal.aborted || document.visibilityState === "hidden") break;
        try {
          const response = await fetch("/agentlink/events", { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
            body: JSON.stringify({ session, after: this.lastSeq }) });
          // An older AgentLink on the computer cannot resume; the reply cannot be followed any further.
          if ([403, 404, 405].includes(response.status)) { this.turnOpen = false; gaveUp = true; break; }
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          if (!(response.headers.get("Content-Type") || "").startsWith("text/event-stream")) { this.turnOpen = false; break; }
          await this.consume(response, session);
        } catch (e) {
          if (e?.name === "AbortError") break;
          /* still offline: try again shortly */
        }
      }
    } finally {
      this.resuming = false;
      if (this.resumeController === controller) this.resumeController = null;
      this.input.placeholder = placeholder;
      if (session === this.session && gaveUp) {
        this.turnOpen = false;
        this.push({ k: "note", text: t("lostReply") });
      }
      if (session === this.session && !this.turnOpen) { this.setBusy(false); this.closeOpenSteps(); this.persist(); }
    }
  }

  closeOpenSteps() {
    const last = this.items[this.items.length - 1];
    if (last?.k === "steps" && !last.steps.some((s) => s.status === "run") && last.open) { last.open = false; this.update(last); }
  }

  stepGroup() {
    const last = this.items[this.items.length - 1];
    return last?.k === "steps" ? last : this.push({ k: "steps", steps: [], open: false });
  }

  async answerPage(event, session) {
    let reply;
    try {
      if (session !== this.session || this.stopped) throw new Error('Page operation cancelled: the chat was stopped or replaced');
      reply = { result: await PAGE_TOOLS[event.name](event.arguments ?? {}, this) };
    } catch (e) {
      reply = { error: e?.message ?? String(e) };
    }
    await request("/agentlink/page_result", { session, id: event.id, ...reply }).catch(() => {});
  }

  handle(event, session = this.session) {
    if (session !== this.session) return;
    // Apps embedding this page (such as ComfyMobile) follow the chat without its window; images stay here.
    const { image, workflow, ...shared } = event;
    globalThis.dispatchEvent?.(new CustomEvent("agentlink:event", { detail: { ...shared, session } }));
    if (this.stopped && event.type === 'open_workflow') return;
    if (event.type === "text") {
      this.push({ k: "text", text: event.text });
    } else if (event.type === "tool_call") {
      const group = this.stepGroup();
      const step = { id: event.id, name: event.name, status: "run", detail: describeCall(event), body: JSON.stringify(event.arguments, null, 2)?.slice(0, 1500) };
      group.steps.push(step);
      this.steps.set(event.id, { group, step });
      this.update(group);
      // A replayed call that this page already answered before the connection dropped must not run twice.
      if (PAGE_TOOLS[event.name] && !event.answered) this.answerPage(event, session);
    } else if (event.type === "tool_result") {
      const entry = this.steps.get(event.id);
      if (entry) {
        entry.step.status = event.is_error ? "bad" : "ok";
        entry.step.detail = describeResult(event) ?? entry.step.detail;
        if (event.text) entry.step.body = `${entry.step.body ?? ""}\n\n${event.text}`.trim();
        this.update(entry.group);
      }
      if (event.image && event.view) {
        const params = new URL(event.view, location.href).searchParams;
        const key = `${params.get("filename")}|${params.get("subfolder") || ""}`;
        if (!this.shownImages.has(key)) {
          this.shownImages.add(key);
          this.push({ k: "images", images: [api.apiURL(event.view)] });
        }
      }
    } else if (event.type === "open_workflow") {
      app.loadGraphData(event.workflow, true, true, event.name.replace(/\.json$/, ""));
      this.push({ k: "note", text: t("opened", { name: event.name }) });
    } else if (event.type === "error") {
      this.push({ k: "error", text: event.message });
    } else if (event.type === "done" && event.stopped) {
      this.push({ k: "note", text: t("stopped") });
    }
  }
}

function describeCall(event) {
  const a = event.arguments ?? {};
  if (event.name === "edit_canvas" && a.changes) return Object.keys(a.changes).join("、");
  if (event.name === "run_canvas") return a.count > 1 ? `× ${a.count}` : "";
  if (event.name === "list_models") return [a.folder, a.query].filter(Boolean).join(" · ");
  if (event.name === "search_nodes") return a.query;
  if (event.name === "get_node_schema") return a.class_type;
  if (["read_workflow", "run_workflow", "save_workflow", "show_in_canvas"].includes(event.name)) return a.name;
  return "";
}

function describeResult(event) {
  if (event.is_error) return event.text.split("\n")[0].slice(0, 200);
  try {
    const data = JSON.parse(event.text);
    if (event.name === "patch_canvas") return `${data.applied} operations`;
    if (event.name === "undo_canvas") return "↶";
    if (event.name === "read_canvas") return `${data.workflow} · ${t("nodes", { n: data.nodes.length })}`;
    if (event.name === "edit_canvas") return data.applied.map((c) => c.key).join("、") + (data.errors.length ? ` · ${data.errors.length} ✗` : "");
    if (event.name === "get_job") return data.status;
  } catch { /* text was cut or not JSON */ }
  return null;
}

const GEOMETRY_KEY = "agentlink.window.v1";

// A floating chat window over the canvas: drag it by its header, resize it from the corner, toggle it with the
// round button or Alt+A. Its place, size and open state are remembered.
class FloatingWindow {
  constructor() {
    this.win = el("div", { class: "al-float", role: "dialog", "aria-label": "AgentLink", hidden: true });
    this.launcher = el("button", { class: "al-launch", title: "AgentLink (Alt+A)", "aria-label": "AgentLink", onclick: () => this.toggle() }, icon("spark"));
    document.body.append(this.win, this.launcher);
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(GEOMETRY_KEY) || "null"); } catch { saved = null; }
    this.place(saved ?? {});
    new ResizeObserver(() => !this.win.hidden && this.save()).observe(this.win);
    // Phone browsers shrink only the visual viewport for the keyboard; follow it so the message box stays above the keys.
    const viewport = window.visualViewport;
    if (viewport) {
      const follow = () => {
        this.win.style.setProperty("--al-vh", `${Math.round(viewport.height)}px`);
        this.win.style.setProperty("--al-vt", `${Math.round(viewport.offsetTop)}px`);
      };
      viewport.addEventListener("resize", follow);
      viewport.addEventListener("scroll", follow);
      follow();
    }
    window.addEventListener("resize", () => this.place(this.geometry()));
    document.addEventListener("keydown", (e) => {
      if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.code === "KeyA") { e.preventDefault(); this.toggle(); }
    });
    if (saved?.open) this.toggle(true);
    const params = new URLSearchParams(location.search);
    if (params.get("agentlink") === "open") {
      params.delete("agentlink");
      const rest = params.toString();
      history.replaceState(null, "", location.pathname + (rest ? `?${rest}` : "") + location.hash);
      if (this.win.hidden) this.toggle(true);
    }
  }

  geometry() {
    const r = this.win.getBoundingClientRect();
    return { left: r.left, top: r.top, width: r.width, height: r.height, open: !this.win.hidden };
  }

  place({ left, top, width, height }) {
    const w = Math.min(width ?? 400, innerWidth - 16);
    const h = Math.min(height ?? Math.min(640, innerHeight - 140), innerHeight - 16);
    const x = Math.max(8, Math.min(left ?? innerWidth - w - 24, innerWidth - w - 8));
    const y = Math.max(8, Math.min(top ?? innerHeight - h - 160, innerHeight - h - 8));
    Object.assign(this.win.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
  }

  save() {
    try { localStorage.setItem(GEOMETRY_KEY, JSON.stringify(this.geometry())); } catch { /* not remembered, still works */ }
  }

  ensurePanel() {
    if (!this.panel) {
      this.panel = new AgentLinkPanel();
      this.panel.onClose = () => this.toggle(false);
      this.win.append(this.panel.root);
      for (const handle of this.panel.root.querySelectorAll(".al-drag")) handle.addEventListener("pointerdown", (e) => this.drag(e));
    }
    return this.panel;
  }

  toggle(open = this.win.hidden) {
    if (open) this.ensurePanel();
    if (!open) this.save();
    this.win.hidden = !open;
    this.launcher.classList.toggle("al-on", open);
    this.launcher.setAttribute("aria-expanded", String(open));
    if (open) {
      this.place(this.geometry());
      this.save();
      this.panel.input.focus();
    }
  }

  drag(down) {
    if (matchMedia("(max-width:640px)").matches) return;
    if (down.button !== 0 || down.target.closest("button,input,select,textarea,a")) return;
    // Capture the pointer on the handle: the canvas listens on the document and would swallow the moves.
    const handle = down.currentTarget;
    const start = this.win.getBoundingClientRect();
    const move = (e) => this.place({ left: start.left + e.clientX - down.clientX, top: start.top + e.clientY - down.clientY, width: start.width, height: start.height });
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      this.save();
    };
    handle.setPointerCapture?.(down.pointerId);
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
    down.preventDefault();
    down.stopPropagation();
  }
}

app.registerExtension({
  name: "AgentLink.Window",
  setup() {
    document.head.append(el("style", {}, CSS));
    const floating = new FloatingWindow();
    // For apps that wrap this page (ComfyMobile's simple mode): chat without opening the window. The conversation is
    // the window's own, so opening it later shows everything; events arrive as "agentlink:event" on window.
    window.AgentLink = {
      version: 1,
      async send(text) {
        const panel = floating.ensurePanel();
        await panel.ready;
        if (!panel.info?.local && !panel.info?.paired) throw new Error(t("notPairedApi"));
        if (!panel.config?.base_url || !panel.config?.model) throw new Error(t("needSettings"));
        if (panel.busy) throw new Error(t("stillBusyApi"));
        panel.input.value = String(text ?? "");
        panel.send();
        return { session: panel.session };
      },
      stop: () => floating.panel?.stop(),
      newChat: () => floating.panel?.newChat(),
      open: () => floating.toggle(true),
      state: () => ({ busy: !!floating.panel?.busy, session: floating.panel?.session ?? null, open: !floating.win.hidden }),
    };
  },
});
