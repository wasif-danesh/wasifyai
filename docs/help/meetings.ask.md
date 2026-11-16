---
action: meetings.ask
screen: meetings.list
synonyms: [ask, question, what did, who said, who agreed, what was decided, find in meeting, meeting question]
---
# Ask about a meeting

Action: `meetings.ask`

## What it is for

Ask a question about one meeting: who said something, what was decided, what someone asked for or promised.
The answer is written from the meeting's transcript only, and each point carries a number that shows the
line it came from.

Questions are answered by Notebooks: the meeting is a source of a notebook, and the question is put to that
notebook with only the meeting's source ticked. A meeting that is in no notebook yet is first added to a new
notebook named after it, and the page says so.

## Steps in the app

1. Open **Meetings › View meetings** and open the meeting.
2. Under Ask, type a question and choose Ask.
3. The answer appears with its numbers; open a number to see the line it came from. Earlier questions stay
   on the page. Open the notebook to go on asking there.

## Fields

- `meeting_id`: The meeting.
- `question`: What you want to know.

## Limits

- One question is answered at a time.
- The answer uses only what was said in that meeting. To ask across many meetings, add them to one notebook
  and ask the notebook.
- The first question of a meeting waits for the notebook to read it (a few seconds to a minute).

## Needs

- A finished meeting, Notebooks, and a chat model (in Models, or on your key in Settings).

## Examples

- What did Asha agree to do in the budget call?
- Was a date set for the launch?

## Problems

- **The notebook is still reading the meeting** Ask again in a minute.
- **The notebook could not read the meeting** Add it to a notebook again from the meeting's page.
