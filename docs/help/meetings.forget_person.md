---
action: meetings.forget_person
screen: meetings.people
synonyms: [forget person, delete voiceprint, delete voice, remove person, forget my voice, privacy]
---
# Forget a person

Action: `meetings.forget_person`

## What it is for

Delete a person from People with every voiceprint of them and all the app learnt about their voice.
Voiceprints are personal data: this is how to take them away.

## Steps in the app

1. Open **Meetings › People**.
2. Choose Forget beside the person, and confirm.

## Fields

- `person_id`: The person (from `meetings.people`).

## Limits

- Meetings keep the person's name as words: the transcripts are not changed. Their speakers are no
  longer linked to anyone, and nobody is suggested from that voice.
- It cannot be undone. Deleting a meeting also deletes what was learnt from it.

## Needs

- Someone in People.

## Examples

- Forget Ben's voice.
- Delete everything you know about Asha.

## Problems

- **That person is not in People** They were already forgotten.
