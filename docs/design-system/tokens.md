# Design tokens

Generated from `design/DESIGN.md` (template **blue**, version 1.0.0) by `scripts/design/build-tokens.mjs`. Do not edit by hand.

| Token | CSS variable | Type | Light | Dark | Use |
|---|---|---|---|---|---|
| `color.bg` | `--bg` | color | `oklch(97% 0.004 250)` ≈ `#f3f5f8` | `oklch(15% 0.012 255)` ≈ `#080b10` | Page background |
| `color.surface` | `--surface` | color | `oklch(100% 0 0)` ≈ `#ffffff` | `oklch(21% 0.014 255)` ≈ `#14191f` | Cards, panels, sidebar |
| `color.surface-solid` | `--surface-solid` | color | `oklch(100% 0 0)` ≈ `#ffffff` | `oklch(21% 0.014 255)` ≈ `#14191f` | Popovers and menus (always opaque) |
| `color.surface-2` | `--surface-2` | color | `oklch(96% 0.006 250)` ≈ `#eff2f6` | `oklch(26% 0.016 255)` ≈ `#1f252c` | Quiet fills: secondary buttons, muted areas |
| `color.text` | `--text` | color | `oklch(21% 0.02 255)` ≈ `#121921` | `oklch(95% 0.006 250)` ≈ `#ebeff2` | Body text |
| `color.muted` | `--muted` | color | `oklch(49% 0.02 255)` ≈ `#59616c` | `oklch(70% 0.016 255)` ≈ `#989fa8` | Secondary text and captions |
| `color.border` | `--border` | color | `oklch(90% 0.01 250)` ≈ `#d9dfe5` | `oklch(34% 0.018 255)` ≈ `#323941` | Lines, input borders |
| `color.accent` | `--accent` | color | `oklch(50% 0.17 258)` ≈ `#145ec1` | `oklch(76% 0.12 250)` ≈ `#73b6fa` | Primary actions, links, focus |
| `color.accent-2` | `--accent-2` | color | `oklch(55% 0.09 205)` ≈ `#13808a` | `oklch(78% 0.11 205)` ≈ `#4fccd9` | Second brand colour: charts, highlights |
| `color.accent-3` | `--accent-3` | color | `oklch(80% 0.11 235)` ≈ `#71c9fa` | same | Third brand colour: charts, highlights |
| `color.on-accent` | `--on-accent` | color | `oklch(99% 0 0)` ≈ `#fcfcfc` | `oklch(19% 0.04 250)` ≈ `#051525` | Text and icons on the accent colour |
| `color.accent-soft` | `--accent-soft` | color | `color-mix(in oklch, oklch(50% 0.17 258) 10%, transparent)` | same | Tinted fill: hovers, selected rows |
| `color.ok` | `--ok` | color | `oklch(52% 0.125 155)` ≈ `#0c7d48` | `oklch(76% 0.15 155)` ≈ `#52cd86` | Success |
| `color.warn` | `--warn` | color | `oklch(58% 0.12 70)` ≈ `#a76c12` | `oklch(82% 0.13 80)` ≈ `#f0ba59` | Warning |
| `color.danger` | `--danger` | color | `oklch(55% 0.19 25)` ≈ `#c92f33` | `oklch(74% 0.14 25)` ≈ `#f7857d` | Errors and destructive actions |
| `color.ok-soft` | `--ok-soft` | color | `oklch(95% 0.03 140)` ≈ `#e4f4e1` | `oklch(28% 0.04 140)` ≈ `#1e2e1b` | Fill behind a success label |
| `color.on-ok-soft` | `--on-ok-soft` | color | `oklch(42% 0.11 145)` ≈ `#1c5c23` | `oklch(82% 0.12 140)` ≈ `#9ad78c` | Text on the success fill |
| `color.scrim` | `--scrim` | color | `oklch(20% 0.03 255 / 0.84)` ≈ `#0c1723` | same | Translucent fill for labels over pictures |
| `color.on-scrim` | `--on-scrim` | color | `oklch(100% 0 0)` ≈ `#ffffff` | same | Text and borders on the scrim |
| `radius.sm` | `--radius-sm` | dimension | `0.5rem` | same | Small controls |
| `radius.md` | `--radius` | dimension | `0.85rem` | same | Cards, inputs |
| `radius.lg` | `--radius-lg` | dimension | `1.15rem` | same | Large panels |
| `radius.control` | `--radius-control` | dimension-theme | `0.65rem` | same | Back links and small buttons |
| `shadow.raised` | `--shadow` | shadow | `0 1px 2px oklch(22% 0.03 255 / 0.05), 0 12px 30px -16px oklch(30% 0.08 255 / 0.22)` | same | The raised surface |
| `font.sans` | `--font` | fontFamily | `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` | same | Interface text |
| `font.serif` | `--font-serif` | fontFamily | `ui-serif, "Iowan Old Style", "Palatino Linotype", Georgia, serif` | same | Headings and long reading |
| `space.page` | `--space` | dimension | `clamp(1rem, 0.8rem + 1vw, 1.75rem)` | same | Gap between page sections |
| `type.step--1` | `--text-step--1` | dimension-theme | `clamp(0.8rem, 0.78rem + 0.1vw, 0.875rem)` | same | Captions, labels |
| `type.step-0` | `--text-step-0` | dimension-theme | `clamp(1rem, 0.96rem + 0.2vw, 1.0625rem)` | same | Body |
| `type.step-1` | `--text-step-1` | dimension-theme | `clamp(1.2rem, 1.1rem + 0.5vw, 1.4rem)` | same | Small headings |
| `type.step-2` | `--text-step-2` | dimension-theme | `clamp(1.5rem, 1.3rem + 1vw, 2rem)` | same | Headings |
| `type.step-3` | `--text-step-3` | dimension-theme | `clamp(2.1rem, 1.6rem + 2.5vw, 3.4rem)` | same | Page titles |
| `type.2xs` | `--text-2xs` | dimension-theme | `0.65rem` | same | Badges and the smallest labels |
| `type.ui-sm` | `--text-ui-sm` | dimension-theme | `0.8rem` | same | Dense interface text |
| `type.ui` | `--text-ui` | dimension-theme | `0.9rem` | same | Interface text |
| `type.ui-lg` | `--text-ui-lg` | dimension-theme | `0.95rem` | same | Roomy interface text |
| `type.lead` | `--text-lead` | dimension-theme | `1.05rem` | same | Intro lines |
| `type.title` | `--text-title` | dimension-theme | `1.15rem` | same | Panel titles |
| `type.display` | `--text-display` | dimension-theme | `clamp(2rem, 8vw, 2.55rem)` | same | Hero heading, phone |
| `type.display-lg` | `--text-display-lg` | dimension-theme | `clamp(2.55rem, 5.3vw, 3.9rem)` | same | Hero heading, wide |
| `motion.ease-soft` | `--ease-out-soft` | cubicBezier | `cubic-bezier(0.22, 1, 0.36, 1)` | same | Entrances and reveals |

## Contrast checks (WCAG 2.2 AA)

| Foreground | Background | Scheme | Ratio | Needs |
|---|---|---|---|---|
| `--text` | `--bg` | light | 16.24:1 | 4.5:1 |
| `--text` | `--bg` | dark | 17.01:1 | 4.5:1 |
| `--text` | `--surface` | light | 17.71:1 | 4.5:1 |
| `--text` | `--surface` | dark | 15.31:1 | 4.5:1 |
| `--text` | `--surface-2` | light | 15.78:1 | 4.5:1 |
| `--text` | `--surface-2` | dark | 13.43:1 | 4.5:1 |
| `--muted` | `--bg` | light | 5.74:1 | 4.5:1 |
| `--muted` | `--bg` | dark | 7.37:1 | 4.5:1 |
| `--muted` | `--surface` | light | 6.25:1 | 4.5:1 |
| `--muted` | `--surface` | dark | 6.64:1 | 4.5:1 |
| `--muted` | `--surface-2` | light | 5.57:1 | 4.5:1 |
| `--muted` | `--surface-2` | dark | 5.82:1 | 4.5:1 |
| `--on-accent` | `--accent` | light | 5.96:1 | 4.5:1 |
| `--on-accent` | `--accent` | dark | 8.65:1 | 4.5:1 |
| `--accent` | `--bg` | light | 5.63:1 | 4.5:1 |
| `--accent` | `--bg` | dark | 9.21:1 | 4.5:1 |
| `--accent` | `--surface` | light | 6.14:1 | 4.5:1 |
| `--accent` | `--surface` | dark | 8.30:1 | 4.5:1 |
| `--text` | `--accent-soft` | light | 16.23:1 | 4.5:1 |
| `--text` | `--accent-soft` | dark | 8.85:1 | 4.5:1 |
| `--accent` | `--accent-soft` | light | 5.62:1 | 4.5:1 |
| `--accent` | `--accent-soft` | dark | 4.80:1 | 4.5:1 |
| `--danger` | `--surface` | light | 5.35:1 | 4.5:1 |
| `--danger` | `--surface` | dark | 7.24:1 | 4.5:1 |
| `--ok` | `--surface` | light | 5.18:1 | 4.5:1 |
| `--ok` | `--surface` | dark | 8.77:1 | 4.5:1 |
| `--warn` | `--surface` | light | 4.40:1 | 3:1 |
| `--warn` | `--surface` | dark | 10.03:1 | 3:1 |
| `--on-ok-soft` | `--ok-soft` | light | 7.04:1 | 4.5:1 |
| `--on-ok-soft` | `--ok-soft` | dark | 8.58:1 | 4.5:1 |
| `--on-scrim` | `--scrim` | light | 4.84:1 | 4.5:1 |
| `--on-scrim` | `--scrim` | dark | 18.04:1 | 4.5:1 |
