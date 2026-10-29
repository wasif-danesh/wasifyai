# ADR-0033: The studio home page and product-scoped URLs

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The web app opened straight on the create-a-song page. The platform is meant to host several products
(music now, image and video next), so the front door should be a studio that offers them, with each
product in its own area.

## Decision

- **`/` is the studio home, "WasifyAI Studio"**: one card per product, from a single list
  (`lib/products.ts`). Music is live; image and video are marked "Coming soon" on their cards and
  link to plain "Coming soon" pages.
- **Public and protected pages.** The home page, `/image`, `/video` and `/signin` need no session and
  are indexable (the coming-soon pages carry `noindex` until real, ADR-0026). Everything else needs a
  session. A signed-out visitor who opens `/music` is sent to sign-in with a return address and a
  reason ("Sign in to create music and keep your songs."), then lands on `/music`. The header shows a
  **Sign in** button to visitors and "My songs" only to signed-in users.
- **Product-scoped URLs.** `/music` is the create page, `/music/songs` the user's songs and
  `/music/songs/{id}` one song; image and video get `/image/...` and `/video/...` the same way. The
  old `/songs` and `/songs/{id}` redirect permanently so links and bookmarks keep working. API
  routes (`/api/products/{product}/...`) are unchanged: page URLs and API URLs are separate.
- **Honest copy.** No claim the platform cannot keep (nothing "unlimited"); each card says what the
  product really does.
- **Artwork is our own vector art** in the theme's colours, not photographs, so there is nothing
  heavy to load. Real examples can replace it later, with the creators' consent.
- **A cross-product "My creations" page** waits until a second product is live.

## Consequences

- Adding a product is one entry in `lib/products.ts` plus its own area; the middleware's public list
  (`lib/auth-mode.ts`) says which pages are open.
- Sign-in is asked for when a visitor opens the product, not when they press the final button; a
  typed idea is not kept across sign-in (a draft saved in the browser could be added later).
- The README screenshots and the cluster smoke test use the new `/music/...` URLs.
