# In-place workflow editing and character LoRA memory

Approved intent: the user explicitly asks GPT-6.1 Sol to implement the features discussed, the parent to review bugs, and GPT-6.1 Terra to synchronize and publish. No further design approval is needed for the scope below.

## User outcome
Edit the existing ComfyUI workflow over successive chat turns without opening a replacement tab. When drawing a named character, search installed LoRAs first; ask for missing trigger words, remember the answer, and reuse the correct character/LoRA settings next time.

## In-place editing
- Add/remove nodes, connect/disconnect sockets, and set widgets on the current graph using native frontend graph APIs. Preserve unrelated nodes, IDs, layout, groups, and user edits.
- Expose a focused page tool for graph patches (e.g. patch_canvas) plus undo_canvas. Keep existing edit_canvas compatibility; widget edits must also participate in undo.
- Read actual canvas state before edits, including nodes that do not currently contribute to an executable output. Empty/incomplete graphs must be inspectable while building in steps.
- Bind mutations to the workflow/graph inspected by the agent; reject stale targets if the user switched workflows or changed the graph in the meantime. Never silently mutate another tab. New turns may explicitly reread the graph to refresh the target.
- Validate all patch operations before mutation where practical. On execution failure restore the pre-patch state rather than leaving a half-applied patch. Unknown nodes, invalid socket names/types, missing nodes, invalid widget values, duplicate references, and unsupported subgraph targets must produce actionable tool errors.
- Allow temporary aliases for newly added nodes so a patch can insert and connect a LoRA in one operation. Connect actual named model/CLIP sockets, not guessed slot numbers.
- Preserve unrelated layout. Place added nodes near relevant existing nodes or in free space; do not rebuild the whole graph or call show_in_canvas to emulate edits.
- Each successful mutation is undoable as one unit; undo must not discard later manual edits unnoticed. Keep a bounded per-workflow undo history in memory.
- Model instructions: modify-only requests stop after modification and a concise summary. Run only when the user asked to generate/run. A requested new workflow can still use the existing save/open flow.
- Keep current chat isolation, progress tracking, stop behavior, and ordinary saved-workflow/MCP functions intact.

## Character LoRA memory
- Local installed LoRAs only in this release; no remote download or online account integration.
- Search character names and user-confirmed aliases plus installed LoRA filenames. Exact/alias matches should outrank broad filename matches. Report ambiguous candidates and ask which to use rather than silently selecting a model/version.
- Persist records outside plugin installation: <ComfyUI user dir>/agentlink/characters.json. Updates and restarts must preserve them; do not publish personal records or API keys.
- A character may have multiple LoRAs/versions. Record exact installed relative model path, character name, aliases, trigger words, optional appearance prompt, optional strength_model/strength_clip, known base-model compatibility, and provenance when available. Keep triggers separate from optional scene/outfit/action text.
- User can save/update via conversation and inspect/list records; after supplying missing triggers the agent saves without a second confirmation. Expose discoverable read/write tools and concise success feedback.
- Reliable user-provided/local sidecar trigger metadata may be read safely, bounded in size. Generic training tag frequency must not be presented as authoritative trigger words. No model weights are loaded to inspect metadata.
- Do not invent missing triggers or compatibility. Mark unknown and ask for relevant information. Preserve explicitly supplied prompt/strength values (including zero) and do not re-add duplicates to the prompt.
- Apply selected LoRA in-place: update an appropriate existing node, or add and wire a standard compatible LoRA loader through the new graph patch tool. If model family or wiring cannot be established, report the uncertainty instead of blindly connecting.
- Memory write endpoints/tools use existing local access boundaries, strict validation and atomic writes. Reject traversal/arbitrary file access; resolve installed models through ComfyUI model registry or its public HTTP listing, never an unchecked user path.

## Engineering and release
- Zero new runtime dependencies; Python >=3.10, existing aiohttp/Pillow, native ES modules.
- Current public repo: https://github.com/Anking8704/ComfyUI-AgentLink . Work in isolated clone feature branch. Parent reviews before installation/publishing.
- Tests must exercise actual behavior and failures, not source string assertions. Python temporary directories and isolated HTTP fixtures; JS graph mocks faithful to native API plus real installed frontend verification where available. Do not alter the user's active workflow or API configuration to test.
- Document supported/unsupported graph cases honestly. Update Chinese/English README; new JS modules must be included in build ZIP. Version bump is handled by the publisher after review.
- Existing adult-content policy is outside scope; do not alter it or weaken safeguards.
