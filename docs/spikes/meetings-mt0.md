# Spike MT0: telling speakers apart, and recording the Mac's sound (ADR-0108)

**In short:** NVIDIA's Sortformer as ONNX on ONNX Runtime is the one tool (MT0b, at the end). sherpa-onnx could not
count the people; FluidAudio was good but Mac only; ERes2Net is the voiceprint model.

- **Date:** 2026-11-15, on this Mac (Apple M5 Pro, 64 GB, macOS 27.0.1).
- **Asked by the owner:** "Yes, run MT0". The question it answers is ADR-0108's decisions 8, 9 and 11: can one tool
  tell speakers apart on every platform, and is it good enough?
- **Work files:** the scratchpad of the session (scripts, outputs). Nothing here is in the app. FluidAudio's models
  were put by StenographAI's helper in `~/Library/Application Support/stenoai/models/speaker-diarization` (to delete
  after the owner has read this).

## What was tested

**Meetings.** The owner's own recordings were not used: none exist yet. Instead, four meetings of the public AMI
Meeting Corpus, with every speaker's turns marked by hand (pyannote's `AMI-diarization-setup`, "only words"). Settings
were tried on the first two; the last two were kept back to check them:

| Meeting | Length | People | Kind |
|---|---|---|---|
| ES2004a | 17.5 min | 4 | A design team in a room, one mixed microphone |
| IS1009a | 14.0 min | 4 | The same, another room |
| TS3003a (kept back) | 25.1 min | 4 | The same, another room |
| EN2002b (kept back) | 29.8 min | 4 | Four people talking freely, much overlap |
| `0-four-speakers-zh.wav` (sherpa-onnx's sample) | 57 s | 4 | Chinese; no hand marks, only the number of speakers checked |

**Tools.**

- **sherpa-onnx 2.0.1** (Python, ONNX Runtime, the processor only): pyannote segmentation 3.0, a voiceprint model,
  and its own clustering. Four voiceprint models: WeSpeaker ResNet34-LM (the one pyannote uses), WeSpeaker CAM++-LM,
  NVIDIA TitaNet small and 3D-Speaker ERes2Net (VoxCeleb).
- **FluidAudio 0.17** (Swift, CoreML on the neural chip), through StenographAI's `diarize-sidecar`, built from a copy:
  NVIDIA's Sortformer (4 speakers) and Nemotron 3 (8 speakers), with WeSpeaker v2 for voiceprints.

**Score.** The diarization error rate (DER) from `pyannote.metrics`: the share of speech time given to nobody, to
somebody when nobody spoke, or to the wrong person. "Full" counts everything (no collar, overlaps included);
"forgiving" leaves out 0.25 s at each turn's edge and the overlapping speech, as many papers do. **Confusion** (speech
given to the wrong person) is the part that matters most for a transcript: missed speech still gets written down by
transcription and goes to the nearest speaker.

## Results

### FluidAudio on the Mac, not told how many speakers

| Engine | Meeting | Speakers found | DER full | Missed | False alarm | Confusion | DER forgiving | Time | Peak memory |
|---|---|---|---|---|---|---|---|---|---|
| Sortformer | ES2004a | **4** | 28.5 | 26.4 | 1.4 | **0.7** | 20.2 | 22 s | 750 MB |
| Sortformer | IS1009a | **4** | 25.9 | 10.9 | 10.4 | **4.7** | 21.5 | 14 s | 695 MB |
| Nemotron 3 | ES2004a | **4** | 27.7 | 26.7 | 0.7 | **0.3** | 22.9 | 19 s | 494 MB |
| Nemotron 3 | IS1009a | **4** | 28.2 | 19.4 | 2.8 | **6.1** | 22.8 | 12 s | 417 MB |

It found the right number of people every time, the Chinese clip included (4 of 4), and almost never gave speech to
the wrong person. Its errors are speech it did not mark at all. It ran at 50 to 70 times the speed of the meeting.

### sherpa-onnx, told that there are 4 speakers

| Voiceprint model | ES2004a DER full (confusion) | IS1009a DER full (confusion) |
|---|---|---|
| WeSpeaker ResNet34-LM | 31.2 (14.8) | 43.1 (28.9) |
| TitaNet small | 20.0 (3.9) | 27.1 (13.1) |
| ERes2Net VoxCeleb | **20.1 (3.9)** | **24.5 (10.3)** |

Told the number, sherpa-onnx with a good voiceprint model misses less speech than FluidAudio (12 and 8 % against 26
and 11 %) and so scores a lower full DER, but gives two to three times more speech to the wrong person on the harder
meeting. The voiceprint model matters more than anything else: ResNet34-LM, the one pyannote uses, is the worst.

### sherpa-onnx, not told: the number of speakers it found

Its clustering joins voices closer than a threshold. No threshold worked for both meetings (4 people in each):

| Voiceprint model | Threshold | ES2004a | IS1009a |
|---|---|---|---|
| ResNet34-LM | 0.5 (default) | 67 | 16 |
| ResNet34-LM | 0.9 | 12 | 2 |
| ResNet34-LM | 1.0 | 7 | 1 |
| TitaNet small | 0.8 | 32 | 34 |
| TitaNet small | 1.0 | 11 | 17 |
| CAM++-LM | 0.5 to 0.8 | 20 to 52 | 12 to 35 |

| ERes2Net VoxCeleb | 1.0 | 13 | 14 |
| ERes2Net VoxCeleb | **1.1** | 9 | 8 |
| ERes2Net VoxCeleb | 1.2 | 4 | 3 |
| TitaNet small | 1.1 | 5 | 11 |
| TitaNet small | 1.2 | 1 | 4 |

The best of these, **ERes2Net at 1.1**, finds 8 or 9 "speakers", but most are fragments. Folding every speaker with
under 5 % of the speech time into the nearest big one in time leaves 4 and 4, with DER full 21.1 and 21.1
(confusion 4.8 and 7.0; forgiving 9.3 and 10.2): better overall than FluidAudio on these two meetings, though it gives
more speech to the wrong person.

**But that setting was picked on these same two meetings.** On two AMI meetings it had not seen, with the setting
fixed (ERes2Net, 1.1, fold under 5 %), it did not hold:

| Meeting (4 people) | Tool | Speakers found | DER full | Missed | Confusion | DER forgiving | Time |
|---|---|---|---|---|---|---|---|
| TS3003a (25 min) | sherpa-onnx | 13, folded to **2** | 20.3 | 10.5 | 6.0 | 14.0 | 92 s |
| TS3003a | FluidAudio Sortformer | **4** | 35.2 | 32.2 | **1.5** | 31.3 | 14 s |
| TS3003a | FluidAudio Nemotron 3 | **4** | 35.9 | 35.2 | **0.3** | 33.2 | 9 s |
| EN2002b (30 min) | sherpa-onnx | 16, folded to **5** | 31.0 | 11.0 | 16.3 | 15.9 | 97 s |
| EN2002b | FluidAudio Sortformer | **4** | 28.5 | 24.5 | **1.6** | 17.2 | 20 s |
| EN2002b | FluidAudio Nemotron 3 | **4** | 31.3 | 29.4 | **0.8** | 21.3 | 15 s |

On the Chinese clip it found anything from 1 to 8 speakers by threshold and model.

Speed: about 20 times the meeting's length on 4 processor threads (53 s for ES2004a), 360 to 750 MB.

### Voiceprints from the two tools

For each speaker FluidAudio found, a WeSpeaker ResNet34-LM voiceprint was made with sherpa-onnx from the same
stretches of speech, and the two compared (cosine; the same model on the same speech gives about 0.9 or more):

| Meeting | Same speaker | Different speakers |
|---|---|---|
| ES2004a | 0.45 to 0.63 | −0.09 to 0.23 |
| IS1009a | 0.06 to 0.22 | −0.07 to 0.12 |

The two are related but **not interchangeable**: FluidAudio's "WeSpeaker v2" is not the ONNX WeSpeaker model.
A voice saved by one could not be recognised by the other. On IS1009a, sherpa-onnx's own ResNet34-LM voiceprints of
different people were 0.71 to 0.83 alike, which is why it confused them.

### Recording the Mac's sound from Rust

A 70-line program after Meetily's capture (`cidre` at Meetily's pinned commit; a Core Audio process tap on all output,
in a private aggregate device) recorded the Mac's speech while `say` spoke: 48 kHz, one channel, peak 0.80. macOS
asked nothing: the permission was already given to the app that ran it. Two things to know:

- **It sends nothing while nothing plays.** A 3 s run in silence gave no samples at all, and the 7 s run gave 5.2 s.
  The recorder must count time by the clock and fill silence, or the microphone and the computer's sound drift apart.
- **The permission prompt** (`NSAudioCaptureUsageDescription`) was not seen; it must be checked from the signed app.

## Not done

- **Windows** (no PC here). sherpa-onnx's speed there is unknown; its quality is the same model.
- **The owner's own meetings**, an online call of four or more, and Bengali or another Indian language with hand
  marks.
- **Sortformer as ONNX.** Community exports of NVIDIA's Sortformer exist on Hugging Face (490 MB, or 141 MB in 8 bit,
  for example `cgus/diar_streaming_sortformer_4spk-v2.1-onnx`), none from NVIDIA. They need Sortformer's own sound
  features and streaming loop around them. Run in MT0b below.
- **A call recorded from both sides** through the tap and the microphone together.

## What it means for ADR-0108

1. **sherpa-onnx is not good enough to be the one tool.** It cannot count the people in a meeting. The best setting
   found on two meetings gave 2 and 5 people for 4 on two others, and the Chinese clip 2 for 4. It also gives up to
   16 % of the speech to the wrong person. It does mark more of the speech than FluidAudio.
2. **FluidAudio is clearly better on the Mac.** Sortformer and Nemotron 3 found the right number of people in all five
   recordings without being told, and gave at most 6 % of the speech to the wrong person (under 2 % in four of the
   five). Their weakness is speech they do not mark at all (11 to 35 %); in a transcript those words still appear
   and go to the nearest speaker. It runs at 60 to 160 times the meeting's speed. But it is Swift and CoreML: Mac
   only.
3. **The single tool most likely to work is Sortformer itself as ONNX**, run by ONNX Runtime on every platform. It is
   the model behind FluidAudio's results, so the Mac would lose little, and Windows and Linux would get the same
   behaviour. Its limit is 4 speakers per channel (the 8-speaker Nemotron 3 has no ONNX export found).
4. **Voiceprints need one model chosen on purpose** (ADR-0108 decision 11): FluidAudio's and sherpa-onnx's do not
   match. With an ONNX path everywhere, one ONNX voiceprint model (ERes2Net or TitaNet scored best here) is used on
   every platform, apart from the tool that finds the turns.
5. **Recording the Mac's sound from Rust works**, with the silence gap to handle.

## MT0b: Sortformer as ONNX on ONNX Runtime (2026-11-15, the owner: "Yes, run MT0b")

**What ran.** NVIDIA's Streaming Sortformer 4spk v2.1 as exported to ONNX for Vernacula
(`christopherthompson81/sortformer_parakeet_onnx`, `diar_streaming_sortformer_4spk-v2.1.onnx`, 492 MB, MD5 matching
its manifest; and the 8-bit file, 141 MB), on ONNX Runtime 1.32.0, **the processor only** (the CPU provider, no
neural chip, no GPU). The graph takes one chunk of 992 sound-feature frames plus the speaker cache and the FIFO; the
streaming loop around it, the speaker-cache compression, the median filter and the turn thresholds were written for
this spike in Python (`sortformer_run.py`, 200 lines) after Vernacula's port of NeMo's loop, read but not run. The
same code runs unchanged on Windows and Linux.

### Results, not told how many speakers

| Meeting (4 people) | Speakers found | DER full | Missed | False alarm | Confusion | DER forgiving | Time | Speed |
|---|---|---|---|---|---|---|---|---|
| ES2004a | **4** | 26.5 | 22.5 | 2.9 | **1.1** | 16.0 | 13.9 s | 76× |
| IS1009a | **4** | 22.9 | 13.4 | 6.0 | **3.6** | 15.8 | 11.3 s | 74× |
| TS3003a (kept back) | **4** | 30.3 | 27.4 | 2.5 | **0.4** | 23.8 | 20.9 s | 72× |
| EN2002b (kept back) | **4** | 29.4 | 25.1 | 3.0 | **1.3** | 13.2 | 25.3 s | 71× |
| Chinese clip | 3 of 4 | | | | | | 0.7 s | 84× |

Against FluidAudio's Sortformer on the same meetings (28.5, 25.9, 35.2, 28.5 DER full): **as good or better on every
AMI meeting**, with the same right count of people and at most 3.6 % of the speech given to the wrong person. It found
3 of the 4 Chinese speakers where FluidAudio found 4 (FluidAudio runs a "high context" Sortformer v2 setup; this is
v2.1 with NeMo's default streaming settings).

**The 8-bit file is worse** (DER full 34.8, 27.1, 30.5, 30.2; confusion up to 6.1 %) and not much faster: the full
file is the one to use.

**Memory.** The model takes about 0.6 GB. The spike's runner made the sound features for the whole meeting at once,
2.9 GB for 30 minutes; the app makes them a chunk at a time, so that part does not grow with the meeting. Turning
ONNX Runtime's memory pool off changed nothing.

### One voiceprint model for naming people

Each person was enrolled from meeting A's hand-marked solo turns (1.5 s or longer) and looked for in the next meeting
of the same four people (B), from B's solo turns of 2 s or longer. AMI's ES2004b and IS1009b have the same people as
ES2004a and IS1009a. Voiceprints made with sherpa-onnx's extractor (ONNX, any platform):

| Voiceprint model | ES2004b: people / turns right | Same person, nearest other (cosine) | IS1009b: people / turns right | Same, nearest other |
|---|---|---|---|---|
| WeSpeaker ResNet34-LM | 3/4, 76 % | 0.65, 0.37 | 2/4, 61 % | 0.80, 0.79 |
| WeSpeaker CAM++-LM | 2/4, 42 % | 0.79, 0.80 | 2/4, 44 % | 0.70, 0.79 |
| TitaNet small | 3/4, 80 % | 0.69, 0.39 | 3/4, 78 % | 0.66, 0.33 |
| **3D-Speaker ERes2Net (VoxCeleb)** | **3/4, 80 %** | **0.66, 0.19** | **3/4, 78 %** | **0.70, 0.29** |

ERes2Net keeps different people furthest apart. Even so, one person in four was named wrong in each meeting from a
room microphone: **names are suggested and a person confirms**, as ADR-0108 decision 12 says.

## What MT0b means for ADR-0108

1. **One tool on every platform: Sortformer 4spk v2.1 as ONNX, on ONNX Runtime.** It counted the people right in all
   four meetings, gave the wrong person at most 3.6 % of the speech, ran at 70 times the meeting's speed on the
   processor alone, and matched or beat FluidAudio. Decision 8 changes from sherpa-onnx to this.
2. **FluidAudio is not needed.** Decision 9 becomes: no second engine. The neural chip can come later through ONNX
   Runtime's CoreML provider (Vernacula publishes a static version of the same graph for it, measured 3.3 times
   faster on an M5), not through Swift.
3. **Voiceprints: 3D-Speaker ERes2Net (VoxCeleb) as ONNX**, made with sherpa-onnx's extractor or ONNX Runtime directly,
   the same file on every platform (decision 11).
4. **The limit is 4 speakers per channel.** "You" is one channel, so a call can name up to 4 others. For bigger rooms,
   NVIDIA's 8-speaker Nemotron 3 can be exported to ONNX with Vernacula's script; no published file was found, and
   it was not tested.
5. **The exported file is a community export**, not NVIDIA's. The app pins it by hash; exporting it ourselves from
   NVIDIA's `.nemo` with the published script is the fallback.

### Still not done

- Windows and Linux runs (the code has nothing Mac-only; speed there is unmeasured).
- The owner's own meetings, an online call recorded from both sides, Bengali or another Indian language with hand
  marks.
- Sortformer on the neural chip through the CoreML provider.
