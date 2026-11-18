---
action: meetings.rename_person
screen: meetings.people
synonyms: [rename person, change a name, wrong name, spell a name, correct a name]
---
# Rename a person

Action: `meetings.rename_person`

## What it is for

Change a person's name in People and in every meeting they were named in: the transcripts, the saved
text and search all use the new name.

## Steps in the app

1. Open **Meetings › People**.
2. Choose Rename beside the person, type the new name and choose Save.

## Fields

- `person_id`: The person (from `meetings.people`).
- `name`: Their new name.

## Limits

- Two people with the same name stay two people. To join them, forget one and name their speakers
  again.

## Needs

- Someone in People.

## Examples

- Ravi's name is Ravindra.
- Fix the spelling of Asha in all my meetings.

## Problems

- **That person is not in People** They were forgotten, or the id is wrong.
