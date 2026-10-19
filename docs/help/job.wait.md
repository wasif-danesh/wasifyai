---
action: job.wait
synonyms: [long job, job]
---
# Wait for a long job

Action: `job.wait`

## What it is for

Wait a little while (at most 50 seconds) for a job to end. This has no screen of its own: the assistant and other apps use it.

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
