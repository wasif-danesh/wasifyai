# wasifyai-training

Teach the app something of the person's own (ADR-0073). Stage T1 builds the platform and the simple screens, with the
image card first (ADR-0076): **Make my own character or style**, from nothing but uploaded pictures. The desktop is first
and the web follows (`docs/train-day1-plan.md`).

This package holds the datasets (pictures with their checks and written captions), the runs and the trained models (a small
SQLite file and the files beside it, under the app's data folder), the picture checks, the captions and magic words, the
routes of the screens and the actions of the catalogue. The trainer itself is an engine behind `state.training`: today a
**preview trainer** that does everything but learn (it says so on the screen); the real one (mflux, then Unsloth's component)
replaces it without touching this package's code. A trained model is a creation of its own kind, `lora`, found by its name
and magic word in My creations.
