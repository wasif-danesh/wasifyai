# ADR-0081: A design system with `design/DESIGN.md` as the single source of the look

- **Status:** Accepted (2026-10-19, by the owner). The axe-core dependency (decision 9) is not yet approved and is asked
  for in DS3. **Priority: top, as soon as the Phase 5
  spikes (G0, T0, V0, TD0) are done**, and before the Phase 5 screens are built.
- **Date:** 2026-10-19
- **Depends on:** ADR-0045 (shadcn/ui, Radix, Tailwind, tokens as CSS variables), ADR-0046 (side panel), ADR-0056 and
  `docs/desktop-profile.md` (one shared `packages/ui` for web and desktop), ADR-0073 (plain words, "For experts"),
  ADR-0012 (licences).
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages DS0 to DS4.

## Context

The web app and the desktop window already share one stylesheet (`packages/ui/src/tailwind.css`): design tokens as
OKLCH CSS variables with automatic light and dark (`light-dark()`), turned into Tailwind colours, fluid type steps and
animations by an `@theme` block, plus about 30 shadcn/ui components and a few of our own in `packages/ui`. There is
**no written design document**: the rules live in the code, in ADR-0045 and in a short `apps/web/README.md` section.
The look is violet (`--accent` about hue 286 in light, 285 in dark; `--hue: 270`) with warm-tinted neutrals.

The owner wants:

1. **One file as the only source of truth for the look.** Replacing `DESIGN.md` with another template re-skins desktop
   and web.
2. **A proper design system** following standard product-design practice.
3. **A blue or blueish accent instead of the default violet.**
4. No Figma. The file is the design source.

What a file can and cannot change, stated plainly: it can change everything that is a *value* (colour, type, shape,
spacing, depth, motion, density). It cannot change *structure* (layout, the shape of components, the screen flow,
icon set, illustration, copy beyond written rules). A structural redesign remains a code change.

## Decision

1. **`design/DESIGN.md` is the source of truth; nothing else defines a colour, size, radius, shadow, duration or
   font.** It holds two parts in one file:
   - **Prose for people and for coding agents:** principles, voice and tone, when to use which component, state
     patterns (empty, loading, error, success), motion principles, accessibility and language rules.
   - **One machine-readable block**: a fenced code block tagged `tokens`, written as **JSON** in the **W3C Design
     Tokens format** (`$type`, `$value`, `{aliases}`), so the generator needs no YAML parser or other dependency.
   A *template* is another such file (`design/themes/<name>.md`). The file named by `design/active` (or the
   `DESIGN_THEME` setting at build time) is the one the build uses.
2. **Three tiers of tokens**, so a re-skin touches the first and second only:
   - **Primitives:** raw values (`color.blue.600`, `radius.3`, `space.4`, `font.family.sans`).
   - **Semantic tokens:** roles (`color.action`, `color.surface`, `color.text.muted`, `color.border`,
     `color.danger`, `radius.control`, `shadow.raised`, `motion.duration.base`, `density.row`). Components may use
     **only** these.
   - **Component tokens** where a component really differs (`button.radius`, `input.height`), always aliases of
     semantic tokens.
3. **A small generator, in our own Node script and with no new dependency** (`scripts/design/build-tokens.mjs`),
   reads the active file and writes:
   - `packages/ui/src/tokens.generated.css` (the variables and the `@theme` mapping that `tailwind.css` imports; light
     and dark through `light-dark()` as today),
   - `packages/ui/src/tokens.gen.ts` (token names and types, for the catalogue and tests),
   - `docs/design-system/tokens.md` (the table of every token, generated).
   Generated files are committed and marked "do not edit". CI fails if they differ from what the generator produces
   (`pnpm design:check`). If the script outgrows us, **Style Dictionary** (Apache-2.0) is the upgrade, with its own
   approval.
4. **Validation runs inside the generator, and a template that fails it does not build:**
   - **Completeness:** every required token exists (a template can be swapped only because the schema is fixed).
   - **Contrast (WCAG 2.2 AA):** a list of required pairs in the file (text on background, on surface, on accent,
     muted text, links, focus ring against its neighbours, error and warning text) is computed in both schemes: 4.5:1
     for text, 3:1 for large text and UI parts.
   - **Gamut:** a colour outside sRGB is reported (it would be clipped differently on different screens).
   - **Motion:** a reduced-motion value for every duration; **forced-colors** mappings for the system colours.
5. **A token lint stops hard-coded values**, the thing that would silently break the one-file promise.
   `scripts/design/check-tokens.mjs` scans `apps/web`, `apps/desktop/src` and `packages/ui/src` and fails on raw hex,
   `rgb(`, `hsl(`, `oklch(` outside the generated files, Tailwind arbitrary colour or size values (`text-[#...]`,
   `rounded-[7px]`, `text-[13px]`), and inline `style={{ color: ... }}`. A short, reviewed allow-list file (with a
   reason per entry) covers real exceptions such as the 3D viewer's background or generated images.
6. **The look is swapped at build time in v1.** The owner replaces the file and rebuilds. The generator can emit
   several packs (so a runtime theme picker is possible later), but a user-selectable theme is **not built now**
   (decision of this ADR; the owner only mentioned swapping the template). Light, dark and system stay as they are.
7. **The blue replaces the violet.** Proposed values, computed in OKLCH and checked for sRGB gamut and WCAG contrast
   (2026-10-19; to be confirmed visually in DS2):

   | Role | Light | Dark | Checks |
   |---|---|---|---|
   | `color.action` (accent) | `oklch(50% 0.17 258)` ≈ `#145ec1` | `oklch(76% 0.12 250)` ≈ `#73b6fa` | in sRGB; white on light accent **6.14:1**; light accent as text on the page background **5.59:1**, on a surface **6.14:1**; dark accent as text on the dark background **9.27:1**, on a dark surface **8.11:1**; dark text on dark accent **8.65:1** |
   | `color.on-action` | white | `oklch(19% 0.04 250)` | as above |
   | Neutrals (background, surface, border, text, muted) | cool, hue about 250, chroma 0.004 to 0.006 | same | re-checked in DS2; warm tint (hue 90) dropped |
   | `color.accent-2`, `accent-3` | re-chosen for the blue (a teal or sky for charts and highlights; the lime is dropped unless a chart needs it) | | chart palette checked for colour-blind safety |
   | `ok`, `warn`, `danger` | unchanged hues, re-verified against the new surfaces | | |

   Two alternatives were computed and kept for the visual review: a deeper blue (`oklch(46% 0.16 255)`, 7.2:1 with
   white but outside sRGB, so it must be clamped) and an azure (`oklch(52% 0.12 235)`, 5.33:1). The first is the
   recommendation.
8. **Component catalogue and states.** A catalogue page (a route in the web app, and an item under Settings in the
   desktop app, both from the same `packages/ui` screen) shows every token and every component in every state
   (default, hover, focus, active, disabled, loading, error) in light and dark, at both densities. It is also the
   target of the Playwright layout and screenshot checks (they exist), plus a **token-swap test**: render the same
   screens under the active template and under a second one, and fail on overflow, clipped text or unreadable pairs.
9. **Accessibility is part of the system, not a later pass:** AA contrast (decision 4), a visible focus ring on every
   control, a minimum target of 24 px (44 px on touch), `prefers-reduced-motion`, forced-colors and high-contrast
   modes, labels and names for every control, no meaning by colour alone. Automated checks with **axe-core**
   (MPL-2.0) through its Playwright integration are proposed; **a new dependency, so it needs your approval
   first** (it closes backlog B2).
10. **Language and script:** logical CSS properties (start and end, not left and right) so right-to-left works;
    font stacks with fallbacks per script; no fixed-width text; layouts tested with long strings. English only in
    v1 (project rule), without closing the door. **Fonts are files in the repository or the app**, with open
    licences recorded; the desktop never fetches fonts from the network.
11. **Content design in `DESIGN.md`:** plain words, sentence case, one action per button, errors say what happened and
    what to do, no jargon on the simple path (the ADR-0073 list of expert words stays behind "For experts"), a glossary
    of product words ("magic word", "Video Builder", "Motion graphics", "My models"), and microcopy for the common
    states.
12. **Motion and density are tokens** (durations, easing, comfortable and compact row and control sizes) with
    reduced-motion fallbacks.
13. **Screen patterns for the new features are written before they are built:** the "Teach" front door and its three
    steps, the Agent feed with inline approvals, the Video Builder and Motion graphics screens, the 3D viewer and result
    page, the setup and download cards (size shown, one click), and the "For experts" panel. Phase 5 screens are built
    against the system, so stages DS0 to DS2 come before T1, G1, V1 and TD1.
14. **Governance:** `DESIGN.md` carries a `version`; every change goes through a pull request with a checklist (tokens
    only, all states, light and dark, keyboard, right-to-left, contrast); a breaking token change is recorded in
    `design/CHANGELOG.md`; a structural change (a new component family, a new layout) gets an ADR. No Figma sync (the
    owner's decision); the file is the design.
15. **Usability testing is part of the practice:** a short task-based test with about five non-technical people for each
    major flow (Teach, Agent, Make a 3D model, Video Builder), notes in `docs/research/`. The system makes screens
    consistent; testing shows whether they are clear.
16. **Brand assets** (wordmark "Wasify AI", icon, favicon) live in `design/assets/` with their source and licence;
    designing a new logo is not part of this ADR.

## Consequences

- A new look is one file and one rebuild, with a failing build instead of a broken screen if the file is incomplete or
  unreadable.
- A one-time clean-up: every hard-coded colour, size and radius the lint finds is replaced by a token. The size of that
  work is unknown until DS1 runs the lint.
- The generated CSS and types are committed, so a build needs no extra step, and CI keeps them in step.
- What the file cannot change (structure, icons, copy beyond the rules) is written down, so "re-skin" is not
  mistaken for "redesign".
- The 3D viewer and the generated media sit outside the tokens; their backgrounds are allow-listed.

## Alternatives considered

- **Style Dictionary (Apache-2.0).** Powerful, multi-platform; adds a dependency and a config language for a job a
  200-line script does today. Kept as the upgrade path.
- **Tokens Studio and Figma sync.** Declined by the owner.
- **Edit `tailwind.css` by hand and add a README.** What we have; it cannot be swapped as a whole and has no checks.
- **Only shadcn/ui theme variables.** Covers colours and radii, not type scale, motion, density or content rules, and
  has no validation.
- **CSS-in-JS themes.** A runtime cost and a rewrite of every component for no gain over CSS variables.
- **A runtime theme picker now.** Not requested; the generator is built so it can be added.

## Open questions

1. The final blue, after a visual review of the recommendation and the two alternatives on real screens (DS2).
2. The font families (the current stack is system fonts; a bundled open family would make web and desktop identical)
   and their licences.
3. The chart palette and how many categorical colours are needed.
4. Whether the desktop window and the web app should share the catalogue route or each have one.
5. Whether a compact density is wanted at launch or only the comfortable one.
6. The axe-core dependency (decision 9) and its licence, MPL-2.0: acceptable for a dev and CI tool?

## Not in v1

A runtime theme picker; Figma sync; per-user theming; a documentation site outside the app; motion design beyond tokens;
a new logo; right-to-left product copy (the layout supports it, translations are not v1).

## Amendment after DS0 to DS2 (2026-10-19)

Built and verified on the owner's Mac. What changed from the plan above, and what was found:

- **Files:** `design/DESIGN.md` (rules and the active tokens), `design/themes/violet.md` and `blue.md` (tokens only),
  `design/token-allowlist.json`, `design/CHANGELOG.md`, `scripts/design/build-tokens.mjs`, `check-tokens.mjs`, `swap-test.mjs`,
  generated `packages/ui/src/tokens.generated.css`, `tokens.gen.ts` (named `.gen.ts` so Biome ignores it) and
  `docs/design-system/tokens.md`. Commands: `pnpm design:build`, `design:use <name>`, `design:check` (also a CI step in the web
  job) and `design:swap-test`. No dependency was added.
- **Templates are tokens-only files.** `pnpm design:use blue` replaces the tokens block inside `DESIGN.md` and keeps its rules, so the
  prose has one copy. This differs from "a template is another whole `DESIGN.md`" in decision 1 on purpose; replacing the tokens
  block is what swaps the look. `design/active` was not needed: `DESIGN.md` is the active file.
- **Gamut is a template policy** (`checks.gamut`: `error` by default, `warn` for violet). The old violet look has four colours slightly
  outside sRGB and two weak contrast pairs (accent text on a selected row in dark, 4.0:1; the picture label, 3.1:1); the validator found
  them. **Blue passes everything strictly** (28 contrast rules in both schemes become 32 with the new tokens, all in sRGB).
- **The `@theme inline` wiring stays in `tailwind.css`** (which role feeds which Tailwind colour is structure, not look). The generated
  file holds the variables and the `@theme` size and easing values. The animation names and their durations also stay there.
- **The lint found about 90 hard-coded values** in 12 files; all were replaced by tokens except the product illustrations
  (`ProductArt.tsx`, a deliberate allow-list entry because DESIGN.md says a template does not change illustrations) and one
  `em`-relative size for inline code. Folding font sizes into a scale moved some text by a pixel or less; `--text-2xs` is 0.65rem so the
  side menu did not shift.
- **Blue 1.0.0 is now the default:** accent `oklch(50% 0.17 258)` light and `oklch(76% 0.12 250)` dark; the recommended blue from decision
  7, with cool neutrals, teal and sky as the other brand colours, status colours reduced in chroma to sit inside sRGB, `--accent-soft`
  at 10% and the picture scrim at 84% so both pass AA.
- **Checks run:** generated files current; lint, types and 1,300+ unit tests pass; the web and desktop builds pass; the 168 Playwright
  checks (102 layout, 66 screenshots in light, dark and phone) pass; **the swap test passed for both templates**. All 66 darwin
  screenshots were regenerated for the blue look; CI keeps running the layout checks only.
- **Not done (DS3 and after):** the component catalogue page, axe-core (needs approval), the content guide beyond the first rules in
  DESIGN.md, bundled fonts, a density token, chart palette, the illustrations in token colours, and the usability tests.
