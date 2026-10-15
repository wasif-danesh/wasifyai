# web

The Next.js app (App Router, React 19, strict TypeScript) that users see, and the backend-for-frontend (BFF)
in front of the API. One app serves every product (ADR-0014). The UI is built from **shadcn/ui** (Radix) with
**Tailwind CSS**, **react-hook-form** and **Zod** for forms and **TanStack Table** for data grids (ADR-0045); inside a
product the user navigates with a **side panel** (ADR-0046), and the home page keeps its cards.

![Create a song, with the side panel](../../docs/images/create.jpg)

| Page | What it is |
|---|---|
| `/` | The home page, "Wasify AI": a card per product (public) |
| `/music`, `/image`, `/video`, `/text-to-speech` | Create a song, an image, a video or speech (sign-in required). A video is made in the background: the top bar shows "Making your video…" and a notice says when it is ready |
| `/music/songs/[id]`, `/image/creations/[id]`, `/video/creations/[id]`, `/text-to-speech/creations/[id]` | One saved result: the media, its words, downloads, delete (links are signed fresh on every visit) |
| `/creations` | My creations: one library of everything the user made, newest first, as cards or a sortable table, with filters (`?show=songs\|images\|videos\|speeches`), "Load more" and a search that finds things by meaning or exact words in any language (sign-in required) |
| `/speech-to-text`, `/speech-to-text/creations/[id]` | Upload or record, choose the language, transcribe; one transcript with Copy and downloads (sign-in required) |
| `/lip-sync` | A "Coming soon" page (public, `noindex`; ADR-0044 designs it) |
| `/admin/...` | The admin area (admins only): usage, users, songs, models, media, audit log, as sortable, filterable, paged tables |

## How it fits together

```
Browser ── fetch ──► app/api/* (BFF route handlers) ──► FastAPI ──► LangGraph, Redis, Postgres, storage
   ▲                                                         
   └── pages (server components) call the API directly for reads ─┘
```

- **The browser never calls FastAPI.** `app/api/**/route.ts` forward to it through `lib/proxy.ts`,
  which validates path segments (UUIDs and product ids, not just URL-encoding them), forwards only
  `Last-Event-ID` when it is a plain number, and passes event streams through unbuffered.
- **Pages that read data are server components** (the saved-result pages, `/creations`, the admin tables): the first
  paint has the data, and an unknown item is a real 404.
- **Interaction is client components** under `components/create/`, driven by one hook.

## The song flow

`lib/song-flow.ts` is a **pure reducer**: server events in, UI state out. It has no fetch and no React,
so every behaviour is tested against recorded event sequences. `hooks/use-song-flow.ts` does the I/O
around it:

- starts a run and answers the approval (`/api/products/wasifyai-music/runs`, `/api/runs/{id}/resume`);
- **reconnects** if the stream drops mid-run, asking only for what it missed (`Last-Event-ID`);
- **re-attaches after a reload** while a run is in progress or waiting for approval (the run id is
  kept in `sessionStorage`; the server replays the events). A *finished* run is not restored: the song
  lives in My creations, and the create page opens on an empty form;
- shows an unreachable server or an API error in plain words, with Try again where retrying can help.

The event contract the UI builds against is in `products/wasifyai-music/README.md`.

## Styling

Tailwind CSS and shadcn/ui (ADR-0045); `app/tailwind.css` is the only stylesheet and has no component classes.

- **Design tokens** as OKLCH custom properties, with `light-dark()`, so dark mode follows the system with no second
  stylesheet. The theme control can override the system choice (it sets `data-theme` on `<html>`, which the `dark:`
  variant follows) and remembers that preference in the browser. `color-mix()` derives borders, tints and glows.
- **Tailwind** turns the tokens into colours (`bg-surface`, `text-muted-foreground`, `bg-primary`), fluid type steps
  (`text-step-2`) and animations; shared class strings are in `lib/styles.ts`.
- **Container queries** (the stepper and the song layout adapt to their container's width), `starting:` entrance
  animations and fluid `clamp()` sizes.
- **Motion respects `prefers-reduced-motion`.**

## Accessibility

Skip link; one `h1` per page; every control labelled; the stepper is an ordered list with `aria-current="step"`;
progress is a native `<progress>` (the visible bar is decorative); status changes and form hints are announced
through `aria-live`; focus moves to the review panel when it appears; errors use `role="alert"`; all colours
are tokens that meet contrast in both schemes.

## Commands

```bash
pnpm --filter web dev      # API_BASE_URL=http://localhost:8000 pnpm --filter web dev, with the stack up
pnpm --filter web test     # about 260 tests: reducers, hooks, components, data tables, BFF routes
pnpm --filter web build    # production build (also type-checks and lints)
```

Tests use Vitest; component tests opt in to jsdom with `// @vitest-environment jsdom`.

## Sign-in

Auth.js (ADR-0030). `AUTH_MODE=stub` (the `.env.example` default) skips sign-in: everything runs as
the dev user. `AUTH_MODE=jwt` needs `AUTH_SECRET`, `API_AUTH_SECRET` (the same value in the API) and at
least one provider and `AUTH_URL` (the public origin; without it a container builds the callback address
from `0.0.0.0` and the provider rejects it). Register one OAuth app per environment with this redirect URI:

| Provider | Id in the URI | Variables |
|---|---|---|
| Google | `google` | `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET` |
| GitHub | `github` | `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET` |
| Microsoft | `microsoft-entra-id` | `AUTH_MICROSOFT_ENTRA_ID_ID`, `_SECRET`, `_ISSUER` (`https://login.microsoftonline.com/<tenant id>/v2.0`) |

Redirect URI: `<web origin>/api/auth/callback/<id>`, e.g. `http://localhost:3000/api/auth/callback/google`.
Only configured providers appear on `/signin`. Set `ADMIN_EMAILS` (API) to make a verified address an
admin (Google's verified email, or the primary verified address on your GitHub account). Pages redirect to `/signin` without a session; `/api` routes answer 401.

## Downloads

The Download buttons point at `/api/products/wasifyai-music/songs/{id}/download/{audio|cover|video}`, not at the
storage link. Browsers ignore the `download` attribute on a link to another origin (the storage host), so
the file would open in a tab. The route is served from the app's own origin with `Content-Disposition:
attachment` and a readable name (`neon-rain.mp3`); the API looks the song up for the signed-in user only
([ADR-0034](../../docs/decisions/0034-song-downloads.md)).

- **Audio** is the MP3 with the title, lyrics and cover art written into its tag, so a music player shows the cover.
- **Cover** is the stored PNG as it is.
- **Video** is the cover as a picture with the song playing (MP4), made on the first click and kept in storage.

Playing and showing on the page still use the signed storage links.

## Admin

`/admin` (Overview with usage, Users, Songs, Models, Media, Audit log) is for users whose role is `admin`; everyone else
sees "Admins only", and the API answers `403` to the same calls. To become admin, list your verified email in
`ADMIN_EMAILS` for the API (Google's verified address, or the primary verified address of your GitHub account) and
sign in again. With `AUTH_MODE=stub` the dev user is an admin. The Admin link (in the header, and in the side panel inside a product) appears only for admins.

### Models

`/admin/models` lists the model aliases the products use and what serves each. Pick a provider, a model and (for hosted
providers) an API key, then **Test connection** (nothing is saved) or **Save**. The key box is write-only and always starts
empty. Saving a new model for the guardrail's `moderator` first runs the guardrail test cases on it and refuses the change if it
lets a must-refuse request through; this takes about half a minute. **Reset to default** undoes a change.

### Media

`/admin/media` lists each product's media capabilities (for example `wasifyai-music` `image.generate` and `music.generate`) and
what runs them. By default that is the product's own ComfyUI workflow on the local ComfyUI. Choose **Comfy Cloud / Comfy API (v2)**
or, for images, an **OpenAI-compatible image API**, enter its address and key, then **Test connection** (it checks the service
answers; it does not generate anything) or **Save**. The next job uses it. A saved key is kept when you save again for the same
backend, and is never shown. Needs `MEDIA_SECRETS_KEY` (`make setup` creates it) before a key can be saved.

## UI components and the side panel (ADR-0045, ADR-0046)

Controls and tables are shadcn/ui components in `components/ui/` (our source: edit them freely), react-hook-form with
Zod for forms and TanStack Table for grids. All styling is Tailwind utilities and these components; `app/tailwind.css` is the only stylesheet (design tokens as
CSS variables, the theme that turns them into Tailwind colours, sizes and animations, and a few base styles). There are no
component classes: shared class strings live in `lib/styles.ts`. Check keyboard use, Bengali and right-to-left text, dark and light colours, and
320 px width.

Adding a component: `pnpm dlx shadcn@latest add <name>`, then (1) the CLI writes `import { cn } from "cn"` and adds a
`cn` package, so change it to `@/lib/utils` and `pnpm remove cn`; (2) it appends light/dark colour variables to
`app/tailwind.css`, so delete those and keep our mapping; (3) run `pnpm exec biome check --write .`.

Data grids use `components/ui/data-table.tsx` (TanStack Table: sorting, a filter box, paging; a server that pages by cursor passes its own "Older" link as `footer`). The admin pages build their tables in `components/admin/tables.tsx`: a server page passes plain rows (dates already formatted) because column definitions cannot cross from a server component.

Routes are in two groups with the same URLs: `app/(product)/` (music, image, video, text-to-speech, creations) has the side
panel and top bar (`components/shell/`: panel, breadcrumb, ⌘K search over My creations, "ready" notices); `app/(site)/`
(home, sign-in, admin, coming-soon pages) keeps the plain header. A product's panel entry and views come from
`lib/products.ts`. My creations has a Cards/Table switch; `/creations?show=songs|images|videos|speeches` opens a filter.

## Not done yet

- Only GitHub sign-in has been tried with a real login; Google and Microsoft are wired the same way.
- Sharing links for songs and a public gallery are out of scope for the MVP.
