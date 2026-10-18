# Phase 3: the web app looks and works like the desktop app (plan)

Status: **Proposed 2026-10-17**. The owner chose the recommended order on 2026-10-17 and said the hosting questions come later. **W1, W2 and W3 built 2026-10-17 and 2026-10-18** (see their sections); the rest is not started. Builds on ADR-0056
("a feature is built once, in the engine, with two shells"), ADR-0046 (the web side panel), ADR-0066 decision 11
(the web stack lists the models a deployment allows) and the shared packages `packages/ui` and `packages/client`.

**Goal.** Someone who opens the web app sees the same shell, the same screens and the same abilities as in the
desktop window, wherever a server can provide them, and is told plainly what only the desktop app does.

## Where the two apps are today

| Area | Desktop | Web | Gap |
|---|---|---|---|
| Design tokens, theme | `packages/ui/src/tailwind.css` | the same file | none |
| Primitives (button, notice, picture input, ...) | `packages/ui` | partly `packages/ui`, partly its own copies in `apps/web/components/ui` | small |
| Shell | grouped side menu (Notebook, Images, Video, Voice, Music), chat-first home, one library | side panel of product links, a home of product cards, My creations | **large (look)** |
| Images | shared `ImageWorkspace`, `ImageLibrary` (favourites, recipes, make it again, styles, edit) | its own `CreateImage` and view, no library of its own | medium |
| Video | shared `VideoWorkspace`, `VideoLibrary` | its own `CreateVideo`, `VideoView` | medium |
| Assistant (chat, tools, recents) | shared `ChatScreen` | none | medium (the engine side exists for both stores) |
| Notebooks | shared workspace, sources, studio outputs | none | **large**: the store, search and file handling are SQLite only |
| Speech, voices, audio tools, dubbing, audiobook | shared workspaces on `wasifyai-voice` | separate older products `wasifyai-tts`, `wasifyai-stt` | **large**: `wasifyai-voice` keeps `voice.db` and local files and runs audio.cpp on the same computer |
| Music | `wasifyai-voice` (audio.cpp), edits, takes, lyrics, split | `wasifyai-music` (lyrics approval flow, ComfyUI) | large, and a choice (below) |
| Lip sync | MuseTalk sidecar, consent, visible mark | `wasifyai-lipsync` | medium |
| Models, Settings, engine installs, discovery, hub | yes | admin pages only | not applicable to a hosted service |

Two kinds of work follow from this and they can be done apart: **the look** (one shell and shared screens) needs no
new server, and **the abilities** (notebooks, voice and the rest on a server) need adapters, a GPU host and the
safeguards a public service must have.

## Principles

1. **One screen, two shells.** A screen lives in `packages/ui` and takes a client; the desktop passes the loopback
   transport and the web passes the BFF one. No screen is written twice.
2. **Hosted means safeguards on.** The web runs with moderation and quotas on (ADR-0047) and a licence filter on the
   models it offers (ADR-0066: only models that allow commercial use are listed there; the others stay badge-only).
3. **No feature pretends.** A screen whose server side is not ready shows the same menu item marked "Soon" (or "In the
   desktop app"), as the desktop menu does for unbuilt items.
4. **Every adapter carries `tenant_id` and `product_id`** (rule 7), files go through the storage interface, long
   work is a job, never a request (rules 6 and 10).
5. **Same images everywhere** (rule 1): the web engine and the desktop engine run the same product code; only
   adapters differ.

## Stages

Sizes are relative: S a few days, M one to two weeks, L several weeks.

### W0. Decide (S, no code)
Answer the questions below and record them as **ADR-0067** (the web reaches desktop parity). Nothing else starts
before the order and the hosting answer are known, except W1, which depends on neither.

### W1. One shell for both apps (M, front end only) — built 2026-10-17
- Move the side menu, its group data and the page frame into `packages/ui` (`AppShell`, `SideMenu`), taking a link
  adapter (hash routes on the desktop, Next links on the web) and a list of what is built. The desktop's menu
  tests move with it.
- The web uses the same groups and labels. Items whose server side is not ready on the web are marked "Soon".
- A generic BFF route (`app/api/products/[productId]/[...path]`, with an allowlist of product ids and methods)
  replaces the per-resource route files, so a new engine route needs no web code. Keeps streaming and uploads as
  they are now.
- Home: the desktop's chat-first home when the assistant is on (W3), the product cards until then.
- Checked by side-by-side screenshots of every shared screen in light and dark, at desktop and phone widths, kept as
  Playwright snapshots in CI.

**What W1 delivered.** The menu is defined once (`packages/ui/src/shell/menu.ts`: groups, items, icons, labels) and
drawn once (`SideMenu`). Each app answers "what does this item open?": `apps/desktop/src/menu.ts` (screens) and
`apps/web/lib/menu.ts` (pages). An item an app does not answer for shows as "Soon"; `models` is hidden on the web.
On the web the menu sits in the existing side panel frame (collapse, phone drawer, remembered state) and Admin is
added for admins. Moving the menu also fixed one thing in the desktop: while a page of one group was open, the other
groups could not be opened by hand; now the person's choice holds until they go to a page of another group. A catch-all
BFF route (`app/api/products/[productId]/[...path]`) forwards any other engine route (plain path segments, at most 6,
110 MB body, never `runs`); the specific routes that existed stay for now (Next.js matches them first) and go as
the screens that use them move to the shared client in W2.

Browser checks (added 2026-10-17, the owner agreed the dependency): `@playwright/test` in `apps/web`, run with
`pnpm --filter web test:e2e` (all) or `test:e2e:layout` (what CI runs). They start the built web app with the sign-in stub
and answer every `/api` call themselves (`e2e/mock-api.ts`), so no service is needed. They check every shared screen
(image create, edit and library; video create, animate and library) for the menu, no sideways scroll and the key
buttons, and keep screenshots in dark and light at desktop width and dark at phone width (`e2e/*-snapshots`, per
operating system, so CI runs the layout checks only; update them with `--update-snapshots`). Not done in W1: the web
home page, which keeps its product cards until W3. On the web the menu marks Images > Edit and Video > Animate an
image as "Soon" although the existing pages have a "From a picture" tab; W2 gives them their own screens.


### W2. Images and video on the shared screens (M) — built 2026-10-17
- Web Create and Edit images become `ImageWorkspace`; "Your images" becomes `ImageLibrary` (favourites, recipes, make
  it again, download in place of "save a copy"); styles (LoRAs) come from a list the admin curates, as there is no
  local folder to scan.
- Video: `VideoWorkspace` and `VideoLibrary`. The web keeps its quota and the one-clip-at-a-time rule.
- My creations stays the unified library; it gains the same card look and the kinds the desktop indexes (`track`,
  `voice`, `speech`, `transcript`, `lipsync`, `conversation`, `notebook`).
- Retires `apps/web/components/image`, `components/video` and their flow code (`lib/video-flow.ts` and the like are
  already in `packages/client`).

### W3. The assistant on the web (M) — built 2026-10-18
- Mount `ChatScreen` on the web home with conversations (recents). The engine side exists for both stores (the
  Postgres tables come from migration 0018) and the tool host runs in both profiles.
- Tools that need things the web does not serve yet (speak, dub, split, lip sync) are left out of the web tool list
  until their stage lands; the list is by deployment, not by profile.
- Needs the hosted gateway's chat model (LiteLLM alias), the safeguards and the per-user quotas for tokens.

**What W3 delivered.** The web home page is now the assistant, the same screen as the desktop's (`AssistantHome` in
`packages/ui`: greeting, "Ask anything", examples, the conversation, rename and delete). A new chat gets its address
(`/chat/<id>`) after its first answer without a reload, and the menu lists Recents (`useConversations`, refreshed when a
chat changes). The page showing what can be made moved to `/explore` (public, with the plain header; the menu links it),
and `/` now needs sign-in like the other pages. On the engine side the assistant is offered only the tools its
deployment can run: `ApiToolHost.available_tools()` (images where the image product is served, music where the
speech runtime exists, notebooks on the desktop, search everywhere), so the web model is never told about music or
notebooks it cannot reach; `offered_tools` in the assistant graph applies it. Replaces the desktop's own copies of
the home screen and the recents hook.

Not done in W3: the assistant's tool results that open a creation only know images and videos on the web (a track or a
notebook has no web page yet), and there is no per-user token quota for the chat model (needs the safeguards
decision of W7).

### W4. Notebooks on the web (L) — built 2026-10-18 (steps 1 to 5)
The largest server piece, in the order a person needs it:
1. **Store and search adapters on Postgres**: sources, chunks, notebooks, outputs; pgvector for the semantic leg and
   full-text search for the keyword leg (the same two legs and blend as `retrieval.py`); migrations.
2. **Files**: source files and generated documents go through the storage interface; ingestion (the document
   reader) runs as a worker job, not in a request.
3. **Embeddings** through the gateway's embedder alias; per-tenant quotas on sources and bytes.
4. **Screens**: the shared notebook workspace over the BFF.
5. **Studio outputs** (briefing, quiz, slides and the rest) as jobs; audio overviews wait for W5.
The desktop's `sqlite-vec` code stays for the desktop; the interface between product code and store is what both
adapters implement.

**Step 1 is built** (the hosting question did not block it, it needs no GPU): `PostgresNotebookStore`,
`pgretrieval` and `PgNotebookIndexSource` (My creations search), described in ADR-0065's amendment of 2026-10-18. The
store, ingest, chat, routes, studio and search tests of the product run on both databases (a Postgres from `podman run
pgvector/pgvector:pg16`, as CI's service). **Step 2 is built**: `FileStore` (folders or object storage, `files.py`), the web runtime (`WebSetup`, behind `NOTEBOOKS_ENABLED`),
and the reading worker (`python -m wasifyai_notebooks.worker`, any number of them, the database as the queue), described in
ADR-0065's second amendment. The web engine can now store and serve notebooks when it is switched on and a worker runs; the
menu keeps them "Soon" because there are no web screens yet (step 4). **Step 3 is built**: the search model through the gateway (`GatewayEmbedder`, alias `creation-embedder`, multilingual), token usage
recorded for every embedding call, and per-person limits on notebooks, sources and bytes, applied while the safeguards are on
(ADR-0065's third amendment). **Step 4 is built**: `/notebooks` (View Notebooks) and `/notebooks/<id>` or `/notebooks/new` (a draft, saved when its first source
is added, then given its address without a reload) show the shared `NotebookList` and `NotebookWorkspace` over the BFF (the
catch-all route carries the uploads, the downloads and the question runs). The menu's two Notebook items are live when the web
app has `NOTEBOOKS_ENABLED=true` (the same switch as the engine's) and "Soon" otherwise. Copy that promised "stays on this
computer" now follows where the screen runs (`NotebookPlaceProvider`: on the web, "kept in your account, private to you"). Browser
checks cover the list and a notebook, on desktop and phone. **Step 5 is built**: Studio outputs are queued by the engine's program and made by the worker (`make_output`, `OutputWorker`; the
output's row is the queue; guide and infographic stay with the engine), described in ADR-0065's fourth amendment. The audio overview's
voices wait for W5; passing `NOTEBOOKS_ENABLED` and the worker's settings through the Helm chart, and the worker's image, are W7.

### W5. Voice, music and avatars on the web (L, in five steps, each shippable) — (a) built 2026-10-18
The hosting answer (2026-10-18): **a rented cloud GPU for staging and production**; the web offers **the models available through OpenRouter or similar** (a hosted provider behind the gateway), so (a) needed no GPU worker. The product code is shared; what changes is the store, the files, the runtime and
the rules.
- **Store and files**: a Postgres and object-storage adapter for what `voice.db` and the local `voice/` folder keep
  (speeches, transcripts, voices, tracks, clips, pictures); `VoiceStore` becomes an interface.
- **Runtime**: speech, music and separation run as **jobs on a GPU worker** (the media worker already has a `speech`
  provider kind). audio.cpp for Linux with CUDA needs its own pinned lock (an open item since V1); the model list a
  deployment offers comes from its allowlist, and the window's "Set up speech" and "Get the model" steps become admin
  actions or disappear.
- **Safeguards**: moderation of text and of uploaded recordings, consent screens kept as they are, the lip sync mark
  kept, quotas by seconds of audio and video, and a policy for cloning a voice from an upload.
- **Order**: (a) Text to speech, Speech to text and Voices; (b) Music, Your music and Lyrics; (c) Split into parts,
  Change a voice and Edit speech; (d) Dubbing and Audiobook (long jobs, partial results as tracks); (e) Lip sync (the
  MuseTalk server is one more GPU worker).
- Each step ships with its search rows, its quotas and its web screens (the same shared workspaces).

**What W5 (a) delivered** (decisions 2 and 3 of 2026-10-18: one voice product, models from a hosted provider):
- **Store**: `PostgresVoiceStore` (schema `voice`, same store class as the desktop's SQLite one, own schema, advisory
  lock on creation) and `PgVoiceIndexSource`, so speeches, transcripts, voices, tracks and clips are searchable in
  My creations. The product's tests run on both databases. The Postgres helpers moved into the platform SDK
  (`wasifyai_platform_sdk.pg`) and the notebooks use them too.
- **Engine**: `HostedSpeechEngine` fills the product's `SpeechEngine` seam with the gateway's
  `/v1/audio/speech` and `/v1/audio/transcriptions`, by alias (`voice-speak`, `voice-transcribe`). The two descriptors
  are in `products/wasifyai-voice/hosted-models.yaml` (`engine: remote`, commercial use "yes", the provider's terms as
  evidence). Every other task answers `not_offered` ("in the desktop app") and the assistant is not offered music on the
  web. `GET /products/wasifyai-voice/models` lists what the deployment offers. Switch: `VOICE_ENABLED`.
- **Screens**: `/voice/speak` and `/voice/transcribe` are the desktop's `SpeakWorkspace` and `TranscribeWorkspace`
  (`createVoiceApi(transport, { hosted: true })`: always ready, no setup card), with a header that says plainly that the
  text, or the recording, is sent to a speech service. The menu items are live with `VOICE_ENABLED=true`; the older
  `/text-to-speech` and `/speech-to-text` pages redirect to them (middleware); their saved-result pages stay.
- **My creations and search** list the voice product's speeches and transcripts beside the older ones
  (`lib/voice-cards.ts`); a card opens the voice screen, which holds the history. The voice product keeps no
  language or gender for a speech, so its cards show the voice only.
- **Not done**: no migration of data kept by the older `wasifyai-tts`/`wasifyai-stt` (there is none in production yet;
  when there is, objects must be copied under the voice product's prefix); the older products' code, routes and bindings
  are not deleted yet (they only lose their menu entries and create pages); voices (cloning and design), music,
  tools, dubbing, audiobook and lip sync stay desktop-only on the web until the GPU host exists ((b) to (e)).
- **W5 (b) to (e) built 2026-10-18, with no GPU host** (decision of the same day: finish the development first, test on a
  Mac). The web profile can run the desktop's own speech runtime: `VOICE_ENGINE=local` (or `both`) makes
  `app.state.audio` the same `AudioEngine` the desktop uses, over the models in `DESKTOP_DATA_DIR` (`local_speech.py`;
  `CombinedSpeechEngine` puts it beside the hosted models, a model belongs to the hosted engine when its descriptor says
  `engine: remote`). The product's graphs, routes, store and search needed no change: they already reach the engine only
  through that seam and keep files in object storage. The web screens are the desktop's pages, now shared:
  `packages/ui/src/voice/pages.tsx` holds Text to speech, Speech to text, Voices, Create music, Your music, Lyrics,
  Split into parts, Change a voice, Edit speech, Dub, Audiobook and Lip sync with their headings, hand-offs and model
  memory, and the desktop's `pages/*` files for them are gone. Where the copy promises where things go it follows
  `place` (`device` or `service`), and a model marked `engine: remote` says that what it is given is sent to its
  provider. On the web they are `/voice/<screen>` (one dynamic page, `VOICE_ENABLED`); the menu links a screen only when a
  **ready** model can do what it needs (`offeredScreens`, asked of `GET /products/wasifyai-voice/models`), so a hosted-only
  service shows speech and transcription and a Mac with the models shows all twelve. The older music page stays where
  music is not offered. The runtime and lip sync component are read through `GET .../runtime` and `.../lipsync-engine`;
  installing and fetching models is refused from the web ("set up by whoever runs this service"). My creations and
  search show the voice product's tracks as Music and its clips as Lip sync (`lib/voice-cards.ts`).
  `scripts/web-local.sh` starts the stack for this (containers for Postgres, Redis, storage and the gateway; the API and the
  web app natively so audio.cpp uses Metal). **Not verified here:** the script and a real run of music, splitting, voice
  change, speech edit, dubbing, the audiobook or lip sync through the web (the checks use fake engines and mocked
  responses; the data folder on this machine has no speech runtime set up).
- **Not done**: usage events and per-person quotas for speech seconds (the gateway's spend log has the cost).
- **The admin must** point the gateway aliases `voice-speak` and `voice-transcribe` at the provider's models
  (`docs/configuration.md`).

### W6. Retire the old web-only products (S to M) — done 2026-10-18 (ADR-0067)
The owner first chose to keep the older results readable, then to delete the four packages and everything they made.
Done, in the order it had to be:
1. **The voice product got what the older ones had.** The voice product recorded usage but moderated nothing and limited
   nothing, so deleting them first would have dropped the safeguards on the public service. It now has
   (`wasifyai_voice/safeguards.py`, ADR-0047, only while the safeguards are on): the text moderator on everything that will be
   spoken or sung (speeches and designed voices, music descriptions and lyrics, the idea for lyrics, new words in a recording,
   a lip sync script, the words of a recording that a face will say, the translated lines of a dub, the text of an audiobook);
   the picture moderator on lip sync pictures; daily limits per person (`product.yaml`: speeches 30, songs 10, lip syncs 3,
   audio tool runs 20, dubs 5 with the script step included, audiobook text 200,000 characters), counted from usage events
   and only when something was made; both moderators fail closed; the same canaries before an admin can bind a model to them
   (`text.moderate`, `text.moderate_image`). Prompts, refusal sentences and canary cases were copied from the older products.
2. **The four packages are deleted** with the web pages, components, hooks, flows and proxy routes only they used, the admin
   Songs list, their smoke tests, and their entries in the Containerfile and the workspace. The old addresses (`/music`,
   `/text-to-speech`, `/speech-to-text`, `/lip-sync`) redirect to the voice screens; Explore shows their cards, pointing
   there, only where `VOICE_ENABLED`. My creations and search read the voice product only.
3. **Their data is deleted, not migrated.** Migration 0019 drops `songs`, `speeches`, `transcripts` and `lipsyncs` and the
   search index rows for them (verified on a scratch Postgres: upgrade, downgrade brings the empty tables back, upgrade
   again). `scripts/purge_older_products.py` deletes their files in object storage (a dry run unless `--yes`; it has not been
   run against a real bucket). Usage events stay.
4. A route of the voice product (`/formats`) answered without a sign-in; it was found by the check that every product route
   needs an identity once that check ran over the voice product, and fixed.
5. **What served them is deleted too:** `services/speech-indic`, `stt-indic`, `lipsync-musetalk`, the compose speech
   services, their Helm templates and values, the scripts and evaluations for them, the media worker's speech,
   transcription and lip sync runners, and the SDK's `speech` and `lipsync` providers and `music` and `speech`
   capability families. ComfyUI music on a GPU host is gone from the web; the voice product's local engine is the way to run
   ACE-Step on a host.

### W7. Hardening and release (M) — deployment half built 2026-10-18
**Built**: the notebooks worker image (`products/wasifyai-notebooks/Containerfile`: the reader and its weights fetched and
checked at build, `reader_install` also runs as a command), the API image now carries the assistant, notebooks and voice
products it was missing, Helm values `notebooks` and `voice` with the worker Deployment and the switches passed to the API
and the web app, the speech aliases seeded and testable in the admin Models page, CI builds the worker image, and
`docs/runbooks/web-notebooks-voice.md`. **Not built or not verified**: the worker image was built on 2026-10-18 on arm64 (3.0 GB; the reader's own
read-a-test-page check passed during the build; it starts as a non-root user and stops with a clear message when the gateway is not
set), but not on amd64 and not run against a real database; no test of the chart on a cluster, and the items below.
Playwright end-to-end on the web for every screen with fake providers; accessibility pass (focus, labels, contrast
in both themes); load and quota tests; Helm GPU worker pods and their autoscaling; runbooks; docs; the terms of
service that the OpenRAIL and consent rules require before the public sees video and voice cloning.

**What W2 delivered.** The web now has the desktop's screens for images and video, from the same components:
`/image` and `/image/edit` (`ImageWorkspace`), `/image/library` (`ImageLibrary`: search, favourites, recipes, make it
again, download, delete), `/video`, `/video/animate` (`VideoWorkspace`) and `/video/library` (`VideoLibrary`, with the
clips being made shown and refreshed). The shared screens gained what the web needs: `downloadHref` (a Download button in
place of "Save a copy"), `subtitle`, `className`, a wait `hint` and an `onMaking` callback (the header's "being made"
badge), and the image screen stacks its two panels on a phone. "Make it again" and "Edit this result" travel between web
pages through the tab's session storage. The old web-only `CreateImage`, `CreateVideo`, `VideoForm` and the video flow
code are removed; the saved-result pages (`/image/creations/<id>`) stay for the My creations cards. The menu items
Images > Edit and Video > Animate an image are live on the web.

Not done in W2: styles (LoRAs) on the web (the list an admin curates has no route yet, so the panel is hidden), and
removing the per-resource BFF route files the new screens no longer need (the catch-all covers them).

## Suggested order

| Order | Stage | Why |
|---|---|---|
| 1 | W0 | the hosting and scope answers decide W4 and W5 |
| 2 | W1, then W2 | this is what "looks the same" means and needs no new server |
| 3 | W3 | cheap once the shell is shared, and it makes the home match |
| 4 | W5 (a), then W4 | voice basics are smaller than notebooks; swap if notebooks matter more to the product |
| 5 | W5 (b) to (e), W6 | |
| 6 | W7 throughout, final pass at the end | |

W1 and W2 can start now. They change no API contract, so they do not touch the desktop except for moving the shell
code, which its tests cover.

## Decisions needed

1. **Scope.** All desktop abilities on the web (recommended, in the order above), or only the look plus images, video and
   the assistant for now?
2. **Where the heavy models run for the web.** The home lab and GPU on k3s are not built (roadmap, Phase 2 and 4). Options:
   a rented cloud GPU, the home lab GPU when it exists, or the web serving only what its current GPU host already
   does (images, video, ComfyUI music) until one is chosen. W5 and the audio overviews depend on this.
3. **Music and speech: one product or two.** Recommended: converge on `wasifyai-voice` for both apps and retire the older
   web products after W5 (a) and (b). The alternative keeps two music products and two speech products for good.
4. **Which models the web may offer.** Recommended: commercial-use models only, as ADR-0066 decision 11 says; this
   leaves out some desktop choices, which stay desktop-only and are labelled so.
5. **Voice cloning and dubbing on a public service.** They need a consent record per voice, moderation of uploads and
   an abuse policy before launch. Recommended: ship cloning last in W5 (a), behind a feature flag, with the desktop's
   consent text.
6. **The desktop's home** (chat-first) as the web home, with the product cards moved to a page called Explore. Yes or
   keep the cards as the home?

## What I would not do

- Rewrite the web as a Tauri-style single page app. The Next.js BFF keeps sign-in, cookies and server-rendered pages;
  only the screens are shared.
- Copy desktop pages into `apps/web`. A page that differs between the apps takes its differences as props.
- Offer a web feature whose server side has no safeguards, quotas or tests; it stays "Soon".
