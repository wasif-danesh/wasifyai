# Spike CU0: assistant-ui and streamdown against our engine

Date: 2026-10-20. Machine: MacBook Pro, Apple M5 Pro, 64 GB. Browser for every browser measurement: **Chromium 156.0.8078.4
through Playwright 1.64.1**. The Tauri window on macOS is a WKWebView (Safari's engine), which was **not** tested (see "What I could not measure").
Plan: `docs/chat-ui-migration-plan.md`, stage CU0. Decision tested: ADR-0082 (chat on assistant-ui and streamdown).
Nothing in the repo was changed except this file. Where a finding contradicts or adds to an ADR it is listed under "What this changes".

Scratch folder (outside the repo, kept): `~/Projects/wasifyai-spikes/cu0/`. It holds the fake engine (`engine/server.mjs`,
speaks our SSE contract, `Last-Event-ID` replay, a message tree, stored parts, interrupt and resume, a loopback "tracker" that
records every request a page makes), prototype A (`shared/runtime-a.ts`, `tree-chat.ts`, `convert.ts`), prototype B
(`shared/runtime-b.ts`), the Vite and Next apps, `v012/` (the same prototype on 0.12.28), and every test script in `tests/`.
`NOTES.md` there has the raw running notes. Our own `sse.ts`, `assistant.ts` (`chatReducer`), `run-client.ts` and `transport.ts`
were copied into the scratch folder; nothing else of ours was copied and **no Unsloth code was copied or read** (I read only the
dependency pins in Studio's `package.json`). Anything not run is marked **not verified**.

## Result in one screen

| Question | Answer |
|---|---|
| Runtime | **`ExternalStoreRuntime` over our state, with a `messageRepository` (the tree)** (prototype A). `LocalRuntime` (B) also passed every item but needed five workarounds for approvals, cannot report a branch switch, and swallows history-load errors |
| Version | **`@assistant-ui/react` 0.15.29**, exact. 0.12.28 (Studio's pin) works for everything except it has no approval seam and no branch-change callback (about 70 changed lines in 3 files), and is 229 KB smaller before compression. 0.15.30 was published the day this was written: releases are about daily |
| Re-attach after a killed connection | **Exact text, no duplicate, no loss** in both runtimes (3 cuts, 3 cases). A 2 s outage recovers; a 7 s outage **gives up** (budget about 5.4 s). A cut before the first event cannot be re-attached |
| Edit, regenerate, branches | **Work in A and B**, survive a page reload. Only A can tell the server which branch is visible |
| Tool parts | Job card steps (queued 2, queued 1, 10 to 90 %, picture), search results, errors, refusals, reload: **identical in A and B**. Parallel jobs need one optional new field, `tool_call_id` on `job_progress` |
| Approvals | `interrupt` becomes a tool call with an `approval`; the answer resumes the run; **a reload keeps the pending card and still works**. A: native seam. B: works after five workarounds. 0.12.28: works through `interrupt` and `resume` |
| Next.js and the Vite window | **Works.** Server render of `/chat/[id]` puts the messages in the first HTML (A); no hydration error. Hash routes, new chat gets its address, open by id, switch in place: pass |
| Tauri CSP | **No violations, no `unsafe-eval`, no `wasm-unsafe-eval`, no remote font.** Highlighting, math and diagrams run under the exact CSP of `tauri.conf.json` |
| `assistant-cloud` | **0 requests** in every capture (browser: 2 hosts only, the app and the engine; Next server: one DNS lookup, `127.0.0.1`). Runtime A's bundle does not even contain it; B's bundle contains its client class but never calls it |
| streamdown | **Go, only with a hardened configuration.** Its defaults are not safe for us (remote images fetched, `<b>` rendered as HTML, diagram labels fetch pictures). With the settings in section 8 every safety rule passes, offline too |
| First chat screen, JavaScript | Today **275 KB raw / 85 KB gzip**. Recommended build **1,090 KB raw / 326 KB gzip**, plus **about 15 MB of lazy chunks on disk** (code languages, math, diagrams). Cold load to a usable box in Chromium: 26 ms today, 55 ms after |
| Accessibility | Primitives pass axe (0 serious or critical), keyboard works, reduced motion honoured. **The library has no live region at all**; screen-reader announcements and `dir="auto"` on our user bubble and box are ours to add |
| Our tests | **All 11 `ChatScreen` cases pass** against the new thread with only wiring changes. The 4 markdown cases test our own parser: 3 retire, the safety rule is re-tested on the new renderer |
| **CU1** | **Go**, with the conditions at the end |

## Method

- A fake engine on `127.0.0.1:8787` (Node, no dependencies) speaks the contract in `docs/contracts/sse-events.md`: `token`, `tool_call`,
  `job_progress`, `tool_result`, `interrupt`, `done`, `error`; `GET /runs/{id}/events` with `Last-Event-ID`; `POST /runs/{id}/resume`;
  `GET /conversations/{id}` with stored parts. Scripted replies: plain, long (380 events), job, parallel, tool error, refusal,
  search, approval, an adversarial markdown message, right-to-left text. Test switches (cut the connection after N events, drop the
  network for N ms) are in the fake only.
- The fake adds what CU2 would add, **as a proposal**: `parent_message_id`, `client_message_id` and `client_reply_id` on a run's input,
  `user_message_id` and `assistant_message_id` in `done.outputs`, `parent_id`, `head_id`, sibling counts and `?tree=1` on a
  conversation read, `PATCH {head_id}`, a stored part of type `interrupt` (with `status`), results stored inside the assistant
  message, and an optional `tool_call_id` on `job_progress`.
- Two prototypes on 0.15.29 with the same UI built from the primitives (`ThreadPrimitive`, `MessagePrimitive`, `ComposerPrimitive`,
  `BranchPickerPrimitive`, `ActionBarPrimitive`), the same `chatReducer` fold, the same converter from `ChatMessage`:
  **A** = `useExternalStoreRuntime` with `messageRepository` and the callbacks `onNew`, `onEdit`, `onReload`, `onCancel`,
  `onRespondToToolApproval`, `unstable_onBranchChange`. **B** = `useLocalRuntime` with a `ChatModelAdapter` (our run client inside an
  async generator) and a `ThreadHistoryAdapter` (`load` reads the tree, `append` does nothing because the engine already stored it).
- Production builds were measured, not dev servers. Sizes are Vite 8.3.4 builds (target es2022) of the first screen: the entry chunk and
  everything it imports statically. "Baseline" is our **current** `ChatScreen` path built from repo source through an alias
  (read-only), with the repo's own versions of React, lucide-react, radix-ui.

## 1. Re-attach and replay

`tests/t1-reattach.mjs`, `t1b-offline.mjs`. A 380-event answer (1,910 characters). After the run the text on screen is compared with
the text the engine stored.

| Case | A (ExternalStore) | B (LocalRuntime) | A on 0.12.28 |
|---|---|---|---|
| Connection cut once after 7 events | exact, sentence 17 once | exact | exact |
| Every connection cut after 100 events (3 re-attaches) | exact | exact | exact |
| Cut after 1 event (before any text) | exact | exact | exact |
| Network down 2 s mid-answer | exact, re-attached on the 2nd try | exact | n/a |
| Network down 7 s mid-answer | **gave up** ("network error"); the run finished on the engine | **gave up** | n/a |

Findings that apply to either runtime (they are in our re-attach logic, which stays ours):

1. **The current `useAssistantChat` gives up after three re-attaches in total**, not three in a row (`attempt` is never reset), with
   backoff 0.8, 1.6, 3 s: **about 5.4 s of outage**. In the prototype the counter resets when `lastSeq` advances; with that, three cuts in one
   answer recover. A first stream that breaks with an exception gets **one** re-attach attempt only (no loop) in the current code.
2. **A cut before the first event cannot be re-attached**: the client has no run id (the id arrives in the first event). The result is
   "network error", and "Try again" **sends the message again** (a second run). A client-chosen run id, or an idempotency key on
   `POST /runs`, would fix it.
3. After a give-up, "Try again" starts a new run although the old one is finishing. Better: on a connection-lost error, "Try again"
   re-attaches; also re-attach on the browser's `online` event.
4. **Stop** aborts the fetch; the engine run goes on (the contract has no cancel call). The partial text stays on screen, the box
   comes back, the next message works (A and B, `tests/t13-stop.mjs`). The engine finishes the run, so a reload would show the full answer (by the engine's design; not run).
5. In B the re-attach loop lives inside the generator, and events must be folded the moment they arrive (not when the generator is
   resumed), or the loop reads a stale `lastSeq`.

## 2. Branching and editing

`tests/t2-branching.mjs`. A seeded conversation with a tree (the second question has two versions), then: open by id, switch branch,
edit, regenerate, reload the page.

| Step | A (`messageRepository`) | B (LocalRuntime + history adapter) |
|---|---|---|
| Open a saved tree by id, picker shows "1 / 2" | yes | yes |
| Switch branch | yes. `unstable_onBranchChange` gives the new head; we `PATCH` it: **server head moved to the chosen branch** | yes in the UI, but **nothing reports it**: server head stayed on the old branch |
| Edit a user message | `onEdit(message)` with `message.parentId` = **the edited message's parent** (null for the first message) and `sourceId` = the edited message. New sibling, "3 / 3" | `run()` is called with `messages` ending at the new user message; parent = `messages[length-2]`. New sibling, "3 / 3" |
| Regenerate | `onReload(parentId)` where `parentId` is **the user message** to answer again. New assistant sibling "2 / 2" | `run()` called with `messages` ending at the same user message; we tell "again" from "new" by the id (the engine sees a client id it already has) |
| Reload the page | the path left on screen is the path shown (needs the head `PATCH` for a plain switch) | same after an edit or regenerate; after a plain **switch** it returns to the old branch |

Both need the message ids to be the same on the client and the server. The prototype sends `client_message_id` and `client_reply_id`
on the run and the engine stores them; otherwise every message needs an id swap after `done`. This is an additive field and is
listed under "What this changes". In B the assistant id comes from `unstable_assistantMessageId`, an experimental option.

Cost of the tree on the client in A: the read must return **all** nodes (`?tree=1`), because the picker needs the sibling bodies. The
conversation read of ADR-0082 decision 3 ("the active path with sibling counts") is not enough for A; a switch would need a second
fetch and a path-only repository. Messages are small; I recommend returning the whole tree.

Today's engine returns no `parent_id` or `head_id`; the converter reads such a conversation as one straight line (tested, section 12), so
CU1 does not wait for CU2.

## 3. Tool parts

`tests/t3-tools.mjs`, 7 scenarios, each also reloaded from the stored conversation. **A and B behave the same** (the rendering is
assistant-ui's and the converter is shared). Tool UIs are registered by name through `MessagePrimitive.Parts components.tools.by_name`, with
a `Fallback`.

| Scenario | Seen on screen |
|---|---|
| Long job | "Waiting for a turn, place 2" then "Waiting for a turn", then "Making your picture, 10 %" ... "90 %", then the picture card with "Open in the library". Progress rides on the running tool call's `artifact` (UI only) |
| Parallel, search first, job second | search card with its result; the job card shows 20, 60, 90 % |
| **Parallel, job first, search second** | **Progress went to the wrong card** (the job card stayed at "Making your picture" with no percent). Our reducer gives `job_progress` to the last running tool. With the optional `tool_call_id` on `job_progress`, correct (20, 60, 90 %). I added `tool_call_id` to the prototype's reducer |
| Tool error | "The picture could not be made." |
| Refused | the engine's own message |
| Search results | card with the references |
| Reload of each | identical cards |

Results are folded into the assistant message as a part right after their call (the engine already stores them next to it; today they are
separate `role: "tool"` rows that `fromStored` folds). For the tree, **keep the tree to user and assistant nodes** and store results inside the
assistant node; a separate row would count as a sibling.

## 4. Approvals

`tests/t4-approvals.mjs`: approve and decline, each answered directly and after a page reload, then reloaded again.

| | A (0.15.29) | B (0.15.29) | A on 0.12.28 |
|---|---|---|---|
| `interrupt` shows a waiting card, no "Stop" shown | yes | yes | yes |
| Stored conversation shows the pending card after a reload | yes | yes | yes |
| Answer after a reload resumes the run | yes (4 of 4) | yes (4 of 4, after workarounds) | yes (4 of 4) |
| Decision shown after a reload | yes | yes | yes |
| Mechanism | tool call with `approval {id, prompt, approved?}`; `respondToApproval` calls `onRespondToToolApproval` | see below | tool call with `interrupt {type: "human"}`; `resume(payload)` calls `onResumeToolCall` |

How an `interrupt` maps (A): a tool call named by the interrupt `kind` (`confirm_action`) whose arguments are the interrupt payload, plus
`approval.id` = the `interrupt_id`. The message status is `requires-action`. The answer goes to `POST /runs/{id}/resume`, and the events that follow
(`tool_call`, `tool_result`, `token`) are folded into the same message. The engine must **store the assistant message with an `interrupt` part at
the moment it pauses** and mark it approved or declined, or the card cannot survive a reload. The `resume` body is song-specific today
(`Approval {action: "approve" | "regenerate"}`); a `confirm_action` value needs defining (stage A2).

B needed five workarounds, each found by a failing run:

1. The paused message status must be `requires-action` with reason **`tool-calls`**; with `interrupt` the runtime never continues after the answer.
2. The runtime re-runs our adapter **on the same assistant message** and passes `messages` ending at the user message: the paused message must be read
   with `unstable_getMessage()` (experimental).
3. What the adapter yields is **appended** to the paused message, so it must yield only the new parts.
4. A declined card gets its result (`isError`) set locally and the adapter still runs again; "decided" is `approved !== undefined`, not "no result yet".
5. The map from the interrupt to its run, and the paused message to seed the fold, are kept in our code.

Expiry: if the person sends a new message while a card is pending, B's runtime marks the card cancelled (`resolution: "cancelled"`); in A that
is our decision, and the engine must say what happens to the paused run (not tested).

## 5. Next.js, the Vite window, routes

Next.js 15.5.27, App Router, React 19.3.0, `next build` and `next start` (production).

| Check | Result |
|---|---|
| Server render of `/chat/[id]` with a server component fetching `?tree=1` and passing it to the client chat (A) | The first HTML contains both user and both assistant messages, the markdown (as `data-streamdown="strong"` spans), the picture card and the branch picker; the empty state is not shown |
| Same route with B (history loads in the browser) | The first HTML has the empty state; messages appear after hydration. The old screen also loads in an effect, so this is not a regression |
| Hydration | No console error or warning; the box works at once; branch switch works after hydration; a new chat streams |
| Client libraries need `"use client"` | Yes; the chat module is a client boundary. No `window` access at import (the build and the server render pass) |
| Server-side outbound | One DNS lookup in total, `127.0.0.1` (the server component's fetch to the engine; see the note in section 7) |
| `next build` | Needed `NODE_ENV=production` set explicitly after the first run; the first run also made Next install `@types/node` (see "Disclosures") |
| Outside Tailwind | streamdown's components use Tailwind classes. In our build Tailwind must scan `streamdown/dist` (a Tailwind 4 `@source`) or its elements are unstyled; not tested here because the scratch app has no Tailwind |

Vite window (built, served from a static server): hash routes `#/a`, `#/a/<id>`; a new chat gets `#/a/<id>` after the first answer
(`replaceState`) and a reload opens it; `location.hash = ...` switches conversations in place; back works; an unknown id shows "No such
conversation." in A. **In B an unknown id shows an empty chat with no message** (the error goes to the console only; LocalRuntime logs
"local thread history load failed" and swallows it).

## 6. Content-security policy in Tauri

The window's real CSP (`apps/desktop/src-tauri/tauri.conf.json`) was applied by a static server to the **production** build:
`default-src 'self'; connect-src 'self' ipc: http://ipc.localhost http://127.0.0.1:*; img-src 'self' data: blob: http://127.0.0.1:*; media-src 'self' blob: http://127.0.0.1:*; style-src 'self' 'unsafe-inline'; font-src 'self' data:`.
Session run: plain, job, parallel, approval, search, adversarial markdown, open a saved tree.

- **No CSP violation was recorded for the app's own code** (`securitypolicyviolation` listener and console).
- No inline script is needed (Vite emits `<script type="module" src>`). No `eval` and no WebAssembly: `@streamdown/code` uses shiki's
  **JavaScript regex engine**, so highlighting worked under `default-src 'self'` without `'wasm-unsafe-eval'`.
- No remote font: KaTeX's three font files are emitted as local assets and fetched from `'self'`.
- Streamdown's and KaTeX's inline `style` attributes are allowed by the existing `style-src 'unsafe-inline'`.
- **`safe-content-frame`** is used only by assistant-ui's `SandboxHost` (sandboxed generated UI). It is **not in any of our bundles**, and its default
  shim address is a **remote** domain (`scf.auiusercontent.com`). We must never render `SandboxHost` or MCP app frames; the CSP would block them, and a lint
  rule (or a test on the bundle) should forbid the import.
- The one console message under this CSP: `Executing inline event handler violates ... 'default-src 'self''`, repeated about 11 times per
  malicious diagram while it streams. It comes from mermaid's DOMPurify handling the hostile label `<img onerror=...>` in an inert document;
  without the CSP the handler **does not run either** (`window.__pwned5` stays unset). Harmless, but it is console noise.
- The CSP does **not** stop a request to any `127.0.0.1` port (`img-src http://127.0.0.1:*`). A model's image pointing at `127.0.0.1:9999` is allowed
  by the CSP and was fetched by streamdown's defaults; only the renderer's own prefix list stops it (section 8).

## 7. `assistant-cloud` network capture

`tests/t6-csp-net.mjs` records every request of the browser context (all frames and workers) and every WebSocket.

| Build | Hosts contacted in a full session | WebSockets | Requests to a cloud host |
|---|---|---|---|
| A, production, Tauri CSP | `127.0.0.1:4173` (the app) and `127.0.0.1:8787` (the engine) | 0 | **0** |
| B, production, Tauri CSP | the same two | 0 | **0** |
| Next production (browser) | `127.0.0.1:3100` and `127.0.0.1:8787` | 0 | **0** |
| Next production (server process) | one DNS lookup, `127.0.0.1` (a hook on DNS and sockets; the socket hook caught nothing because Node's `fetch` uses its own, so this row is weaker than the browser rows) | n/a | **0** seen |

Static check of the built JavaScript: **A's bundle has no `assistant-cloud` code and no cloud URL** (the class is tree-shaken, `sideEffects: false`).
**B's bundle contains `AssistantCloudAPI`** and the string `https://backend.assistant-api.com` (the default when an API key is given) but never
calls it. The `assistant-cloud` telemetry module (OpenTelemetry exporter to `/v1/traces`) is opt-in and not imported. So the ADR's fallback
(alias to a stub) is **not needed for A**. Add a build test: the first-screen bundle must not contain `assistant-api.com` or `auiusercontent.com`.

Limits of this proof: it covers the flows listed in section 6. Attachments, dictation, feedback and the thread list (CU3, CU5) were not exercised.

## 8. streamdown safety and offline behaviour

streamdown 2.7.1 with `@streamdown/code` 2.0.0, `/math` 1.0.3, `/mermaid` 1.0.3 (katex 0.16.47, mermaid 11.17.2, shiki 4). The test sends one adversarial
message: raw `<script>`, `<img onerror>`, `<iframe>`, `<b>`; links `javascript:`, `data:`, `vbscript:`, `file:`, relative and `https:`; images from a
remote host, from a loopback port, from the engine and a `data:` URL; a code block; inline and block math; two diagrams (one hostile: an `<img>`
label and a `click ... "javascript:"` directive). `tests/t8-safety.mjs`; "pwned" flags are `window.__pwned*` set by any payload that ran; a **tracker**
counts requests.

| Rule | streamdown defaults | Hardened (below) |
|---|---|---|
| Raw HTML shown as text | **No.** `<script>`, `<iframe>`, `<img onerror>` are removed (sanitized, not executed), but `<b>` becomes a real element and `<img src>` stays an image | **Yes**: `<script>`, `<img>`, `<iframe>`, `<b>` appear as text |
| Script ran (`__pwned*`) | no | no |
| `javascript:`, `data:`, `vbscript:`, `file:` links | inert (no link made) | shown as "[blocked]" text |
| Relative link | a link | text |
| `https:` link | a button that opens a confirmation dialog (link safety on) | `<a target="_blank" rel="noopener noreferrer">` |
| Remote images not fetched | **No.** Without a CSP, 4 requests reached the tracker (raw `<img>`, markdown image, loopback image, the diagram label). Under the Tauri CSP the remote ones were blocked by the CSP and the loopback one still went out | **Yes: 0 tracker hits**; only the engine's own origin loads |
| `data:` images | allowed | blocked |
| Mermaid | level `strict`, but an `<img>` in a node label **still fetched** a remote picture | `securityLevel: "strict"` **and** `htmlLabels: false`: no `foreignObject`, **0 requests** |
| Code highlighting | works | works: 26 coloured spans |
| Math | works for `$$...$$`; **`$x$` stays text** (single-dollar math is off in the plugin, fine for prices) | same |
| Network off (everything except the app and the engine aborted) | n/a | code, math and diagrams all render; fonts local; nothing blocked-by-test was requested |
| Under the Tauri CSP | | same results, no violation |

The hardened settings (in `shared/md-config.tsx`), in the form we would ship:

```tsx
<Streamdown
  dir="auto"                                   // right-to-left per block
  linkSafety={{ enabled: false }}              // our own SafeLink below, no dialog
  components={{ a: SafeLink }}                 // only an absolute http(s) address is an <a>; rel="noopener noreferrer"
  mermaid={{ config: { securityLevel: "strict", htmlLabels: false, flowchart: { htmlLabels: false } } }}
  remarkPlugins={[...Object.values(defaultRemarkPlugins), htmlAsText]}      // a 10-line plugin: html nodes become text
  rehypePlugins={[defaultRehypePlugins.sanitize,
    [defaultRehypePlugins.harden[0], {
      allowedImagePrefixes: [ENGINE_ORIGIN],   // the engine only
      allowedLinkPrefixes: ["*"], allowedProtocols: ["https:", "http:"],   // note the colons
      defaultOrigin: "http://relative.invalid", // required whenever prefixes are given; SafeLink refuses anything that resolved to it
      allowDataImages: false }]]}
/>
```

Traps found on the way (each cost a failing run): `allowedProtocols` takes `"https:"`, not `"https"`; `defaultOrigin` is **required** (the server render
threw without it); `allowedLinkPrefixes: ["https://"]` blocks everything (prefixes are parsed as URLs, so use `"*"` plus the protocols list); a new
`Md` component identity on each render remounts every message (in the first prototype each token re-requested the same image 87 times).

**Lazy loading** (`tests/t9-lazy.mjs`, build `a-lazy`: core eager, each plugin dynamic-imported when the text needs it):

| Step | New files | Raw | Gzip |
|---|---|---|---|
| First screen (empty chat) | 3 (entry, runtime chunk, css) | 1,090 KB | 326 KB |
| A plain message | 0 | 0 | 0 |
| First code block (TypeScript) | 5 (shiki core, TS grammar, 2 themes) | 387 KB | 79 KB |
| First math block | 6 (katex, its css, 3 font files) | 340 KB | 134 KB (the fonts are already compressed; the real cost is about the raw size) |
| First diagram (a flowchart) | 29 | 825 KB | 208 KB |

Other languages and diagram types are further chunks. The whole lazy set is **406 JavaScript files, 13.2 MB raw (about 16 MB on disk with fonts)**: shiki
ships every language grammar and theme, mermaid every diagram. Today the whole desktop `dist` is 644 KB. `@streamdown/code` is a 2.5 KB shim over shiki's full bundle; a
small custom `CodeHighlighterPlugin` over `shiki/core` with 15 or 20 languages would cut most of the 13 MB (not built).

If streamdown is dropped, the fallback of ADR-0082 decision 4 (`@assistant-ui/react-markdown`, or our own renderer extended) was **not measured**: that package was not in
the approved list. Our own renderer already meets every rule in this table, has no tables of its own for math or diagrams, and costs 60 KB raw (the whole current chat).

## 9. Bundle size and startup

Vite production builds, first screen JavaScript (entry plus static imports), no CSS unless stated. React and ReactDOM are 214 KB raw / 66 KB gzip of every number.

| Build | Raw KB | Gzip KB | Brotli KB | Cold load to a usable box (median of 9, loopback, Chromium) |
|---|---|---|---|---|
| React only (floor) | 214 | 66 | 57 | 18 ms |
| **Today: current `ChatScreen`** | **275** | **85** | 74 | 26 ms |
| A + plain text, 0.12.28 | 364 | 108 | 93 | 29 ms |
| A + plain text, 0.15.29 | 593 | 175 | 148 | 39 ms |
| B + plain text, 0.15.29 | 696 | 205 | 172 | 42 ms |
| A + streamdown core (no plugins) | 1,087 | 324 | 271 | 54 ms |
| **A + streamdown core, plugins lazy (recommended)** | **1,090** | **326** | 273 | 55 ms |
| A + all three plugins static | 2,205 (+29 CSS) | 630 (+8 CSS) | 525 | 79 ms |
| B + all three plugins static | 2,309 | 660 | 549 | not timed |

So: assistant-ui costs about **379 KB raw / 109 KB gzip** over React (A, 0.15.29) against **60 KB / 19 KB** for all of our current chat code; streamdown's core adds
**494 KB raw / 149 KB gzip**. The recommended first screen is **+815 KB raw / +240 KB gzip** over today.

Next.js, "First Load JS" as Next reports it (gzip, shared chunks included): empty server page 109 KB; **current `ChatScreen` route 132 KB**; A with plain text 245 KB;
**A with lazy streamdown 399 KB (+267 KB)**; A and B with static plugins 759 KB.

Streaming cost (`tests/t12-perf.mjs`, 380 events sent as fast as the engine could, script time on the main thread): A plain 141 ms on an empty thread, 435 ms on a
200-message thread; A with streamdown 237 and 436 ms; B plain 80 and 233 ms; A with `messages` plus `convertMessage` instead of a repository 140 and 482 ms. Part of A's
growth is our own reducer's O(n) bookkeeping, not the library. At real speeds (30 to 100 tokens per second) this is about 1 ms per token on a long thread; fine, and an
optimisation target if a 500-message thread feels slow. Memory with 100 code-bearing messages rendered by streamdown was clearly higher than plain text; the heap numbers were
too noisy to quote.

## 10. Accessibility

`tests/t10-a11y.mjs` (prototype markup, Chromium, axe-core 4.14.0 on the finished thread).

| Check | Result |
|---|---|
| Keyboard | Tab reaches the box, then Send (skipped while it is disabled); Enter sends, Shift+Enter is a new line; focus is back in the box after the answer. The edit, branch and action-bar controls render as buttons (named by our labels); edit, save and cancel were **not** driven by keyboard in a test |
| axe (wcag2a, 2aa, 21aa, best-practice) | **0 serious or critical.** 3 moderate, all page-level in the scratch page (`landmark-one-main`, `page-has-heading-one`, `region`); none from the primitives |
| **Live regions while streaming** | **None.** No `aria-live`, `role="log"`, `role="status"`, or `aria-busy` anywhere in the library or in streamdown (searched the sources and the DOM). A screen reader hears nothing as the answer arrives. Our current screen puts `aria-live="polite"` on the whole thread, which announces every chunk. The new screen needs a deliberate design (a visually hidden status "Assistant is answering" then "Answer ready", and the finished text in a `role="log"` region) |
| Reduced motion | assistant-ui's text smoothing (`useSmooth`) switches itself off under `prefers-reduced-motion`; streamdown's reveal animation is opt-in (`animated`), off by default; no CSS smooth scrolling; no animations running while streaming in either setting |
| Right-to-left | With `dir="auto"` streamdown paragraphs with Arabic or Hebrew computed `direction: rtl`. **Our user bubble and box did not** (`direction: ltr` for Hebrew text): they need `dir="auto"` |
| Screen reader | **Not run** (no VoiceOver session). Checked only the DOM and the accessibility tree |

## 11. Version: 0.12.28 against 0.15.29

`v012/` is the same prototype A on 0.12.28 with Studio's exact pins (`@assistant-ui/core` 0.1.17, `store` 0.2.9, `tap` 0.5.10).

| | 0.12.28 (2026-04-30) | 0.15.29 (2026-10-15) |
|---|---|---|
| `useExternalStoreRuntime`, `messageRepository`, `onNew`, `onEdit`, `onReload`, `onCancel`, `setMessages` | same | same |
| `ThreadPrimitive.Messages` render function, `AuiIf`, `useAuiState` | present | present (`components` prop marked deprecated) |
| `fromThreadMessageLike` (convert once per message, keep identity) | **absent**: the repository is rebuilt from `ThreadMessageLike` items each time | exported, marked experimental |
| `unstable_onBranchChange` | **absent**: a branch switch cannot be persisted | present, experimental |
| Tool approvals: `approval` on a tool call, `respondToApproval`, `onRespondToToolApproval`, options, `display` modes | **absent**. Use `interrupt {type: "human"}` plus `resume()` and `onResumeToolCall` (works, 4 of 4) | present; a request can offer options, free text, questions |
| Results on our 12 items | items 1, 3, 4: pass; item 2: pass **except** the head is not persisted | all pass |
| First screen, A plus plain text | 364 KB raw / 108 KB gzip, 29 ms | 593 / 175, 39 ms |
| Changes to port the prototype between them | **70 changed lines in 3 files** (`runtime-a.ts` 43, `convert.ts` 18, `tools.tsx` 12); `thread-ui.tsx` unchanged | |
| Release pace | | 0.15.27 (Oct 10), .28 (Oct 12), .29 (Oct 15), **.30 (Oct 19, hours before this spike's last run)** |

Target **0.15.29**: ADR-0071's `confirm_action` card is what the `approval` seam is for, and the branch-change callback closes the persistence gap. The price is
**+229 KB raw / +68 KB gzip** and 10 ms of start. Both versions put the whole API behind the same set of 3 files, so our adapter (not the screens) is where an upgrade lands, and it can
fall back to the 0.12 shape in about 70 lines if a 0.15 release breaks us. Bump deliberately: every release so far in October moved something; pin exactly.

Two experimental names are in use by A (`fromThreadMessageLike`, `unstable_onBranchChange`); B would use `unstable_getMessage` and `unstable_assistantMessageId`. Both are flagged "may change in any release".

## 12. Our tests

`packages/ui/src/chat/chat.test.tsx` has **15 cases**: 4 on `markdown.tsx` and 11 on `ChatScreen`. `tests/vitest/chat-port.test.tsx` runs the 11 `ChatScreen` cases against the new
thread (prototype A: the real primitives, `useExternalStoreRuntime`, our reducer, the **current `ToolCard` reused inside a tool UI**) with the same mocked run client.

| Case | Survives? | Edit needed |
|---|---|---|
| Enter sends, Shift+Enter is a new line, answer appears, `onConversation` called, box clears | **yes** | the run input also carries `client_message_id` and `client_reply_id`: `toEqual` becomes `objectContaining` |
| Continues the same conversation on the next message | **yes** | same |
| Picture the assistant made, with a way to open it | **yes**, unchanged | `ToolCard` runs unchanged inside the tool UI |
| Notebook results card and its "Open notebook" button | **yes**, unchanged | |
| Notebook search error text | **yes**, unchanged | |
| Music player in the chat and its open button | **yes**, unchanged | |
| Music could not be made | **yes**, unchanged | |
| No model chosen: message and "Choose a model" button | **yes** | the screen's error notice is ours (about 8 lines in the harness) |
| "Try again" re-runs after a retryable error | **yes** | |
| Blocked: Send disabled, nothing sent, reason shown | **yes, rewired** | disabling the button is not enough, **Enter still sends**; use the runtime's `isSendDisabled` |
| Opens a saved conversation | **yes** | the assertion that bold is a `<strong>` is a renderer detail (streamdown uses a span); assert the text |
| markdown: `parseBlocks` kinds, unclosed block, `inline()` | **retire** (they test our parser's internals) | |
| markdown: "never makes markup, only links http(s)" | **survives as a rule**, re-run on the new renderer in a browser (section 8) | |

Selectors that kept working untouched: `getByRole("textbox", {name: "Message"})`, `getByRole("button", {name: "Send"})`, "Try again", "Choose a model", text of cards. The
tests do not depend on assistant-ui's internals. They needed jsdom stubs for `ResizeObserver`, `matchMedia`, `scrollTo`. `assistant-home.test.tsx` was not examined (it tests the
side-menu list, which stays).

## Recommendation

**Runtime: `ExternalStoreRuntime` (prototype A), assistant-ui 0.15.29.**

Why, in order of weight:

1. **The engine is the system of record, and A makes that literal.** Our state is the only copy; the runtime reads it through a repository we hand over. In B the runtime keeps its own
   message tree and our history adapter has to be kept in step by id; B has no callback for "the visible branch changed", and it swallows a failed history load.
2. **Approvals, the feature we are building this for, are a first-class seam in A** (`approval`, `respondToApproval`). In B they need five workarounds and an experimental read of the paused message.
3. **Both are equally good at re-attach, tool parts, edit, regenerate, routes**, because the hard parts (re-attach, folding events, converting) are ours either way. B is not simpler once approvals work:
   `runtime-b.ts` is 183 lines against 70 for `runtime-a.ts`, and both reuse the same converter (65 lines) and event folding. A also carries the 380-line tree state, which CU2 needs anyway.
4. B is cheaper on the main thread for a long thread (233 against 435 ms of script per 380 tokens at 200 messages) but its first screen is **30 KB gzip larger** (205 against 175). Neither decides it.

**Versions to pin exactly** (the versions tested): `@assistant-ui/react` **0.15.29** (pulls `@assistant-ui/core` 0.3.29, `store` 0.3.21, `tap` 0.9.23, `assistant-stream` 0.3.52,
`assistant-cloud` 0.2.7, `safe-content-frame` 0.0.34, `zustand` 5.0.15, `zod` 4.6.x, `nanoid` 6.0.2, `react-textarea-autosize`); `streamdown` **2.7.1** (published 2026-10-19; pnpm's release-age
gate needed an exclusion, 2.7.0 is from 2026-09-30 and untested); `@streamdown/code` **2.0.0**, `@streamdown/math` **1.0.3**, `@streamdown/mermaid` **1.0.3**; `katex` **0.16.47** (we import its CSS, so
add it directly). `radix-ui` 1.7.0 is what assistant-ui asks for (`^1.7.0`); the repo pins 1.6.7, so align `packages/ui` and `apps/web` to 1.7.0 first or two copies of the primitives get bundled.
`zod` 4.6.5 in `apps/web` already matches.

**Dependencies to add** (all production closure counted by `pnpm licenses`: 351 packages, 187 MB unpacked in `node_modules`, hard-linked from the store):

| Package | Own size (unpacked) | With dependencies | Licence |
|---|---|---|---|
| `@assistant-ui/react` 0.15.29 | 2.9 MB (with `core` 9.4 MB, `assistant-stream` 1.7 MB, `assistant-cloud` 0.6 MB, `safe-content-frame` 0.07 MB, `store`, `tap`) | 82 packages, 36 MB (13 MB of it is `radix-ui`, which we already have) | MIT |
| `streamdown` 2.7.1 | 125 KB | 103 packages, 14 MB (unified, remark, rehype, marked, remend) | Apache-2.0 |
| `@streamdown/code` 2.0.0 + `shiki` 4 | 6 KB | 28 packages, 15 MB | Apache-2.0, MIT |
| `@streamdown/math` 1.0.3 + `katex` | 3 KB (katex 4 MB) | 48 packages, 7 MB | Apache-2.0, MIT |
| `@streamdown/mermaid` 1.0.3 + `mermaid` 11.17.2 | 3 KB (mermaid 122 MB incl. all diagrams and maps) | 114 packages, 131 MB | Apache-2.0, MIT |

Licences in the whole closure: MIT 299, ISC 34, Apache-2.0 6, BSD 8, 0BSD 1, plus `dompurify` (MPL-2.0 OR Apache-2.0: use the Apache-2.0 option), `robust-predicates` (Unlicense, public domain),
`khroma` (MIT in its LICENSE file, missing in its package metadata). No copyleft. Shipped weight is in section 9: **326 KB gzip eager, about 15 MB of lazy chunks**.

**streamdown: GO, with the hardened configuration of section 8 and these conditions:** (a) the safety page (the adversarial message) becomes a permanent test that fails on a tracker hit, a
`__pwned` flag, an element from raw HTML or a link that is not http(s); (b) plugins load lazily, never statically (a static build is +300 KB gzip on every first screen); (c) re-run the test on every streamdown bump;
(d) decide the 15 MB (curated shiki languages, or accept it). **Fallback if the owner says no:** keep our own renderer (it already meets the rules), add code highlighting through a small shiki-core
plugin and math/diagrams later; `@assistant-ui/react-markdown` was not measured.

## CU1 plan (concrete)

Scope is the plan's CU1 (parity, no branching UI, no approvals UI), built so CU2 only adds.

0. **Small PRs first.** (i) Align `radix-ui` to 1.7.0 in `packages/ui` and `apps/web` (run their tests and the Playwright screenshots). (ii) Add the dependencies above to `packages/ui` only
   (`apps/web` and `apps/desktop` get them through it); add `streamdown@2.7.1` to the pnpm release-age exclusions. (iii) A bundle test (`scripts/` or a Vitest on a Vite build): the first-chat
   chunk must not contain `assistant-api.com` or `auiusercontent.com`, and has a gzip budget (start at 330 KB for the chat entry, as measured).
1. **`packages/client`:** `src/chat-tree.ts` (the `treeReducer`, `applyEvent`, `nodeFromStored`, linear fallback for conversations without `parent_id`; from `scratch/cu0/shared/tree-chat.ts`)
   with tests; in `assistant.ts`: `ChatPart` gets an `approval` field and `job_progress` honours an optional `tool_call_id`; `createAssistantApi.get(id, {tree: true})`. `chatReducer` and its
   tests stay.
2. **`packages/client/src/run-follower.ts`:** move the re-attach loop out of `use-assistant-chat.ts` (progress resets the attempt counter, an exception on the first stream loops too, longer
   budget, re-attach on `online`); "Try again" after a connection loss re-attaches instead of re-sending. Tests with the fake stream from `run-client.test.ts`.
3. **`packages/ui/src/chat/thread/`** (new, next to the old files): `use-chat-runtime.ts` (**the only file that imports assistant-ui's runtime API**: `useTreeChat` plus `useExternalStoreRuntime` with a
   `messageRepository`, `isSendDisabled` for `blockedReason`), `convert.ts`, `Thread.tsx` (`ThreadPrimitive`, tokens only), `Composer.tsx` (same element before and after the first message, Enter and
   Shift+Enter, `dir="auto"`), `Message.tsx`, `tool-uis/` (the four existing `ToolCard` branches registered by name through `components.tools.by_name`, reusing `ToolCard` pieces; `confirm_action` placeholder),
   `markdown/` (`Markdown.tsx` with lazy plugins, `md-config.tsx` as in section 8, `SafeLink`), `announcer.tsx` (the live region, section 10).
4. **Mount:** `ChatScreenNext.tsx` with `ChatScreen`'s props; `AssistantHome` takes a `screen` choice; the Labs switch in `apps/web/components/chat/ChatHome.tsx` and `apps/desktop/src/pages/Home.tsx`.
   The web `/chat/[id]` page may fetch `?tree=1` on the server and pass `initialConv` (measured to work).
5. **Engine, additive, with the owner's approval** (CLAUDE.md "Ask before"): `tool_call_id` on `job_progress`; `client_message_id` and `client_reply_id` on a run's input (and `user_message_id`, `assistant_message_id` in `done.outputs`).
   CU1 can ship without these (ids are remapped after `done`), but it is simpler with them. The tree fields stay in CU2.
6. **Tests:** port the 11 `ChatScreen` cases (section 12); add the safety test (Vitest for the pure parts, Playwright for the network and CSP parts in `apps/web/e2e` and a desktop CSP check against
   `dist` with the real CSP string); the parity checklist as Playwright cases at 320 px, light, dark, and right-to-left; delete nothing yet.
7. **Verify in the real window:** run the Tauri app once (WKWebView): streaming, code highlighting, a diagram, the CSP. Chromium results do not prove WebKit.
8. Design: tokens only (ADR-0081), update `design/DESIGN.md` chat patterns and DS3 when it lands.

## What this changes

**ADR-0082** (proposed edits, not made):
- Decision 2: choose **`ExternalStoreRuntime` with a `messageRepository`**, version **0.15.29**; keep LocalRuntime as the documented alternative that was prototyped and passed.
- Decision 3: a conversation read returns **all nodes** (`parent_id`, `head_id`, sibling ids) rather than the active path; results are stored inside the assistant node (the tree is user and assistant only); runs take
  `parent_message_id`, `client_message_id`, `client_reply_id`; `done.outputs` returns the two ids; `PATCH {head_id}` saves the visible branch.
- Decision 4: streamdown is **Go with the hardened configuration** (section 8), not "if it keeps our safety". Add: its defaults fail the rules; mermaid `strict` alone is not enough (`htmlLabels: false`); the CSP does not stop loopback.
- Decision 5: spell out the `interrupt` mapping (an `approval` on a tool call named by the interrupt kind) and add a stored `interrupt` part with `status`, persisted when the run pauses.
- Decision 8: `assistant-stream` and `assistant-cloud` come with core; no stub needed for A. Add `safe-content-frame`: never render `SandboxHost`. `radix-ui` must be 1.7.0.
- Open question 4 (thread list): **keep our Recents list**; `RemoteThreadList` is not needed with A. Open question 7 (notebook chat on the same thread) is **not tested** here.
- Add a decision on accessibility: the library provides no live region; we build the announcer. Add `dir="auto"` to the user bubble and box.

**`docs/chat-ui-migration-plan.md`:** mark CU0 done with this report; CU1 steps as above; add to the contract list the optional `tool_call_id`, the run ids and the stored `interrupt` part; add the risks below.
**`docs/contracts/sse-events.md`:** one optional field (`job_progress.tool_call_id`) needs no ADR; the others are public API shape and need the owner's yes.

## Risks found

1. **0.x API churn, daily releases.** 0.15.30 appeared hours after the tested 0.15.29; two names A uses are marked experimental. Control: exact pin, one adapter file, behaviour tests, bump on purpose.
2. **First-screen weight.** +240 KB gzip over today, about 15 MB of lazy chunks on disk. Control: lazy plugins, the size test, curated shiki languages.
3. **streamdown defaults are unsafe for us** and a bump could change them. Control: the safety page as a permanent test (including the network tracker).
4. **WKWebView untested.** The Tauri window is not Chromium. Regex engines, `ReadableStream` fetch, CSS, mermaid's layout may differ. Control: CU1 step 7.
5. **No live regions** in the library; a screen-reader user would hear nothing, and the old screen's whole-thread `aria-live` is noisy. Control: build the announcer; test with VoiceOver.
6. **Connection loss:** the 5.4 s give-up, the cut before the first event, and "Try again" that duplicates a run. Control: `run-follower.ts`, a client-chosen run id.
7. **Parallel jobs mis-attributed** without `tool_call_id` (already true today).
8. **Stop does not stop the engine** (no cancel call); a reload would show an answer the person stopped.
9. **radix-ui version drift** (1.6.7 against 1.7.0) duplicates primitives in the bundle until aligned.
10. **Mermaid console noise** under the strict CSP (11 messages per hostile diagram) and mermaid's weight; consider a click-to-render diagram.
11. **Hidden remote default in `safe-content-frame`** (`scf.auiusercontent.com`) if anyone ever renders `SandboxHost`. Control: lint rule and the bundle test.
12. **Per-token cost grows with thread length** (1 ms per token at 200 messages in the prototype). Control: measure in CU1 with the real reducer; the repository can be built incrementally.
13. **Component identity trap:** creating the markdown or message component inside a render remounts every message each token. A lint note and a test.
14. **Interrupt lifetime:** what happens to a paused run when the person never answers, or sends a new message first, is not decided (LocalRuntime would cancel the card; A leaves it to us).

## What I could not measure

- **WKWebView / the real Tauri window**, Safari, Firefox (only Chromium 156).
- A real model's streaming rhythm, or the real engine (everything ran against the fake).
- A screen reader (VoiceOver); only the DOM, the accessibility tree and axe.
- The fallback renderer `@assistant-ui/react-markdown` (not installed).
- B in Next.js beyond the render test; B with streamdown; `next dev`.
- The `reasoning` part, attachments, dictation, read-aloud, notebooks on the same thread, the thread list (CU3 to CU5).
- Layout at 320 px, light and dark, with our tokens: the prototype is unstyled by design.
- Tailwind scanning of streamdown's classes in our build.
- 0.12.28 in Next.js; the head-persistence and branch tests beyond what section 11 lists.

## Disclosures

- `next build` **installed `@types/node` 20.17.6 by itself** (types only) into the scratch folder, which was not in the approved list. Nothing else was installed unasked. Scratch only.
- pnpm fetched two more exact pins of the approved 0.12.28 set: `@assistant-ui/store` 0.2.9 and `@assistant-ui/tap` 0.5.10. No Playwright browser was downloaded (the cached Chromium revision 1248 matches Playwright 1.64.1). The assistant-ui CLI was not run.
- Nothing was written in the repo except this file; no lock file, workspace, ADR, plan, code or `CLAUDE.md` was touched.

## Decisions needed from the owner

1. **Runtime and version:** `ExternalStoreRuntime` and 0.15.29 (recommended), or LocalRuntime / 0.12.28.
2. **streamdown:** go with the hardened configuration; and the **15 MB** of lazy chunks (accept, or curate shiki languages first).
3. **Additive engine fields** (public API shape): `job_progress.tool_call_id`, `client_message_id` / `client_reply_id` / `parent_message_id` on a run, the two ids in `done.outputs`, a stored `interrupt` part, and
   what `POST /runs/{id}/resume` carries for `confirm_action`.
4. **A cancel call** for Stop, and a **client-chosen run id** so a cut before the first event can be re-attached.
5. Whether the **size budget** (330 KB gzip eager) is acceptable for the web app, which loads over a network (the desktop loads from disk).
