# Composer options plan: Attach, Search, Thinking, Mic

Written 2026-10-19 for ADR-0083 (Accepted by the owner the same day). **Status (2026-10-20): the owner said start; CO0 is done (`docs/spikes/composer-co0.md`) and CO1 (the options bar and Thinking)
is built; CO3 (Search) is built (2026-10-20, see "What CO3 built" in the spike report); CO2 (Attach) and CO4 (Mic) are not started.** The chat box gets four options. The options bar is built once and works in the **usual** composer and the assistant-ui one
(`docs/chat-ui-migration-plan.md`, stage CU1, built behind Labs).

## The four options at a glance

| Option | What the person sees | Engine work | New dependency or download | Size |
|---|---|---|---|---|
| **Thinking** | a toggle, off by default; the thinking text collapsed under the answer | request option, capability flag, `reasoning` event and part, bigger token budget | none | S |
| **Attach** | `+`, drag and drop, paste; a thumbnail or a file chip in the box | hardened upload, image part, text extraction, window fitting, vision projector setup | `mmproj-F16.gguf` 0.92 GB for Qwen3.5-9B (owner's yes) | M |
| **Search** | a toggle, off by default; a consent card on first use; source cards under the answer | `caps.web.*`, `web.search` and `web.read` actions, SSRF guard, extraction, taint rule | `ddgs` (MIT), `trafilatura` (Apache-2.0) (owner's yes) | M |
| **Mic** | press to record, press to stop, "Transcribing…", text in the box | WAV recorder in the window, no-save transcribe route, setup card, light-owner slot rule | a speech model if none installed (owner's yes, size shown); Tauri microphone permission | M |

## Stages

| Stage | What | Size | Done when |
|---|---|---|---|
| **CO0** | **Done 2026-10-20 (`docs/spikes/composer-co0.md`).** **Spikes and approvals** (one short session): (1) does `getUserMedia` work in the Tauri window on macOS with the entitlement, and does a WAV recorder produce what the runtime reads; (2) `ddgs`: result quality, speed, rate limits, regions, breakage, and DuckDuckGo's terms for this use, read and summarised; `trafilatura` against `readability-lxml` on 20 pages; (3) how llama.cpp streams thinking (field name, `--reasoning-format`) for Qwen3.5-9B, and with Ollama and LM Studio servers; (4) the vision projector: pictures described by Qwen3.5-9B with `--mmproj`, memory and speed; (5) the light-owner rule: can Parakeet stay resident beside the 9B chat model, memory on this Mac and what a 16 and 32 GB Mac would need | S | `docs/spikes/composer-co0.md` with measured answers and a go or no-go per option; the owner approves the dependencies |
| **CO1** | **Built 2026-10-20 (see "What CO1 built" in the spike report).** **The options bar and Thinking.** `ComposerOptions` and `useComposerOptions` in `packages/ui`, token-styled, on the current composer; the `thinking` request option; the model capability flag; the `reasoning` event and message part; a collapsible "Thinking"; token budget; tests on both profiles | S to M | A thinking turn shows its reasoning collapsed and does not feed it back; a model without thinking has no button; light, dark and phone layouts pass |
| **CO2** | **Attach.** Picture and document attachments end to end: hardened upload, thumbnail and chips, image parts to the model, document text through the notebooks reader and the window-fitting rule, "Add to a notebook instead?" for large files, the vision projector setup card, deletion with the conversation | M | A picture can be attached and described locally; a PDF can be attached and questioned; a hostile file is refused in words |
| **CO3** | **Built 2026-10-20 (see "What CO3 built" in the spike report).** **Search.** `caps.web.search` and `caps.web.read` with `ddgs` and a keyed-provider seam; the actions in the catalogue (`leaves_device`, `needs_consent`); the SSRF guard; extraction; the taint rule; the consent card and Settings; source cards and citations; quotas and usage events; evaluation cases (answers that need the web, injection pages, refusal to act after reading a hostile page) | M | The assistant answers a current-events question with cited sources after the consent card; a page that tells the model to delete things is shown as quoted text and no action runs without a click |
| **CO4** | **Mic.** Tauri microphone permission; the WAV recorder; the no-save transcribe route (an additive route or `speech.transcribe` with `save: false`); the setup card; the light-owner rule in `SlotManager`; the mic button with a visible recording state; the hosted-web path | M | Dictation fills the box in a few seconds without unloading the chat model on this Mac; the OS asks for the microphone once; audio is not kept |

## Order and how it fits the other work

1. **CO0 first.** It decides what is feasible and asks for the dependencies.
2. **CO1 (Thinking and the bar)** next: it is the smallest, it creates the bar the other three plug into, and it needs no download.
3. **CO2 (Attach) and CO3 (Search)** can run in parallel sessions once the bar exists: they touch different engine code (uploads and
   extraction against web access and consent) and share only the bar.
4. **CO4 (Mic)** after the slot change is measured; it can start its shell work early.
5. **The chat migration (CU0 to CU4)** runs beside this. CU1 swaps the thread under the same bar; CU3 then switches attachments
   and dictation onto assistant-ui's adapters without changing the engine routes built here.
6. **The design system (DS3)** gets the bar, the consent card, source cards and the attachment chips as catalogue items.
7. **The action catalogue (A1, built)** gains `web.search` and `web.read` in CO3; adding them is one file each.

## Security and privacy checklist (reviewed at the end of CO3 and CO4)

- Search and web reading are off until the person says yes; the card names the provider; the setting can be turned off.
- Fetches cannot reach loopback, private, link-local or metadata addresses, including through redirects; only http and https; size
  and time limits; no cookies or credentials are sent.
- Web and attachment text is quoted as untrusted; after it, non-read actions ask the person (taint rule).
- No raw HTML from a page or a model runs; links open only if `http(s)`.
- The microphone is on only while recording, with a visible indicator; audio is processed on this computer and not saved by default.
- Attachments obey upload hardening, are stored through the storage interface and are deleted with the conversation.
- Queries and clips are not written to logs or metrics (ADR-0048).

## Test strategy

- Unit tests for each option's engine path with fakes (a fake search provider, a fake speech runtime, a fake model that emits thinking).
- Hostile cases in CI: SSRF addresses and redirects, a prompt-injection page, an oversized page, a poisoned PDF, a clip with silence.
- Playwright layout and screenshot checks for the bar in light, dark and phone widths; the token lint covers the new files.
- Evaluation: the assistant's tool cases run with thinking on and off; search answer cases with and without sources.

## Decisions needed from the owner

1. ~~Say yes to the plan and ADR-0083~~ done 2026-10-19. **Say when to start CO0.**
2. Approve the dependencies at CO0: `ddgs`, `trafilatura` (engine), and the downloads: the vision projector (0.92 GB) and, if none is
   installed, a speech model (size shown).
3. After CO0: accept or change DuckDuckGo's terms position, and the keyed second provider (Brave, Tavily, or none for now).
4. Whether Thinking should default to off everywhere (recommended, per ADR-0078) or on for the agent.
