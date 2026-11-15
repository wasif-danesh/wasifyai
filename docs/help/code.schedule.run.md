---
action: code.schedule.run
screen: code.scheduled
synonyms: [run it now, run the schedule now, try the schedule, start the nightly run]
---
# Run a coding schedule now

Action: `code.schedule.run`

## What it is for

Start a schedule's run at once: the same run as at its time, on a copy of the project.

## Steps in the app

1. Open **Code › Scheduled**.
2. Choose "Run now" on a row. The row says "Running now" until it has ended.
3. Open "History" to look at what it changed, and apply it or let it go.

You can also ask the assistant in the chat.

## Fields

- `schedule_id`: From `code.schedule.list`.

## Limits

- Schedules run only while Wasify AI is open and this computer is awake. A time that passes otherwise is written down as missed; a schedule can run once when the app is back, if less than a day has passed.
- A run works on a copy of the project and never touches the project. Its changes wait in **Code › Scheduled** until you apply them or let them go.
- Nobody is there to answer during a run. A step that a chat would ask about (deleting, installing, a picture) is refused and written down, unless you allowed that kind for the project.
- One run of a schedule at a time: a time that comes while the earlier run is still going is skipped.

## Needs

- The coding engine set up (Settings, under Optional parts), and a project opened in Code › Projects.

## Examples

- Run the nightly check now.

## Problems

- **There is no such schedule** Ask for the list first.
- **Coding is not available** Set up the coding engine in Settings, under Optional parts.
