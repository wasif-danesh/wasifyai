# ADR-0108: Meetings: record a meeting, tell the speakers apart, write reports and ask about it

- **Status:** Accepted (2026-11-16, the owner: "Accept it"). MT1 built 2026-11-16 (`docs/spikes/meetings-mt1.md`); MT2 built 2026-11-16 (`docs/spikes/meetings-mt2.md`); MT3 and MT4 built 2026-11-16 (`docs/spikes/meetings-mt3.md`, `meetings-mt4.md`); MT5 and MT6 built 2026-11-16 (`meetings-mt5.md`, `meetings-mt6.md`; the web checked with stand-ins only). All stages are built.
  Proposed 2026-11-15. Spikes MT0 and MT0b are done
  (`docs/spikes/meetings-mt0.md`); decisions 8, 9 and 11 were changed by their results the same day.
- **Date:** 2026-11-15
- **Asked for by the owner, 2026-11-15:** a way to record and summarise meetings. "Telling speakers apart is an
  important part for us. Also, ask questions, report etc." On the tool for telling speakers apart: "Can we keep a
  single tool for all platforms, if possible?"
- **Keeps:** ADR-0041 (every creation can be searched), ADR-0065 (notebooks), ADR-0066 (speech models are chosen per
  task), ADR-0068 (every feature is an action), ADR-0086 (the model button and its download approval), ADR-0094 (no
  consent gates or marks), ADR-0100 (cloud models on the person's keys), rule 6 (slow work is a job), rule 7
  (tenancy), rule 9 (usage), rule 10 (files through storage).
- **Read for this ADR:** StenographAI (`github.com/stenolabs/stenoai`, MIT, commit f4bbe81) and Meetily
  (`github.com/Zackriya-Solutions/meetily`, MIT, commit 2166bc6), both cloned under `~/Projects`. Neither was run.
- **Number:** 0108. 0107 is taken by the coding harness on branch `coding-harness`. If another branch takes 0108
  first, this one moves up.

## Context

The owner wants to record a meeting (an online call or people in a room), get a transcript that says who spoke,
get a summary or a report in a chosen shape, and ask questions about one meeting or many.

What Wasify AI has already:

- **Speech to text** in the voice product: Parakeet TDT 0.6B v3 on this computer (25 European languages, word
  times), IndicConformer 600M for Bengali, Hindi, Marathi, Telugu, Tamil and Gujarati, and cloud transcription on the
  person's key. The cloud call sends `"diarize": False` today (`own_keys_voice.py`).
- **A chat model** for summaries (local, or Claude Haiku 5.5 on a key, ADR-0100).
- **Notebooks**, which answer questions from their sources with search and citations (ADR-0065).
- **One search** over every creation (ADR-0041), and **actions** the chat can run (ADR-0068).

What is missing: recording the other side of a call (system audio), telling speakers apart, naming them, and report
templates.

### What the two apps offer

| | StenographAI | Meetily (free version) |
|---|---|---|
| Shell | Electron, a Python backend, Swift helpers | Tauri 2 and Rust, like ours |
| System audio | `electron-audio-loopback` on Mac and Windows, PipeWire `pw-record` on Linux | Rust: a Core Audio tap through `cidre` on Mac, `cpal` loopback on Windows, PulseAudio on Linux |
| Speakers | "You" and "Others" from the two channels; then Speaker 2, 3… from a Swift helper on FluidAudio (Sortformer, 4 speakers, or Nemotron 3, 8) with WeSpeaker voiceprints; **macOS 14 and later only** | None. Speaker identification is in the paid version |
| Naming speakers | Suggests a known person from saved voiceprints; a person always confirms (`speaker_suggestions.py`) | None |
| Reports | Several per meeting from templates; long transcripts summarised in overlapping parts | Six templates, one summary |
| Asking | The whole transcript (up to 100,000 characters) put in the prompt | None found |

The lesson in StenographAI's speaker code is worth keeping: automatic naming was tried and taken out, because
people sharing a room or a microphone scored as alike whoever they were. It now keeps a person's voiceprints apart
by how they were recorded (in the room, remote, imported) and remembers who a voice is **not**.

## Decision

### Name and place

1. **It is called Meetings.** A recording, its transcript, its speakers and its reports are one **meeting**. The
   menu group is **Meetings**, with three items: **Record**, **View meetings** and **People** (the voices it knows).
2. **Its own menu group, not under Voice.** Voice holds one-step tools (speak, transcribe, dub). A meeting is a
   workspace the person comes back to, with a list, people and reports, like Notebook. Voice already has seven
   items. "Speech to text" stays in Voice for a single file.
3. **Its own product, `products/wasifyai-meetings`.** It uses the voice product's transcription and the notebooks'
   search; it does not copy them.

### Recording

4. **The desktop records two channels: the microphone and the computer's sound.** The microphone is "You", the
   computer's sound is "Others". The capture is in the Tauri shell, in Rust, after Meetily's approach (Core Audio tap
   on Mac, WASAPI loopback on Windows, PulseAudio or PipeWire on Linux). Code taken from Meetily keeps its MIT notice.
5. **A meeting can also start from a file:** a recording from the Library or from the computer, with one channel.
6. **While recording, the tray and the window show it plainly**, with Stop one click away. There is no consent
   question and no mark on the file (ADR-0094).
7. **On the web, v1 takes a file only.** Recording in the browser (microphone and a tab's sound) is a later stage.

### Telling speakers apart

8. **One tool on every platform: NVIDIA's Streaming Sortformer (4 speakers, v2.1) as ONNX, on ONNX Runtime**, in
   the engine, on the processor. Our own Python code runs its streaming loop. In MT0b it counted the people right in
   four meetings out of four, gave at most 3.6 % of the speech to the wrong person, ran at about 70 times the
   meeting's speed, and matched or beat FluidAudio on the Mac. sherpa-onnx, proposed first, could not count the
   people (MT0). The ONNX file is a community export, pinned by hash; exporting it from NVIDIA's own file is the
   fallback.
9. **No second engine.** FluidAudio is not used. The Mac's neural chip may come later through ONNX Runtime's CoreML
   provider, on the same model, behind the same result: turns with a speaker each, and one voiceprint per speaker.
10. **Speakers are found inside each channel.** "You" stays one speaker; "Others" is split into Speaker 2, 3…
11. **One voiceprint model everywhere: 3D-Speaker ERes2Net (VoxCeleb) as ONNX**, so a voice saved on one computer
   is known on another. In MT0b it kept different people furthest apart of four models tried, and still named one
   person in four wrong from a room microphone, which is why decision 12 holds. Up to 4 speakers are told apart per
   channel; more needs NVIDIA's 8-speaker Nemotron 3, not exported or tested yet.
12. **Naming is suggested, never done alone.** A person confirms each name. Voiceprints are kept per person and by
   how they were recorded, with "not this person" evidence, after StenographAI's design (MIT notice kept).
   Voiceprints stay on this computer (on the web, in the person's tenant) and People can delete them.
13. **In the cloud, transcription with speakers is used where the provider offers it**, on the person's key.

### Transcripts, reports and questions

14. **Transcription uses the voice product's chosen model for the meeting's language** (Parakeet, IndicConformer,
   or a cloud model). Telling speakers apart does not depend on the language. A language no model covers is a
   separate model decision under ADR-0066, not part of this one.
15. **Reports come from templates.** A meeting has a standard summary and any number of reports (minutes, action
   items, decisions, a sales call, a stand-up, or the person's own template). A long transcript is summarised in
   overlapping parts. Reports run on the chosen chat model, local or on a key.
16. **Questions go through notebooks.** A meeting can be asked about on its own page, and meetings can be added to a
   notebook as sources, to ask across many with citations. No second question-answering engine is built.

### Rules every feature follows

17. **Slow work is a job** (rule 6): transcription, telling speakers apart and reports. Each says where it is.
18. **Every step is an action** (ADR-0068) with a help page: start and stop a recording, make a meeting from a
   file, name a speaker, write a report, add to a notebook, delete. Deleting asks first.
19. **A meeting is a creation** (ADR-0041): its title, transcript, speakers and reports are indexed; it has a card
   and a filter in the Library.
20. **Files go through storage** (rule 10); rows carry the tenant (rule 7); transcription and reports write usage
   events (rule 9).

## Spikes MT0 and MT0b (done 2026-11-15)

Run on four AMI meetings with hand-marked turns and a Chinese clip (`docs/spikes/meetings-mt0.md`): sherpa-onnx and
FluidAudio (MT0), then Sortformer as ONNX and four voiceprint models (MT0b), and a Rust capture of the Mac's sound.

**Still to check before MT2:** Windows and Linux speed, the owner's own meetings, an online call recorded from both
sides, an Indian language with hand marks, and the permission prompt from the signed app. The capture sends nothing
while nothing plays, so the recorder fills silence by the clock.

## Stages

| Stage | What |
|---|---|
| MT0, MT0b | The spikes above (done) |
| MT1 | The product, a meeting made from a file: transcript, speakers, the meeting page (built 2026-11-16) |
| MT2 | Recording on the desktop: two channels, tray, Stop (built 2026-11-16; Linux records only the microphone so far) |
| MT3 | People: naming speakers, voiceprints, deleting them (built 2026-11-16) |
| MT4 | Reports and templates (built 2026-11-16) |
| MT5 | Asking: the meeting's own questions and "Add to a notebook" (built 2026-11-16) |
| MT6 | The chat runs all of it; search, Library card; the web from a file (built 2026-11-16; one real Scribe v2 run on fal.ai: 3 of 4 speakers found) |

## What the owner approved (2026-11-16)

- **New models:** NVIDIA Streaming Sortformer 4spk v2.1 as ONNX (492 MB) and 3D-Speaker ERes2Net VoxCeleb as ONNX
  (26 MB).
- **New dependencies:** `onnxruntime` in the meetings part of the engine (and `sherpa-onnx` only if its voiceprint
  extractor is kept); `cidre` and audio crates in the shell.
- **Code taken from both apps**, with their MIT notices.

## Not in v1

- Live captions while recording (StenographAI shows "You" and "Others" as people speak).
- Noticing that a meeting started, calendars, opening a call's link.
- Recording in the browser on the web.

## Consequences

- One product, one menu group and one way to tell speakers apart, built from the parts of two apps that fit ours.
- Questions and search come from what exists, so a meeting is searchable and can be asked about from the start.
- Voiceprints are personal data. They stay with the person and can be deleted, and no name is given without them.
- One model family on every platform, so the Mac, Windows and Linux give the same speakers and the same voiceprints.
