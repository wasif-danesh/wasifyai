# ADR-0022: The song graph and its guardrail

- **Status:** Accepted
- **Update (2026-10-18):** superseded in part by ADR-0067: the song graph and its guardrail was removed and replaced by the voice product (ADR-0066).
- **Date:** 2026-10-08

## Context

`wasifyai-music` turns an idea into lyrics, a track and cover art. Its product rules make the
guardrail mandatory (no artist-voice imitation, no reproduced lyrics, no disallowed content) and
require the quota to be checked before GPU work. ADR-0018 left open whether `gemma4:e4b` is good
enough for that guardrail or whether the moderator needs `gemma4:12b`.

## Decision

- **Graph.** `check_request` (input validation, quota, guardrail) then `write_lyrics`, the
  `approve_lyrics` interrupt, music job, cover job and `finalise`; a refusal ends the run with
  `done` and `outputs.status = "refused"` plus a fixed message (not an `error`: it is a normal
  outcome). Every job is two nodes (enqueue, then `await_job`).
- **Fail closed.** If the classifier cannot return a valid verdict after two tries, the run stops
  with a retryable `moderation_unavailable` error. It never defaults to "allowed". A verdict that
  contradicts itself is treated as a refusal.
- **Screening points.** The request; the lyrics that will actually be sung (once, after approval,
  whether generated or edited); and the cover prompt. A refused cover prompt is replaced by a
  neutral one so a finished song is not lost.
- **Quota.** Songs per user per day, counted from `song.created` usage events since 00:00 UTC.
  Checked first (before any model), and again just before the music job. Two simultaneous runs can
  still both pass the first check; the second check narrows that window but does not close it.
- **Lyrics.** One JSON-schema-constrained call. The `lyrics` field is streamed to the client as it
  is written. Output is normalised (`[Verse 1]` becomes `[verse]`) and validated (a verse, a
  chorus, at least 6 sung lines); up to 3 attempts, each told what was wrong. A repeated
  `started` event for the node tells the UI to clear what it had shown.
- **Approval.** Approve (with optional edits of title, lyrics, style) or regenerate, at most 5
  times. Invalid edits are asked again with the reason, never silently fixed.
- **Files.** Finished files are moved to `{song_id}/audio.*` and `{song_id}/cover.*` under the
  user's prefix; the worker's `jobs/` paths are temporary.
- **Moderator sampling.** `temperature: 0`, thinking left on.

## Evidence (gemma4:e4b, 70 labelled cases, 3 repeats each = 210 verdicts)

Cases: 26 legitimate requests (dark, political, sad, other languages, artists named only as a
topic), 10 artist-voice, 8 reproduced-lyrics, 12 disallowed content, 6 prompt-injection attempts,
and lyrics and cover-art screening. The set is in `products/wasifyai-music/evals/`.

| Moderator | Wrongly allowed | Wrongly refused | Answers that varied | Time per verdict |
|---|---|---|---|---|
| Default sampling (temperature 1), thinking | 3 of 78 refuse-cases | 0 | 3 cases | 1.6 s |
| Temperature 0, thinking | 3 of 117 (one case, every time) | 0 | 0 | 1.9 s |
| Temperature 0, no thinking | 6 of 117 | 0 | 0 | 0.3 s |
| **Temperature 0, thinking, election rule made concrete** | **0 of 123** | **0 of 87** | **0** | 2.0 s |

- Randomness caused the flip-flopping, so the moderator runs at temperature 0.
- Thinking is needed to recognise reproduced lyrics: without it, copied "Bohemian Rhapsody"
  lyrics were allowed 3 of 3 times. So the moderator keeps thinking (about 2 s per verdict).
- "Election deception" in the prompt was too vague (voter-deception requests were always allowed).
  Describing it concretely fixed it, including two differently worded cases not used to tune it.
- All 18 prompt-injection verdicts were correct (instructions inside the request were ignored).

Lyrics (8 ideas, JSON-schema output, thinking off): 8 of 8 valid JSON, 7 of 8 with the required
section tags before retries. That is why validation and retry exist.

## Consequences

- **`gemma4:e4b` is sufficient for the guardrail on this evidence**, so the moderator stays on it;
  `gemma4:12b` remains the fallback if a future evaluation shows regressions.
- **Limits of the evidence.** The cases were written by the author of the prompt, in English
  (plus one Spanish), and are few. This is not red-teaming. Before a public launch, evaluate with
  cases from outside the team, in more languages, and re-run it whenever the prompt or model changes
  (`products/wasifyai-music/evals/run_guardrail_eval.py`; exits non-zero on a false allow).
- Thinking costs about 2 s per screen, three screens per song, all before or between GPU jobs.
- The ACE-Step and FLUX.2 workflows are structure-validated against ComfyUI but not executed (the
  models are not installed); the map files say so.
- Listing a user's songs for the "My songs" page needs a read path that does not exist yet and a
  decision about its shape (a generic or per-product endpoint).
