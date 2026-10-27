# SSE event contract

Status: **Finalised (Phase 1)**. Changes need an ADR. Additive fields of ADR-0082 (accepted 2026-10-20): `job_progress.tool_call_id`,
the run request's `run_id`, `POST /runs/{run_id}/cancel`, the `reasoning` event, and the assistant's message ids, `thinking` option, message tree and `confirm_action` cards (last section). The Pydantic models in `packages/contracts` (`wasifyai_contracts/events.py`) are the source of truth;
this doc describes them. TypeScript types are generated into `packages/contracts-ts` with
`make contracts`.

## Transport

- `POST /products/{product_id}/runs` starts a run and returns `text/event-stream`. The body is `{"input": {...}}`
  with two optional fields: `thread_id`, and `run_id`, **a UUID the client chose** (ADR-0082, CU1). With `run_id` the run
  has that id from its first event, so a connection that breaks before anything arrived can still be picked up again.
  Starting again under the same `run_id` (same person, same product) does not make a second run: it answers with that
  run's events from the first. Another person's or product's `run_id` is a 409.
- `GET /runs/{run_id}/events` reconnects to an existing run. Supports `Last-Event-ID`; the
  server replays events after that sequence number.
- `POST /runs/{run_id}/resume` answers an `interrupt` (approve, edit) and continues the
  stream.
- `POST /runs/{run_id}/cancel` stops a run (the chat's Stop button) and answers `{"run_id", "status"}`: `cancelled`, or the
  state the run had if it was over already (`done`, `error`), so a Stop that arrives late is not an error. A stopped run
  ends with an `error` event with the code `cancelled` (`retryable: false`). The graph stops where it is, and the assistant
  keeps the text it had written; a media job it started is not recalled. A stop that reaches another replica is noticed by
  the replica running the graph within a second. Not the owner's run, or no such run: 404.
- The Next.js BFF passes the upstream stream through unchanged: return the upstream
  `ReadableStream`, disable compression and buffering.
- Heartbeat comment (`: ping`) every 15 s to keep proxies from closing idle streams.

## Envelope

Each SSE message:

```
id: <seq>
event: <type>
data: <json>
```

Every `data` object includes:

| Field | Type | Notes |
|---|---|---|
| `run_id` | string (UUID) | |
| `thread_id` | string (UUID) | Conversation / song thread |
| `seq` | int | Monotonic per run; also the SSE `id` |
| `ts` | string | ISO 8601 UTC |

## Event types

| Event | When | Payload fields (besides envelope) |
|---|---|---|
| `node` | A graph node starts or finishes | `node`, `status` (`started` \| `completed`), `label` (human-readable) |
| `token` | LLM output streams | `node`, `text` (delta) |
| `interrupt` | Graph pauses for the user | `interrupt_id`, `kind` (e.g. `approve_lyrics`, or `confirm_action` for the assistant's card), `payload` (editable data, or the card) |
| `reasoning` | A model's thinking text streams (ADR-0082 decision 6, ADR-0083); only when thinking was asked for, or the model thinks anyway | `node`, `text` (delta). Shown collapsed under "Thinking"; stored as a `reasoning` part; **never sent back to the model as context**. The notebooks' chat also emits it (not stored there) |
| `tool_call` | The assistant calls a tool (ADR-0057) | `id`, `name`, `arguments` (object) |
| `tool_result` | A tool call finished | `id` (same as its `tool_call`), `name`, `status` (`ok` \| `refused` \| `error`), `output` (a small reference: an image id, search hits; never a file) |
| `job_progress` | Media job state changes | `job_id`, `capability`, `status` (`queued` \| `running` \| `completed` \| `failed`), `queue_position?`, `progress?` (0–1), `preview_url?`, `tool_call_id?` (the assistant's `tool_call` this job belongs to; without it a client gives the progress to the last tool still running) |
| `error` | Recoverable or fatal error | `code`, `message` (user-safe), `retryable` (bool), `job_id?` |
| `done` | Run finished | `outputs` (product-specific, e.g. `{title, lyrics, audio_url, cover_url}`) |

Rules:

- `done` and fatal `error` are terminal; the server closes the stream after them.
- Asset fields are always URLs (pre-signed or served by the API), never bytes.
- `message` fields never contain stack traces or internal hostnames.
- New optional fields may be added without an ADR. Renaming or removing fields, or adding
  event types, needs one.

## Example

```
id: 1
event: node
data: {"run_id":"…","thread_id":"…","seq":1,"ts":"…","node":"write_lyrics","status":"started","label":"Writing lyrics"}

id: 2
event: token
data: {"run_id":"…","thread_id":"…","seq":2,"ts":"…","node":"write_lyrics","text":"[verse]\n"}

id: 40
event: interrupt
data: {"run_id":"…","thread_id":"…","seq":40,"ts":"…","interrupt_id":"…","kind":"approve_lyrics","payload":{"title":"…","lyrics":"…"}}

id: 41
event: job_progress
data: {"run_id":"…","thread_id":"…","seq":41,"ts":"…","job_id":"…","capability":"music.generate","status":"queued","queue_position":2}

id: 57
event: done
data: {"run_id":"…","thread_id":"…","seq":57,"ts":"…","outputs":{"title":"…","lyrics":"…","audio_url":"https://…","cover_url":"https://…"}}
```

## Implementation notes

- Run events live in a **Redis Stream per run** (ADR-0021), written by the API runtime and by the
  media worker. `seq` is allocated atomically, so it stays ordered across processes, and any API
  replica can serve any run's stream. `Last-Event-ID` reconnects work across replicas.
- A stream closes after `done`, `error`, or an `interrupt` that is the latest event;
  `POST /runs/{run_id}/resume` continues the same run with the next `seq`.
- **Media jobs** produce `job_progress` events from the worker: `queued` (with `queue_position`,
  1 = next to run, updated as jobs ahead finish), `running` (with `progress` 0 to 1, never
  decreasing), then `completed` or `failed`. A job wait is not a user prompt: no `interrupt`
  event is sent and the stream stays open until the run finishes. A failed job ends the run with
  an `error` event carrying the job's user-safe `code`, `message`, `retryable` and `job_id`.
- A product may repeat a `node` `started` event for a node that is retrying (for example
  `write_lyrics` rewriting a rejected draft). Clients should discard what that node had streamed so
  far and start again. This is a convention, not a new event type.
- Runs are scoped to the resolving identity (stub user in dev); other users get 404.

## The assistant's run (ADR-0057, ADR-0082)

- **Input.** `text`, `conversation_id?`, and two optional ids the window chose for the turn's two messages:
  `client_message_id` (the person's message) and `client_reply_id` (the assistant's reply). They must be UUIDs; one that is
  not, or is already taken, is only a wish and the engine makes its own. With them, what the window shows and what is stored
  have the same ids. A turn can store several assistant rows (one with a tool call, then the tool's result, then the answer);
  the **first** assistant row of the turn gets `client_reply_id`, and it is the id a reload shows for the reply (the window
  folds the turn's rows into one message named by its first row).
- **`thinking`** (bool, off by default, ADR-0078): the person switched Thinking on for this turn. The engine asks a model that can think to do so (for the
  app's own llama-server, `chat_template_kwargs {"enable_thinking": ...}` on every request, so a model that thinks by default does not unless asked). A model's
  thinking arrives as `reasoning` events and is stored as a `reasoning` part before the text it led to; it is not part of `reply` and is not given back to the model on the next turn.
- **`search`** (bool, off by default, ADR-0083): the person switched web Search on for this turn. Only then is the model offered `web_search` and `web_read`; their results
  arrive as ordinary `tool_call` / `tool_result` events (`output` carries the sources, titles, sites, addresses and snippets, or `{"message": ...}` when it failed) and are stored as
  tool parts. Web text is untrusted: after it is in a conversation, an action that is not a plain read is refused in words.
- **`GET` and `PUT /products/wasifyai-assistant/search`** read and change the search settings: `{provider, consented, consent_text, can_save_keys, providers[]}`; a `PUT` takes any of
  `provider`, `consent`, `key {provider, value}`, `remove_key`. A key is written and never read back (only `key_set`). `404` where the engine has no web service.
- **`GET /products/wasifyai-assistant/options`** answers `{"thinking": bool, "search": {...}}` (`search.available` false where the engine cannot search): the Search button needs
  `available`; pressing it asks for consent first when `consented` is false. Also `{"thinking": bool}`: whether the model in use can think (desktop: the chosen file's chat template takes
  `enable_thinking`, or the chosen model of Ollama says `thinking` at `/api/show`; web: the chat alias declares `thinking_options`). The window shows a Thinking switch only when it is true.
- **`done.outputs`** also carries `user_message_id` and `assistant_message_id`: the ids the two messages were stored under
  (the chosen ones, or the engine's own when none were sent, or when the chosen ones were taken).
- **Stop** keeps the words written so far as the reply (stored under `client_reply_id` when it is the turn's first assistant
  message).
- **The message tree (ADR-0082, stage CU2).** Every stored row has a `parent_id` (none for a first message) and the conversation a `head_id`, the last row of the
  branch on screen. An edited message is a sibling of the one it replaced; an answer made again is a sibling of the answer it replaced. One assistant turn is
  several rows chained one under the other (the call, the tool row, the answer); the first row of it names the turn. Run input:
  - **`parent_message_id`** (string): where the turn goes. Left out = under the head (what every client did before). `""` = a first message. An id = under the
    **last row of the turn that starts at that id** (a user message is its own last row), so a client names an assistant turn by its first row. An id that is not
    in the conversation is refused (`not_found`).
  - **`regenerate`** (bool, with `conversation_id` and `parent_message_id` = a **user** message): answer that message again. No new message is stored; the answer
    becomes its sibling; `text` is not needed. Anything else as the parent is refused (`invalid_request`).
  - `GET /products/wasifyai-assistant/conversations/{id}` answers the branch on screen (messages oldest first, each with `parent_id`) and `head_id`; with
    **`?tree=1`** every message of every branch. `PATCH` takes `{title?, head_id?}`: `head_id` (any message of a branch; the engine keeps the last row of that turn)
    is how the window says which branch the person chose, so a reload comes back to it. A conversation from before the tree reads as a chain with its head at the end.
  - The model is only ever given the branch the turn is on.
- **Attachments (ADR-0083, CO2).** Run input **`attachments`**: `[{id, name}]`, at most 4, the ids of uploads made just before: a picture through `POST /products/wasifyai-assistant/uploads/images`
  (the hardened upload; answers `upload_id`), a document through `POST /products/wasifyai-assistant/attachments` (body = the file, `x-file-name` = its name, percent-encoded; answers `{id, kind, name, chars,
  pages, truncated}`; text, Markdown, CSV and HTML, and PDF and Office when the document reader is installed). The user message is stored with `attachment` parts `{kind, id, key, name, bytes}` and the
  uploads are consumed; a conversation read adds a short-lived `url` to a picture part. A picture for a model that cannot read pictures ends the run with `refused`, code `no_vision`, and stores nothing.
  Attachments are untrusted text (see the next point). `GET .../options` also answers `attach: {available, images, documents, images_note, picture_reader}`; `picture_reader`
  `{state: "available" | "downloading", title, licence, from, bytes, download?}` appears when the chosen file model has no vision projector and the app can fetch one (desktop):
  `GET /desktop/vision` answers `{vision: {state: "ready" | "unavailable" | "available" | "downloading", ...}}` and `POST /desktop/vision/download {bytes}` (the size the person was shown; `409` otherwise)
  fetches it. A message may have attachments and no `text`; the chat is then named after the first file. A failed `web_search` / `web_read` result's `output` carries `{message, code}`.
- **Read aloud (ADR-0083, CU3) is not a stream and not a run.** `POST /products/wasifyai-voice/read-aloud` takes JSON `{text, part}` (`text`: a reply as the model wrote it, 1 to 40,000
  characters; `part`: 0 to 7, default 0; unknown fields are refused) and answers one **passage** of it spoken: `{audio, part, parts, truncated, seconds, model, displaced}`. The engine turns the text into
  plain words (code blocks, addresses, tags, citations like `[1]`, table rules, control and bidirectional characters dropped; the text of links, headings and emphasis kept), cuts it at the ends of
  sentences into passages of at most 600 characters (the first about 300, so sound starts sooner), and reads at most 8 of them (`truncated` is true when the reply was longer than that: it is read from its start). `parts` is how many passages
  there are (never above 8) and the window asks for `part` 1 while part 0 plays. `audio` is a **base64 WAV** (the speech model's own rate, mono, 16-bit): this is the one route that carries sound
  bytes in JSON, because nothing is stored to link to (the audio is not kept anywhere, on the engine or in the window) and the web's pass-through (`apps/web/app/api/products/[productId]/[...path]`)
  forwards a JSON body unchanged, so no custom response headers are needed. `displaced` is `"chat"` when the chat model had to be unloaded to make room. Nothing is kept: no creation, library row,
  search entry, usage row, file or log of the words. Refusals are `{detail: {code, message}}`: `nothing_to_read` (422: only code or a picture), `no_such_part` (404), `text_too_long` and the
  speech model's own refusals (422), `model_missing` / `runtime_missing` / `no_model` (409: the message says what to get), the speech runtime failing (502), no speech engine (503). The window shows
  the `message`. It is not an action (`docs/actions.md`, "Not actions").
- **Cards that wait for the person (ADR-0071).** Run input **`approvals`** (bool): this client shows a card and sends the answer back. Only then does an action that
  needs the person's yes (after the web was read, a picture or a song; a `destroy` action) park the turn. Without it that action is refused in words, as before.
  The turn emits `interrupt` with `kind: "confirm_action"` and `payload {kind, tool_call_id, title, summary, params, action_id, effect, badges, consent, fields,
  screen}` (`params`: a few short parameters, plain text; `fields`: one row per field of the action's input, drawn from its schema: `{name, label, kind: text |
  long_text | number | bool | choice, required, description?, choices?, min?, max?, max_length?, value?}`; `badges`: short words such as "leaves this computer";
  `consent`: the statement a `needs_consent` action needs ticked; `screen`: the menu item that does the same thing; stage A2 of ADR-0071), stores a `tool` row with
  a part `{type: "interrupt", kind, status: "pending", tool_call_id, approval_id, run_id, ...the same}` so a reload shows the card, and waits (`waiting_input`).
  **`POST /runs/{run_id}/resume {"value": {"approved": true}}`** answers it; anything but a literal `true` is a no. `{"approved": true, "params": {...}}` is a yes
  with the fields as the person edited them: the action runs with those (the stored part keeps them in `params`), and an action on the floor (delete, consent)
  shows a second card for the edited request. `{"approved": false, "expired": true}` is "the person went on without answering": the turn closes without another
  model call. The part becomes `approved` or `declined`; the tool's `tool_result` follows in the same row and the stream goes on in the same message. A second
  answer is `409`. The window's click is the only way an approval is decided: no action exposes it.
- **When the assistant asks (ADR-0071 decision 5).** Run input **`approval`**: `ask` (the default: a card before every make), `ask_costly` (a card only
  for what takes a while or leaves this computer) or `auto` (no card). The box's Ask button and the card's "Don't ask again in this chat" set it per
  conversation. Deleting and anything that needs the person's word still ask, and after the web or a file is in the chat everything that is not a read
  asks (the taint rule). The card also carries `estimate {seconds, runs}` (the median of this person's last runs of the action, from the audit log; absent
  until one ran) and `pauses_chat` (on the desktop: the action takes the one memory slot, so the chat model pauses).
