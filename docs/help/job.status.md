---
action: job.status
synonyms: [long job, job]
---
# Check a long job

Action: `job.status`

## What it is for

How a long job started earlier is going. This has no screen of its own: the assistant and other apps use it.

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
