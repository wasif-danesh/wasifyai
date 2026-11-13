# wasifyai-creative

Creative Studio (ADR-0090): one project that goes from a song to a finished video. Stage CS1 is the brief and the
**Plan**: a song becomes an editable list of shots, and nothing is made yet. Desktop first.

- `layout.py` works out where the cuts fall from the song's beats (a pure function).
- `writer.py` writes the plan in small steps. Code owns the times, cast, places, camera and motion; the model writes
  story beats and one sentence per shot (`docs/spikes/creative-cs0.md`). Each step is a checkpoint.
- `document.py` is the plan and its edits and checks; `store.py` keeps projects, revisions, checkpoints and the log.
- `runtime.py` runs one plan at a time for a person; `routes.py` and `actions.py` are the screen's and the agents' way in.

The beats come from `music.analyse` in the voice product; its tool is the `music-analysis` component.
