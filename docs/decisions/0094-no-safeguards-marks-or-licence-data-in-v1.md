# ADR-0094: No safeguards, marks, consent gates, terms or licence data in v1

- **Status:** Accepted (2026-10-29, by the owner)
- **Date:** 2026-10-29
- **Supersedes:** ADR-0047 (the safeguards switch) whole; in part ADR-0022 (the guardrail), ADR-0025 (the canary
  checks before an alias changes), ADR-0036 and ADR-0037 (the image and video guardrails), ADR-0038 (the Enhance
  guard), ADR-0044 (the lip sync safety policy and its mark), ADR-0066 (the mark, the consent records and decision 4's
  licence rule), ADR-0073 decision 7 (whose face it is), ADR-0076 and ADR-0080 (the picture checks and the 3D
  statement), ADR-0079 (the words check of Motion graphics), ADR-0065 (the notebook quotas).
- **Related:** ADR-0088 (one job per person: a queue rule, kept), ADR-0069 and ADR-0092 (connection approval and
  secrets: security, kept), ADR-0083 (the web search opt-in: privacy, kept).

## Context

The desktop app is an open-source product, and the web app will run on the person's own provider keys (ADR-0095).
The owner decided on 2026-10-29 that v1 has no censorship and no restrictions on what a person makes, no
"AI-generated" mark of any kind, no terms of service, and no licence data in the code or the screens. The licence
text had already been taken out of the ADRs (commit `d8b452f`).

## Decision

1. **No content checks.** The text and picture moderators, every product's `guardrail.py`, their prompts, canaries
   and evaluation sets, and the model checks that ran before an admin could change an alias (`add_check`,
   `model_checks.py`, the `protected` aliases, `moderator` and `moderator-nothink`) are removed. Nothing a person
   types or adds is judged or refused for what it shows or says.
2. **No safeguards switch and no daily limits.** `Safeguards`, `SAFEGUARDS_FORCE_ON`, Helm `safeguards.forceOn`,
   Admin > Safeguards, `quotas:` in `product.yaml` and every per-person daily limit (images, videos, speeches,
   songs, lip syncs, tools, dubs, audiobook characters, 3D pictures and models, training pictures and runs, Motion
   graphics renders) and the notebook size limits are removed. Usage is still recorded (`RouteUsage`, `metered`)
   for the usage pages.
3. **No marks.** Lip sync draws no "AI-generated" label on the frames and writes no metadata note; the descriptor
   field `mark: required` and `MARK_TEXT` are gone.
4. **No consent gates.** Cloning a voice, copying a speaker in a dub, lip sync, the 3D "I may use this picture"
   tick and the four Train flows' "whose is it" step ask nothing and record nothing. The `consent` and `rights`
   columns of existing databases stay, unused, so no migration is needed (the voice store no longer returns
   `consent`; a training set's `rights` is always empty).
5. **No terms.** Backlog item B4 (terms of service) is dropped. The consent text in the app is gone with the gates.
6. **No licence data.** The `licence`, `commercial_use`, `licence_evidence` and `reviewed` fields are removed from
   the model catalogues, the component manifests, the shelves, the descriptors, the API and the client types; the
   Models page has no licence column; the voice model picker, the setup cards, Model hub and found models show no
   licence. A model's tier no longer depends on a licence.

**Kept, because they are security, privacy or the machine's limits, not censorship:** approval of MCP connections and
their own daily cap (set by the person), "Ask me before" for actions, the model-download approval (`needs_consent`
on `models.download`: the person sees the files and their size), the web search opt-in, upload size limits, the
Enhance flood limiter, one job at a time per person (ADR-0088), and one clip at a time on the GPU. The licence and
notice files that pixal3d.cpp's MIT licence and Meta's DINOv3 licence require to travel with their files are still
written beside them on disk, and "Built with DINOv3" is still shown: they are conditions of redistributing those
files, not licence data about models.

## Consequences

- What a person makes is their responsibility; the app does not check it, label it or limit it.
- A model provider on the web may still refuse a request under its own terms; the app passes on its words.
- Re-adding any check, mark, gate or licence badge needs a new ADR.
