# Meetings MT4: reports from templates (2026-11-16)

Stage MT4 of ADR-0108 (decision 15). A meeting's page writes reports: a summary, minutes, action items,
decisions, a stand-up, notes of a sales call, or a template of the person's own. The chat model chosen in
Models writes them from the transcript (`text.chat` in `product.yaml`: the local model, or one on the person's
key). Branch `meetings-adr`, after MT3.

## What was built

| Piece | Where | What |
|---|---|---|
| Templates | `wasifyai_meetings/reports.py` (`TEMPLATES`), `store.py` (`templates`) | Six built in; a person's own are a name and what the report says, kept per person. |
| Writing | `ReportJobs` | A job (rule 6), one at a time. The transcript as `[m:ss] Name: words`. Under 12,000 characters it is written in one go; longer, it is read in parts of 12,000 that overlap by 1,200, cut at lines, with notes of each part, and the report is written from the notes (notes over 24,000 characters are shortened first). The instructions: only what was said, never made-up names, numbers or tasks, the names in the transcript, the meeting's language, Markdown. Usage `meetings.report`. A missing or failing chat model is said in words. |
| Search | `runtime.py` (`words_of`) | A meeting's reports are part of its words in search (the first 1,500 characters of each). |
| Routes | `routes.py` | `GET`, `POST`, `DELETE /templates`; `POST /meetings/{id}/reports`; `GET /reports/{id}`, `POST …/stop`, `GET …/export` (Markdown, as an attachment), `DELETE`. |
| The screen | `packages/ui/src/meetings/Reports.tsx` | Choose a report and Write; while it is written, where it is and Stop; then the text with Copy, Save and Delete (asks first). New template; Delete template for one's own. |
| Actions | `actions.py`, `docs/help/` | `meetings.write_report` (needs a chat model), `meetings.add_template`, `meetings.delete_report` (destroy: asks a person). |

## Measured (the real check of MT3, `mt3/real_check.py`; Qwen3 8B Q4_K_M in the app's llama-server, context 16,384, an M5 Pro)

| Report | Result |
|---|---|
| Summary of IS1009a (14 min, one part) | 28 s. Right and useful: the aims, the budget (25 euros, under 12.50 to make), who does what, next steps. The people's own names (they introduce themselves) were used. |
| Action items of ES2004b (39 min, 3 parts) | 179 s: "Reading part 1 of 3" … "Writing". The tasks are right and have who said them ("MEE014" where the speaker was named, "Speaker 3" where not), but an 8B model also listed points discussed, not only tasks. |
| Save | the Markdown file as an attachment, named after the report |
| Delete | gone |
| Search for the report's words | "action items of the remote control design" found the meeting; "who will work on the buttons" did not |

## Not done

- The real window; the screen is tested with stand-ins.
- A cloud chat model on a key (the binding is the same `text.chat`); a meeting in another language.
- Templates in the chat (the actions are there; the evaluation of the assistant was not run for them).
- The web (MT6).
