# Meetings on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## A meeting from a file (ADR-0108, stage MT1)

A recording becomes a meeting: who spoke when, and what they said. The menu group **Meetings** has View
meetings, Record (MT2) and People (MT3), below. Details and measurements:
`docs/spikes/meetings-mt1.md`.

| Piece | What |
|---|---|
| The speaker model | Sortformer 4spk v2.1 as ONNX (`sortformer-4spk-v2.1` in `products/wasifyai-meetings/models.yaml`, 492 MB, model folder `meetings`), run by `wasifyai_meetings/sortformer.py` on ONNX Runtime on the processor, about 70 times faster than the recording. Up to 4 speakers per recording |
| Writing it down | the speech-to-text model chosen for Voice (`state.audio`), in pieces of at most 4 minutes cut in pauses; word times (Parakeet) give each word to whoever spoke then |
| The product | `products/wasifyai-meetings`: `<app data>/meetings/meetings.db` and each meeting's recording (16 kHz WAV) under `files/`; one meeting made at a time; routes under `/products/wasifyai-meetings/`; the creation kind `meeting` in search; actions `meetings.make` and `meetings.name_speaker` |
| The screen | `packages/ui/src/meetings/Meetings.tsx`, `/meetings` in the window (`#/meetings/<id>` opens one): the list, Language of the meeting, New meeting from a file, the meeting page (speakers, player, lines, Rename, Save as text, Stop, Delete) |
| The recording | kept in the desktop's file storage, played from a signed link that the `/files` route serves in ranges |
| The Library | a card and a Meetings filter; search finds a meeting by its title, its people and its words |
| Checks | `products/wasifyai-meetings/tests/`, `services/api/tests/test_meetings_routes.py` (stand-ins for the models); the walk `apps/desktop/scripts/ui-audit.sh light meetings,meetings-page,meetings-make` |

Asking (MT5) and the web (MT6) are below. Not checked: the Tauri window itself and a speech model without
word times. Meetings are checked in English only for now (owner, 2026-11-16).

## Recording a meeting (stage MT2)

Meetings › Record records the microphone as You and the computer's sound as Others, in one file with two
channels, and makes it into a meeting when Stop is chosen (here or in the menu bar). Details and
measurements: `docs/spikes/meetings-mt2.md`.

| Piece | What |
|---|---|
| The shell | `apps/desktop/src-tauri/src/recorder.rs`: the microphone through `cpal`; the computer's sound through a Core Audio process tap on a Mac (macOS 14.2 or later, `cidre`, after Meetily, MIT) and a WASAPI loopback on Windows; none on Linux yet. Files in `<app data>/meetings/recordings/`. The menu bar shows the time and Stop. Check it with `WASIFYAI_RECORD_TEST=<seconds>` and a throwaway `WASIFYAI_DATA_DIR` |
| The engine | `POST /meetings/recorded {name}`, `DELETE /recordings/{name}`, `recordings` in `/status`; each side written down on its own, the microphone one speaker (You), its echo of the call dropped |
| The screen | `packages/ui/src/meetings/RecordMeeting.tsx`, `#/meetings/record`; the bridge `apps/desktop/src/meetings.ts` |
| Action | `meetings.make_recorded` (from a waiting recording; the assistant cannot start one) |

Not checked: the microphone and the permission questions in a signed app, a real two-sided call, the menu
bar item by eye, Windows, Linux's computer sound.

## People (stage MT3)

A speaker named on a meeting's page becomes one of **People** (Meetings › People): their voice is kept,
and later meetings suggest them ("Is this Asha?", Yes or No). A name is only given when the person says
Yes; No is remembered and counts against that suggestion later. Details and measurements:
`docs/spikes/meetings-mt3.md`.

| Piece | What |
|---|---|
| The voiceprint model | 3D-Speaker ERes2Net (VoxCeleb) as ONNX (`eres2net-voxceleb` in `models.yaml`, 26 MB, folder `meetings`), fetched in Models; `wasifyai_meetings/voiceprint.py` makes Kaldi features in numpy (the same as sherpa-onnx's, cosine 1.000) and a 192-number voiceprint per speaker from up to 30 s of their speech alone |
| When | after a meeting is made (a recording's You and Others channels are used apart); a meeting made before the model was fetched gets its voiceprints when it is next opened |
| Suggesting | `wasifyai_meetings/people.py`, after StenographAI's rules (MIT, `NOTICE`): the nearest named person by cosine distance under 0.40 and 0.10 nearer than the next; "likely" only with two meetings of evidence recorded the same way and enough speech, otherwise "possible"; a "not this person" answer near the voice stops it |
| Kept | `people`, `speaker_prints`, `evidence` in `meetings.db`; deleting a meeting deletes what was learnt from it; Forget deletes a person and every voiceprint of them, and keeps their name in transcripts as words |
| The screens | the meeting page (suggestions, known names offered when naming, a pointer to the model), `packages/ui/src/meetings/People.tsx` at `#/meetings/people` |
| Actions | `meetings.name_speaker`, `meetings.people`, `meetings.rename_person`, `meetings.forget_person` (asks first) |

## Reports (stage MT4)

A meeting's page has **Reports**: choose a template (Summary, Minutes, Action items, Decisions, Stand-up,
Sales call, or one of your own) and Write. The chat model chosen in Models writes it from the transcript,
in the meeting's language; a long meeting is read in overlapping parts and the report written from the
notes, so a small model can do it. Details and measurements: `docs/spikes/meetings-mt4.md`.

| Piece | What |
|---|---|
| The engine | `wasifyai_meetings/reports.py` (`ReportJobs`, one at a time; `text.chat` in `product.yaml`); `reports` and `templates` in `meetings.db`; usage `meetings.report` |
| Search | a meeting's reports are part of its words in search |
| The screen | `packages/ui/src/meetings/Reports.tsx`: Write, the progress and Stop, the text with Copy, Save (Markdown) and Delete (asks first); New template |
| Actions | `meetings.write_report`, `meetings.add_template`, `meetings.delete_report` (asks first) |


## Asking (stage MT5)

A meeting's page has **Ask** and **Add to a notebook**. Questions go through Notebooks: the meeting becomes a
source (speakers with their minutes, the transcript, its reports), and a question on its page is answered
from that source only, with the lines it came from. A meeting in no notebook is added to a new one named
after it at the first question. Details and measurements: `docs/spikes/meetings-mt5.md`.

| Piece | What |
|---|---|
| The engine | `wasifyai_meetings/asking.py` (`AskJobs`, one at a time per person), through the notebooks' actions; `in_notebooks` and `questions` in `meetings.db` |
| The screen | `packages/ui/src/meetings/Asking.tsx`: the question box, answers with numbered lines, Stop, Delete (asks first), the notebooks it is in, Add to a notebook |
| Actions | `meetings.add_to_notebook`, `meetings.ask` |
| Known limit | questions about the whole meeting ("who spoke most") are answered from passages and can be wrong |

## On the web (stage MT6)

From a file only; written down with speakers by the cloud model an admin chose. Rows in Postgres,
recordings in storage, no voiceprints. Details: `docs/spikes/meetings-mt6.md`.
