# ADR-0057: An AI assistant, ChatGPT-style, on desktop and web

- **Status:** Accepted (2026-10-15)
- **Date:** 2026-10-14
- **Depends on:** ADR-0003 (graphs), ADR-0010 (capabilities), ADR-0021 (event log), ADR-0040/0041 (library and
  search), ADR-0046 (side panel), ADR-0047 (safeguards). Related: ADR-0056, ADR-0058.

## Context

People are used to ChatGPT. The owner wants the same feel on desktop and web, and the assistant should be able to
use the products (make an image, find an earlier creation) rather than only talk. wasifyai has chat model aliases
(`default-chat`, `prompt-enhancer`, `multimodal`) and an event contract with `token`, `node`, `interrupt`,
`job_progress`, `done`, but no conversation product. Unsloth's chat feature (history, attachments, retrieval,
tool calling, MCP, web search, sandboxed code execution, model comparison) was read from its file names and docs,
not run; its frontend uses `assistant-ui` (MIT).

## Decision

1. **The assistant is a product, `wasifyai-assistant`,** one LangGraph graph with a tool-calling loop. It is
   the **home screen** of the desktop app and a first-class page of the web app (the side panel lists
   conversations, then the products).
2. **Tools are capabilities.** The registry exposes each enabled capability as a typed tool built from its
   existing schema (`image.generate`, `image.edit`, search my creations, later document and audio tools). The
   graph never names a model or a node (rule 4). A tool call that runs a job is a normal job: queue position,
   progress and the resulting creation appear in the message as a card and land in My creations.
3. **Conversations are creations.** Tables `conversations` and `messages` (parts as JSON: text, image, tool
   call, tool result), scoped by tenant, product and user (rules 7 to 9). Title and text are indexed for
   semantic search (ADR-0041); the rule "every creation is searchable" applies. Deleting a conversation
   unindexes it.
4. **Events.** The SSE envelope and `Last-Event-ID` behaviour are unchanged. Two event types are added by this
   ADR, as the contract requires: `tool_call` (name, arguments, id) and `tool_result` (id, status, output
   reference). Streaming text uses the existing `token` event. `interrupt` is used to confirm an action that
   costs money (a cloud tool call with the user's key) or acts on files; the default is to confirm, with a
   "don't ask again for this conversation" choice.
5. **The model rule fits.** On desktop the assistant model may be a cloud alias while the single local slot is
   used by the image engine, so chat and image do not fight over memory. When both are local, the slot manager
   (ADR-0056) switches and the UI says so.
6. **Look and behaviour (ChatGPT-like):** conversation list; composer with attachments (pictures now, documents
   later) and an Enhance button (ADR-0038); streaming markdown; stop, regenerate, edit-and-resend; copy; message
   branching later; model/alias picker limited to configured aliases; tool cards with progress and thumbnails.
   Keyboard first, accessible, right-to-left and multilingual by default.
7. **UI implementation is decided in a spike:** `assistant-ui` against our own components on shadcn (ADR-0045).
   Criteria: streaming, tool cards, accessibility, bundle size, RTL, how easily it mounts in both shells.
8. **Safeguards and quotas** go through the existing switch (ADR-0047): off locally, forced on in the hosted web
   product. Usage events record tokens and tool jobs.

## Consequences

- Two new tables and one migration; a new graph and its prompt files; two event types in the contract and the
  generated TypeScript types; a shared chat module in `packages/ui`.
- The tool schema generation couples the assistant to the capability registry: a new capability appears as a
  tool only if its manifest says so (explicit allow, not automatic).
- Tool calling quality depends on the chat model. Evaluation cases (does it call the right tool, with valid
  arguments) are kept in the repository like the search corpus.

## Not in this version

Web search, code execution, MCP servers, browser agents and "deep research" (all present in Unsloth). Each needs
its own security decision first. Voice input waits for the audio vertical.
