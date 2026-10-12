# ADR-0013: MVP authentication with Auth.js

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

`wasifyai-music` requires sign-in with Google and other common providers. A central identity provider is overkill for one product.

## Decision

Use Auth.js in Next.js with Google, GitHub and Microsoft. Next.js sends a signed token to FastAPI, which validates it and resolves `user_id` / `tenant_id`. Sign in with Apple deferred. When a second product needs shared sign-in, introduce a central OIDC broker (Keycloak or Authentik) without changing FastAPI's validation contract.

## Consequences

- Fast to ship, open source.
- Each Next.js app holds provider config until a broker is introduced.
