# Phase 2, stage B: gallery and recipes in the desktop app (plan)

Status: **Approved 2026-10-15; B1, B2 and B3 done the same day** (evidence below). Implements the second slice of ADR-0061 phase 2. Builds on
stage A (real images) and the side-menu window (`docs/desktop-profile.md`, "The window").

**Goal.** Every image keeps the recipe that made it; the person can reopen it, make it again exactly, mark
favourites, save a copy to their Downloads folder, and find images by words. The Library and Create screens
are shared code (`packages/ui`), not desktop-only.

## What changes

| Today | After stage B |
|---|---|
| The image row keeps prompt, size, mode | plus the **recipe**: prompt, mode, size name, width, height, **seed** (JSON, versioned) |
| The seed is drawn inside the graph and lost | a run may carry a `seed`; the graph validates it and stores the one it used |
| "Use this prompt" fills the prompt only | **Run again** restores prompt, size and seed (text images); same seed + same model = same picture |
| No favourites | `favourite` flag, `PATCH /images/{id}`, `?favourites=true` filter, a heart in the Library |
| Download is a browser attachment route | the web keeps it; the desktop adds `POST /images/{id}/export`, which copies the file into the Downloads folder (`WASIFYAI_EXPORT_DIR` overrides) and says where |
| Library and Create live in `apps/desktop` | Library, Create and the image strip move to `@wasifyai/ui` and take a small `ImagesApi` (list, search, get, delete, favourite, export) as a prop |

## Design decisions

1. **Additive schema.** Postgres gets migration 0017 (`recipe` text, `favourite` boolean on `images`); SQLite
   gets guarded `ALTER TABLE ... ADD COLUMN` (`ensure_columns` in the SDK). Old rows have `recipe = null`:
   the window shows what the row has and disables "Run again".
2. **Edits are not re-runnable.** An edit's source picture is deleted once the image is saved (privacy
   decision in the image graph), so only text images offer **Run again**. Edit images offer "Use this prompt".
3. **The model is not in the recipe yet.** The graph names capabilities, not models (rule in the image
   graph); exact reproduction therefore holds for the same installed model. The recipe is versioned (`v: 1`)
   so the model id can be added when the catalogue is wired through the capability.
4. **Export goes through the engine** because a webview cannot save a blob without a native dialog; the
   engine already owns the file. Only the desktop profile sets `export_dir`; elsewhere the route is 404.
5. **Search is unchanged** (ADR-0041): prompt words and meaning. Favourites are a filter, not a new index.

## Order of work

| Step | What | Evidence |
|---|---|---|
| B1 | Recipe and favourite in the store, graph, routes, migration | Python tests: store contract (SQLite and in-memory), graph stores the seed it used and honours a given one, routes (favourite, filter, export) |
| B2 | Client and shared UI: `ImagesApi`, Library, Create, Recipe actions | TypeScript tests for the API wrapper and recipe-to-form mapping; typecheck of web and desktop |
| B3 | Desktop wiring, self-test, docs | The self-test makes an image, favourites it, runs it again with the same seed and checks the same size and recipe |

## Not in stage B

Collections and tags, bulk actions, edit remix and LoRAs (stage C), the model id in the recipe.

## Evidence

- B1: store contract on SQLite and in memory (recipe round-trip, favourites, an older database file gets the new
  columns), graph tests (seed kept, given seed used, invalid seeds refused before any model), route tests
  (favourite, filter, export, ownership), and one end-to-end desktop-profile test through the real app with the
  CORS preflight.
- B2: `@wasifyai/client` images API tests (9) and `@wasifyai/ui` studio and library tests (6): make an image,
  favourite, save, make it again with the same prompt, size and seed, favourites filter, delete asks twice.
- B3: the window self-test (`WASIFYAI_SMOKE=1`) passes with the new steps. It found that `PATCH` was missing
  from the desktop CORS methods before the end-to-end test existed; both now cover it.
