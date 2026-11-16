# Meetings, stage MT1: a meeting made from a file (2026-11-16)

ADR-0108, stage MT1: the product `products/wasifyai-meetings`, a meeting made from a recording (who
spoke when and what they said), and the meeting page. Built on branch `meetings-adr`, not committed.

## What is built

| Piece | What |
|---|---|
| The speaker model | `wasifyai_meetings/sortformer.py`: Sortformer 4spk v2.1 as ONNX on ONNX Runtime (CPU), our own streaming loop, ported from the MT0b runner. Features are made one chunk (about 10 s) at a time from the WAV on disk (memory-mapped), so a long meeting does not load whole |
| The model file | `products/wasifyai-meetings/models.yaml`: `sortformer-4spk-v2.1`, 492,268,840 bytes, SHA-256 `d853932a…b8bc`, the URL pinned to commit `434632d5` of `christopherthompson81/sortformer_parakeet_onnx`. Fetched in Models after a click, into the new model folder `meetings` |
| Reading a file | `audio.py`: any sound or video file through the bundled FFmpeg (`imageio-ffmpeg`), else `afconvert`, to 16 kHz mono 16-bit WAV kept as the meeting's recording |
| Writing it down | the voice product's chosen speech-to-text model through `state.audio`, **in pieces of at most 4 minutes**, each cut in the longest pause of the minute before (from the speaker model's turns) |
| Who said what | `merge.py`: each word goes to whoever spoke at that moment (Parakeet gives word times; `TranscriptResult.words` is new, optional, and empty for models without them); a line ends where the speaker changes, or after a sentence once it is 30 s long. Without word times a sentence goes whole to whoever spoke most of it |
| The product | `store.py` (`<app data>/meetings/meetings.db`, recordings under `files/`), `runtime.py` (one job at a time, stages in words, Stop, a left-running meeting failed in words at start), `routes.py` (`/products/wasifyai-meetings/status`, `/meetings` …), `index.py` (the creation kind `meeting` in search: title, speakers' names, words) |
| Actions | `meetings.make` (from a track or speech of the library, waits for it), `meetings.name_speaker`; meetings as a library kind (list, look, rename, delete, save as text, read). Help: `docs/help/meetings.make.md`, `docs/help/meetings.name_speaker.md`. The catalogue's cap moved from 100 to 102 |
| The menu | the group **Meetings** after Notebook: Record, View meetings, People. The desktop hides Record (MT2) and People (MT3) until they are built; the web shows all three as Soon |
| The screen | `packages/ui/src/meetings/Meetings.tsx`: the list with progress, New meeting from a file, what is missing in words with Open Models; the meeting page with the speakers (time each spoke, choose one to name them), a player, the lines with a time that plays from there, Rename, Save as text, Stop, Delete (asks first) |

## Measured

The real engine app (in process) on a throwaway data folder linked to the app's installed audio.cpp and
Parakeet TDT 0.6B v3, the real Sortformer file; an M5 Pro. "Right person": in 0.1 s steps across each
line, while someone in the hand-marked turns speaks, the line's speaker (best one-to-one naming) is one of
them. Script and data: the session scratchpad (`mt1/real_run.py`, `mt1/score.py`), AMI meetings from MT0.

| Meeting | Length | Whole job | Speakers step | Writing it down | Speakers found | Right person |
|---|---|---|---|---|---|---|
| ES2004a | 17.5 min | 29.6 s (35x) | 16.6 s (63x) | 12.8 s, 5 pieces | 4 of 4 | 95.9 % |
| EN2002b | 29.8 min | 44.4 s (40x) | 25.5 s (70x) | 18.3 s | 4 of 4 | 94.6 % |
| IS1009a | 14.0 min | 24.0 s (35x) | 11.9 s (71x) | 11.8 s | 4 of 4 | 92.1 % |
| IS1009a as M4A (96 kb/s AAC) | 14.0 min | 23.5 s | 11.8 s | 11.4 s | 4 of 4 | 89.6 % |

- The port gives exactly the MT0b runner's turns on ES2004a (242 turns; two with the same start swap
  places). Features made a chunk at a time equal the whole recording's to the last bit, ends included.
- **audio.cpp's Parakeet refuses a whole meeting** ("Parakeet TDT encoder relative position frames exceed
  maximum" at 17.5 min; 5 min works), hence the pieces.
- With sentences given whole to one speaker, "right person" on ES2004a was 80 % by an older measure that
  counted overlapping speech as wrong; by the measure above, words lifted it to 95.9 %.
- Peak memory of the speaker step alone: 883 MB (the model is 492 MB).

The window: `apps/desktop/scripts/ui-audit.sh light meetings,meetings-page,meetings-make` (and `dark
meetings,meetings-page`) with `WASIFYAI_AUDIT_MEETING` set to a recording, on the throwaway data folder;
pictures in `docs/ui-audit/desktop/meetings*.png`. A 5-minute WAV and a 14-minute M4A were made from the
window's file picker, followed while working and opened when done; naming a speaker was opened. This is
the window's code served by Vite with the shell stood in for, not the Tauri window.

## Finished after the first pass (2026-11-16)

| Piece | What |
|---|---|
| The Library | the kind `meeting` has a card (title, length, number of speakers, the people icon), a **Meetings** filter, search hits shown as cards, and Delete from the Library (`packages/client/src/creations.ts`, `packages/ui/src/creations/`). A meeting opens at its own address, `#/meetings/<id>` (`apps/desktop/src/router.ts`). The web lists none (MT6). The search check corpus has a meeting row (`roof-budget-meeting`) |
| The language | **Language of the meeting** on the screen (the voice screens' `LanguageField`): "Find it by itself", the languages a ready speech model knows, then the rest. `/status` lists the ready speech models with their languages; a meeting in a language the Voice model does not know goes to a ready one that does (`model_for`, so Bengali goes to IndicConformer and English stays on Parakeet). With none, the screen says so and offers Models, and the engine refuses in words |
| Playback | the recording lives in the desktop's file storage (`<data>/files/<tenant>/wasifyai-meetings/<user>/<id>/audio.wav`) and plays from a signed link (`GET /meetings/{id}/audio-link`, six hours). The desktop's `/files` route now sends a file from disk in ranges (`FileResponse`): an hour of a meeting is no longer loaded whole into the window, and videos and music gain ranges too |
| Search words | a meeting's search text says "A meeting." besides its title, people and words |
| Clean-ups | the converter is stopped when it runs past 30 minutes; pyright is clean on the product |
| Tests | the screen had none: `packages/ui/src/meetings/meetings.test.tsx` (missing model, the language sent, no model for a language, a meeting's page and naming, following and stopping); a Library test; route tests for the link, ranges and a forged link; `model_for` |

### The real check (engine in process, a fresh data folder, 2026-11-16)

`mt1b/real_check.py` in the session scratchpad, on IS1009a (14 min, M4A):

| Step | Result |
|---|---|
| Making a meeting with no speaker model | refused: "Get the speaker model first (about 490 MB, in Models)." |
| The speaker model through Models (the real download from Hugging Face) | 492,268,840 bytes in 32 s; the hash matches the pin; `/status` then ready |
| Bengali with only Parakeet here | refused: "Parakeet TDT 0.6B v3 does not know Bengali. Choose a model that does." |
| The meeting, language English | done in 25.5 s (speakers 11.7 s, words 13.4 s), 4 speakers, 94 lines |
| A range of the recording by its link | 206, `bytes 1000000-1000999/26843234` |
| The Library's list by id | found |
| Search "remote control design meeting" | found |
| Search with other words, in French, in Bengali | not found |
| Delete | the recording gone, no longer found by search |

Search with other words or another language misses because a desktop without a model gateway indexes
every kind with the hashing embedder (`local_embedder.py`, words, not meaning): this is the platform's,
for every kind, not something meetings can fix.

## Not done

- **The Tauri window.** The shell was built, and a data folder with two real meetings was made for it, but
  this session had no desktop control (Computer use), so the real window was not looked at. The screens
  were seen through Vite and Playwright in the first pass.
- **A Bengali meeting: not needed for now.** The owner, 2026-11-16: meetings are checked in English only
  for now. The language field and the choice of model stay (tested with stand-ins; the refusal for real).
- **A model without word times** (or a cloud speech model, which costs money) was not run; the sentence
  path is tested only with stand-ins.
- Windows and Linux; the owner's own meetings; Stop while the real speaker model works.
- The web (MT6).
