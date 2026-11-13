# ADR-0047: A system-wide safeguards switch

- **Status:** Superseded by ADR-0094 (2026-10-29, by the owner): no safeguards switch, moderation or daily limits in v1
- **Date:** 2026-10-09

## Context

Every product has a safeguard that runs before work starts: the music, image, video and text-to-speech
products each have a mandatory classifier (`guardrail.py`, its prompts and a canary), the image product also
checks pictures, and ADR-0044 designs more for Lip Sync (a real-person photo refusal, audio checks, MP4 marking,
no voice cloning). The accepted ADRs call these safeguards mandatory and fail-closed.

The owner has decided that, for now, **no safeguards should apply**, and wants an **on/off switch in the Admin
section** that turns safeguards on or off across the whole system. This supersedes the "mandatory" wording of
the product ADRs for as long as the switch is off; it does not delete any safeguard.

## Decision

1. **One setting, `safeguards.enabled`**, stored in the database (a small `system_settings` table) and edited
   on a new **Admin > Safeguards** page. The change is written to the audit log (who, when, old and new value).
2. **Default: off on local and staging (the home lab); forced on in production (AWS, GCP, Azure).** The
   difference is configuration only (rule 1): the Helm `cloud/` overlays set `SAFEGUARDS_FORCE_ON=true`, which
   makes the stored setting ignored and the Admin switch read-only ("on, set by the deployment"). No code path
   checks the environment name.
3. **What the switch covers (when off):** the text and picture classifiers in all five products, the Lip Sync
   real-person-photo refusal and audio check, the Lip Sync "AI-generated" MP4 marking and **all per-user
   quotas** (daily and monthly limits in every `product.yaml`). When off, none of these apply; in production
   they always do. Usage events are still recorded, so billing and reports keep working.
4. **What it never covers (always on):** upload hardening (type sniffing, ffmpeg limits, size limits), the
   one-at-a-time rule (it protects the GPU, not content), authentication and admin checks, and storage rules. These protect the
   system, not the content.
5. **One seam.** The platform SDK gets `caps.safeguards_enabled()`; each product's guardrail step reads it and
   skips the classifier when it is off. Graphs and
   products do not read the table themselves.
6. **Visible state.** While off, the Admin page and the admin header show a clear "Safeguards are off" banner.
   The guardrail evals and canaries keep running against the classifiers directly, so turning the switch on
   later is safe.

## Consequences

- Anyone can generate content the classifiers would have refused, including realistic videos of real people
  speaking. The owner accepts that risk and the legal responsibility for it. Production always has it on; Terms of Use and takedown handling are needed first.
- Several accepted ADRs (0034-0044) say "mandatory"; this ADR overrides that while the switch is off. They are
  not edited; a later ADR can supersede them if the default changes.
- Cost: one table and migration, one admin route and page, one SDK method, and a small change in each guardrail
  step plus tests for both states.

## Owner's answers (2026-10-09)

1. Off by default on local and staging; forced on in production.
2. The AI-generated marking follows the same rule, and so do all quotas (the owner: quotas apply only in production).
3. One global switch (the owner has no preference; it is the simplest).

## Docs to update if accepted

`CLAUDE.md` (rules and "Ask before"), `docs/architecture.md`, `docs/configuration.md`, ADR-0044 (safety section
points here), product READMEs.
