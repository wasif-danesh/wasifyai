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
