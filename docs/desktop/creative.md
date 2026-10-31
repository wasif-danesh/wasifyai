# Creative Studio on the desktop

ADR-0090. At stage CS1 a project ends at a plan of words. Stills, clips and the cut come in later stages.

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
