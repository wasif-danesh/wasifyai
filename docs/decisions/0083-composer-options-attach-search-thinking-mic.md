# ADR-0083: The chat box gets Attach, Search, Thinking and Mic

- **Status:** Accepted (2026-10-19, by the owner). The owner's decisions: these four options are wanted now; **DuckDuckGo** is
  the first search provider. **Stage CO0 is not started** (the owner said to hold it); new dependencies (`ddgs`, `trafilatura`) and
  the downloads are asked for when CO0 starts.
- **Date:** 2026-10-19
- **Update 2026-10-20:** CO0 and CO1 are done, and **CO3 (Search) is built** as decision 4 describes, with these concrete choices: `ddgs` (`backend="duckduckgo"` only, one search at a time, at least 4 s apart, a refusal said in words) is the default; Ollama, Tavily, Exa and Brave Search work with the person's own key behind the same seam; consent is **per service** (choosing another asks again); keys are encrypted at rest with a key file in the app's data folder (the keychain is a later step); the web tools are offered to the model only while Search is switched on for that message; `web_read` opens only addresses the person typed or a search returned; after the web is in a chat, anything that is not a plain read stops (taint rule, and the approval card is not in this screen yet). **Still open for the owner:** nothing for CO3: the dependencies and the DuckDuckGo position were decided the same day (see "Owner decisions on CO3" below).
- **Depends on:** ADR-0082 (chat on assistant-ui; the primitives for attachments, dictation and reasoning), ADR-0057 (the
  assistant), ADR-0068 and ADR-0071 (actions, approvals, action cards), ADR-0070 (trust and the taint rule), ADR-0066 (our
  speech runtime), ADR-0078 (Qwen3.5-9B: reads pictures, thinks by default), ADR-0056 and ADR-0063 (the model slot, will it
  fit), ADR-0035 (upload hardening), ADR-0065 (notebooks reader), ADR-0081 (design tokens), ADR-0047, ADR-0012.
- **Plan:** `docs/composer-options-plan.md`, stages CO0 to CO4.

## Context

The owner's screenshot of Unsloth Studio's composer shows `+` (attach), Search, Tools, Skills, "Approve for me", Thinking and a
mic. `assistant-ui` supplies the plumbing for attachments, dictation, read-aloud and a reasoning part; the **Search, Thinking
and permission controls are Studio's own** features on its own backend (found by reading Studio's code, 2026-10-19). The owner
wants **Attach, Search, Thinking and Mic** in our chat box now.

What exists today (checked in the repo, 2026-10-19):

- **Thinking:** Qwen3.5-9B thinks by default; llama.cpp turns it off with `--reasoning off` or per request with
  `chat_template_kwargs {"enable_thinking": false}` (spike G0, `docs/spikes/agent-g0.md`). Thinking tokens count against
  `max_tokens` (ADR-0018). No `reasoning` event or message part exists.
- **Attach:** an image upload endpoint with hardening exists (ADR-0035) and the multimodal model can read pictures. The desktop
  chat model, run through llama.cpp, needs the model's **vision projector file** to read a picture: for Qwen3.5-9B it is
  `mmproj-F16.gguf`, 0.92 GB (Hugging Face `unsloth/Qwen3.5-9B-GGUF`). Not wired in the app. No attachment in the chat today.
- **Search:** nothing. The assistant's tools search the person's own creations and notebooks only.
- **Mic:** the speech-to-text runtime exists (Parakeet, Whisper; ADR-0066) and transcripts are saved as creations. There is
  **no microphone code** in the window and **no microphone permission** in the Tauri shell. The speech runtime reads **WAV
  only**. The model slot keeps **one resident owner**: starting the speech runtime unloads the chat model and the reverse
  (`SlotManager.hold`), so dictation would evict a 9B model on every use.
- **DuckDuckGo:** the `ddgs` library (PyPI 9.16.0, **MIT**, "a metasearch library that aggregates results from diverse web
  search services"; the renamed `duckduckgo-search`) scrapes search pages; it is unofficial and can break or be rate limited.
  Page text extraction: `trafilatura` (**Apache-2.0**) or `readability-lxml` (Apache-2.0).

## Decision

1. **One shared composer options bar** (`ComposerOptions` in `packages/ui`): `+` Attach, Search, Thinking, Mic and the send/stop
   button, in our own token-styled components, with a small state hook (`useComposerOptions`, per conversation). It works in
   the **current** composer and in the assistant-ui composer (CU1), so none of this waits for the chat migration. A button
   appears only when it can work (a model without thinking has no Thinking button; no speech model shows a setup state on the
   Mic), and every disabled button says why.
2. **Thinking.**
   - A request option `thinking: on | off`, **off by default** (ADR-0078), per conversation, passed by the text provider to
     llama.cpp (`chat_template_kwargs`) and to hosted models through the alias setting.
   - The model's thinking text is returned as a new **optional `reasoning` event** and stored as a `reasoning` message part,
     **never sent back as context** on the next turn; shown collapsed under "Thinking" (assistant-ui's reasoning part from
     CU1; a simple collapsible before it).
   - A Thinking turn gets a larger token budget and the screen says it takes longer. The button needs a **capability flag**
     on the model (its chat template supports thinking), read when the model is chosen.
3. **Attach.** `+` opens a file picker and accepts drag and drop and paste.
   - **Pictures** (PNG, JPEG, WebP): hardened as today (decode, correct rotation, strip metadata, size limit; ADR-0035), shown as
     a thumbnail in the box, sent to the model as an image part. Needs the vision projector for the chosen model: **offered as a
     download with its size** (0.92 GB for Qwen3.5-9B) the first time a picture is attached, and a hosted model needs nothing.
   - **Text, Markdown, CSV and PDF** (and Word where the notebooks reader is installed): turned into text on the engine
     (the notebooks reader for PDF and Office; ADR-0065), cut to the model's window with the notebooks' "whole, an even share,
     or the best passages" rule, shown to the person as an attached chip with a page or character count. Large files get
     "Add this to a notebook instead?".
   - Attachments are stored with the conversation through the storage interface, deleted with it, and never indexed as
     separate creations. A picture the model makes from an attachment is a normal creation.
4. **Search (the web), DuckDuckGo first.**
   - **Off by default and opt-in.** The first use shows a **consent card**: "Searching the web sends your question to
     DuckDuckGo. Results are read by the assistant on this computer." The choice is remembered per person and can be turned
     off in Settings. Search is never silent.
   - Two actions join the catalogue (ADR-0068): **`web.search(query)`** and **`web.read(url)`**, effect `read`, flags
     `leaves_device` and `needs_consent` (first use). They go through the executor with audit and usage events.
   - A provider-neutral capability, **`caps.web.search` and `caps.web.read`** (rule 4), with `ddgs` as the first provider
     behind it and a keyed provider (Brave, Tavily or the person's own) as the documented second, so the unofficial
     scraper can be replaced without touching the assistant.
   - `web.read` fetches a page with an **SSRF guard** (no loopback, private, link-local or metadata addresses, including after
     redirects; only `http` and `https`; size, time and content-type limits), extracts the main text with `trafilatura`, and
     returns text plus the URL and the time read.
   - **Web text is untrusted.** The **taint rule** of ADR-0070 applies: after a web result is in the conversation, any action
     that is not a plain read asks the person first. The prompt tells the model that web text is quoted material, not
     instructions (as notebooks do).
   - **Sources are always shown:** result cards under the answer with title, site and a link, and citations in the text; a
     reply that used the web says so.
   - Queries are not stored beyond the conversation; the search provider and the consent are shown in Settings. The **hosted
     web product** uses a server-side provider with our key, quotas and a cost limit; it is behind the same consent and the
     safeguards switch (ADR-0047).
5. **Mic (dictation).**
   - **Record, then transcribe** (v1): press the mic, press again; the clip becomes 16 kHz mono **WAV in the window** (no
     ffmpeg); a no-save route transcribes it with the chosen speech model and **returns text only** (nothing becomes a
     creation unless the person asks); the text lands in the box to edit. Live word-by-word dictation is later.
   - **The browser's speech API is not used** (it sends audio to a third party and does not work offline in the desktop
     webview).
   - **Tauri shell:** a microphone usage description and entitlement so macOS asks once. Whether the shell's webview allows
     `getUserMedia` is **unverified** and is the first CO0 check.
   - **Setup card** when no speech model is installed (what, where from, size, licence, one click; ADR-0066 runtime). Language
     follows the model's languages (Parakeet about 25 European ones; Whisper more); the picker says so.
   - **The model slot gets a "light owner" rule:** a small speech model may stay resident next to the chat model when the fit
     check (ADR-0063) says they fit together; otherwise dictation says so and falls back to unloading. This is a small change
     to `SlotManager` with a measurement (CO0), and it also serves the sorter (ADR-0075).
   - On the web, the browser records and uploads to the hosted transcribe alias under its existing daily limits.
6. **assistant-ui mapping (CU1 to CU3):** `+` and the attachment chips use its attachment adapters, the mic uses its dictation
   adapter calling our recorder and route, Thinking uses its reasoning part. Search and the permission-style controls stay our
   own components. Until CU1, the same options bar sits on the current composer.
7. **What is not in this ADR:** Tools and Skills buttons (they need the MCP client of ADR-0070 or a skills concept), an
   "Approve for me" mode (a design decision for stage A2; `destroy` and `needs_consent` actions always ask), read-aloud
   (CU3), live dictation, web image search, a research mode.
8. **Dependencies (asked for in CO0, versions pinned):** `ddgs` (MIT) and `trafilatura` (Apache-2.0) in the engine; nothing new
   in the window for Thinking, Attach or the recorder (the browser's `MediaRecorder` or an `AudioWorklet` is enough). The
   vision projector (0.92 GB) and a speech model are downloads with the owner's yes, sizes shown.
9. **Safety and privacy summary:** no network request for search without the person's opt-in; web and attachment text is
   untrusted and quoted; microphone audio is processed on this computer and not kept by default; the microphone is only on
   while recording, with a visible indicator; attachments obey upload hardening; all of it is audited and counted like any
   action.

## Consequences

- The chat box matches what people expect from Studio and other assistants, with the four things the owner asked for, built so
  that each works with the current composer and the assistant-ui one.
- A new capability class (web access) arrives with its own security work (SSRF guard, taint rule, consent), which is also what
  the agent (ADR-0072) needs, so it is built once.
- Search quality rests on an unofficial scraper at first; the provider seam and the sources display limit the damage.
- Dictation needs a slot-manager change and a shell permission; both are small but touch core code.
- Vision input needs a 0.92 GB download for the default model on the desktop.

## Alternatives considered

- **A search-only API provider first (Brave, Tavily):** more reliable, but needs a key and a cost; kept as the second provider.
- **Self-hosted SearXNG (AGPL-3.0):** private, but a service to run; a candidate for the hosted product, not the desktop.
- **The browser's built-in speech recognition for the mic:** simple but not private or offline.
- **Streaming (live) dictation first:** nicer, but needs partial results from the speech runtime; deferred.
- **Wait for the assistant-ui migration:** the options bar is independent of the thread, so there is no reason to wait.

## Open questions

1. Whether `getUserMedia` works in the Tauri webview on macOS with the right entitlement (CO0).
2. How `ddgs` behaves under repeated use (rate limits, result quality, region and safe-search settings, breakage) and DuckDuckGo's
   terms for this use (CO0 reads them; the owner decides).
3. The reasoning field name and streaming format from llama.cpp in our setup, and with Ollama and LM Studio servers.
4. The light-owner rule's memory limits on 16 and 32 GB Macs.
5. PDF and Office text extraction without the notebooks reader installed.
6. Whether web search should be available to agents under the same consent, or have its own.

## Owner decisions on CO3 (2026-10-20)

**A. Dependencies: approved.** `ddgs` 9.16.0 (MIT) and `trafilatura` 2.3.1 (Apache-2.0), as pinned in `packages/platform-sdk` and locked in `uv.lock`.

**B. DuckDuckGo: stays the default, the terms risk is accepted.** The owner knows that DuckDuckGo's terms do not mention automated use, offer no search API and forbid
"displaying" the service inside another service (CO0 section 5), and that `ddgs` is an unofficial scraper DuckDuckGo can block at any time. **When it stops working, the
app tells the person in words to add a search key in Settings** and use another service (Ollama, Tavily, Exa or Brave Search): both the "busy" and the "could not be reached" messages say so.
Counsel has not been asked; revisit before a public release if the risk changes.

## Not in v1

Tools and Skills buttons, "Approve for me", live dictation, read-aloud of replies (CU3), image search, deep research, search history,
voice conversations.
