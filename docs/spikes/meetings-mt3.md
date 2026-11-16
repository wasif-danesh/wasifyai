# Meetings MT3: People, by voice (2026-11-16)

Stage MT3 of ADR-0108 (decisions 11 and 12). A speaker named on a meeting's page becomes one of People;
their voice is kept, and later meetings suggest them. A name is suggested, never given: the person says
Yes or No, and No is remembered. People can rename or forget a person. Branch `meetings-adr`, after MT2.

## What was built

| Piece | Where | What |
|---|---|---|
| The voiceprint model | `models.yaml` (`eres2net-voxceleb`) | 3D-Speaker ERes2Net (VoxCeleb), the ONNX file sherpa-onnx publishes (26,485,263 bytes, pinned by SHA-256 and a commit), the one MT0b measured. Fetched in Models like the speaker model. |
| Voiceprints | `wasifyai_meetings/voiceprint.py` | Kaldi features in numpy (80 mel bands from 20 to 7,600 Hz, a frame every 10 ms centred with mirrored edges, Povey window, pre-emphasis 0.97, each band's mean taken out, the model's `global-mean`), then a 192-number voiceprint on ONNX Runtime from up to 30 s of a speaker's speech alone (`solo_spans`: lines of at least 0.8 s that no one else talks over). |
| When they are made | `runtime.py` (`MeetingJobs._prints`, `ensure_prints`) | After a meeting is made; for a recording, the You and Others channels are used apart. A meeting made before the model was fetched gets them when it is next opened. |
| Suggesting | `wasifyai_meetings/people.py` | After StenographAI's `speaker_suggestions.py` (MIT, `NOTICE`): the nearest named person by cosine distance, under 0.40 and at least 0.10 nearer than the next person; none when a "not this person" voice is under 0.40 and about as near. "Likely" needs evidence recorded the same way (in the room, on a call, or a file), two meetings, 20 s of speech, 3 turns and turns of 1.55 s on average; otherwise "possible". |
| Evidence | `store.py` (`people`, `speaker_prints`, `prints_made`, `evidence`) | Naming adds `voice` evidence, and `confirmed` evidence between the people named in one meeting (each is not the other); No adds `rejected`. Naming a speaker back to nobody takes back what naming added. Deleting a meeting deletes what was learnt from it. |
| Forgetting | `people.forget_person` | Deletes the person and every voiceprint of them; their name stays in the meetings' transcripts as words. |
| Routes | `routes.py` | `PATCH /meetings/{id}/speakers/{key}` (`name`, or `person_id` for Yes), `POST …/speakers/{key}/not`, `GET /people`, `PATCH` and `DELETE /people/{id}`. `/status` says whether the voiceprint model is here. |
| Screens | `Meetings.tsx`, `People.tsx` (`#/meetings/people`) | On a meeting's page: "Is this Asha?" (likely) or "Could this be Asha?" (possible) with Yes and No; known names offered when naming; a pointer to Models when the voiceprint model is missing. Meetings › People lists people with their meetings and voiceprints, Rename, Forget (asks first). |
| Actions | `actions.py`, `docs/help/` | `meetings.name_speaker` (now through People), `meetings.people`, `meetings.rename_person`, `meetings.forget_person` (destroy: asks a person). |

## Measured

**The features match sherpa-onnx's.** The same WAV through sherpa-onnx 2.0.1's extractor (the one MT0b used)
and through `voiceprint.py`: cosine 1.000. A top band of 8,000 Hz and snipped edges had given 0.83 to 0.88.

**The real check** (`mt3/real_check.py` in the session scratchpad): the real engine in process on a fresh data
folder, linked to the app's installed audio.cpp (Parakeet TDT 0.6B v3) and llama.cpp; the real Sortformer
file; an M5 Pro. AMI meetings: ES2004a and IS1009a made from files, each speaker named by the AMI participant
who spoke most of their lines (a speaker less than 60 % one person was left unnamed); then ES2004b and IS1009b,
the same eight people on other days.

| Step | Result |
|---|---|
| The voiceprint model through Models (the real download) | done in 3 s, hash matches, `/status` ready |
| Making ES2004a (17 min), IS1009a (14 min), ES2004b (39 min), IS1009b (34 min) with voiceprints | 29 s, 19 s, 52 s, 46 s |
| Suggestions in ES2004b and IS1009b, of the 7 people named before | **5 right, 0 wrong**, 2 not suggested; all "possible" (one meeting of evidence each) |
| The one person never named (FIO084, mixed in IS1009a) | not suggested, as it should be |
| Yes on a suggestion | the speaker is named, People shows them in 2 meetings |
| Forget a person | gone from People; their voiceprints and evidence deleted |

The distances: the right suggestions were 0.08 to 0.29 from the earlier voiceprint. The two missed were 0.60
away (the same person sounding different on another day's microphone); for one of them a wrong person was at
0.45. So 0.40 was kept: a looser line would have named the wrong person. The thresholds are StenographAI's.

## Not done

- The real window (no desktop control in this session); the screens are tested with stand-ins.
- A third meeting of the same people, where "likely" would show.
- Recorded meetings (You and Others) with real people; meetings in other languages (English only for now,
  owner 2026-11-16). The voiceprint model is trained on VoxCeleb, which has many languages.
- The web (MT6).
