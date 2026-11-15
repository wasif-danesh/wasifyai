---
action: code.schedule.change
screen: code.scheduled
synonyms: [pause a schedule, stop the nightly run, resume a schedule, change the time, switch a schedule off, change what it does]
---
# Change or pause a scheduled coding run

Action: `code.schedule.change`

## What it is for

Pause a schedule, start it again, or change what it asks, when it runs or its name.

## Steps in the app

1. Open **Code › Scheduled**.
2. Use the switch on a row to pause it or start it again.
3. To change its words or its time, open "History" on the row and choose "Change".

You can also ask the assistant in the chat.

## Fields

- `schedule_id`: From `code.schedule.list`.
- `enabled`: False pauses it, true starts it again.
- `request`, `rule`, `title`: What to change.

## Limits

- The next time is worked out again from now. Nothing that passed while it was paused is run.
- A schedule stays in its project: to move it, delete it and make it again.
- Deleting a schedule is done on its History page, not by the assistant.

## Needs

- The coding engine set up (Settings, under Optional parts), and a project opened in Code › Projects.

## Examples

- Pause the nightly check.
- Move the README schedule to Friday at four.

## Problems

- **There is no such schedule** Ask for the list first.
- **Coding is not available** Set up the coding engine in Settings, under Optional parts.
