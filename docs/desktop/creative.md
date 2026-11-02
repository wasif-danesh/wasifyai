# Creative Studio on the desktop

ADR-0090. At stage CS3 a project goes from a song to a finished video: a plan, stills, a cut with captions and titles, and the video kept in Your videos. Clips for every shot come in CS4.

## How a plan is made

1. **The song is analysed** by the `music.analyse` action in the voice product. It uses the optional component `music-analysis` (Settings › Optional parts, or the card on the brief). The answer is kept with the song.
2. **The code lays out the cuts** on the beats and downbeats (`layout.py`), and owns the order of places, the camera and the motion.
3. **The chat model writes** the story, then one sentence per shot, a part at a time (`writer.py`). A sentence that fails the checks is asked for again, then falls back to the part's words with a mark on the shot.
4. **Each step is kept** as a checkpoint, so stopping or a crash loses at most one part. **Go on** continues from there. **Plan again** starts afresh, and Undo brings the earlier plan back.

## The screen

One project is one screen: the Make panel on the left, the plan as the stage, the media rail on the right.

- **Ask** is the chat, working on this project and the selected shot. Changes apply at once, and each card has its own Undo. The guide is `editor.py`. The model copies whatever id its examples show, so they are built from the selected shot.
- **Add** tags a Library item with the project and the selected shot. Nothing is copied, so a thing deleted from the Library goes from the rail too.
- **The other tabs** say which step brings them, and open the screen that makes it today.
- **Evaluate the guide** with `products/wasifyai-assistant/evals/run_tool_eval.py --only cs-`.

## Things to know

- **The chat model sets the time.** A 3-minute song takes 44 s on Qwen3-8B on an M5 Pro; a 90 second song took 529 s on a 27B model on Ollama. A schema reply turns thinking off (`desktop_language.py`).
- **An install records a digest of its pins**, so changing `packages_bytes` in the manifest asks for a new install.
- **After `kill -9` the engine's `llama-server` stays running**, so stop it by PID when testing a crash.
- **Search matches words here.** The desktop's index is `local-hash/v1` for every kind.

## Checking it

```bash
DESKTOP_DATA_DIR=<throwaway> apps/desktop/scripts/ui-audit.sh light creative
```

The throwaway folder links `models`, `components`, `engine` and `comfyui-data` from the app's data and holds a `sqlite3 .backup` of `wasifyai.db`, plus `secrets.key`. It needs a song in Your music and a chat model chosen. The walk's `unregisterListener` page error comes from the stand-in window.

## The Shots step (CS2)

Choose **Make the stills**. The panel says how many, how long and how much disk, and refuses what will not fit. Reference pictures are the default (about 40 s a still here); Plain is about twice as fast.
Each still is a picture in your Library, saved as it is made, so **Stop** or a crash loses only the one under way and **Go on** makes only what is missing. Measured: 55 shots in 37 minutes, preview in 9 seconds. `creative.db` keeps takes, the chosen take, the run, the preview and people; the preview file is under the product's storage at `previews/<project>/`.

## The Cut step (CS3)

Choose **Cut**. The cut starts as the plan's shots for their planned lengths, with the song's words where they are sung (typed words only: a song with none has no
captions from the singing). Change it on the timeline under the video: choose a piece or a caption, then use its buttons, or the keys (space plays, S splits, the arrows
move by a beat, Z undoes, Shift+Z redoes). Voice turns the song's words on or off and puts them back; Titles adds a title or a lower third where the video is playing.

**Make a version to watch** makes the video only; **Make the video** makes it if the cut changed and keeps it in Your videos, a new video every time; **Save a copy** writes
the last one kept as an MP4. Measured: a 90 s song of 25 stills rendered in 19 s at 1920x1080. `creative.db` keeps the cut's revisions (`cuts`, `cut_revisions`, the last
30), its latest video (`renders`, under the product's storage at `cuts/<project>/`) and what was kept (`exports`). Captions are burned in by the bundled ffmpeg (libass).
