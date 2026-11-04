# In-place editing and character memory implementation plan

> For agentic workers: use subagent-driven-development; user explicitly assigns one GPT-6.1 Sol implementer, parent bug review, then GPT-6.1 Terra release.

Goal: incrementally edit the open workflow and remember local character LoRA settings.
Architecture: page-owned transactional graph editing with graph identity/revision checks; server-owned atomic character records with installed-model lookup; model tools coordinate both.
Tech stack: existing Python/aiohttp and browser JavaScript/LiteGraph; no runtime dependencies.
Spec: ../specs/2026-11-04-inplace-character-memory.md

## Global constraints
Preserve unrelated workflow state. No automatic generation for edit-only requests. Personal memory lives outside package. Do not touch API credentials, live user graphs, or install/publish before parent review. User-assigned implementer performs all tasks sequentially, no child agents.

## Review focus
1. Workflow switch or manual edit while model thinks: fail stale edits without side effects.
2. Mid-patch failure: whole patch rollback and no misleading success.
3. Multiple versions/same LoRA basename: exact paths and explicit disambiguation.
4. Corrupt/missing record files, process restart and malicious paths: recover safely without silent loss or arbitrary file access.
5. Incomplete graphs, dynamic/custom nodes and unsupported subgraphs: either work correctly or return a clear unsupported-target error.

### Task 1: Transactional page graph tools
Files: create focused web/canvas_edit.js (or equivalent), modify web/agentlink.js and agentlink/tools.py, add tests/test_canvas_edit.cjs.
- [ ] Write and run failing behavioral tests for add/connect/disconnect/remove, widget changes, undo, stale target, rollback and incomplete graph reads.
- [ ] Implement module with readable graph state, identity/revision token, transactional patch and bounded undo. Tool names patch_canvas and undo_canvas; native LiteGraph factories and graph/node mutation APIs. Record exact API schemas in README/report.
- [ ] Wire page tools and return actionable error/result payloads. Preserve edit_canvas compatibility and isolation.
- [ ] Run focused Node tests plus existing frontend regressions; commit.

### Task 2: Persistent local character records
Files: create agentlink/characters.py, tests/test_characters.py; modify agentlink/tools.py, server.py, client.py and __init__.py only where wiring requires.
- [ ] Write failing tests for persistence/restart, aliases, multi-version ambiguity, exact LoRA identities, zero strengths, malformed input, corrupt storage and path traversal.
- [ ] Implement atomic CharacterStore with validated records, installed LoRA search and bounded sidecar lookup if available. Provide list/search/read/save/update tools; exact public signatures may follow existing tool conventions and must be recorded.
- [ ] Wire store under user/agentlink/characters.json; ensure defaults in test fixtures remain usable and do not write real user state.
- [ ] Run focused Python tests; commit.

### Task 3: Agent behavior, integration and docs
Files: agentlink/agent.py, affected test_agent.py/test_server.py, README.md, build.py if new assets require.
- [ ] Add tests for tools available in the proper chat/MCP scope and saved records surviving a fresh instance.
- [ ] Instruct agent to reread and incrementally patch current graph; edit-only vs generation; character lookup first, query for missing triggers, save provided answers, reuse exact selected LoRA and avoid duplicate prompt tags.
- [ ] Document usage examples and limits in Chinese/English, including local-only character discovery and normal load/open behavior.
- [ ] Run full pytest and all JS test files; verify ZIP includes new modules. Self-review and commit.
- [ ] Write implementation report with red/green evidence and limitations. Return to parent for independent review. Do not install or publish.

## Pre-flight decisions
Tasks share tools.py and agent.py interfaces: execute sequentially in one implementer to avoid conflicts. Character application consumes Task 1's named-socket patch operations; metadata does not invent compatibility. Native subgraph support is not guaranteed: reject unsupported targets explicitly instead of rewriting them. Publish credentials/approval are already authorized by user, but publisher must verify remote head and exclude personal files.
