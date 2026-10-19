/* The resolved design tokens, for the catalogue and tests. GENERATED from design/DESIGN.md by scripts/design/build-tokens.mjs (ADR-0081). Do not edit by hand:
   change design/DESIGN.md and run `pnpm design:build`. Template: blue 1.0.0. */

export const templateId = "blue";
export const templateVersion = "1.0.0";

/** The page background as hex, for the browser's own chrome (the `theme-color` meta tag). */
export const themeColor = {"light":"#f3f5f8","dark":"#080b10"} as const;

/** CSS variable name -> value, or { light, dark } where the colour differs by scheme. */
export const tokens = {
  "--bg": {
    "light": "oklch(97% 0.004 250)",
    "dark": "oklch(15% 0.012 255)"
  },
  "--surface": {
    "light": "oklch(100% 0 0)",
    "dark": "oklch(21% 0.014 255)"
  },
  "--surface-solid": {
    "light": "oklch(100% 0 0)",
    "dark": "oklch(21% 0.014 255)"
  },
  "--surface-2": {
    "light": "oklch(96% 0.006 250)",
    "dark": "oklch(26% 0.016 255)"
  },
  "--text": {
    "light": "oklch(21% 0.02 255)",
    "dark": "oklch(95% 0.006 250)"
  },
  "--muted": {
    "light": "oklch(49% 0.02 255)",
    "dark": "oklch(70% 0.016 255)"
  },
  "--border": {
    "light": "oklch(90% 0.01 250)",
    "dark": "oklch(34% 0.018 255)"
  },
  "--accent": {
    "light": "oklch(50% 0.17 258)",
    "dark": "oklch(76% 0.12 250)"
  },
  "--accent-2": {
    "light": "oklch(55% 0.09 205)",
    "dark": "oklch(78% 0.11 205)"
  },
  "--accent-3": "oklch(80% 0.11 235)",
  "--on-accent": {
    "light": "oklch(99% 0 0)",
    "dark": "oklch(19% 0.04 250)"
  },
  "--accent-soft": "color-mix(in oklch, oklch(50% 0.17 258) 10%, transparent)",
  "--ok": {
    "light": "oklch(52% 0.125 155)",
    "dark": "oklch(76% 0.15 155)"
  },
  "--warn": {
    "light": "oklch(58% 0.12 70)",
    "dark": "oklch(82% 0.13 80)"
  },
  "--danger": {
    "light": "oklch(55% 0.19 25)",
    "dark": "oklch(74% 0.14 25)"
  },
  "--ok-soft": {
    "light": "oklch(95% 0.03 140)",
    "dark": "oklch(28% 0.04 140)"
  },
  "--on-ok-soft": {
    "light": "oklch(42% 0.11 145)",
    "dark": "oklch(82% 0.12 140)"
  },
  "--scrim": "oklch(20% 0.03 255 / 0.84)",
  "--on-scrim": "oklch(100% 0 0)",
  "--radius-sm": "0.5rem",
  "--radius": "0.85rem",
  "--radius-lg": "1.15rem",
  "--radius-control": "0.65rem",
  "--shadow": "0 1px 2px oklch(22% 0.03 255 / 0.05), 0 12px 30px -16px oklch(30% 0.08 255 / 0.22)",
  "--font": "ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif",
  "--font-serif": "ui-serif, \"Iowan Old Style\", \"Palatino Linotype\", Georgia, serif",
  "--space": "clamp(1rem, 0.8rem + 1vw, 1.75rem)",
  "--text-step--1": "clamp(0.8rem, 0.78rem + 0.1vw, 0.875rem)",
  "--text-step-0": "clamp(1rem, 0.96rem + 0.2vw, 1.0625rem)",
  "--text-step-1": "clamp(1.2rem, 1.1rem + 0.5vw, 1.4rem)",
  "--text-step-2": "clamp(1.5rem, 1.3rem + 1vw, 2rem)",
  "--text-step-3": "clamp(2.1rem, 1.6rem + 2.5vw, 3.4rem)",
  "--text-2xs": "0.65rem",
  "--text-ui-sm": "0.8rem",
  "--text-ui": "0.9rem",
  "--text-ui-lg": "0.95rem",
  "--text-lead": "1.05rem",
  "--text-title": "1.15rem",
  "--text-display": "clamp(2rem, 8vw, 2.55rem)",
  "--text-display-lg": "clamp(2.55rem, 5.3vw, 3.9rem)",
  "--ease-out-soft": "cubic-bezier(0.22, 1, 0.36, 1)"
} as const;

export type TokenName = keyof typeof tokens;
