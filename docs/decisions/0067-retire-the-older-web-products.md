# ADR-0067: Retire the older web products and delete what they made

- **Status:** Accepted (2026-10-18, by the owner)
- **Date:** 2026-10-18
- **Depends on:** ADR-0066 (the voice product), ADR-0047 (safeguards), ADR-0041 (search)
- **Supersedes in part:** ADR-0012 (the ACE-Step model stays; the product that ran it on ComfyUI goes),
  ADR-0022 and ADR-0034 (the song graph and song downloads), ADR-0038 (prompt enhancement for music; images
  and video keep theirs), ADR-0042 (text to speech), ADR-0043 (speech to text), ADR-0044 (lip sync)

## Context

The voice product (ADR-0066) makes speech, transcripts, music, audio tools, dubbing, audiobooks and lip sync on
the desktop, and on the web either through hosted models or through the models on the machine that runs the
service. It replaced four web-only products: `wasifyai-music`, `wasifyai-tts`, `wasifyai-stt` and
`wasifyai-lipsync`. The owner asked first to keep their results readable, then (the same day) to delete the
packages and their results: there is no production data and none is wanted.

## Decision

1. **The four packages are deleted** (code, tests, prompts, evals, READMEs), with the web pages, components,
   hooks, flows and proxy routes that served only them, the admin Songs list, and their entries in the smoke tests,
   the Containerfile and the workspace.
2. **The voice product takes on what they enforced** before they go: the text moderator on everything spoken or
   sung, the picture moderator on lip sync pictures, daily limits (speeches, music, lip syncs, audio tools,
   dubs, audiobook characters), the same canaries (`text.moderate`, `text.moderate_image`), all only while the
   safeguards are on (ADR-0047). The prompts, refusal sentences and canary cases were copied, not shared.
3. **Their data is deleted**, not migrated: migration 0019 drops the tables `songs`, `speeches`, `transcripts` and
   `lipsyncs` and the search index rows that pointed at them (its downgrade brings back empty tables), and
   `scripts/purge_older_products.py` deletes their files in object storage (a dry run unless `--yes`). Usage
   events stay (they are the billing record).
4. **The old addresses move**: `/music`, `/text-to-speech`, `/speech-to-text` and `/lip-sync` redirect to the voice
   screens (middleware); the Explore cards point there and show only where the voice product is on.
5. **What served them is deleted too** (same day, same owner): `services/speech-indic`, `services/stt-indic`,
   `services/lipsync-musetalk`, the compose `speech`, `speech-indic` and `stt-indic` services, their Helm templates and
   values, `scripts/lipsync-server.sh` and `scripts/speech-models.sh`, the speech evaluation scripts, the media worker's
   speech, transcription and lip sync runners (and its `SPEECH_*` and `LIPSYNC_*` settings), and in the platform SDK
   the `speech` and `lipsync` providers and the `music` and `speech` capability families (`caps.music`, `caps.speech`).
   The voice product's own lip sync server (`wasifyai_api.lipsync_server`, run by the engine) is the only copy now.

## Consequences

- The ComfyUI music path of the first product is gone from the web. Music on the web is the voice product's:
  hosted models if the gateway has them, or the models of the machine it runs on. A cloud GPU deployment that
  wants ACE-Step must run the voice product's local engine on that host.
- Nothing about the older products can be recovered from a deployed database once 0019 has run, except from a
  backup. In git they are in the history before this change.
- `docs/decisions/` keeps the older ADRs as history; their status lines point here.
