# Design changelog

Changes to the tokens in `design/DESIGN.md` and the templates in `design/themes/` (ADR-0081). Breaking changes (a renamed or
removed token) are marked **breaking**.

## 2026-10-19: DS0 to DS2

- **DS0:** `design/DESIGN.md` becomes the source of the look. `pnpm design:build` generates `packages/ui/src/tokens.generated.css`
  and `tokens.gen.ts` and `docs/design-system/tokens.md`. The old stylesheet values moved into the template **violet 1.0.0** with no
  visual change.
- **DS1:** the token lint (`pnpm design:check`) and the validation (completeness, contrast, gamut, reduced motion). New tokens so
  screens no longer hard-code values: `--ok-soft`, `--on-ok-soft`, `--scrim`, `--on-scrim`, `--radius-control`, and the text sizes
  `--text-2xs`, `--text-ui-sm`, `--text-ui`, `--text-ui-lg`, `--text-lead`, `--text-title`, `--text-display`, `--text-display-lg`.
  Arbitrary font sizes in screens were folded into that scale (0.7rem and 0.72rem became 0.65rem; 0.78 and 0.82 became 0.8; 0.85
  and 0.92 became 0.9), so some text moved by a pixel or less. `--hue` (unused) was removed. **breaking:** none for screens.
- **DS2:** the default template is now **blue 1.0.0**: accent `oklch(50% 0.17 258)` light and `oklch(76% 0.12 250)` dark, cool
  neutrals, teal and sky as the other brand colours, status colours pulled inside sRGB, `--accent-soft` 10% (was 14%), the picture
  scrim 84% opaque (was 72%) so its label passes AA. The violet template is kept in `design/themes/violet.md`. The product
  illustrations (`ProductArt.tsx`) keep their own palette and are on the lint allow-list.
