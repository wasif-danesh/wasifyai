---
action: code.schedule.add
screen: code.scheduled
synonyms: [schedule a run, every night, automate, run every day, nightly check, do this every week, recurring task, cron]
---
# Schedule a coding run

Action: `code.schedule.add`

## What it is for

Have the coding agent do something in a project by itself at set times: every day at a time, on chosen weekdays, every month on a day, every few minutes or hours, or once. You can start from a template and change its words and its time.

## Steps in the app

1. Open **Code › Scheduled** and choose "New schedule".
2. Choose the project and say what should be done, or start from a template.
3. Choose when: one of five plain kinds of rule. There is no cron text.
4. "Save the schedule". The list shows when it will run next.

You can also ask the assistant in the chat.

## Fields

- `session_id`: A coding session of the project it runs in.
- `template`: A template's id, from `code.schedule.list`. Its request and rule are the start.
- `request`: What the agent is asked at each run.
- `rule`: When it runs, for example `{"kind": "daily", "time": "09:00"}` or `{"kind": "weekdays", "days": [0, 2, 4], "time": "09:00"}` (0 is Monday).
- `title`: A short name.

## Limits

- Schedules run only while Wasify AI is open and this computer is awake. A time that passes otherwise is written down as missed; a schedule can run once when the app is back, if less than a day has passed.
- A run works on a copy of the project and never touches the project. Its changes wait in **Code › Scheduled** until you apply them or let them go.
- Nobody is there to answer during a run. A step that a chat would ask about (deleting, installing, a picture) is refused and written down, unless you allowed that kind for the project.
- One run of a schedule at a time: a time that comes while the earlier run is still going is skipped.
- Times are clock times in this computer's time zone, also when the clocks change. "Every so many minutes" is five minutes at the least and is counted from when the schedule is saved.

## Needs

- The coding engine set up (Settings, under Optional parts), and a project opened in Code › Projects.

## Examples

- Run the check on the bakery site every night at two.
- Every Monday morning, bring the README up to date.

## Problems

- **There is no such schedule** Ask for the list first.
- **Coding is not available** Set up the coding engine in Settings, under Optional parts.
