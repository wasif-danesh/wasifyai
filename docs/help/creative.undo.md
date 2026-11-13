---
action: creative.undo
screen: creative
synonyms: [undo the plan, take that back, go back a change, undo that change]
---
# Undo a change to a plan

Action: `creative.undo`

## What it is for

Take back the last change to the plan of a project in Creative Studio.

## Steps in the app

1. Open the project in **Creative Studio**.
2. Choose **Undo** above the plan, or **Undo** on the assistant's card in the Ask tab.

## Fields

- `project_id`: The project.

## Limits

- The last 30 plans of a project are kept, so it goes back that far.
- It cannot go back past the first plan.

## Needs

- A project with a change to take back.

## Examples

- "Undo that."

## Problems

- "There is nothing to undo": this is the project's first plan.
- "The plan is being written": wait for it to finish, or stop it.
