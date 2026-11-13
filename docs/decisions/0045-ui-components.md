# ADR-0045: UI components for forms and data grids (shadcn/ui, TanStack Table)

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

The web app (`apps/web`) has no UI library. It is React and Next.js with one hand-written stylesheet
(`app/globals.css`, about 1,700 lines, with design tokens as CSS variables and light and dark colours). Every
control is a plain browser element styled by hand: selects, radios, textareas, file inputs and dialogs. The
forms of the music, image, video and text-to-speech products look basic, focus and keyboard behaviour is
re-implemented per component, and there is no data grid at all: My creations and the admin pages are cards and
simple lists. The speech and lip-sync products (ADR-0042 to ADR-0044), the admin area and future products need
richer forms (selects with search, combobox, dialogs, toasts, date and range inputs) and real tables (sorting,
filtering, paging, column choice) for usage, models, voices and transcripts.

The owner wants a professional look and decided to reuse a component library instead of growing our own.
Options looked at (2026-10-09):

| Option | Notes |
|---|---|
| **shadcn/ui** | Not a package: components are copied into our repo as source, built on Radix UI (accessibility, keyboard, focus, right-to-left) and Tailwind CSS |
| **TanStack Table** | Headless: sorting, filtering, paging, column visibility, no markup or styles |
| Material UI | Heavy, runtime CSS-in-JS, a strong Google look that is hard to brand, App Router friction |
| Flowbite, DaisyUI, HeroUI | Good looks, but accessibility and theming vary, and they tie us to their theme and release pace |

Rule 12 (open source first, ask before adding a dependency) applies; accepting this ADR is that approval for the
packages named here. The project must be multilingual: components must work with Bengali and other scripts, and
with right-to-left languages.

## Decision

- **Forms: shadcn/ui** (Radix primitives with Tailwind CSS). Components are added one by one with the shadcn CLI
  into `apps/web/components/ui/`; they are ours to edit. Needed first: Button, Input, Textarea, Label, Select,
  Combobox (Command and Popover), RadioGroup, Checkbox, Switch, Tabs, Dialog, AlertDialog, DropdownMenu, Tooltip,
  Toast (Sonner), Skeleton, Badge, Alert, Form helpers.
- **Form state and validation: react-hook-form with Zod** through shadcn's Form component. Validation
  messages are plain, translatable sentences.
- **Data grids: TanStack Table** with shadcn's Table component (the "data table" pattern): sorting, filtering,
  paging (server side where the list is large, using our cursor `before` paging), column visibility, row actions.
  Virtualised rows (TanStack Virtual) only when a list proves too long.
- **Tailwind CSS** is added only as the engine shadcn needs. Our design tokens stay the source of truth: the
  existing CSS variables (colours, radii, focus ring, light and dark) are mapped into the Tailwind theme and
  shadcn's variables, so there is one palette and the current look and brand carry over.
- **Migration is gradual, screen by screen.** New and changed screens use the new components; old screens keep
  their CSS until touched. Both can coexist (Tailwind's preflight is switched off or scoped so it does not
  reset the old styles until migration ends). The old classes are deleted only when nothing uses them.
- **First trial, before the rest is migrated:** the Text to Speech form and one list (My creations as a table
  view, and the admin media backends). The trial must pass the checks below, or this ADR is revised.
- **Checks every migrated screen must pass:** keyboard only, a screen reader (labels and errors announced),
  Bengali and another non-Latin script in every text field and select (including long words and no clipping),
  a right-to-left layout (Arabic or Urdu sample), dark and light colours, 320 px wide, and the existing Vitest
  tests updated or replaced.
- **Pins and updates.** Versions are pinned. Tailwind and Radix versions are chosen at least two weeks old; shadcn
  component source is reviewed like our own code when added or refreshed.

## Consequences

- New dependencies in `apps/web`: tailwindcss (with its PostCSS plugin), Radix UI packages, class-variance-authority,
  clsx and tailwind-merge, lucide-react (icons), sonner, react-hook-form, zod, @tanstack/react-table. The shadcn CLI is a development tool only.
- Two styling systems exist during migration. That costs some confusion and a larger bundle until the old CSS goes;
  the rule is "touch a screen, migrate it".
- We own the component source, so fixes and look changes are ours, and upgrades are manual and deliberate.
- Accessibility and keyboard behaviour improve across the app; right-to-left support depends on a `dir` attribute
  and logical CSS properties, which the migrated screens must use.
- Existing component tests (`components/**/*.test.tsx`) must be updated as screens move; Biome and the TypeScript
  checks stay as they are.
- Not decided here: the app shell and navigation (ADR-0046), a full redesign or rebrand, charts, and a
  translation system for interface text.

## Docs to update if accepted

`CLAUDE.md` (Tooling: add shadcn/ui, Tailwind and TanStack Table; a Convention: "use `components/ui` for controls
and tables"), `docs/architecture.md` (web section), `docs/decisions/README.md` (status), and a short
`apps/web/README.md` section on adding a component and the design tokens.
