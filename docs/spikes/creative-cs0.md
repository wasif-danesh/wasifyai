# CS0: can Creative Studio make a fast, honest draft on this Mac? (run 2026-10-31)

Question from ADR-0090: before 24 days are spent, do the beat tools, the plan writer, the stills, the clips, sung lip sync and the cut
hold up? Run on this Mac (M5 Pro, 64 GB) through a real desktop engine on a throwaway data folder, with the real models. No product code
changed. Pictures: `docs/spikes/creative-cs0/`. Videos: `docs/listening/samples/creative-cs0-*.mp4`. Scripts and plans (not in the repo):
`~/Projects/wasifyai-spikes/cs0/`.

## Result: go (owner, 2026-10-31, after watching: "It works as a fast, honest draft")

My recommendation was go, with the changes below; they are now in ADR-0090. The parts all ran, and the times are close to the ADR's, except that stills with reference pictures take twice as long. The plan writer
only became good once the code took more of the plan away from it. I looked only at still frames and numbers; the judgement of the cuts and the singing in motion is
the owner's.

What the owner was given to watch:

| File in `docs/listening/samples/` | What it shows | Look for |
|---|---|---|
| `creative-cs0-preview-12-shots.mp4` (45 s) | The fast draft: 12 stills with camera moves, cut on the beats, over the song, no captions | Do the cuts land on the music? Does it read as one story? |
| `creative-cs0-cut-60s.mp4` (61 s) | The fuller cut: 6 real clips and 11 stills, song and captions | Do clips and stills sit together? Is it worth about 30 minutes of making? |
| `creative-cs0-sing-vocal.mp4` (20 s) | MuseTalk on a sung vocal | Is a still portrait with a moving mouth acceptable as "Sing"? |

Both excerpts use the English song, which is the one where the beat tool was least steady, so they are the harder test.

## Measured

| Step | Result | ADR assumed |
|---|---|---|
| Make a 90 s song (ACE-Step turbo) | 44 to 70 s | |
| Vocal separation | 39 s per song | |
| Beats and downbeats, 90 s song (beat_this final0, 77 MB) | 0.9 s on CPU, 0.23 s on MPS once warm, 26 s for the first load with the download | |
| Sections (librosa, beat-synced) | under 3 s; boundaries and an energy label, **no verse or chorus names** | names assumed |
| Timed words (Parakeet v3) | 0.5 to 1.9 s. English works, with mishearings. **Bengali comes out as gibberish** | "any language the speech model knows" |
| Plan, final form, 24 shots on 9B | 25 s; 17 to 50 s across five briefs | |
| Still, plain (klein 4B, 1344x768) | 14 to 20 s, mean 17 s | about 13 s |
| Still, two reference pictures | 34 to 39 s, mean 37 s (a later batch of 5: mean 42 s) | |
| Preview join, 12 shots | 2.6 s, 4.1 MB | |
| Clip, 5 s, final (121 frames, 30 steps, about 0.25 MP) | 142 to 192 s, about 3 min | 252 s |
| Clip, 5 s, draft (121 frames, 15 steps, 0.125 MP) | 48 to 50 s | |
| MuseTalk, 20 s sung | 144 s on the vocal stem, 134 s on the full mix | |
| Captions, 60 s transparent WebM (Motion graphics) | 78 s, 2.3 GB peak | |
| Join, 60 s cut, 17 shots | 7 s, 6.9 MB | |

Worked out from those for a 3-minute song, about 48 shots:

| To make | Time | ADR assumed |
|---|---|---|
| Plan | about 1 min | |
| Preview, plain stills | **about 15 min** | 10 to 15 min |
| Preview, reference stills | **about 30 min** | 10 to 15 min |
| Draft motion on every shot | about 40 min, on top of the stills | |
| Final motion on every shot | **about 2.4 h**, on top of the stills | 1.5 to 2.5 h |

The 60 s cut as made is about 30 minutes: 17 reference stills (10 min), 6 final clips (17 min), captions and join. The plan writer's process
stays near 7 GB; LTX's peak was not measured again here (ADR-0037 says about 13 GB).

## (a) Beat and section tools

**Pick: beat_this with librosa for sections.** allin1 is dropped: its import fails against current natten, and the older natten needs
CMake, which this Mac does not have and which was not approved.

| Song | BPM | Beat spacing variation (lower is steadier) | Bars of 4 beats | Agreement with librosa |
|---|---|---|---|---|
| Instrumental | 125.0 | 0.015 to 0.019 | almost all | 1.0 |
| Bengali | 88.2 | 0.015 to 0.019 | almost all | 1.0 |
| English, final0 | 103.4 | 0.216 | 25 of 42 | 0.74 |
| English, small0 (8 MB) | 103.4 | 0.148 | 33 of 39 | 0.74 |

- There is no ground truth and nobody listened, so the English result may be the song or the tool. The smaller checkpoint was steadier on
  that song and is one tenth the size, so CS1 should try small0 first.
- The tool needs PyTorch: about 900 MB for the environment. That needs the owner's yes under "Ask before".

## (b) The plan

**The first schema failed; the second worked.**

| Run | Model fills | Time, song-en | Rows repaired | Rows that fell back | What it read like |
|---|---|---|---|---|---|
| v1, no schema | every field | 205 s | | **24 of 24** | Nothing usable. **Engine schema support is required** |
| v1, schema | every field | 73 s | 10 | 0 | Valid JSON, but repetitive, stuck in one place, ahead of the story, 22 of 24 Animate, Sing never used |
| **v2, schema** | **beats, then one sentence per shot** | 25 s | 0 | 0 | In story order, every place used, follows a written script |

Every schema run gave valid JSON, covered the timeline and stayed in the cast. The v1 runs were refused 77 times for word-for-word
repeats and 7 times for Sing without a line or person.

**The schema that worked.** The model answers two questions, with fixed array lengths taken from the code:

```json
{"beats": [{"what": "25 to 140 characters", "who": "a cast name"}]}
{"shots": ["one sentence of 25 to 150 characters, one per shot"]}
```

The code owns the times, the cast, the order of places, the camera (a repeating cycle of six framings, each with its own instruction) and
the motion level (about 1 shot in 6 Animate). The guide asks for who, doing what, with which object, in which place, and for no style or
camera words.

| v2 (repaired, fell back) | song-en, 24 | song-inst, 24 | song-bn, 32 | story-short, 12 | story-long, 12 |
|---|---|---|---|---|---|
| Qwen3.5-9B | 0, 0 (25 s) | 1, 1 (31 s) | 0, 3 (51 s) | 0, 2 (17 s) | 1, 0 (18 s) |
| Qwen3-8B | 0, 0 (26 s) | 0, 0 (22 s) | 2, 0 (42 s) | 0, 0 (13 s) | 0, 0 (16 s) |

**8B did at least as well as 9B and used no fallback rows**, on one run each. The ADR names 9B; CS1 should run both again and choose,
since 8B may already be on a person's Mac and 9B is a 5.68 GB download. 9B can read pictures; these runs did not use that.

**My read of the v2 shots**, standing in for "a person's read": a person can start from these, and they will edit them. Flaws that remain:

- Details drift: a grey car becomes a red car.
- Some lines cannot be shot: "while thinking about...", "The camera shows".
- A person who appears only in a photo (Sam) gets confused with someone present.
- Misheard lyrics leak into shots. **Typed lyrics should be the text, with speech used only for timing.**
- Sing was not tried in v2, because the code did not assign it. CS1 has to give it a rule.

## (c) Stills and the preview

See `sheet-a.jpg` (plain), `sheet-b.jpg` (reference) and `sheet-mira.jpg` (the two reference portraits).

- **Plain is more consistent than I expected.** Hair and jacket hold; the face varies.
- **Reference is steadier** in face and jacket colour, at about twice the time. It is good enough for a draft, not for a person who must be
  recognised every time. So: reference by default, plain when a person wants speed.
- **Objects and places do not carry over.** The car changes between modern and vintage from shot to shot. CS1 needs a line of fixed words
  per object and place, the same as for a person.
- **"who: sam" drew Sam as a real man in the car**, because Sam was meant to appear only in photos. The cast needs a "seen only in photos"
  state, or to be left out of the picture prompt.
- One reference still shows two copies of the woman, and the "crying" still is awkward. Re-making one shot has to stay easy.
- An overhead framing can put a person in an odd place: one shot in the cut stands the woman above a busy road.

## (d) Clips

See `sheet-clips.jpg`. The character stays recognisable from the still, motion is gentle, background cars move plausibly, some detail
softens. Draft is softer but usable. **The product has no draft setting today**, so draft clips were sent straight to ComfyUI; CS4 has to add
it.

## (e) MuseTalk on singing

See `sheet-sing.jpg`. It finishes and the face stays clean, but it is **a still portrait whose mouth moves: the head, hand and body do not**.

| Measure, 20 s | Vocal stem | Full mix |
|---|---|---|
| Time | 144 s | 134 s |
| Mouth opening against vocal loudness, same moment (r) | 0.57 | 0.54 |
| Mouth opening, vocal rests / singing (share of dark pixels in the mouth box) | 0.079 / 0.099 | 0.078 / 0.099 |

For comparison, r at far-off time shifts averages -0.04 and peaks at 0.26, so the mouth does follow the voice, and the best match is at no
delay. The mouth barely rests in the gaps. Stem and mix are almost the same, so **separation may not be needed for lip sync**. These are
crude pixel measures and say nothing about whether the words look right.

The output's sound is 16 kHz mono, so the cut must lay the real song over it and take only the picture.

## (f) The 60 s cut

See `sheet-cut.jpg`. 17 shots, 61.2 s, 1280x720 at 24 fps, ffmpeg 4.4 bundled, overlaying a transparent WebM from Motion graphics.

- **Captions are not timed to the singing.** The `captions` template gives every line the same 2, 3 or 4 seconds, so the excerpt's words run
  ahead of or behind the voice, and I repeated five lyric lines to fill the 60 s. CS3 needs a timed caption track. MX6's `cues` are on opaque
  scenes, so they do not do this yet.
- The first render's captions stopped at 30 s, because I gave the template a length field it ignores. That is corrected in the kept
  file and was not a limit of the tool.

## What changed in ADR-0090 because of this

1. **Decision 4:** the plan schema is the two-question form above, and the code also owns the order of places, the camera and the motion.
2. **Decision 4:** schema support is required, not to be verified. The 9B or 8B choice is made in CS1.
3. **Decision 5:** beat_this and librosa are the analysis, subject to the owner's yes on the dependency. Sections have boundaries and energy,
   no names.
4. **Lyrics:** typed lyrics are the text. Timed words are English in practice; Bengali has none today.
5. **Time panel:** the preview is about 15 min plain and about 30 min with reference pictures, for a 3-minute song.
6. **Fixed words** for objects and places, and a "seen only in photos" cast state.
7. **CS4** adds a draft setting to Animate. **CS3** adds a timed caption track.

## Not checked

- Whether the beats are right, by a measure: the owner's watch is the only check.
- Whether 8B beats 9B beyond one run each.
- A real 3-minute song from start to end: its times above are worked out from shorter runs.
- The picture-reading ability of 9B, Sing in the plan, and a saved character LoRA.
- The web. The ADR is desktop first.

## Disk

Ceiling 15 GB, internal disk. Peak about **7.5 GB**: 6.5 GB at the end (Qwen3.5-9B 5.3 GB, tools 903 MB, outputs and engine data about
300 MB) plus about 1 GB for the allin1 attempt, deleted when it failed.

Deleted afterwards: Qwen3.5-9B, the tools, the allin1 environment, both beat_this checkpoints (85 MB), the throwaway engine folder, and about 80
files the spike left in the shared ComfyUI input, output and temp folders. The spike's HyperFrames render history (18 small files) stays in
the shared video-builder component. uv's shared package cache (9.4 GB in all) was not cleared, so this spike's packages may still be in it. Kept: scripts and outputs (178 MB, outside the repo), the three videos (12 MB, git-ignored), and six
pictures here (under 1 MB).
