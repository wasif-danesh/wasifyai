---
action: job.cancel
synonyms: [long job, job]
---
# Stop a long job

Action: `job.cancel`

## What it is for

Stop a job and the work behind it. A product's own run is stopped too: on this computer the speech runtime restarts, and on the service the engine worker stops its job. A picture or clip the image engine has already started may still finish there, but it is not kept. This has no screen of its own: the assistant and other apps use it.

## Steps in the app

This has no screen of its own: the assistant and other apps use it.

## Fields

- `job_id`: The id an action returned while it was still running.

## Limits

- A job outlives a restart: its status then comes from the product run it started. Work that ran inside the engine itself stopped when the app closed, and says so.

## Needs

- Nothing.

## Examples

- Is the video done yet?

## Problems

- **Not found** The id is wrong or belongs to someone else.
