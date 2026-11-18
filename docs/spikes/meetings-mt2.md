# Meetings MT2: recording on the desktop (2026-11-16)

Stage MT2 of ADR-0108. A meeting is recorded in the window: the microphone is "You", the computer's
sound (the people on the call) is "Others", in one WAV with two channels. While it records, the menu bar
and the window show it, with Stop one click away. There is no consent question and no mark (ADR-0094).
Branch `meetings-adr`, after MT1.

## What was built

| Piece | Where | What |
|---|---|---|
| The recorder | `apps/desktop/src-tauri/src/recorder.rs` | One thread records both sides into `<app data>/meetings/recordings/rec-<unix secs>-<8 hex>.wav` (`.part` while it records): 2 channels, 16 kHz, 16-bit. The header is written again every 2 s, so a crash leaves a usable file. |
| The microphone | `mod microphone` | The default input through `cpal`. |
| The computer's sound | `mod system` | On a Mac, a Core Audio process tap on all output in a private aggregate device (`cidre`, after Meetily, MIT, `PROVENANCE.md`); needs macOS 14.2 or later and "Screen & System Audio Recording". On Windows, a WASAPI loopback through `cpal`. On Linux it is refused in words, and only the microphone is recorded. |
| One clock | `Lane` | Each piece of sound is placed by when it arrived, not by how many came: a gap over 0.2 s is silence, and the writer stays 0.5 s behind the clock, filling silence up to it. A Mac tap sends nothing while nothing plays, so without this the two sides drift apart. |
| Problems in words | `record()` | The microphone giving only zeros for 3 s means it is not allowed: "The microphone gives no sound…". The computer's sound that cannot be opened says why. Either side may fail; recording goes on with the other. |
| The menu bar | `mod tray` (Mac) | A red dot with the time ("● 1:15"), "Recording a meeting", Stop recording and Open Wasify AI. Stop there finishes the file, shows the window and tells it (`meeting-recorded`); the window opens Record and makes the meeting. |
| Commands | `meeting_record_state`, `meeting_record_start`, `meeting_record_stop` | Start waits up to 20 s for the devices (and macOS's questions) off the main thread. A recording still on when the app quits is finished (`finish_on_exit`). |
| The engine | `wasifyai_meetings/channels.py`, `runtime.py`, `merge.py` | `POST /meetings/recorded {name}` takes a recording by its name only (a pattern; nothing else in the folder). It is split into You, Others and both mixed (the mix is kept to play back). A side quieter than 0.2 % of full scale is skipped. Each side gets the speaker model and the transcriber; `merge_two` makes the microphone one speaker, S1 "You", and the computer's speakers S2, S3…; a microphone word that the computer's side has within 1.5 s is its echo and is dropped. `source` is `recorded`. `GET /status` lists the recordings waiting; `DELETE /recordings/{name}` throws one away. |
| The screen | `packages/ui/src/meetings/RecordMeeting.tsx`, `#/meetings/record` | Meetings › Record: Language of the meeting, Start recording; then the time, a meter for You and for Others, problems in words, Stop; then the meeting is made and opened. Recordings not made into a meeting (no speaker model yet, the window closed) wait below: Make it into a meeting, Throw away. |
| The window's bridge | `apps/desktop/src/meetings.ts` | `recorder` over the three commands; Stop in the menu bar is kept until a Record screen listens, and the shell opens Record. |
| Action | `meetings.make_recorded` | Makes a meeting from a waiting recording (the newest without a name). The assistant cannot start a recording: the person does. Help: `docs/help/meetings.make_recorded.md`. |

## Measured on this Mac (M-series, macOS 27, the debug shell, unsigned)

The shell's own check (`WASIFYAI_RECORD_TEST=<seconds>` with `WASIFYAI_DATA_DIR` set to a throwaway
folder) records for real and prints a line about the file.

| Check | Result |
|---|---|
| 16 s while `say` spoke | The computer's side was captured (`others=true`); the speech landed at 7 to 10 s, where it was spoken. |
| 68 s while `afplay` played a 60 s clip of AMI ES2004a through the speakers | The computer's side as loud as the clip (RMS 0.0081 against 0.0087 in the source; peak 0.315 against 0.324); the clip starts 3.27 s into the recording. |
| That recording made into a meeting by the real engine (Sortformer, Parakeet TDT 0.6B v3) | 7.7 s for 68 s (speakers 1.49 s, words 5.89 s); `source` recorded; 2 of the 3 people of that minute found (S2, S3), right person 77.3 % of the speaking time. The same clip from a file in MT1 also gave 2 speakers. |
| The microphone in those runs | Near silent (peak 0.00027): no one spoke, and the unsigned debug build may not have been given the microphone. So "You" was not shown; the silent side was skipped, as meant. |

## Tests

- `products/wasifyai-meetings/tests/test_meetings_channels.py`: splitting, a header with no size, the loudness floor, `merge_two` with the echo dropped.
- `services/api/tests/test_meetings_routes.py`: a recording made into a meeting with You and the others, a silent computer side, throwing one away, bad names refused, the action from the newest waiting recording.
- `packages/ui/src/meetings/record-meeting.test.tsx`: start, the time and meters, Stop and opening the meeting; problems in words; Stop from the menu bar with the chosen language; a refused recording waiting and thrown away; only the microphone.
- `cargo test recorder` (6): the lane's clock placement, gaps, the resampler, the header.

## Not done or not checked

- The microphone in a signed app, and macOS's two permission questions as a person sees them.
- A real two-sided call (someone speaking into the microphone while others speak on the call), and the echo rule on it.
- The menu bar item seen by eye, and the Record screen in the real Tauri window (no screen control in this session).
- Windows' WASAPI loopback (written, not run) and Linux's computer sound (PulseAudio or PipeWire, not built: Linux records only the microphone).
- Meetings are checked in English only for now (owner, 2026-11-16).
