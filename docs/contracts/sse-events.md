# SSE event contract

Status: **Finalised (Phase 1)**. Changes need an ADR. Additive fields of ADR-0082 (accepted 2026-10-20): `job_progress.tool_call_id`,
the run request's `run_id`, `POST /runs/{run_id}/cancel`, and the assistant's message ids (last section). The Pydantic models in `packages/contracts` (`wasifyai_contracts/events.py`) are the source of truth;
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
| `interrupt` | Graph pauses for the user | `interrupt_id`, `kind` (e.g. `approve_lyrics`), `payload` (editable data) |
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
- **`done.outputs`** also carries `user_message_id` and `assistant_message_id`: the ids the two messages were stored under
  (the chosen ones, or the engine's own when none were sent, or when the chosen ones were taken).
- **Stop** keeps the words written so far as the reply (stored under `client_reply_id` when it is the turn's first assistant
  message).
- Not in this contract yet (stage CU2): `parent_message_id`, a conversation read with the tree, a stored `interrupt` part.
