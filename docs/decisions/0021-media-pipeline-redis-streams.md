# ADR-0021: Media pipeline on Redis Streams

- **Status:** Accepted
- **Date:** 2026-10-08
- **Refines:** ADR-0006 (queue-based media jobs). The worker no longer "calls back the API".

## Context

ADR-0006 decided that media jobs are queued and run by a worker, never awaited inline. Building
it raised two questions: how does a finished job resume a paused graph, and how can a graph's
events reach the browser when the process that resumes it is not the one holding its connection?

## Decision

- **One event log in Redis Streams.** Every run's SSE events (from the API runtime and from the
  worker) are appended to a per-run stream. A Lua script allocates `seq` and appends atomically,
  so concurrent writers on different processes stay ordered, and `seq` is the SSE id. Any API
  replica serves any run's stream, and `Last-Event-ID` reconnects work across replicas. An
  in-memory implementation remains for tests.
- **Run records in Redis** (owner, status, what the run waits for). Taking a pending user
  answer or job wait is atomic, so two concurrent resumes cannot both win.
- **Job queue and results as streams with consumer groups.** `wasifyai:jobs` (group `workers`) carries
  jobs; `wasifyai:jobs:done` (group `api`) carries results. This gives at-least-once delivery, crash
  recovery (a job idle past its timeout is re-claimed) and queue positions without extra state.
- **Completion without an HTTP callback.** The worker writes the result to `wasifyai:jobs:done`; one API
  replica claims it, takes the run's job wait atomically and resumes the graph. If the result
  arrives before the graph reached its wait, the entry stays unacknowledged and is retried.
  This replaces ADR-0006's "calls back the API": no new HTTP surface, shared secret or retry
  logic, and it survives API restarts.
- **Graph pattern.** Enqueue in one node and pause in the next (`await_job`), because LangGraph
  re-runs a paused node from its start. A job wait is not a user prompt: no `interrupt` event
  is sent, and the stream stays open.
- **Worker guarantees.** One job at a time per GPU id (a Redis lock with renewal, so workers on
  different machines take turns and a dead holder's lock expires). Results are published before the
  job is acknowledged, and a stored per-job result makes redelivery idempotent. Transient
  backend failures retry (back of the queue, bounded attempts); job failures fail once with a
  user-safe error. Ollama's loaded models are unloaded (`keep_alive: 0`) before each job.
- **ComfyUI client.** `POST /prompt`, progress over the WebSocket (connected before submitting),
  outputs from `/history` and `/view`, then `/free` to release models. `COMFYUI_MODE=stub` returns
  placeholder images or audio with simulated progress, so the whole flow runs without a GPU.
- **Usage.** The worker records `gpu.seconds` and `job.completed`; job outputs are stored under the
  owner's `tenant/product/user` prefix and results carry keys relative to it.
- Keys are prefixed with the tenant (`wasifyai:{tenant}:run:{run}:...`); product and user are checked
  against the run record.

## Consequences

- API replicas and workers scale independently; KEDA can scale workers on `wasifyai:jobs` length.
- Redis is now required for runs (it was already in the stack). It holds run state for 7 days.
- Completion messages for runs that ended are dropped after a retry window.
- The Helm chart gains an in-cluster object store, worker wiring and an optional ComfyUI
  Deployment. No ComfyUI image is chosen for you; set `comfyui.image`.
- The GPU Operator and time-slicing steps are documented but were not run on a GPU node.
