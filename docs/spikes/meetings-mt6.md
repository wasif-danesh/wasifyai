# Meetings MT6: the chat, search and the web (2026-11-16)

Stage MT6 of ADR-0108. The chat runs everything through actions; search and the Library card were built
in MT1. The web takes a file only (decision 7), and in the cloud the provider tells the speakers apart, on
the key (decision 13). Branch `meetings-adr`, after MT5.

## The chat

Every part of Meetings is an action with a help file: `meetings.make`, `meetings.make_recorded`,
`meetings.name_speaker`, `meetings.people`, `meetings.rename_person`, `meetings.forget_person`,
`meetings.write_report`, `meetings.add_template`, `meetings.delete_report`, `meetings.add_to_notebook`,
`meetings.ask`, and the Library's list, read, rename and delete for the kind `meeting`. Two guide cases were
added to the assistant's evaluation (`products/wasifyai-assistant/evals/cases.yaml`: `guide-meeting-ask`,
`guide-meeting-notebook`). They were not run here.

## The web

| Piece | Where | What |
|---|---|---|
| Assembly | `services/api/src/wasifyai_api/assemble.py` (`_web_meetings`) | When the product is in the build: the rows in Postgres (`MeetingStore.on_postgres`, schema `meetings`), the recordings in object storage, a scratch folder for the work (`WebMeetings`). At start, work left `working` for over an hour by a gone replica is failed in words; the list does the same. |
| The image | `services/api/Containerfile` | `--package wasifyai-meetings` |
| Readiness | `tool_host.py` | On the web the actions are ready when the store is there; a missing cloud model is said when a meeting is made. |
| Writing it down | `runtime.py` (`_in_the_cloud`, `turns_of`) | The whole recording to the admin's cloud transcription model (`key:transcribe`) with `diarize`; each word comes back with who said it, and the turns are made from those words (a pause of 2 s or more starts a new turn). A model on the engine is refused: "Meetings need a transcription model in the cloud. An admin chooses one in Admin › Media." |
| The cloud request | `own_keys_voice.py` | Scribe v2 is asked for speakers on every provider; Whisper only on fal.ai (its `diarize` option, `chunk_level: segment`). `words_of` reads Scribe's `words` with `speaker_id`, or Whisper's chunks with `speaker`. `TranscriptSegment` gains `speaker`. |
| Jobs | `MeetingJobs`, `ReportJobs`, `AskJobs` | One at a time for each person on the web (one for everyone on the desktop). |
| The recording | `keep_recording`, `recording_url` | Into storage when the meeting is made; played from a signed link (6 h); deleted with the meeting. No voiceprints on the web (no voiceprint model), so People keeps names only and nobody is suggested. |
| Pages | `apps/web/app/(product)/meetings/page.tsx` (`?open=<id>`), `meetings/people/page.tsx`, `components/meetings/MeetingsScreen.tsx` | The shared `Meetings` and `People` with `hosted`: the texts say "here", not "on this computer", and nothing about voices. Ask opens `/notebooks/<id>`. |
| Menu, Library, parity | `lib/menu.ts`, `lib/creations-nav.ts`, `lib/parity.ts`, `docs/web-parity-ledger.md` | View meetings and People are live; Record is desktop-only (decision 7). A meeting's card opens `/meetings?open=<id>`. |

## Checked

With stand-ins: a fake cloud model that gives speakers per word, and fake storage
(`services/api/tests/test_meetings_routes.py`), plus the cloud requests and the reading of the answers
(`test_own_keys_voice.py`). The web pages were not opened in a browser (vitest and tsc only).

**One real run, 2026-11-16** (the owner's yes). Scribe v2 on fal.ai with the owner's own key (read from
the app's keychain), through the app's `KeyedSpeechEngine` and the Meetings web path (`WebMeetings`, the
routes, the store). Only the storage was a stand-in. The file was 150 s of AMI ES2004a (12:30 to 15:00),
chosen because all four people speak in it (25 to 60 s each). The AMI reference speakers were used to
score the result.

| What | Result |
|---|---|
| `/status` on the web | ready, "Scribe v2 · with your key" |
| Made from the file | done in 16 s (15.7 s of it at fal.ai); 61 lines |
| Speakers found | **3 of 4.** Speaker 1 = FEE013 (87 % of its time), Speaker 2 = FEE016 (79 %), Speaker 3 = MEE014 and MEO015 together (58 % / 33 %) |
| Time with the right person | 74 % |
| Recording kept in storage, then deleted with the meeting | yes |
| Cost | about $0.02 (2.5 min at $0.008 a minute; this fal.ai key cannot read its balance) |

No fault of the app was found. Scribe joined the quietest person (25 s) with another man. That is the
model's own quality, not something the app can fix without being told how many people there are. Whisper
on fal.ai with speakers was not run.

## Not done

- A real run of Whisper on fal.ai with speakers (cost; ask first).
- The web in a browser against a real deployment.
- Recording on the web (decision 7: not in v1).
- The two evaluation cases, run against a real model.
