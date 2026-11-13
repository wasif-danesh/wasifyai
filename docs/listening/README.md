# Listening check

What a machine cannot judge: whether speech sounds natural, whether a song sings its words in order, whether a
copied voice is recognisably the same person, whether a dub sounds like someone speaking. This folder is the set of
samples and the checklist for doing it by ear, on this computer, in about 45 minutes.

## How to do it

1. Serve the folder and open the page in Safari or Chrome (headphones help). A preview inside an editor or
   the Claude app cannot read the sound files next to the page and shows every player at 0:00:

   ```bash
   python3 -m http.server 8765 --bind 127.0.0.1 -d docs/listening
   ```

   then open <http://127.0.0.1:8765>. (`open docs/listening/index.html` also works in a real browser.) Each
   sample shows its length under the player before you press play.

2. Play each sample, rate it (**Good**: you would use it; **Acceptable**: usable with a caveat; **Poor**: you would
   not; **Broken**: wrong or unusable) and write a note when something stands out. Ratings stay in the browser.
3. Press **Copy results** and paste the list into the chat. The notes decide what is fixed first.

The page and the 34 samples were made on 2026-10-17 by the app's own engine from the models on this computer
(`docs/listening/samples/`, 77 MB, git-ignored; `manifest.json` lists what each one is). Every sample can be made
again with `scripts/listening_samples.py` (seeds are fixed) and the page rebuilt with `scripts/listening_page.py`.

## What the machine already checked

| Check | Result |
|---|---|
| Every file has the length asked for and is not silent (the video was read with ffprobe: H.264 and AAC, 5.2 s) | all 34 |
| Speech to text on the fox sentence and on the first chapter of the audiobook | word for word |
| Dubbing and speech editing read back with the speech-to-text model | the translated first lines and each edit matched (the dub's last words were not picked up: listen to it) |
| Clipping (samples at full scale) | under 0.03% of samples in five files (`music-ace-spanish`, `music-ace-cover`, `music-ace-comfyui-spanish`, `sfx-rain`, `tools-convert-meanvc2`): listen for crackle in them |
| The stems of a song add back up to the song | within 3% (HTDemucs 4), exactly (Mel-Band RoFormer) |
| The lip sync mark | the label is on the frame and in the file's metadata (looked at once) |

## The checklist, by feature

Rate against these. The sample names are the file names in `samples/`.

### Speech (`speech-*`)

| Look for | Samples |
|---|---|
| Natural pace, stress and breathing; no metallic buzz, clipped words or echo | all Kokoro, VoxCPM2 |
| Numbers, a date, a currency, a time, "Dr." and a name said correctly; questions rise | `speech-kokoro-hard` |
| Slower and faster still sound like a person, not a stretched recording | `speech-kokoro-speed-0.8`, `-1.25` |
| 48 kHz sounds fuller than 24 kHz, with no gasps or skipped words | `speech-voxcpm2` |
| A voice made from the words "warm, slow, gravelly older man" sounds like that, and keeps the same voice to the end | `speech-design-storyteller` |
| A copied voice is recognisably the speaker of the reference (the reference here is a synthetic voice; **make one from your own 10 seconds in Voices for the real test**) | `speech-clone-result` vs `speech-clone-reference` |

Known risks: VoxCPM2 ignores a spoken description (voices are made with Qwen3-TTS); copied voices carry an accent
into another language.

### Speech to text (`transcribe-fox`)

Count wrong words in the text shown under the player. Also try a recording of your own with names and numbers, and
one with background noise, in Speech to text.

### Music and effects (`music-*`, `sfx-*`)

| Look for | Samples |
|---|---|
| Lyrics sung **in the order written**, words understandable; style matches (pop, female voice, guitar) | `music-ace-song` |
| Pleasant to the end; no stray vocal sounds; steady tempo | `music-ace-instrumental`, `music-stable-ambient` |
| Spanish sung clearly. The audio.cpp build cannot be told the language; the image-engine build can: **which is better?** | `music-ace-spanish` vs `music-ace-comfyui-spanish` |
| Repaint changes only seconds 10 to 15 and joins smoothly at both ends; cover keeps the melody in a new style | `music-ace-repaint`, `music-ace-cover` against `music-ace-song` |
| Restyle is recognisably the same piece | `music-stable-restyle` |
| Sound effects sound like the words, start and end cleanly, no clicks | `sfx-rain`, `sfx-door` |

Known risks: lyric order and word clarity (the known weak spot of every song model); Stable Audio is instrumental
only; the Stable Audio licence is conditional.

### Audio tools (`tools-*`)

| Look for | Samples |
|---|---|
| Vocals stem: only the singing, little drum or guitar left, the voice not thin or watery | `tools-sep-*-vocals` |
| Drums, bass, other: what the name says, without the voice. Which separator is better, HTDemucs or Mel-Band RoFormer? | `tools-sep-*` |
| Instrumental: any singing left over? | `tools-sep-mel-band-roformer-instrumental` |
| Change a voice: same words and timing, now lower and male; no robotic or underwater sound. Which model is better? | `tools-convert-tone-color-vc`, `tools-convert-meanvc2` |
| Edit speech: only the changed words differ; the rest sounds untouched; no click at the edit | `tools-edit-replace`, `-delete`, `-insert` against `tools-edit-source` |

### Lip sync (`lipsync-sample.mp4`)

The mouth moves with the words (not early or late); the rest of the face is stable; the "AI-generated" mark is in the
bottom-left corner of every frame. The head stays still by design. Try your own drawing or a photo you may use.

### Dubbing (`dub-es`, `dub-de`)

| Look for | |
|---|---|
| Translation correct and natural (only if you speak the language) | the script is under each sample |
| Still sounds like the English speaker (with an accent is expected) | compare with `dub-source-english` |
| Each line fits its time; no line cut off at the end; no overlap | |
| Pace not hurried (one of three lines was sped up to fit in each; the largest overrun is 0.17 s) | |

### Audiobook (`audiobook-lighthouse`)

Pauses between sentences, paragraphs and chapters feel natural; the chapter titles are read; no change of voice or
volume between pieces.

## What your answers decide

| If this is poor | What changes |
|---|---|
| Lyrics out of order or unclear | change the guidance the lyrics writer gives (shorter lines, fewer lines); try a second song model |
| ACE Spanish better on the image engine | make the image-engine model the suggested one for non-English songs |
| Tone Color VC or MeanVC2 | which one stays recommended for Change a voice |
| HTDemucs vs Mel-Band RoFormer | which separator is the default for Split into parts and for dubbing |
| Dub endings cut or lines hurried | lower the speed-up limit (1.3) and warn earlier about long translations |
| Clipping audible | add a limiter to what the music and effect models return (dubbing's mix already has one) |
| Lip sync timing off | look at the padding MuseTalk puts around the audio features in the lip sync engine |

## Not covered here

Real recordings of people other than you (copying a voice needs the speaker's permission); long reads over an hour
(pace and fatigue); languages other than English, Spanish and German; noisy or music-heavy sources for dubbing and
speech to text. Add your own files in the app for those.
