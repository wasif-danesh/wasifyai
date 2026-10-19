# ADR-0082: The chat UI is built on assistant-ui (and streamdown), not on our own components

- **Status:** Accepted (2026-10-19, by the owner) for **assistant-ui**. **Not yet approved:** the other dependencies named in
  decision 8 (`streamdown` and its plugins, `katex`); they are asked for at the start of stage CU0.
- **Date:** 2026-10-19
- **Amends:** ADR-0057 decision 7 ("UI implementation is decided in a spike"). The spike's outcome, recorded in
  `docs/phase2-stage-d-plan.md` (D5, 2026-10-16), was "our own components, not `assistant-ui`". This ADR reverses it.
- **Depends on:** ADR-0057 (the assistant), ADR-0045 (shadcn/ui, Radix, Tailwind), ADR-0081 (the design system: tokens only),
  ADR-0062 and ADR-0061 (how Unsloth code may be reused), ADR-0066 (our speech runtime), ADR-0068 and ADR-0071 (actions,
  the assistant's action cards), ADR-0065 (notebooks), ADR-0047, ADR-0012.
- **Plan:** `docs/chat-ui-migration-plan.md`, stages CU0 to CU5.

## Context

The owner wants the chat built on the same open-source project that Unsloth Studio uses, for its advanced features. Facts
(read 2026-10-19):

- **Unsloth Studio's chat is built on `assistant-ui`** (`@assistant-ui/react` 0.12.28, with core, store and tap) and on
  `streamdown` 2.5.0 with its code, math and mermaid plugins, `katex`, Radix and shadcn. Its runtime provider alone is 4,372
  lines (local runtime, a remote thread-list adapter, a thread-history adapter, attachment adapters, dictation and
  speech-synthesis adapters, tool approval, MCP, research mode).
- **`assistant-ui`** (`assistant-ui/assistant-ui`, **MIT**, 12,600 stars, pushed 2026-10-19). npm `@assistant-ui/react` is at
  0.15.29 (unpacked 2.9 MB); it is **0.x and its API moves**. Dependencies: `radix-ui`, `zustand`, `zod`, `assistant-stream`
  (MIT), `@assistant-ui/core|store|tap`, `react-textarea-autosize`, `safe-content-frame`, and **`assistant-cloud`** (a hosted
  service SDK; whether it makes network calls when unused is not verified). Peers: React 18 or 19. It is headless: Radix-style
  primitives that we style ourselves.
- **`streamdown`** (Vercel, **Apache-2.0**, 125 KB unpacked), with `@streamdown/code`, `/math`, `/mermaid` (Apache-2.0) and
  `katex` (MIT, 4 MB unpacked). `@assistant-ui/react-markdown` (MIT) is the alternative markdown part.
- **Unsloth Studio's chat code is AGPL-3.0-only** (every file carries the header). `packages/ui` and the web app are
  Apache-2.0. **No Studio frontend code can be copied into them.** `assistant-ui` itself is MIT and can be used directly.
- **What we have today** (about 2,800 lines): `chatReducer` and `useAssistantChat` (events into state, stop, retry, re-attach
  after a broken connection by replaying the event log), `ChatScreen`, `ToolCard`, `AssistantHome`, our own safe `Markdown`
  (React nodes, never HTML strings, links only `http(s)`), `NotebookChat` with `[n]` citation pills.
- **What the owner wants from it:** message **editing and branching**, **attachments**, **dictation and read-aloud** (we have a
  speech runtime, ADR-0066), richer tool and approval UI for the assistant's **action cards** (ADR-0071), a **reasoning**
  ("Thinking") part, better streaming markdown with code, math and diagrams, and reuse of what the community builds on it.
- **Constraints that do not change:** our engine is the system of record (SSE events, `Last-Event-ID` replay, conversations
  and parts stored server-side, jobs that outlive the screen, creations that land in the library); the same screens run in the
  web app and the desktop window; the design system (ADR-0081) decides every colour and size.

## Decision

1. **Adopt `@assistant-ui/react` for the chat runtime and the thread, message and composer primitives**, in `packages/ui/src/chat`,
   for both the assistant and the notebook chat. Our own `ChatScreen`, `ToolCard`'s chrome and `Markdown` are replaced as the
   migration proceeds (decision 11). The owner's decision; no spike can undo it, but a spike picks the runtime and the version.
2. **The engine stays the store.** The default runtime is **`ExternalStoreRuntime`** over our own state: `chatReducer` keeps
   folding engine events into messages, a converter turns `ChatMessage` into assistant-ui's `ThreadMessage`, and the runtime's
   callbacks (`onNew`, `onCancel`, `onReload`, `onEdit`, branch switching) call our run client. Reason: re-attaching to a run
   after a broken connection, replaying missed events, server-side history, long jobs and interrupts are ours. The alternative
   is `LocalRuntime` with a chat-model adapter and a thread-history adapter (what Studio does); **stage CU0 prototypes both
   against a fake engine and picks one** on the checklist in the plan (reconnect, branching, edit, tool parts, approvals,
   SSR in Next.js, the Tauri content-security policy, bundle size, accessibility, right-to-left).
3. **Branching and editing need the server to keep a message tree** (stage CU2). The conversation tables gain additive fields
   (`parent_message_id`, a branch marker and sibling counts; Alembic on the web profile, additive `ensure_columns` on the
   desktop profile); a run accepts `parent_message_id` (an edit or a regenerate forks there); a conversation read returns the
   active path with sibling counts. This is an additive change to a public API shape; **accepting this ADR is the owner's
   approval for those fields** (CLAUDE.md "Ask before"). Nothing else in the SSE contract changes, except one optional new part
   type, `reasoning` (decision 6).
4. **Markdown through `streamdown`** (with the code, math and mermaid plugins), replacing `markdown.tsx`, **only if it keeps
   our safety guarantees**: no raw HTML from a model ever runs; links open only if `http(s)` and with `rel="noopener noreferrer"`;
   images from a model are not fetched from arbitrary hosts; mermaid runs with its strict security level; code highlighting and
   math work **offline** (no CDN, nothing fetched at run time, bundled fonts); a Tauri CSP that allows none of the above to
   reach the network. CU0 tests each. If `streamdown` cannot meet them, the fallback is `@assistant-ui/react-markdown` with our
   components, or our own renderer extended. Notebook `[n]` citation pills stay a custom inline component.
5. **Tool UI and action cards are assistant-ui tool UIs, one per catalogue action or kind.** The job card (a picture being made,
   then shown with a way to open it), the search-results card, the **`confirm_action` card** of ADR-0071 (human-in-the-loop:
   the person approves or declines and the result goes back through the tool-result path), and every future action's result
   render through registered tool UIs keyed by action id, with a generic fallback. `interrupt` events map to a tool call that
   waits for the person's result.
6. **A `reasoning` part** carries a model's "thinking" text when the model returns it, shown collapsed under "Thinking". The
   engine adds the optional event; the default is off for models whose thinking is switched off (ADR-0078).
7. **Features arrive in this order** (stages in the plan): streaming, markdown, stop, retry, copy, tool UI (CU1); edit,
   branch picker, action-card approvals (CU2); attachments (images for the multimodal model first; documents through the
   notebooks reader later), dictation and read-aloud through **our own** speech models, opt-in, local, with the download size
   shown (CU3); the notebook chat on the same primitives and the reasoning part (CU4); thread list or compare mode only if
   they earn their place (CU5). Our side menu's "Recents" list stays the conversation list unless CU0 shows
   `RemoteThreadList` is a better fit.
8. **Dependencies** (versions pinned exactly; assistant-ui is 0.x):
   - `@assistant-ui/react` (MIT): **approved by the owner**. Version chosen in CU0 (Studio pins 0.12.28; current is 0.15.29).
   - `assistant-stream` (MIT) only if the runtime needs it; `zustand`, `zod`, `radix-ui`, `react-textarea-autosize` come with it.
   - `streamdown`, `@streamdown/code`, `@streamdown/math`, `@streamdown/mermaid` (Apache-2.0) and `katex` (MIT): **approval asked
     in CU0**, with their sizes. Math and diagrams load lazily so the first chat does not pay for them.
   - **`assistant-cloud`** (a transitive dependency): CU0 proves with a network capture that it makes **no request** unless a
     cloud project is configured, which we never do; if it does, we alias it to a stub.
   The assistant-ui CLI, which copies component source into the repo (shadcn-style), may be used to generate the thread
   components; it needs a network fetch, so **it is run only after the owner says yes**, and its output is then ours: it must
   pass the token lint (ADR-0081).
9. **Reuse rule (ADR-0062).** Studio's frontend is AGPL-3.0 and is **read for ideas only, never copied** into `packages/ui` or
   `apps/web`. `apps/desktop` is AGPL-3.0, but it shares `packages/ui` with the web app, so a desktop-only copy would split the
   code path; we do not do it.
10. **Styling is ours.** assistant-ui is headless. Every colour, size, radius and motion comes from the design tokens
    (ADR-0081); the token lint covers the new files; light, dark, phone width and right-to-left are checked by the existing
    Playwright layout and screenshot tests plus the new chat cases.
11. **Migration is gradual and reversible.** The new thread is built next to the old `ChatScreen` (a setting under Labs, then
    the default when it passes the parity checklist, then the old code is deleted one release later). `chatReducer`,
    `createAssistantApi`, the run client and the engine contract keep their tests.
12. **Out of scope:** `assistant-cloud` and any hosted thread storage, a full-duplex voice mode, sharing links, deep-research
    mode, generative UI beyond our own tool cards, and Studio's extras (MCP server dialogs, sandboxes, model comparison):
    the last two may return in CU5.

## Consequences

- The chat gains editing, branching, attachments, dictation, read-aloud, reasoning display and a maintained set of
  accessible primitives, and the screens can follow what the project (and Studio) learns.
- A 0.x dependency with a moving API sits at the centre of the main screen: pinned exactly, wrapped by our adapter, covered by
  behaviour tests, upgraded deliberately.
- A real engine change (the message tree) and a new optional event type; both additive.
- About 2,800 lines of our chat code are replaced over time; the reducer, API and client stay.
- Bundle size grows (assistant-ui is 2.9 MB unpacked before tree-shaking; markdown extras are lazy). CU0 measures it.

## Alternatives considered

- **Keep our own components** (the D5 decision): smaller and fully ours, but we would have to build branching, editing,
  attachments and the rest ourselves, and we could not follow Studio.
- **`useChat` from the Vercel AI SDK with `@assistant-ui/react-ai-sdk`:** assumes the AI SDK's streaming protocol and request
  model; our engine has its own event contract and replay.
- **`@assistant-ui/react-langgraph`:** for LangGraph Cloud style servers; our engine is not one.
- **LibreChat, Open WebUI as the whole assistant:** full products with their own servers and licences; they would replace our
  engine, tools and library integration.
- **`assistant-ui` on `LocalRuntime` only** (what Studio does): simplest, but the runtime then owns the message state while our
  engine is the system of record; kept as the CU0 alternative.

## Open questions

1. `ExternalStoreRuntime` against `LocalRuntime` (decision 2), and which version of assistant-ui (CU0).
2. Whether `assistant-cloud` makes any request when unused (decision 8).
3. Whether `streamdown` meets the safety and offline rules (decision 4).
4. Whether assistant-ui's thread list can sit on our conversation list without a second source of truth.
5. How tool approvals map onto our `interrupt` event, and who owns the card state after a reload (CU2 with stage A2).
6. Attachment policy: file types, size limits and where originals live (ADR-0035 upload hardening applies).
7. Whether notebooks should adopt the same thread for their chat in CU4 or keep a lighter composer.

## Not in v1 of this migration

Hosted thread storage, cloud sync, voice mode, model comparison, Studio's research mode, sharing, and any change to the engine's
event contract beyond the optional `reasoning` part and the message-tree fields.
