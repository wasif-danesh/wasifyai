# ADR-0030: Authentication (Auth.js sign-in, signed API tokens)

- **Status:** Accepted (2026-10-08; sign-in verified with a real GitHub login)
- **Date:** 2026-10-08
- **Builds on:** ADR-0011 (identity seam)

## Context

Every request already resolves an `Identity` (rule 8), but it is a stub user. Real users need to
sign in with Google, GitHub or Microsoft. The admin section (ADR-0025), billing (ADR-0029) and
analytics (ADR-0027) all depend on a stable, trustworthy user id. The browser never calls the API
directly (BFF), and the API must not trust anything the browser can forge.

## Decision

- **Sign-in in the web app with Auth.js v5**, JWT session cookie, no database adapter. Google,
  GitHub and Microsoft Entra ID are each enabled only when their client id and secret are set.
- **The BFF mints a short-lived API token per request.** After checking the Auth.js session, the
  route handler (or server component) signs an HS256 JWT (`iss=wasifyai-web`, `aud=wasifyai-api`, five-minute
  expiry) and sends it as `Authorization: Bearer`. Claims: `sub` = `<provider>:<account id>`,
  `email`, `email_verified`, `name`, `picture`. The shared secret (`API_AUTH_SECRET`, at least 32
  bytes) is separate from `AUTH_SECRET`. The Auth.js cookie is never forwarded. Moving to asymmetric
  keys (API holds only the public key) is a later change with no API shape impact.
- **The API owns users.** Users and identities belong to a tenant, not to a product: a person signs in
  once for every product (an exception to "every table carries `product_id`"; product data is scoped by
  `user_id`). Migration 0005 replaces the empty, product-scoped `users` placeholder from 0001.
   On a valid token it resolves or creates a row in `users` and
  `user_identities` (migration 0005) and returns `Identity(tenant_id, user_id, role)`. `user_id` is
  our own UUID, stable across providers; tenant stays the default tenant for now. No endpoint
  changes, so every existing route is protected by the same dependency.
- **Account linking is conservative.** A new provider identity joins an existing user only when
  **both** emails are verified and equal. Google reports `email_verified`; for GitHub the web app asks
  `/user/emails` at sign-in and counts only a primary, verified address (ADR-0025); Microsoft emails are
  treated as unverified. An unverified address never links, which prevents account takeover. Linking by an explicit "connect account" flow
  is future work.
- **Roles.** `users.role` is `user` or `admin`. Admin comes only from a verified email listed in
  `ADMIN_EMAILS` (a bootstrap, until the admin UI can manage roles). Removing an email does not
  demote automatically.
- **Auth mode is an env var, secure by default.** `AUTH_MODE=jwt` is the default in the API and
  the web app. `AUTH_MODE=stub` keeps the dev stub user for local work without OAuth credentials
  and for tests; it logs a warning at startup, and the staging and production overlays never set it.
  This is wiring, not a code path per environment (rule 1).
- **Failure behaviour.** Missing, malformed, expired or wrongly signed tokens get `401` with
  `WWW-Authenticate: Bearer`; the BFF returns `401` when there is no session and middleware sends
  page requests to `/signin`. A token is verified once per request; SSE streams are not
  re-verified while open (the token only has to be valid when the stream starts).
- **Separate OAuth apps per environment** (dev, staging, prod), each with its own redirect URI
  (`<origin>/api/auth/callback/<provider>`).

## Consequences

- New dependencies: `next-auth` v5 and `jose` (web), `PyJWT` (API).
- Songs and runs created under the stub user belong to a user id that no real login maps to; dev
  data from before this change is not visible after switching to `jwt` mode.
- The secret rotation story is simple: replace `API_AUTH_SECRET` on web and API together; tokens
  live five minutes.
- Email verification for non-Google providers, "connect account", sign-in rate limits and abuse
  controls come with the billing and analytics work.
