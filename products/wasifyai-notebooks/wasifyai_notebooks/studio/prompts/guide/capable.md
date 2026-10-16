You write a short guide to a set of source documents, strictly from what they state.

Task: write the guide to the sources below for someone opening the notebook for the first time.
Work in this order:

1. Read every source and note what it is about and the figures and names it states.
2. Write a summary of three to five sentences that says what the sources are, together, about.
3. List the main topics, each a few words, at most 8.
4. Write three questions this material can answer, the kind a curious reader would ask first. Each is a full question that the sources answer.

Grounding rules:

- Use only facts the sources state. No outside knowledge, no plausible-sounding filler.
- A question must be answerable from the sources; never ask about what they do not cover.

Return only JSON, no prose: {"summary": str, "topics": [str], "questions": [str]}

Worked example — a different topic in the same shape. Copy the structure, never the content:

{"summary": "These documents describe the electrification of the Leeds-Hull line: its schedule, its cost and how signalling work moved the date.", "topics": ["Schedule", "Cost", "Signalling"], "questions": ["When must the line be fully electrified?", "What changed the schedule?", "How much does the programme cost?"]}

Return only the JSON. Nothing before it, nothing after it.
