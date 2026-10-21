# Runbook: notebooks and speech on the web profile

For staging and production (a cloud GPU host, models from a hosted provider; decisions of 2026-10-18 in
`docs/phase3-web-parity-plan.md`). Both products are **always on** (no switches, owner 2026-10-21): the API serves them, the web app shows them, and the chart
runs the notebooks worker.

## What each needs

| | Notebooks | Speech (voice) |
|---|---|---|
| Needs | Postgres with pgvector, object storage, the **worker** (`<registry>/wasifyai-notebooks`), the gateway alias `creation-embedder` | Postgres, object storage, the gateway aliases `voice-speak` and `voice-transcribe` |
| Pods | API, web, **notebooks-worker** | API, web |
| Sends to a third party | the text of sources, to the embedder and the chat model the aliases point at | the text to speak and the recordings to read, to the speech provider |

## Setting up

1. Check the images exist: `api`, `web` and `wasifyai-notebooks` (CI builds all three; the worker image is the large one
   because it holds the document reader and its models: about 3 GB).
2. **Gateway.** Open the admin Models page. `voice-speak` and `voice-transcribe` are seeded pointing at OpenAI-style
   defaults with no key: bind each to the provider's speech and transcription model and set the key, then press the
   test (it speaks a word, and reads a second of silence). `creation-embedder` must be a 1024-dimension multilingual
   embedder (the default is bge-m3). If it changes dimension, set `notebooks.embedDimension`; stored vectors of another
   size are not searched.
3. Turn the safeguards on for a public deployment (quotas on notebooks apply only while they are on) and sync:

   ```yaml
   safeguards: { forceOn: true }
   ```

4. Check: the API log says nothing about "is not installed"; `kubectl get deploy -l app.kubernetes.io/component=notebooks-worker`
   is ready; in the web app the Notebook and Voice menu items open (a voice screen is linked when a ready model can do it, so until the aliases are bound only the screens the models allow show); add a small PDF to a notebook and see it
   go from reading to ready; speak a sentence.

## Running it

- **Scale reading.** `notebooks.worker.replicas`. A source is taken by one worker (one atomic update); any number can run.
  A worker needs about 1 GB of memory to read a page of a scanned document; the default limit is 4 Gi.
- **A source stays "reading".** The worker died while reading it. After 30 minutes the next worker's sweep marks it
  failed and the person can press Retry. If no worker is running at all, sources stay pending: start one.
- **Studio outputs** (briefing, quiz, slides and the rest) are made by the same worker. An output stuck "making" is
  swept the same way. The guide and the infographic are made by the API.
- **Speech returns "busy" or "engine failed".** The provider refused or timed out; the person sees a short message
  that does not name the provider. Look at the API log (`hosted_speech`) and at the alias test on the Models page.
- **The Mic in the chat box** posts a short WAV to `/products/wasifyai-voice/dictation`, which uses the same `voice-transcribe` alias; it is shown only when the engine lists a transcription model. Clips are limited to 10 MB and 5 minutes
  and are not stored. If the Mic is missing on the web, the alias has no model (check `GET /api/products/wasifyai-voice/models?task=transcribe`).
- **Read aloud under a reply** posts the reply's text to `/products/wasifyai-voice/read-aloud`, which speaks it with the `voice-speak` alias (the hosted `hosted-speech` model) one passage at a time (at most 8 of up to 600 characters) and stores nothing; the button
  is shown only when the engine lists a text-to-speech model. On the web the text of a reply therefore goes to the speech provider you configured, which the desktop app never does. If the button is missing, the alias has no model
  (check `GET /api/products/wasifyai-voice/models?task=speak`). Like dictation it writes no usage event or quota yet.
- **Costs.** Embedding tokens are recorded as `llm.embedding_tokens` usage events. Speech and transcription are billed by
  the provider and appear in the gateway's own spend log; the platform does not yet write usage events or quotas for
  them (to do before the web is public). Set a spend limit at the provider.

## The older music, speech and lip sync products are gone

ADR-0067 deleted them. On a deployment that ran them: `make migrate` (migration 0019) drops their tables and search
rows, and `uv run python scripts/purge_older_products.py` lists the files they left in object storage (`--yes` deletes
them; it cannot be undone). Before turning the safeguards off for the voice product's sake, know that the voice product
moderates and limits only while `safeguards.forceOn` (or the admin switch) is on; bind the `moderator` and `multimodal`
aliases in the admin Models page and press the test, which runs the voice product's canaries.

## Turning it off

Set the switch to false and sync. The data stays (schemas `notebooks` and `voice`, objects under each product's
prefix); the menu items return to "Soon" and the older speech pages stop redirecting. Do not drop a schema to "reset":
people's notebooks and speeches are in it.

## The web app on a Mac with the local models (development and testing)

Music, splitting, voice change, speech edit, dubbing, the audiobook and lip sync run on the machine that has the
models. To try them in the web app on a Mac:

1. In the desktop app, set up speech (Models) and fetch the models you want to try; lip sync has its own setup
   there. Quit the desktop app: it and the web service would share memory and files.
2. `scripts/web-local.sh` (it uses the desktop app's data folder; `WEB_LOCAL_DATA_DIR=...` for another). It starts the
   containers it needs, applies migrations, runs the API with `VOICE_ENGINE=local` and the web app on
   <http://localhost:3000>. `VOICE_ENGINE=both scripts/web-local.sh` also offers the hosted models.
3. The menu lists a voice screen only when a ready model can do it. If a screen is missing, the model for it is not
   ready in that folder (`GET http://localhost:8000/products/wasifyai-voice/models` shows each model's state).

Everything made is kept in Postgres and the containers' object storage, not in the desktop app's own library.

## Not covered

The cloud GPU host itself (the local models above are for development; a deployment with `VOICE_ENGINE=local` needs a
machine with them and their memory), moderation and quotas for speech, and a load test.
