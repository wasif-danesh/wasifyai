---
action: meetings.write_report
screen: meetings.list
synonyms: [summary, summarise, summarize, minutes, action items, todo, tasks, decisions, stand-up, standup, sales call, report, recap, meeting notes]
---
# Write a report of a meeting

Action: `meetings.write_report`

## What it is for

Write a report of a meeting from a template: a summary, minutes, action items, decisions, a stand-up
or a sales call, or a template of your own. The chosen chat model writes it from the transcript, with the
speakers' names, in the language of the meeting, using only what was said.

## Steps in the app

1. Open **Meetings › View meetings** and open the meeting.
2. Under Reports, choose a template and choose Write.
3. It is written in the background; a long meeting is read in parts first. You can leave the screen.
4. Copy the report, save it as a Markdown file, or delete it. A meeting can have many reports.

## Fields

- `meeting_id`: The meeting.
- `template`: `summary`, `minutes`, `actions`, `decisions`, `standup`, `sales`, or the id of your own
  template (`own-…`).

## Limits

- One report is written at a time.
- A small local model may miss things in a long meeting; a larger one, or one on your key, does better.
- Name the speakers first: a report says "Speaker 2" where no name was given.

## Needs

- A finished meeting and a chat model (in Models, or on your key in Settings).

## Examples

- Summarise this morning's stand-up.
- What are the action items from the budget call?

## Problems

- **The chat model did not answer** Check the chat model in Models and try again.
- **A report is being written** Wait for it to finish, or stop it on the meeting's page.
