# ComfyUI-AgentLink

![AgentLink 概念示意图 / Concept illustration](docs/introduction.png)

*概念示意图，非真实截图。 / Concept illustration, not an actual screenshot.*

[中文](#中文) | [English](#english)

## 中文

在 ComfyUI 里直接和 AI agent 聊天：它会查模型、搭工作流、提交生成、把结果图拿回来给你看，搭好的工作流一键载入画布。用你自己的模型 API Key。

### 安装

1. 把 `ComfyUI-AgentLink` 文件夹放进 `ComfyUI/custom_nodes/`。
2. 重启 ComfyUI。不需要安装任何额外依赖。

### 使用

1. 点画布右下角的 **AgentLink** 悬浮按钮（✨），或按 Alt+A。
2. 第一次会打开设置：在“快速填写”里选服务商，填 API Key 和模型名，点“测试连接”。
3. 直接说需求，例如：
   - 用 Anima 工作流画一只海边的猫，出 2 张
   - 帮我搭一个文生图加放大的工作流，保存成“放大流程”
   - 我有哪些 LoRA？
   - 刚才为什么失败了？

聊天中可以用回形针、粘贴或拖放添加最多 4 张 PNG、JPEG 或 WebP 参考图。内置聊天可以读取、修改并运行当前画布；连线输入不能作为普通控件值修改。

### 模型要求

- 必须支持 **工具调用**（function calling）。
- 支持 **识图** 时，agent 能看到生成结果并自己判断；不支持请在设置里取消“模型支持识图”。
- 支持 OpenAI 兼容接口（DeepSeek、通义千问、Kimi、智谱、OpenRouter、OpenAI、Ollama 等）和 Anthropic 接口（Claude）。

### 安全

- 只接受运行 ComfyUI 的这台电脑上的请求。开了局域网访问时，其他设备打不开聊天，也调用不了接口。
- API Key 保存在 `ComfyUI/user/agentlink/config.json`，不会返回给网页，也不会写进工作流。

### 给外部 agent 用（MCP）

文件和生成工具也通过 MCP 提供；读取、编辑和运行当前画布的工具仅供内置聊天使用。MCP 地址 `http://127.0.0.1:8188/agentlink/mcp`（端口以你的 ComfyUI 为准）。设置页里有 Claude Code、Codex、Cursor 的配置，点“复制”即可。

### 限制

- 内置聊天可运行当前画布。通过 MCP 按文件运行时，使用 API 格式工作流或 AgentLink 保存的工作流；普通画布工作流需先导出为 API 格式。
- 约 10% 的节点（带自定义网页控件或动态输入的）载入画布后显示可能错位，不影响运行。
- 聊天显示记录保存在浏览器本地存储中，可在刷新后恢复；模型使用的服务端对话历史只存于内存，重启 ComfyUI 后清空。
- 最近的异常响应和连线输入修复尚未使用真实模型 API 进行验证。

## English

Chat with an AI agent inside ComfyUI. It looks up your models, builds workflows, queues generations, shows you the results, and opens the workflows it builds on your canvas. Bring your own model API key.

### Install

1. Put the `ComfyUI-AgentLink` folder in `ComfyUI/custom_nodes/`.
2. Restart ComfyUI. No extra dependencies are installed.

### Use

1. Open **AgentLink** with the floating sparkles button at the bottom right, or press Alt+A.
2. On first use, pick a provider under Quick fill, enter your API key and model, and press Test connection.
3. Ask for what you want, e.g. "Build a txt2img + upscale workflow and save it as upscale", or "Draw two cats on a beach".

Attach up to four PNG, JPEG or WebP reference images with the paperclip, paste, or drag and drop. Built-in chat can read, edit, and run the current canvas; linked inputs cannot be edited as ordinary widget values.

### Model requirements

- Must support **tool calling** (function calling).
- With **vision**, the agent can look at its results; otherwise untick "Model can see images".
- Works with OpenAI-compatible APIs (OpenAI, OpenRouter, DeepSeek, Qwen, Kimi, GLM, Ollama, …) and the Anthropic API.

### Security

- Only requests from the computer running ComfyUI are accepted, even when ComfyUI listens on the LAN.
- The API key is stored in `ComfyUI/user/agentlink/config.json`; it is never sent back to the page or written into workflows.

### MCP for outside agents

File and generation tools are also available over MCP; reading, editing, and running the current canvas are available only in built-in chat. The MCP endpoint is `http://127.0.0.1:8188/agentlink/mcp` (use your ComfyUI port). The settings page has ready-to-copy configs for Claude Code, Codex and Cursor.

### Limits

- Built-in chat can run the current canvas. For file-based execution through MCP, use API-format workflows or workflows saved by AgentLink; export ordinary canvas workflows as API format first.
- About 10% of node types (those with custom web widgets or dynamic inputs) may show values in the wrong widgets on the canvas; running is unaffected.
- Displayed chat history is stored in browser local storage and can be restored after refresh. Server-side conversation history used by the model is held in memory and cleared when ComfyUI restarts.
- The latest malformed-response and linked-input fixes have not been tested against a real model API.
