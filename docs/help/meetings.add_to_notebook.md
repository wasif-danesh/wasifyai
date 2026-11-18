---
action: meetings.add_to_notebook
screen: meetings.list
synonyms: [add to notebook, notebook source, ask across meetings, compare meetings, research meetings]
---
# Add a meeting to a notebook

Action: `meetings.add_to_notebook`

## What it is for

Make a meeting a source of a notebook: its title, date, speakers, the transcript with who said what, and its
reports. In the notebook it can be asked about with the other sources there (other meetings, documents,
pages), with citations, and used for Studio outputs.

## Steps in the app

1. Open **Meetings › View meetings** and open the meeting.
2. Choose **Add to a notebook**, then a notebook of yours or a new one.
3. The page shows the notebooks the meeting is in, with a link to open each.

## Fields

- `meeting_id`: The meeting.
- `notebook_id`: The notebook (empty makes a new one).
- `title`: The new notebook's name (empty uses the meeting's title).

## Limits

- The notebook keeps the meeting as it was when added. Names given or reports written later are in it only
  when it is added again; the newer source is then the one questions on the meeting's page use.
- Deleting the meeting does not delete it from the notebook: delete the source there.

## Needs

- A finished meeting and Notebooks.

## Examples

- Put this week's three stand-ups in one notebook.
- Add the sales call to my "Acme" notebook.

## Problems

- **The meeting is not made yet** Wait until it is made, then add it.
- **That notebook is not there** It was deleted: choose another or a new one.
