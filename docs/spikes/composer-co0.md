# Spike CO0: the four options of the chat box, measured

Date: 2026-10-20. Machine: MacBook Pro, Apple M5 Pro, 64 GB, macOS. Plan: `docs/composer-options-plan.md`, stage CO0. Decision tested:
ADR-0083 (Attach, Search, Thinking, Mic). The owner said "start CO0 and CO1" and "I approve the downloads" on 2026-10-20.
The spike changed nothing in the repo (a temporary microphone page was added to the desktop window for one run and removed; its files and the
`Info.plist` it needed are in the scratch folder). CO1 (below, "What CO1 built") is the only code change of this session.

Scratch folder (outside the repo, kept): `~/Projects/wasifyai-spikes/co0/` (scripts, raw logs in `logs/`, the recorded `mic.wav`, a Python
environment with `ddgs`, `trafilatura` and `readability-lxml` installed **there only**). llama.cpp: the app's own install, **build 11655**
(`engine/llamacpp/b11655`, Metal). Model: `unsloth/Qwen3.5-9B-GGUF` `Qwen3.5-9B-Q4_K_M.gguf` (5.68 GB) with `mmproj-F16.gguf` (918,166,080
bytes; **it was already in the Hugging Face cache on this Mac**, so no download was needed for the measurements). Speech runtime: the app's
`audiocpp_server` v0.9.0-unsloth.1 with Parakeet TDT 0.6B v3 (q8_0). Anything not run is marked **not verified**.

## Result in one screen

| Question | Answer |
|---|---|
| **Thinking:** how does llama.cpp stream it? | In the OpenAI stream, `delta.reasoning_content`, **before** `delta.content`. Per request `chat_template_kwargs: {"enable_thinking": false}` turns it off and **works** (0.3 s and 9 tokens for "17 times 23", against 23 s and 1,001 tokens with thinking). Ollama's field is **`reasoning`**, not `reasoning_content`. **The app today leaves thinking ON** (it sends no switch): a trivial question costs about a thousand tokens, and with a token limit of 1,500 the answer never arrived (the thinking used it all) |
| Thinking, other servers | **Ollama 0.40.5:** `gpt-oss:20b` always thinks (`think=false` is ignored; `reasoning_effort: low` cuts it from 249 to 8 thinking tokens); `gemma4:e4b` does not think by default and sends no reasoning. **LM Studio: not installed, not verified** |
| **Attach (pictures):** vision with `--mmproj` | **Works.** A 768 x 512 picture costs **411 prompt tokens** and 2.4 s, and the model read the sign text ("OPEN 24h") exactly. Memory: **6.70 GB** against 5.84 GB without the projector (the projector adds about **0.9 GB**). A 3072 x 2048 picture costs **4,083 tokens and 18.6 s** and the answer got worse (it called the teapot "an alarm clock"): **pictures must be fitted to about 1,024 pixels on the long edge before they are sent** |
| **Mic:** `getUserMedia` in the Tauri window | **Works in WKWebView**, on the real desktop app (`pnpm tauri:dev`): secure context, `mediaDevices` present, the macOS prompt appeared once (2.0 s the first time, 9 ms after). Needs `NSMicrophoneUsageDescription` in `src-tauri/Info.plist` (dev builds embed it in the binary; **forced a rebuild**: Cargo does not watch that file) |
| Mic: a recorder that the runtime reads | **Yes.** An `AudioWorklet` loaded from the app's own file (`/recorder-worklet.js`; **a blob URL would be refused by the window's policy**, `default-src 'self'`), 44.1 kHz input, averaged down to **16 kHz mono 16-bit WAV in the page**: Parakeet transcribed it in **54 ms** (3.3 s of audio). The page's own request to `127.0.0.1` worked under the policy |
| Mic: the device | The first two recordings were silent (peak 0.001 and 0.000): the system's default input was a **speaker with a microphone ("Creative Pebble Pro")**. The track's label is available, so the button can show which microphone is listening. With the MacBook microphone and the default constraints the level was good (peak 0.59). A "raw" recording (no echo cancellation, noise suppression or gain control) was very quiet (peak 0.0034): **inconclusive** (the speaker may have been quiet); use the browser's default constraints |
| **Mic:** can Parakeet stay resident beside the chat model? | **Yes on this Mac.** Parakeet resident: **2.42 GB**, loads in **8.1 s** the first time, **58 ms** warm. With the 9B model **and its projector** loaded (6.85 GB) both together are **9.3 GB**. Dictating **while the chat model was writing** took 0.10 s and the chat speed did not change (44.3 tokens/s alone and while dictating) |
| **Search:** `ddgs` 9.16.0 (MIT) | **Fragile with DuckDuckGo alone.** The `duckduckgo` backend returned results for the first query and then "No results found" at 0.15 s for the rest (1/20 at a 1 s pause, 2/8 at 8 s). The raw page shows why: **HTTP 202 and DuckDuckGo's bot challenge** (`anomaly`) after a few automated queries. At **one query a minute** after a rest it worked: 4 of 5, 0.9 s each. The `auto` backend (several engines at once) returned results for 15 of 20, median **6.3 s**, **including advertisement links** (`bing.com/aclick`) and a bug with some regions (`us.wikipedia.org` does not resolve). Single engines: `bing` 14/20, `yahoo` 12/20, `brave`, `mojeek` and `google` 0/20 |
| DuckDuckGo's terms | Read 2026-10-20 (`duckduckgo.com/terms` and `/acceptable-use`). They **do not mention automated queries or scraping** and offer **no public search API** (only Instant Answers). They say use must be "authorized" or access may be suspended, and the acceptable-use list forbids to "frame, inline link, or similarly display any portion of the services within another service" and to "sell or resell any portion of the services". Showing result titles and links inside our chat can be read as that. **This is a summary, not legal advice** |
| Page text: `trafilatura` against `readability-lxml` | 20 pages (17 fetched). `trafilatura` 2.3.1 (Apache-2.0) found **470,228 characters against 302,586**, and was the better one on every long page (Python docs 114,171 against 13,909; Hindi Wikipedia 18,543 against 5,547; Japanese Wikipedia 43,002 against 21,925); 12 to 300 ms a page. **Both found nothing** on pages that need JavaScript or are index pages (Hacker News, Arduino docs, Rust blog, the Guardian section page), and Reuters (401) and Stack Overflow (403) refuse non-browser clients: **a "could not read this page" path is needed** |
| Licences | `ddgs` MIT, `trafilatura` Apache-2.0, `readability-lxml` Apache-2.0, `lxml` BSD-3-Clause, `primp` MIT |
| Go or no-go | **Thinking: go (CO1, built). Attach: go** (download the projector, fit the picture). **Mic: go** (shell permission, worklet from our own file, light-owner rule). **Search: conditional on the owner's decision about DuckDuckGo** (below) |

## 1. Thinking (llama.cpp and other servers)

`tests` are `stream_probe.py` and `ollama_probe.py` (raw output in `logs/probe_default.txt`, `logs/probe_ollama.txt`). One question ("What is
17 times 23? Answer with just the number and one short sentence."), streamed, `max_tokens` 1,500:

| Server and option | Delta fields seen, in order | Time and tokens |
|---|---|---|
| llama.cpp, no option | `reasoning_content` ×1,500, **no content at all**, `finish_reason: length` | 32.9 s, 1,500 tokens (cut) |
| llama.cpp, `enable_thinking: false` | `content` only | 0.3 s, 9 tokens: "The result is 391." |
| llama.cpp, `enable_thinking: true` | `reasoning_content` ×981 (4.7 s of nothing else), then `content` ×17 | 23.0 s, 1,001 tokens |
| llama.cpp, no option, `max_tokens: 60` | `reasoning_content` ×60, no content | the answer is lost when the budget ends inside the thinking |
| Ollama `gpt-oss:20b`, default | `reasoning` ×249, then `content` ×11 | 8.9 s |
| Ollama `gpt-oss:20b`, `reasoning_effort: "low"` | `reasoning` ×8, `content` ×10 | 0.8 s |
| Ollama `gpt-oss:20b`, `think: false` | **still `reasoning` ×568** | 12.1 s (the flag is ignored on this endpoint) |
| Ollama `gemma4:e4b`, any option | `content` only | 0.1 to 7.9 s (first call loads the model) |

- **For CO1:** read `delta.reasoning_content` or `delta.reasoning` (whichever is there); send `chat_template_kwargs {"enable_thinking": bool}`
  to the app's **own** llama-server on every chat request (off unless the person switched Thinking on); leave other tools' models as they are and pass
  on any thinking they send. The capability flag is read from the GGUF chat template: the Qwen3.5-9B template contains `enable_thinking`
  (7,816 characters, `enable_thinking` and `<think>` both present); the Ollama blob of `gpt-oss:20b` has no template at all in the file.
- **A trap found:** with thinking on, a limit on the answer's tokens also limits the thinking. The assistant sends no `max_tokens` (the
  context is the limit); keep it so, and say in the screen that a thinking answer takes longer.
- **Ollama, found while fixing "no button" on the owner's machine (their chosen model is `gpt-oss:20b` through Ollama, not the app's own server):**
  `/api/show` lists each model's abilities and says `thinking` for both `gpt-oss:20b` and `gemma4:e4b` (`['completion', 'tools', 'thinking']`); on the OpenAI endpoint `think: true` makes
  `gemma4:e4b` think (107 reasoning tokens, 0.9 s) and it does not by default; `reasoning_effort` is the only switch of `gpt-oss:20b` (`none` is ignored: 494 tokens, 9.8 s; `low`: 39 tokens, 0.7 s;
  `medium`: 219; `high`: 468). The app now sends `think` and `reasoning_effort` ("low" when off, "medium" when on) to an Ollama model that says it can think. A saved choice is read again
  at every start (the owner's was saved before the flag existed, which is why no button showed). LM Studio: not installed, no switch.
- Not measured: whether a hosted model through LiteLLM passes `chat_template_kwargs` (it depends on the provider; CO1 reads the alias's own
  setting `thinking_options` and sends nothing when there is none).

## 2. Attach: pictures through the vision projector

`vision_probe.py`, `vision_big.py` (logs `vision.txt`, `vision_big.txt`). llama-server `-ngl 99 --jinja -fa on -np 1 -c 8192 --cache-ram 512`
with `--mmproj mmproj-F16.gguf` (loaded in 2 s, model already warm in the file cache):

| Picture | Prompt tokens | First request | Same picture again | Answer |
|---|---|---|---|---|
| 768 x 512 PNG | 411 | 2.4 s (484 tokens/s read, 45.5 written) | 1.2 s (the picture is cached) | exact: red teapot, blue sign "OPEN 24h" |
| 3072 x 2048 PNG (same drawing) | **4,083** | **18.6 s** (239 tokens/s) | 2.3 s | **wrong the first time** ("an alarm clock", "OPEN 24") |

Memory (server RSS): 6.70 GB after load with the projector, 6.84 GB after the small picture, 7.38 GB after the big one. llama.cpp warns that
Qwen-VL models "require at minimum 1024 image tokens" for grounding tasks (`--image-min-tokens`); we use descriptions, so the default was kept.
**For CO2:** fit every picture to about 1,024 pixels on the long edge (the upload hardening already re-encodes it); offer the 918 MB projector as
a download with its size the first time a picture is attached; a hosted model needs nothing. The projector must be **selected with the model**
(`--mmproj`), which means the language server restarts when it is first needed. **Not tested:** a projector for any model other than
Qwen3.5-9B; Ollama's and LM Studio's own picture paths.

## 3. Mic: the Tauri window (WKWebView)

Facts read in the code first: wry 0.57 (`webkit` UI delegate) **grants** a media-capture request by default and lets the shell set a
`permission_handler`; Tauri 2's `tauri-codegen` embeds `src-tauri/Info.plist` into the **dev** binary and merges it into a **bundle**; the repo has
**no `Info.plist` and no entitlements file**, and the window's policy is `default-src 'self'; connect-src 'self' ipc: http://ipc.localhost
http://127.0.0.1:*; img-src ...`.

The run (owner's hands, real window, 2026-10-20 14:06 to 14:10): a temporary page with a button; `getUserMedia` (mono), an `AudioContext`
(44,100 Hz, state `suspended` until resumed), an `AudioWorklet` from `/recorder-worklet.js`, 4 seconds, the blocks averaged to 16 kHz and written as
a WAV, sent to a loopback scratch server. Results:

| Check | Result |
|---|---|
| `isSecureContext`, `navigator.mediaDevices` | `true`, present (origin `http://localhost:1420`) |
| The permission | macOS asked once; `getUserMedia` resolved after 2,038 ms including the prompt, then in 7 to 176 ms |
| Worklet from our own file under `default-src 'self'` | works; **a worklet from a blob URL was not tried and would be refused** by that policy |
| The WAV | 16,000 Hz, 1 channel, 16-bit, 3.32 s; read by the speech runtime as 'Hello this is the test one two three this is the test' in 54 ms |
| Tracks | `readyState: ended` after `stop()`: the microphone is released |
| Which microphone | the track's label was shown ("MacBook Pro Microphone", earlier "Creative Pebble Pro"); the silent runs were the speaker's |
| Posting the result to `127.0.0.1` | allowed by the policy (`fetch` answered 200 and image requests got through). **Unexplained:** the first two POSTs answered 200 but my first scratch server wrote no file; the later ones (a rewritten server) arrived |

**For CO4:** add `src-tauri/Info.plist` with `NSMicrophoneUsageDescription` (the wording used in the spike is in the scratch folder), and, for the
signed bundle, an entitlements file with `com.apple.security.device.audio-input` referenced from `bundle.macOS.entitlements` (**not tested**:
no signed build was made); keep the permission handler unset (the default grants the page, the operating system still asks); ship the worklet as a file in the window's
`public/`; show the microphone's name and a visible recording state; resample in the page. The prompt text must say that nothing is
recorded or kept. A `touch src-tauri/build.rs` is needed after editing `Info.plist` in development.

## 4. Mic: the model slot

`concurrent.py`. `audiocpp_server --config` with one `asr` model (family `parakeet_tdt`, not `parakeet`), `lazy_load`, next to llama-server
(Qwen3.5-9B Q4_K_M, projector, 8,192 context):

| | Resident memory | Time |
|---|---|---|
| llama-server, 9B and projector, after a picture | 6.85 GB (RSS) | |
| `audiocpp_server` idle | 0.01 GB | |
| Parakeet loaded | **2.42 GB** | first transcription **8.05 s** (load), then 58 ms for 5.3 s of speech |
| Both | **9.3 GB** (RSS counts the mapped file, so this overstates) | chat 44.3 tokens/s alone and 44.3 while dictating; dictation 0.10 s while the chat model writes |

The fit check (`desktop_fit`: unified memory, capacity 90%, budget 75% of the memory) puts the chat model (5.7 GB file + 0.9 projector + 0.3 cache + 0.6
overhead, about 7.5 GB) and Parakeet (2.4 GB) at about **10 GB together**: a **16 GB Mac** has a budget of 12 GB (fits, tight with other apps); a **32 GB Mac** 24 GB
(fits easily); an **8 GB Mac** cannot run the 9B model at all. **Rule for CO4:** a small speech model may stay resident beside the chat model when
the two needs together fit the budget the fit check gives; otherwise dictation says so and falls back to the current swap (one owner at a time).

## 5. Search: `ddgs`, DuckDuckGo and page text

`ddgs_probe.py` (20 queries in 12 regions and languages: English, German, French, Spanish, Arabic, Japanese, Hindi, Bengali), `extract_probe.py`
(logs `ddgs_*.json`, `extract.json`):

| Backend and pause | Returned results | Median time | Notes |
|---|---|---|---|
| `duckduckgo`, 1 s | 1 of 20 | 1.8 s (the one) | then "No results found" in 0.15 s: DuckDuckGo's challenge |
| `duckduckgo`, 8 s | 2 of 8 | 1.4 s | the same |
| `duckduckgo`, 60 s (after 10 minutes of rest) | **4 of 5** | 0.9 s | the realistic use of one person |
| `auto` (the library mixes engines), 2 s | 15 of 20 | 6.3 s | includes **advertisement links**; some regions fail on a Wikipedia lookup (`us.wikipedia.org`) |
| `bing` / `yahoo` | 14 of 20 / 12 of 20 | 6.3 s / 2.5 s | |
| `brave` / `mojeek` / `google` | 0 of 20 | | blocked or "No results found" from this address |

A direct request to `html.duckduckgo.com/html/` from `curl` got **HTTP 200 with nine results once**, then **HTTP 202 and the challenge for ten in a
row** at 3 s apart. So the limit is DuckDuckGo's against automated bursts from one address, not a fault of the library; at the pace of one person
asking now and then it works, and an agent that searches in a loop will be blocked. Non-English queries returned results in every language tried (the `auto` runs).

**Options for the owner (not decided here):**
1. **`ddgs` with `backend="duckduckgo"` only,** honest consent card ("your question goes to DuckDuckGo"), one search at a time with a minimum gap, a clear
   "search is busy, try again in a minute" when challenged. Cheapest; breaks when DuckDuckGo changes its page; the terms question above stays.
2. **`ddgs` `auto`:** works more often and is slower, but sends the question to several engines (the card would have to say which), returns ads.
3. **A keyed provider first** (Brave Search API, Tavily, or the person's own key; **their terms and prices were not read or tested here**): reliable and allowed, costs
   money or needs a key. ADR-0083 already puts it second behind the provider seam.
4. **A self-hosted SearXNG** (AGPL-3.0, a service to run): not for the desktop.

## What CO1 built (the same day)

The options bar and Thinking, end to end (`docs/composer-options-plan.md`, CO1): `ComposerOptions` and `useComposerOptions` (`packages/ui/src/chat/composer-options.tsx`),
on the usual chat and on the new one; the run input `thinking` (off by default, remembered per conversation); the capability read from the model's chat template
(`GET /products/wasifyai-assistant/options`); the `reasoning` event and the stored `reasoning` part, shown collapsed under "Thinking" and never given back to the model; the
app's own llama-server told per request whether to think (`chat_template_kwargs`), which also **stops the silent thinking the app did before**. Tests on the
in-memory, SQLite (desktop) profile and in the browser at 320 px, light and dark. The Attach, Search and Mic buttons are not built (CO2 to CO4).

## What CO3 built (2026-10-20)

Search, end to end (`docs/composer-options-plan.md`, CO3); option 1 above, plus keyed services behind the same seam.

- **Engine:** `wasifyai_platform_sdk/web.py` (`caps.web.search` / `caps.web.read`: providers DuckDuckGo via `ddgs`, Ollama, Tavily, Exa, Brave Search; `WebReader` with the SSRF
  guard: http/https on ports 80, 443, 8080, 8443 only, no loopback, private, link-local or metadata address whether typed, looked up or reached by a redirect, the connection goes to the checked
  address, no cookies, 2 MB and 15 s limits; `trafilatura` for the text, 12,000 characters at most) and `wasifyai_api/web_search.py` (`WebService`: the person's service, consent
  per service, encrypted keys, readiness, usage events with no query or address in them). Actions `web.search` and `web.read` in the catalogue (effect `read`, `leaves_device`,
  need `web`), help files, tool-host methods, `GET/PUT /products/wasifyai-assistant/search` and the `search` part of `/options`.
- **Assistant:** the run option `search` (off by default); the web tools and a short prompt about untrusted text are offered only on a message sent with Search on; `web_read` is
  limited to addresses the person typed or a search returned; once the web is in the chat, every non-read action goes through the approval policy and is refused in words
  (there is no approval card in this screen yet).
- **Window:** the Search button and its consent card (`composer-options.tsx`), the "needs your key" card, source cards for `web_search` and `web_read` on both chat screens
  (links open in the person's own browser through the shell's `open_external`, http and https only), and "Searching the web" in Settings (service, permission, key).
- **Found while testing for real:** when DuckDuckGo answers with its bot challenge, `ddgs` returns **one row with every field empty** instead of an error. That is now treated
  as "busy" (said in words), not as "nothing found". A live read of a Wikipedia article (11,882 characters, cut) and the refusals of `127.0.0.1`, the metadata address and `file://`
  were checked on this Mac. **A live DuckDuckGo search returned only the challenge from this address that day, so result quality of a live search was not re-checked.**
- **Not done:** the approval card for actions after the web was read (A2), the keychain for keys, the hosted web product's server-side provider (the web app shows no Search button
  because it has no web service yet), and the evaluation cases against a real model (the graph tests use a fake model).

## What CO4 built (2026-10-20)

Mic (dictation), end to end (`docs/composer-options-plan.md`, CO4; ADR-0083 decision 5).

- **Window:** a **Mic** entry in the options bar (`composer-options.tsx`; the state and the cards are in `packages/ui/src/chat/dictation/`). Press, speak, press **Stop** (the same pill); while it listens
  a card shows a pulsing dot, "Listening with <the microphone's name> · 0:07" and a Cancel; then "Transcribing…"; the words land **after what is already in the box**, to be changed, and are never sent
  by themselves. It works on both chat screens (`ChatScreen` gets the text through its draft, `ChatScreenNext` through `DictationBridge`, a component inside the runtime that sets the composer's text).
  The recorder (`recorder.ts`, `wav.ts`) is the one CO0 proved: `getUserMedia`, an `AudioWorklet` loaded from the app's own file `/recorder-worklet.js` (**the same file in `packages/ui/public`, served
  by the desktop through Vite's `publicDir`, and a copy in `apps/web/public`; a test keeps them identical**), the samples averaged down to 16 kHz mono 16-bit in the page, the microphone released on
  Stop, Cancel or leaving the screen. A clip is stopped at 290 s. A silent clip (peak under 0.004) or one shorter than 0.3 s is refused in the window without an upload. Every failure is a sentence:
  the microphone is turned off for this app / none was found / another app is using it / this window cannot use a microphone / nothing could be heard / no words were caught / the engine's own sentence
  (for example "The speech model is busy").
- **Engine:** `POST /products/wasifyai-voice/dictation` (`wasifyai_voice/routes.py`, checks in `wasifyai_voice/dictation.py`). The body is one WAV file and nothing else is read: **16 kHz, mono, 16-bit
  PCM exactly** (so there is no ffmpeg), at most **10 MB and 5 minutes**, at least 0.3 s, the real RIFF/WAVE header (not the file name), the length measured from the samples that are there (not from what
  the header claims) and a peak of at least 0.004 (a silent clip is refused rather than sent to a model that would invent words). The answer is `{text, seconds, model, displaced}` and **nothing is kept**: no file,
  no database row, no search entry, no usage row, and the words are not logged. `displaced` is `"chat"` when the chat model had to be unloaded to make room. A missing runtime or model is a 409 with what to do,
  the engine failing a 502 with its sentence, no engine a 503. The route is additive and uses the existing `SpeechEngine`, so on the web it goes to the hosted engine and the `voice-transcribe` alias
  (`TranscriptResult` gained an optional `displaced`; `transcribe` gained a keyword `beside`, ignored by the hosted engine).
- **Light owner (the slot):** `SlotManager.hold(owner, beside_bytes=...)` (`packages/platform-sdk/.../slots.py`). A small owner asks to stay beside the resident model; `can_share(owner, bytes, resident)` decides, and when it says
  yes the resident model is **not touched and the small one does not wait for the chat turn that is running**. When it says no (or cannot tell, or errs) the small owner takes the slot as before, the other model is unloaded and
  `Held.displaced` says whose. The desktop's `can_share` allows only the pair that was measured (speech beside chat) and asks `ModelsService.fits_beside`: the ordinary fit check (ADR-0063) on the **sum** of the chat server's
  resident memory (read from the process) and the speech model's catalogue figure (Parakeet 3 GB; measured 2.42 GB), with the chat model's memory counted as already used; unknown sizes say no. By the same numbers
  as section 4: this Mac, a 32 GB Mac and a 16 GB Mac with about 4 GB free beside the chat model share; a 16 GB Mac with the rest of it busy, and an 8 GB Mac, do not and fall back to unloading. The idle timer unloads both, a
  running dictation finishes before its model goes, and an ordinary owner arriving (an image) unloads the small one too. `reclaimable_bytes` now counts every resident model. The slot logic is tested with fakes
  (`test_slots.py`), the memory rule in `test_desktop_models.py`, the engine's use of it in `test_audio_runtime.py`.
- **Tauri shell:** `src-tauri/Info.plist` (`NSMicrophoneUsageDescription`: "Wasify AI listens only while you press Mic in the chat box, to write down what you say. The sound is turned into text on this computer and is
  not kept.") and `src-tauri/Entitlements.plist` (`com.apple.security.device.audio-input`), referenced from `tauri.conf.json` (`bundle.macOS.entitlements`). **Cargo does not watch `Info.plist`: after editing it run `touch build.rs`.**
  Checked: a debug build after `touch build.rs` contains the usage description (`strings` on the binary), `plutil -lint` passes, `cargo check` accepts the config. **Not checked: a signed and notarised bundle**
  (no signing identity here), so whether the hardened runtime lets the microphone through with that entitlement is untested.
- **Setup card:** when no speech model is installed the first press of Mic shows what it is, the model's name and licence, where it comes from, the size (the model plus the speech runtime when that is missing) and one
  "Download 956 MB" button with "Not now". Nothing is fetched before the click. The click installs the runtime if needed (the same `confirm_bytes` handshake as the Voice screen), then the model (the same files-and-bytes
  confirmation as Models), with a progress bar. `dictationReadiness` (`packages/client`) reads the engine's transcription models and runtime; the desktop supplies `getSpeechModel` (`apps/desktop/src/speech-model.ts`).
- **Web:** the browser records and uploads to the hosted engine through the BFF's catch-all (no web code for the route), under the BFF's body limit (110 MB) and the route's own 10 MB / 5 minute limits. **The Mic is
  shown when the hosted engine lists a transcription model and is absent otherwise** (no model, no engine, an error); a model that is missing and cannot be fetched (the web has no download) also means no button.
  The Containerfile now copies `apps/web/public` (the worklet). **There is no daily quota on dictation**: the platform does not write usage events or quotas for hosted speech yet (the runbook says so for transcripts too).
- **Not an action** (see `docs/actions.md`, "Not actions"): the audio is the person's own voice in the window, and the route returns text to the box and nothing else.
- **Tests:** engine (`test_dictation.py`: 18 cases, including an oversized upload, an MP3 called WAV, wrong rate and channels, a header that claims more than the file has, a silent clip, no words, nothing kept, the words not
  logged), slots, memory rule, engine; window (`dictation/dictation.test.tsx`, `home-mic.test.tsx`: both chat screens, every error, the setup card, cancel, the microphone released on unmount, the worklet files identical);
  client; desktop (`speech-model.test.ts`); **a real browser** (`apps/web/e2e/dictation.spec.ts`, Chromium with a fake microphone: the real recorder and worklet run, the posted file is a 16 kHz mono 16-bit WAV of about the
  recorded length, the words land in the box, nothing is sent, every track has ended, a refused microphone is said in words, and at 320 px in light and dark the Mic and the card fit with no sideways scroll).
- **Not verified:** a **real microphone through the desktop window** with the new code (CO0 proved the same recorder and permission path on this Mac, but this build was not run in the Tauri window by me), the macOS prompt wording on screen,
  a **signed bundle**, dictation in a language other than English, Windows and Linux, and the real `fits_beside` decision on a 16 or 32 GB Mac (computed from the rules, not run there). The first dictation after the chat model
  starts loads Parakeet (8 s once, 58 ms after); it is loaded beside the chat model from then on. If Parakeet was resident first and the chat model starts later, the chat turn unloads it (the other direction of the rule is not built).

## What CU3 read-aloud built (2026-10-20)

Read aloud, end to end (`docs/chat-ui-migration-plan.md`, "CU3 read-aloud as built"; ADR-0083 decision 5 for the model slot, ADR-0066 for the speech models). The last open part of stage CU3.

- **Engine:** `POST /products/wasifyai-voice/read-aloud` (`wasifyai_voice/routes.py`; the text handling and every limit in `wasifyai_voice/read_aloud.py`). The body is `{text, part}` (unknown fields refused); `text` is a reply as the model wrote it, at most **40,000
  characters** (longer is a 422 before anything runs). `plain_words` turns markdown into what a person would say: fenced code and block maths are dropped, links keep their text and lose their address, bare addresses and HTML tags are dropped
  (`script`, `style`, `iframe`, `svg` and their contents with them), `[1]`-style citations and table rules are dropped, a table row is read as its cells, headings and list items get a full stop so the voice pauses, and
  every control, private-use and bidirectional or invisible formatting character is removed (the joiners U+200C and U+200D, which Bengali, Hindi and Persian words use, stay). The words are cut at sentence ends (full stops, `?`, `!`,
  the Devanagari and Bengali danda, the CJK and Arabic marks) into **passages of at most 600 characters, the first about 300** (so the first sound comes sooner), at most **8 passages** (about five minutes); a sentence
  with no space in it is cut where it must be. The route speaks the one passage asked for (`part`) and answers `{audio (base64 WAV), part, parts, truncated, seconds, model, displaced}`. Only code or a picture is a 422
  `nothing_to_read`; a passage past the end a 404; a missing voice or runtime a 409 that says what to get; the runtime failing a 502; no engine a 503. **Nothing is kept:** the tests check that no file or row appears, that
  `/speeches` and `/transcripts` stay empty, and that the words are not in the log. It is **not an action** (`docs/actions.md`).
  The sound travels as base64 inside the JSON answer because nothing is stored to link to and the web's pass-through forwards only a few response headers; a 600-character passage is about 40 seconds, roughly 1.9 MB of WAV (2.6 MB as base64)
  at Kokoro's 24 kHz.
- **Speech runtime:** `SpeechEngine.speak` gained the keyword `beside` (and `SpeechResult.displaced`), passed through the combined, hosted (ignored: a hosted model holds no local memory) and local engines; `AudioEngine._synthesize` asks the slot with
  `beside_bytes = _ram_bytes(model)`, the same call dictation makes. No new slot code was needed: the light-owner rule of CO4 is keyed on the pair (speech, chat), and read aloud is the same owner.
- **Memory rule, computed not run:** `fits_beside(1 GB, 6.9 GB chat model)` with this Mac's rules (`test_the_read_aloud_voice_stays_beside_the_chat_model_only_when_the_two_fit`): a 64 GB Mac with 40 GB free: **shares**; a 32 GB Mac with 20 GB free: **shares**;
  a 16 GB Mac with 4 GB free: **shares** (7.9 GB together, budget about 12 GB); a 16 GB Mac with 0.5 GB free: **does not share** (the chat model is unloaded for the passage and the window says "The chat model was put away to make
  room for the voice. It loads again when you send your next message."); an 8 GB Mac (7.9 GB is over its 6 GB budget): **does not share**. The catalogue figure is Kokoro's 1 GB (measured 0.9 GB resident in the voice spike, `docs/spikes/voice-v0.md`).
  One audio.cpp server holds one model at a time (`max_loaded_models: 1`), so a dictation right after a reading swaps Kokoro for Parakeet inside that server (1.5 to 3.8 s, measured in the voice spike) and back.
- **Speed (from the voice spike, not re-measured):** Kokoro 8.6 to 9.3 times faster than real time warm (503 characters in 3.3 s for 31 s of audio), 4.7 s to load once. The first passage is about 300 characters, so on this Mac the first sound should
  come about 2 s after the press once the voice is warm, and about 7 s the first time after it was away; each next passage (600 characters, about 4 s) is asked for while the previous one plays, so it is ready long before it is needed.
- **Window:** a speaker button in the action row under each finished reply of the new thread (`thread/Message.tsx`) and under each reply of the old screen (`ChatScreen.tsx` `Bubble`); it is named "Read this reply aloud" and, while it works,
  "Stop reading aloud" (`aria-pressed`), with a status line in words next to it: "Getting ready to read…", "Reading aloud", "Reading aloud · 2 of 3" and a pulsing dot (still when the person prefers less motion). **Never automatic:** nothing plays
  without a press, and no setting turns that on. One reply at a time (starting another stops the first); Stop, and leaving the screen, abort the request and the sound. A problem is an alert card with the engine's sentence (shown as text) and
  "Close"; a long reply gets "only the first part is read aloud"; when the chat model was put away, the same note as dictation. With no voice the first press shows **the setup card**: "Set up read aloud", the voice's name and licence, the source host, the
  languages it speaks, the size (the voice, plus the runtime when that is missing) and one "Download" with "Not now" (nothing is fetched before the click; the web shows no button because it cannot download). `player.ts` plays on one audio
  element that is unlocked with a silent clip inside the click (WebKit, which is the Mac window, lets a page play only after a click, and the later passages are played after the network answered); every sound is a blob address released at once.
  The window's content policy already allows `media-src blob:`.
- **Tests:** engine (`test_read_aloud.py`, 18 cases: markdown to words, markup and control characters, only code, passage limits and truncation, a sentence with no spaces, Bengali sentence ends, one passage at a time with nothing kept, past the end, oversized and
  malformed bodies, hostile text never reaching the model as markup, `displaced`, no model yet, engine failing, no engine, no words in the log); slot (`test_audio_runtime.py`, `speak` asks for 1 GB beside); memory rule (`test_desktop_models.py`); client (`voice.test.ts`:
  the call, the 40,000-character cap, the abort signal, the engine's sentence, readiness); window (`read-aloud/read-aloud.test.tsx`: both chat screens, 14 cases including no auto-play, one passage ahead, Stop, one reply at a time, the engine's sentence as
  text, setup, unmount, and the player; `read-aloud/home-read-aloud.test.tsx`: the home screen with a voice, without a client, without a model, and the whole setup on both screens).
- **Not verified:** the real voice **by ear on a real reply** (Kokoro is not on this Mac; **no download was made**, the owner has to say yes to 190 MB first); the real desktop window (WKWebView) and VoiceOver; the unlock trick on a signed bundle; the web profile
  against a real hosted voice; a language other than English (Kokoro lists `en-us` and `en-gb`; other text is spoken badly, which the setup card says; a language-aware choice of voice is the follow-up); that reading starts quickly with the chat model answering
  the next message at the same time (the slot lets the voice finish first, as for dictation). There is **no daily quota or usage row** for read aloud, as for dictation, because the platform writes none for hosted speech yet.

## What CO2 built (2026-10-20)

Attach, end to end on the desktop profile (`docs/composer-options-plan.md`, CO2).

- **Pictures.** The assistant product now accepts uploads (`uploads: image` in `product.yaml`), so a picture goes through the ordinary hardened route (ADR-0035: decoded, rotated,
  stripped, re-encoded). The graph fits it to **1,024 pixels** on the long edge (JPEG) before the model sees it (CO0: 411 tokens at 768 px, 4,083 and a wrong answer at 3,072) and sends it as
  an `image_url` part; the newest three pictures of a chat are given, older ones are named as "not included any more". A model reads pictures only with its **projector**: for a file model
  `find_projector` looks for `mmproj*.gguf` next to it (Hugging Face and LM Studio keep it there; the 16-bit one is preferred), the chosen selection records it (`Selection.projector`, `vision`)
  and the language server is started with `--mmproj` (the server restarts when the choice changes). A model of Ollama says `vision` itself (`/api/show`); another tool's model is "not known"
  and the picture is tried. Without a projector the person is told in words (`no_vision`) and nothing is stored.
- **Documents.** `POST /products/wasifyai-assistant/attachments` (`attachments.py`): the notebooks' file check (the bytes must match the name), the notebooks' built-in reader for text, Markdown, CSV
  and HTML, and the notebooks' document reader for PDF and Office files **when it is installed** (a refusal that says what to set up when it is not). The stored copy is the **text** (`uploads/<id>.txt`,
  at most 200,000 characters), never the file. The model is given at most 12,000 characters of one document and 24,000 of a chat, newest first, quoted between `<<<` and `>>>`.
- **Trust.** What is in an attachment is untrusted like a web page: the system prompt says so, and once an attachment is in the chat an action that is not a plain read asks the person (the same
  card as after a web read). A picture can carry written orders too; the prompt says to describe it, not obey it.
- **Keeping.** A message's `attachment` parts (`id`, `key`, `kind`, `name`) are stored with it; the upload is "consumed" so the 24-hour sweeper leaves it; the conversation read adds a short-lived link
  to a picture; deleting the conversation deletes the files. Run input `attachments: [{id, name}]` (at most 4); an empty message with an attachment is allowed by the engine.
- **Window.** An Attach button (a paperclip) in the options bar, a file picker, drag and drop on the box, paste of a file (a screenshot), chips above the words (a thumbnail for a picture, name and size for
  a document, "Reading" while it goes up, the engine's sentence when it is refused, a remove button), Send waits for files still going up, the message shows its attachments, on **both** chat screens.
  `GET /options` has `attach {available, images, documents, images_note}`.
- **Not done:** the **one-click download of the projector** (918 MB): it needs a catalogue entry with a published checksum, and the download needs your yes; without it a person who has no `mmproj` file is
  told why a picture is refused. "Add this to a notebook instead?" for a long document (the chip says "Only the start is used"); the notebooks' "best passages" rule (a long file is cut to its start);
  Word and PDF were tested only with the reader mocked; **a picture alone, with no words, is allowed by the engine but the box still wants a question** (the new thread's send button waits for text).

## What this changes

- **ADR-0083** (proposed edits, not made): decision 2 gains the **measured reasoning field names** (`reasoning_content` for llama.cpp, `reasoning` for Ollama) and
  the finding that **the app thinks by default today**; decision 3 gains **"fit pictures to about 1,024 pixels"** and the projector's measured cost (0.9 GB, 411 tokens
  a picture); decision 4 needs the owner's choice among the four search options and a line on DuckDuckGo's terms; decision 5 gains the measured **light-owner numbers** (2.4 GB
  resident, 58 ms warm) and the **16 and 32 GB** answers, the **blob-worker** trap, and the Info.plist and entitlement facts; open question 1 is answered (works), 3 is answered,
  4 is answered for this Mac.
- **Dependencies:** none were added to the repo. `ddgs` and `trafilatura` are needed only from CO3; **this spike did not approve them (the owner did, 2026-10-20, ADR-0083)** (the owner approved the *downloads*); the projector
  (0.92 GB) and a speech model are approved for CO2 and CO4.

## Not measured

- LM Studio (not installed); the Ollama vision path; a projector for models other than Qwen3.5-9B.
- A signed and notarised bundle with the audio-input entitlement; Windows and Linux microphone paths.
- `ddgs` over days of normal use; keyed providers (Brave, Tavily): documentation only, not read for this spike.
- Dictation in languages other than English (the runtime says Parakeet covers about 25 European languages; not tested here).
- The 16 GB and 32 GB answers are computed from the fit rules and this Mac's measurements, not run on such Macs.

## Disclosures

- Installed on my own initiative: **nothing outside the scratch folder** (a virtual environment there holds `ddgs`, `trafilatura`, `readability-lxml`, `lxml`, `requests`, `primp`).
- I started the desktop window and Vite myself (port 1420 was free; your previous window was closed) and stopped both after the check. A temporary `src-tauri/Info.plist`, a page
  and a worklet were added to the repo for that run and **removed**; `git status` shows none of it.
- About 80 search requests were sent to DuckDuckGo, Bing, Yahoo and others from this address in a few minutes, which probably caused the challenge pages seen; the later "polite" run waited ten minutes first.
