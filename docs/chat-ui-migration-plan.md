# Chat UI migration plan: from our own components to assistant-ui

Written 2026-10-19 for ADR-0082 (Accepted for assistant-ui). The chat screens (the assistant home and conversation, and the
notebook chat) move to `@assistant-ui/react` and `streamdown`, in stages, with the old screen kept until the new one has parity.
Nothing here is built yet. Dependencies other than `@assistant-ui/react` are asked for at the start of CU0.

## What is replaced, what stays

| Today (`packages/ui`, `packages/client`) | Becomes | Notes |
|---|---|---|
| `chatReducer`, `ChatState`, `fromStored` (events into messages) | **stays**, feeds the runtime | the engine contract and its tests are unchanged |
| `useAssistantChat` (send, stop, retry, re-attach after a broken connection) | the runtime's callbacks (`onNew`, `onCancel`, `onReload`, `onEdit`) calling the same run client | the re-attach and replay logic is kept as it is |
| `ChatScreen` | assistant-ui `Thread` (viewport, messages, composer, scroll to bottom), styled with tokens | new files next to the old one |
| `ToolCard` | tool UIs registered per action id, with a generic fallback | the job card, search results, `confirm_action` card |
| `Markdown` (own, safe) | `streamdown` + code, math, mermaid plugins, if it meets the safety rules; else `react-markdown` through `@assistant-ui/react-markdown` | citations `[n]` stay a custom inline component |
| `AssistantHome` | the same composer primitive plus welcome suggestions | |
| `useConversations`, side menu "Recents" | **stays** (CU0 checks whether the thread list should replace it) | one source of truth: the engine |
| `NotebookChat` | the same primitives with a notebook adapter (scope chips, citations, passage viewer) | CU4 |
| `createAssistantApi` (list, read, rename, delete) | **stays**, gains the message-tree fields in CU2 | additive |

## How events map to assistant-ui messages

| Engine event | assistant-ui |
|---|---|
| `token` | text part delta on the running assistant message |
| `tool_call` | tool-call part (name, arguments, status running) |
| `job_progress` | the tool-call part's progress (a custom data part) |
| `tool_result` | the tool-call part's result and status (ok, refused, error) |
| `interrupt` (action card, ADR-0071) | a tool call that waits for the person's result, then `addResult` |
| `reasoning` (new, optional) | a reasoning part, collapsed under "Thinking" |
| `done` | message complete, with `conversation_id` and title |
| `error` | message status incomplete with the error (retryable or not) |

## Stages

Sizes: S under a week, M one to two weeks.

| Stage | What | Size | Done when |
|---|---|---|---|
| **CU0** | **Spike and decision.** Ask the owner for the dependency approvals (sizes shown). Prototype `ExternalStoreRuntime` and `LocalRuntime` against a fake engine inside a scratch app, in both the Next.js app and the Vite window. Run the checklist below. Write `docs/spikes/chat-ui-cu0.md`; pick the runtime and the version | S | A table per checklist item, the runtime and version chosen, the bundle-size delta, a go or no-go on `streamdown` |
| **CU1** | **Parity.** The new thread, composer, streaming text, markdown, stop, retry, copy; tool UIs (job card, search results) ported from `ToolCard`; the home composer and suggestions; tokens only; both apps; behind a Labs switch. Rewrite the tests around behaviour | M | The new screen passes the parity checklist (below) in the web app and the desktop window, in light, dark and phone width, and the Playwright screenshots are reviewed |
| **CU2** | **Edit and branch, and action cards.** Server: message tree fields (additive migration and `ensure_columns`), a run's `parent_message_id`, a conversation read with the active path and sibling counts. UI: edit a message, regenerate, branch picker. The `confirm_action` card as a human-in-the-loop tool UI (with stage A2) | M | Edit and regenerate create branches that survive a reload; an approval card works and the result reaches the assistant |
| **CU3** | **Attachments, dictation, read-aloud.** Image attachments for the multimodal model (upload hardening of ADR-0035); documents later through the notebooks reader. Dictation and read-aloud adapters on our own speech models (ADR-0066): opt-in, local, the download size shown | M | A picture can be attached and described; dictation fills the box; read-aloud speaks a reply, all locally |
| **CU4** | **Notebook chat on the same primitives; reasoning part; switch the default and delete the old chat code** one release later | M | The notebook chat has scope chips and citation pills as before; "Thinking" shows for models that return it; the old `ChatScreen`, `ToolCard`, `markdown.tsx` are gone |
| **CU5** | Optional: the thread list, compare mode, anything from Studio that earns its place | S | Only if wanted |

## CU0 checklist (each item gets a measured answer)

1. **Re-attach and replay:** kill the connection mid-answer; the run continues and the screen catches up with no duplicate or lost text.
2. **Branching and editing** with `ExternalStoreRuntime` (our tree) against `LocalRuntime` (its repository plus a history adapter).
3. **Tool parts:** a long job card, results as references, tool errors, parallel tool calls.
4. **Approvals:** an `interrupt` becomes a waiting tool call; the result goes back; a reload keeps the card state.
5. **Server rendering and routing** in Next.js; the Vite window; hash routes on the desktop; opening a saved conversation by id.
6. **Content-security policy in Tauri:** no inline script or remote font is needed; `safe-content-frame` does not call out.
7. **`assistant-cloud`:** a network capture proves no request is made when no cloud project is set.
8. **`streamdown` safety:** raw HTML in a message is shown as text; `javascript:` and `data:` links are inert; remote images are not fetched; mermaid uses the strict level; code highlighting and math work with the network off; the 4 MB of `katex` and the diagram code load only when used.
9. **Bundle size:** the first chat screen's JavaScript before and after, per app.
10. **Accessibility:** keyboard use, focus order, screen-reader announcements for streaming, live regions, reduced motion, right-to-left text.
11. **Version:** 0.12.28 (Studio's pin) against the current 0.15.x: which API we target and how much moves between them.
12. **Our tests:** which of the 333-line `chat.test.tsx` cases survive as behaviour tests.

## Parity checklist for CU1 (what the old screen does today)

Streaming with a stop button; try again after a failure; re-attach after a broken connection; the box is the same element before and
after the first message (Enter sends, Shift+Enter is a new line); a conversation opens by its address and a new chat gets its
address after the first answer; a job card that shows progress, then the picture with a way to open it; search results as a card;
copy a reply; links open only if `http(s)`; no model output runs as markup; works at 320 px; light and dark; right-to-left text.

## Order relative to the rest

0. **The composer options (Attach, Search, Thinking, Mic; ADR-0083, `docs/composer-options-plan.md`) are built on the current composer first** as a shared options bar; CU1 swaps the thread under the same bar and CU3 moves attachments and dictation onto assistant-ui's adapters without changing the engine routes.
1. **CU0 can start now** (it needs your approval for the dependencies and uses no GPU). It runs beside the Phase 4 work.
2. **CU1 should land before the assistant's action cards (stage A2) are built as UI**, so the cards are written once as
   assistant-ui tool UIs. A2's backend (the help corpus, `propose_action`, `confirm_action`) can proceed without waiting.
3. **DS3** (the component catalogue) and the chat patterns in `design/DESIGN.md` are updated when CU1 lands.
4. The Phase 5 screens (Teach, Agent, Video Builder, Motion Graphics, 3D) use assistant-ui tool UIs for their live feeds where a
   chat-like feed is the right shape (the Agent's feed in particular).

## Risks

| Risk | Control |
|---|---|
| assistant-ui is 0.x and changes quickly | pin exactly; our adapter is the only code that touches its runtime API; upgrade deliberately with the behaviour tests |
| Two sources of truth for messages | `ExternalStoreRuntime` over our reducer; CU0 proves it before CU1 |
| `streamdown` does not meet the safety rules | the fallback renderer in decision 4; the rules are tests, not intentions |
| Bundle size | lazy math and diagrams; measured in CU0 and kept as a budget in CU1 |
| The message tree changes the engine | additive fields, covered by the same tests on both profiles; reads of old conversations unchanged |
| A hidden network call from a transitive dependency | the CU0 network capture; the Tauri CSP |
| Rewrite fatigue: 2,800 lines replaced | stages ship alone; the old screen stays until parity; the reducer, API and tests carry over |
| Studio's AGPL code leaks in | reading only; no copy; the licence note in ADR-0082 decision 9 |

## Decisions needed from the owner

1. **Approve the CU0 dependencies** when CU0 starts (`streamdown` and its three plugins, `katex`; sizes shown).
2. **Say yes before the assistant-ui CLI is run** (it fetches component source from the network; its output becomes ours).
3. The runtime and version, after CU0 (I will recommend).
4. Whether CU3's dictation and read-aloud should be on by default once the speech models are installed, or stay opt-in.
