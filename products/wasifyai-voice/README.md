# wasifyai-voice

Speak and transcribe on this computer, with the model the person picks (ADR-0066). The engine owns the speech
runtime (audio.cpp) and the model descriptors; this product keeps what was made (`voice.db`) and offers the routes.
Read `docs/phase2-voice-plan.md` and the "Speech" section of `docs/desktop-profile.md`.

Add a model: an entry in `models.yaml` (files pinned by commit, size and SHA-256, and a `voice:` descriptor with a
licence reviewed from the model card). If the runtime already runs its family, no code is needed. Run
`uv run pytest products/wasifyai-voice services/api/tests/test_audio_runtime.py`.
