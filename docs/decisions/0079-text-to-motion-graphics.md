# ADR-0079: Text to motion graphics: describe it, get an animated title, chart or overlay

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. **Names:** *Motion Graphics* (this feature) and
  *Video Builder* (ADR-0077's HTML-to-video product) are working names chosen by the owner on 2026-10-18 until better ones
  are found; "Compose" was dropped because it clashes with Compose Multiplatform and `docker compose`.
- **Date:** 2026-10-18
- **Depends on:** ADR-0077 (Video Builder: the render engine, sandbox and `video_builder.*` actions), ADR-0068 (action catalogue),
  ADR-0069 (our MCP server), ADR-0070 (trust levels for outside content), ADR-0071 (assistant, `how_to`), ADR-0072
  (agent), ADR-0078 (Qwen3.5-9B, a model that reads pictures), ADR-0066 (speech, music, word times), ADR-0041
  (searchable), ADR-0047 (safeguards), ADR-0061 (how outside material enters), ADR-0012 (licences).
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages MG0 to MG3.

## Context

The owner pointed at `iart-ai/motion-skills` and asked for text to motion graphics in the product. What was read
(2026-10-18, repository and three of its packs):

- **What it is.** Not a model and not a renderer. It is **craft knowledge for coding agents**: 55 "skills" in 18
  separate pack repositories (the `motion-skills` repository is only the index, a showcase and three verify
  scripts). A skill is a folder with `SKILL.md` (a few thousand words at most; about 4,260 words across the three
  read) and `references/` recipes: kinetic typography, animated charts and infographics, explainers (script to
  storyboard to scenes to captions), lower thirds, web animation, Manim, WebGL, b-roll for talking-head videos. Each
  skill ends in a **deliver-and-verify loop**: render a frame, screenshot it, check it (clipped glyphs, wrong line
  breaks, no motion-reduced fallback), and a short pre-flight list.
- **Licence.** MIT for the index and 16 packs; **`generative-illustration-skills` has no licence** and
  `awesome-motion-skills` is "other" (neither is usable). It is by iart.ai, whose hosted product is promoted in the
  READMEs (a competitor in spirit; nothing in the skills calls it).
- **What they run on.** Two tiers in the skills read: a **light tier of standalone HTML** with CSS or **GSAP**
  timelines and a "freeze at time t" harness (`?t=1.5`, `tl.pause(); tl.seek(t)`), screenshotted with Playwright;
  and a **deliverable tier on Remotion** (React) for MP4. The lower-thirds pack ships its own `render.mjs`
  (Playwright plus FFmpeg) that writes **WebM with alpha (VP9) and ProRes 4444** and checks that the alpha is really
  there. Nothing mentions HyperFrames.
- **Remotion's licence** (read from its `LICENSE.md`, 2026-10-18): free for individuals, for-profit organisations of
  up to 3 employees, and non-profits; **a paid company licence for larger for-profit organisations**. An app that
  ships Remotion would pass that obligation to every business user. ADR-0077 already declined Remotion.
- **The match with ADR-0077.** The light tier (HTML plus a seekable GSAP timeline, rendered frame by frame in headless
  Chrome) is the same idea as HyperFrames (HTML clips, GSAP timelines on `window.__timelines`, seek each frame,
  encode with FFmpeg). GSAP is cleared for the open-source, free desktop (ADR-0077, owner's answer).

The real question is not "can we install these skills" but **what makes a non-technical person's "make me a
kinetic title that says X" come out right**, with the app's own models, locally, safely.

## Decision

1. **Product: "Motion Graphics" inside Video Builder** (ADR-0077's screen, Labs switch, desktop only in v1). The person
   picks a starting point or just types. Starting points, each a **template with slots** (decision 3): *Animated
   title*, *Quote or kinetic text*, *Chart from my numbers* (a spreadsheet), *Lower third / name strap* (transparent),
   *Captions for a video*, *Logo reveal*, *Explainer from a script*. Output: MP4, **WebM with transparency**
   (stream and web overlays) or ProRes 4444 where the engine can write it, and GIF; plus the editable composition.
2. **The loop is plain words.** *Describe → preview (three stills and a short loop) → "change it" in words → render.*
   "Make the text bigger", "slower", "use my brand colours" revise the composition and re-preview. No code is shown
   unless the person opens the code view. The previous version is kept, so "undo" is always there.
3. **Template first, written code second.** Two paths, so a small local model is enough for the common cases:
   - **Template path (default):** the model only fills **slots** (text, numbers, colours, font, duration, language)
     in a vetted template of ours. No model-written code runs. This is safe by construction and fast.
   - **Custom path:** for requests no template fits, the assistant or agent writes the HTML/GSAP composition with a
     skill loaded, inside the ADR-0077 sandbox, with the untrusted-source rule (ADR-0070). Offered when a capable
     model is available (`agent-ready`, ADR-0072) and always behind the preview.
4. **The motion-skills material is imported as reviewed content, not as a dependency** (ADR-0061, level B: copy
   what we need, keep the notice):
   - Take only **MIT packs**, pinned to a **commit hash**, and only the skills the evaluation (decision 7) shows help:
     the starter set is kinetic typography, chart animation, explainer, lower thirds, and web/GSAP recipes.
   - **Read every line, then adapt:** keep the recipes and the verify list, rewrite the build and render steps for
     HyperFrames and our `video_builder.*` actions, **drop the Remotion steps**, drop `npx`, `curl` and package installs
     (a skill that tells a model to install things is an injection path), and keep the MIT notice and a source
     line with the commit. Skills are stored as our files (`products/wasifyai-video-builder/skills/`), versioned with
     the app, **never fetched or updated at run time, never `npx skills add`**.
   - **Exclude** `generative-illustration-skills` (no licence), `awesome-motion-skills` (a list, "other" licence),
     and anything that links to iart.ai.
5. **Skills are loaded one or two at a time, by a lookup.** The model does not see 50 skills. A **skill catalogue**
   (name, one-line "use when", tags) is searched with the person's request (the `how_to` meta-tool of ADR-0071, the
   same embeddings as help), and the chosen skill's text plus one reference file go into the prompt (about 3,000 to
   5,000 tokens). This is what keeps a 9B model on task (ADR-0071's finding that many tools break small models).
6. **The model checks its own work by looking.** `video_builder.preview_frame` (ADR-0077) returns stills at the start, the
   middle and the end; the multimodal model (ADR-0078) is asked the skill's verify questions about them (is any text
   clipped, is the text exactly the requested text, does it fit the safe area), and the composition is fixed once,
   at most twice. The result carries the verdict in plain words ("checked: nothing clipped").
7. **Numbers and words are exact by construction.** Text the person typed and numbers from their spreadsheet go
   into slots **verbatim**; a model never retypes them. After rendering, the on-screen text is read back from the
   composition (the DOM text at the last frame) and **compared with the input**: a mismatch is a failed check,
   not a silent change. This answers the thing generated video cannot do.
8. **Evaluation before shipping (stage MG0):** about 20 requests with rubrics (the exact text appears, nothing is
   clipped, it stays inside the safe area, it ends on time, the motion matches the brief, the file plays), each run
   **with and without the skill**, on three model tiers (local Qwen3.5-9B, a hosted model from Hugging Face or
   GitHub, and a strong reference). A skill that does not raise the score is not shipped. Results are kept next to
   the assistant's and the agent's.
9. **Safeguards and rights.** Prompts and slot text pass the text moderator when safeguards are on (ADR-0047). Fonts
   are open fonts we ship (licences checked); a logo or picture comes from the library with the person's statement
   that they may use it. No brand or real-person impersonation templates.
10. **Outputs are creations (ADR-0041).** Kinds `composition` and `video` as in ADR-0077; the index text is the slot
    text, the script and the captions; "Make it again" opens the composition. `motion.make` (effect
    `make`, not costly) and `motion.revise` join the catalogue (ADR-0068) so the assistant, the agent and MCP
    clients can use them: *"Make a lower third for Maya Chen, Head of Design"* works from chat.
11. **Transparent output.** Verified by spike V0 (2026-10-19): HyperFrames itself writes WebM VP9 with alpha and ProRes
    4444, and the alpha survives decoding (with libvpx). The lower-thirds pack's own capture route (Playwright plus
    FFmpeg, MIT) is kept only as a fallback.

## Consequences

- The app turns a sentence into a finished animated graphic that is **editable, exact and repeatable**, using the
  same engine as Video Builder, with no new model.
- We own and review a small body of skills; we do not track the upstream repository, so improvements there are
  taken by hand, on purpose.
- Quality for custom compositions depends on the model; the template path is what a small local model can do
  reliably. The evaluation says where the line is.
- The work is almost entirely content and evaluation, not infrastructure, but it cannot start before Video Builder's
  render engine and sandbox exist (V1, V2).

## Alternatives considered

- **Install the packs as agent skills (`npx skills add`).** Fetches unreviewed instructions onto the person's
  machine and into a model's prompt at run time. Rejected: a supply-chain and injection path.
- **Remotion as the render engine** (the skills' deliverable tier). Licence obligation for larger companies, and
  React-only authoring. Rejected (ADR-0077).
- **Use iart.ai's hosted service.** Sends the person's content to a competitor, a paid service, outside the
  desktop's local-first rule. Rejected.
- **Let the model write code for everything.** Slower, riskier, and wrong more often on a local model; kept only as
  the custom path.
- **Image or video generation models for titles and charts.** They draw letters and numbers wrongly; exact text is
  the point of this feature.

## Open questions

1. Whether Qwen3.5-9B writes valid HyperFrames HTML with a skill loaded, and how often it needs the fix loop (MG0).
2. Whether HyperFrames writes transparent video; if not, the lower-thirds route (decision 11).
3. Which of the 55 skills are worth adapting: the evaluation picks; web, WebGL and Manim ones are probably not v1.
4. Whether to contribute adaptations back to the upstream pack (the MIT notice allows it; not a v1 task).
5. Languages: right-to-left and Indic text in kinetic type needs font and shaping checks; English only is v1.

## Not in v1

The 3D and WebGL packs; Manim maths animation; a visual timeline editor; music-synced beat cuts (the music analysis
is not built); automatic b-roll from a talking-head recording; a template store or sharing; the web deployment.

## Amendment after spike V0 (2026-10-19; `docs/spikes/video-builder-v0.md`, technical half of MG0)

- **Verdict: MG1 Go for the template path.** MG2 (model-written compositions) is **not assessed**: no model was
  evaluated; that is the other half of MG0 and still has to be run (about 20 requests with and without a skill, three
  model tiers).
- **Two skills were adapted and rendered** (a lower third and a kinetic title, from the MIT packs, with the notice kept);
  every `npx`, CDN and Google Fonts reference was removed. Conditions for MG1: **ship open fonts with the templates**
  (system fonts differ per machine), and run the exact-text readback at the hold frame **with a pixel check** and a
  clipped-glyph look-check.
- **Exact-text readback (decision 7):** reading the text from the DOM catches retyped text but **cannot be the only
  check**: the DOM still holds the text on frames that are visually empty, and it misses clipped descenders.
- **Sandbox:** the ADR-0077 amendment applies; custom compositions (MG2) only run through the sandboxed render path.
