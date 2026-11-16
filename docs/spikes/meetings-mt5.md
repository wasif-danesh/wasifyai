# Meetings MT5: asking through notebooks (2026-11-16)

Stage MT5 of ADR-0108 (decision 16). A meeting's page has **Ask**, and **Add to a notebook**. Questions go
through the notebooks; there is no second engine for questions. Branch `meetings-adr`, after MT4.

## What was built

| Piece | Where | What |
|---|---|---|
| The note | `wasifyai_meetings/asking.py` (`note_of`) | The meeting as a notebook source: title, date, length, the speakers with how long each spoke, the transcript as `[m:ss] Name: words`, and its finished reports. |
| Add to a notebook | `add_to_notebook` | Through the notebooks' own actions (`notebook.list`, `notebook.create`, `notebook.add_source`), run by the app's one executor, as the window would run them. To a notebook of the person's, or to a new one. Kept in `in_notebooks`; added again, the newer source is used. |
| Asking | `AskJobs` | A job (rule 6), one at a time for each person. It goes to a notebook the meeting is in, still there, through `notebook.ask` with `document_ids` limited to the meeting's own source, so the answer cites the meeting's own lines. If the meeting is in no notebook, it is added first to a new notebook named after it (the page says so). It waits up to 3 minutes for the notebook to read a new source. If the source was deleted in the notebook, the link is forgotten and the meeting is added again. Failures are said in words. Kept in `questions`. |
| Routes | `routes.py` | `GET /notebooks`; `POST /meetings/{id}/notebook`; `POST /meetings/{id}/questions`; `GET /questions/{id}`, `POST …/stop`, `DELETE`. The meeting carries `notebooks` and `questions`. |
| The screen | `packages/ui/src/meetings/Asking.tsx` | The question box (Enter asks); each question with where it is, Stop, Delete (asks first); the answer as Markdown with its numbered lines and "Go on in the notebook"; the notebooks it is in, as links; Add to a notebook (an existing notebook or a new one, named). |
| Actions | `actions.py`, `docs/help/` | `meetings.add_to_notebook` and `meetings.ask` (change: a meeting in no notebook is added to a new one first; needs Notebooks and a chat model). |

## Measured (the real engine on the MT3 data folder: four AMI meetings made for real; real notebooks with bge-small embeddings; Qwen3 8B Q4_K_M in the app's llama-server; an M5 Pro; `mt5/real_check.py` in the session scratchpad)

| Step | Result |
|---|---|
| Add ES2004b (39 min) to a new notebook "AMI design project" | 0.4 s; IS1009b added to the same notebook |
| "What did they decide about the remote control's buttons, and who will do what next?" (on ES2004b's page) | 7 s. Right in substance (fewer buttons, most people use about 10% of them, cost; a shockproof, trendy case; more market research), with lines from ES2004b only |
| "What is the project about, and what did each person say about the budget?" (ES2004a, in no notebook) | 6 s: "Adding the meeting to a notebook", "The notebook is reading the meeting", then the answer. The notebook "ES2004a" was made; 25 euros selling price, 12.50 to make, 50 million profit aim, cited from the meeting |
| The notebook across both meetings ("Compare the two meetings") | 7 s; a good account of the first, but it cited IS1009b only |
| "Who spoke most, and what was their role?" | **Wrong**: "Speaker 3"; Speaker 1 spoke 11 minutes, Speaker 3 9. The note now gives each speaker's minutes, but the notebook answers from the passages it finds, and the speaker line was not one of them (asked again after the change: the same answer) |

## What this shows

Asking through notebooks works for what was said: the answers are fast, grounded and cited. Questions
about the whole meeting (who spoke most, how long) are not answered well, because they need the head of the
note, not passages. The meeting page already shows each speaker's time. A fix would be the notebooks' own
(always giving a source's first passage); it is not done here.

## Not done

- The real window; the screen is tested with stand-ins.
- A cloud chat model; another language.
