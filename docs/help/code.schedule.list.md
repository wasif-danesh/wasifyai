---
action: code.schedule.list
screen: code.scheduled
synonyms: [my schedules, scheduled runs, what runs tonight, automation, nightly run, when does it run next, schedule history]
---
# List the scheduled coding runs

Action: `code.schedule.list`

## What it is for

See which schedules you have for the coding agent: what each asks, in which project, when it runs next and how its last run ended. It also gives the short list of templates a new schedule can start from.

## Steps in the app

1. Open **Code › Scheduled**. Each row shows the rule in words, the next time and the last run.
2. Choose "History" on a row for every time it came due and what happened.

You can also ask the assistant in the chat.

## Fields

- `schedule_id`: A schedule. Its runs are returned too, the newest first.

## Limits

- Schedules run only while Wasify AI is open and this computer is awake. A time that passes otherwise is written down as missed; a schedule can run once when the app is back, if less than a day has passed.
- A run works on a copy of the project and never touches the project. Its changes wait in **Code › Scheduled** until you apply them or let them go.
- Nobody is there to answer during a run. A step that a chat would ask about (deleting, installing, a picture) is refused and written down, unless you allowed that kind for the project.
- One run of a schedule at a time: a time that comes while the earlier run is still going is skipped.

## Needs

- The coding engine set up (Settings, under Optional parts), and a project opened in Code › Projects.

## Examples

- Which coding schedules do I have?
- How did last night's run of the bakery site go?

## Problems

- **There is no such schedule** Ask for the list first.
- **Coding is not available** Set up the coding engine in Settings, under Optional parts.
