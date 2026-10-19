---
action: job.cancel
synonyms: [long job, job]
---
# Stop a long job

Action: `job.cancel`

## What it is for

Stop a job that can be stopped. Work that already runs as a product's own run finishes and is kept. This has no screen of its own: the assistant and other apps use it.

## Steps in the app

This has no screen of its own: the assistant and other apps use it.

## Fields

- `job_id`: The id an action returned while it was still running.

## Limits

- A job lives while the app runs; after a restart only how it ended is known.

## Needs

- Nothing.

## Examples

- Is the video done yet?

## Problems

- **Not found** The id is wrong or belongs to someone else.
