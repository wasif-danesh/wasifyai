# ADR-0093: One shell and one make screen for every product

- **Status:** Proposed (2026-10-27; built only when the owner picks a stage of `docs/ui-improvement-plan.md`)
- **Date:** 2026-10-27
- **Depends on:** ADR-0081 (the design system), ADR-0086 (the model button and its dialog), ADR-0041 (every
  creation is searchable), ADR-0087 (the web is the desktop's twin).
- **Related:** ADR-0091 (Styles in the image screens), ADR-0090 (Creative Studio), ADR-0057 (the chat as home).
- **Audit:** `docs/ui-audit-2026-10-27.md`. **Plan:** `docs/ui-improvement-plan.md`.

## Context

Twenty-one make screens were built product by product over three weeks, each with the layout its stage found
natural, and the window and the web app grew different shells. The audit (pictures of the real window and of
the web) counted three page layouts for the same job, nine words on the main button, four shapes of the model
button, five libraries with two of them called Library, a two-click menu with "Create" listed four times, six
experts' fields on first screens, seven native selects, eleven actions on one creation, and two shells that differ
in their bar, their search, their job chip and their theme switch although ADR-0087 says the two apps are one.
The owner is not happy with the look and feel or the flows, and wants the app advanced and intuitive.

## Decision

1. **One shell, on the window and on the web.** The side menu as it was (its groups open one at a time; the
   owner tried a flat menu with the modes as tabs in the bar on 2026-10-27 and asked for the groups back on
   2026-10-28), and one `AppBar` of one height on every screen of both apps holding back and forward (window),
   the title, the model button, the job tray, search (⌘K) and the theme. No breadcrumb; no "Group: Item" title;
   no second bar; no magnifier in the menu.
2. **One make screen** (`MakeScreen` in `packages/ui`): **ask** (the prompt, the few controls that matter,
   the experts' fields collapsed under "For experts", the main button always visible), **stage** (the result with its empty, progress, error and
   result states and the result's actions), **recent** (the last creations of the kind from the one library).
   Every tool that makes something uses it; a tool with steps uses it with a stepper in the ask column.
3. **One word for the main action, "make"**, and one set of nouns (picture, video, speech, song, voice,
   recording, notebook, model), kept in one file that every screen imports and a test checks.
4. **One model control:** the top-bar button names a real model by its display name (never a raw tag or a
   hash) with a readiness dot, or says "Choose a … model"; the picker is a dialog that does not cover the form; a
   tool's first visit without a model shows the ADR-0086 card. The "Model for …" placeholder goes.
5. **One library:** My creations is the only library; the per-product "Your …" pages go; every creation opens to
   a detail view with its recipe, actions and what was made from it; make screens show a recent strip read from
   the library.
6. **One job system:** progress on the screen that started the work and in the tray, which lists every running
   job with Stop (the engine already offers `GET /actions/jobs` and cancel).
7. **Every state is designed**, the error notice component can never show a path or a code, and no screen uses
   a native select, checkbox, radio, slider or audio player: the design-system controls replace them.
8. **Three actions and a menu** on any creation, wherever it is shown.
9. **Design before build:** each stage starts with an HTML mockup the owner sees.

## Consequences

- Every make screen is rebuilt on the frame; about forty-four days in thirteen stages (the plan, U0 to U12),
  each shipping on its own, with the window checked for real (`apps/desktop/scripts/ui-audit.sh`) and the
  web's screenshots regenerated.
- The window's `TitleBar` and the web's top bar are replaced by one `AppBar` in `packages/ui`; the window gets a
  job tray, search and a theme switch it does not have today, the web loses its breadcrumb and Explore.
- The routes of the "Your …" pages and of the grouped menu change (old addresses redirect); `parity.ts` and the
  menu walk spec are updated with the menu.
- The Library needs list filters by kind and a detail route; the engine's actions and routes otherwise stand.
- The web's Explore page is folded into the home unless the owner keeps it as a marketing page.

## Alternatives considered

- **Polish each screen where it is.** Cheaper per screen, but it keeps three layouts and four libraries, which is
  the problem.
- **One canvas for everything (Creative Studio, ADR-0090).** That is a project surface over the products, not the
  products' own screens; it arrives after them and will use the same frame.
- **A visual refresh only (colours, type, spacing).** The audit found the inconsistency in structure and words,
  not in the tokens; the tokens stay.

## Open questions

The owner decisions in the plan: names, the accessibility checker dependency, and mockup review per stage. The menu
without groups was tried and decided against (2026-10-28). The per-product libraries go (owner, 2026-10-28):
decision 5 above stands as written. The web's Explore page stays as a marketing page outside the app, and the chat
box has three pills and a "+" menu (owner, 2026-10-28).
