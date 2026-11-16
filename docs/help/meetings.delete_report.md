---
action: meetings.delete_report
screen: meetings.list
synonyms: [delete report, remove summary, delete minutes]
---
# Delete a report of a meeting

Action: `meetings.delete_report`

## What it is for

Delete one report of a meeting. The meeting and its other reports stay.

## Steps in the app

1. Open the meeting in **Meetings › View meetings**.
2. Under Reports, choose Delete beside the report, and confirm.

## Fields

- `report_id`: The report.

## Limits

- It cannot be undone; write it again from its template if needed.

## Needs

- A report.

## Examples

- Delete the old summary of the budget call.

## Problems

- **That report is not there** It was already deleted.
