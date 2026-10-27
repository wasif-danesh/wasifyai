# ADR-0092: Principals, scopes and the secret store (the seams every agent surface needs)

- **Status:** Proposed (stages F3 and F4 built 2026-10-27; the API-key parts, stage K1, are to be decided here too
  and are marked **K1** below).
- **Date:** 2026-10-27
- **Asked by:** the owner, 2026-10-27: "Complete the F3 and F4" of `docs/improvement-plan-2026-10-27.md`.
- **Depends on:** ADR-0011 (an identity on every request), ADR-0030 (roles), ADR-0056 (the desktop profile and its
  per-launch secret), ADR-0068 (the action catalogue: `origin`, audit, approvals), ADR-0069 (MCP server: connections),
  ADR-0070 decision 7 (secrets in the OS keychain), ADR-0083 (web search keys), ADR-0025 (`SecretBox`).

## Context

`Identity(tenant_id, user_id, role)` came from one HS256 token whose subject is a sign-in provider or `desktop:local`.
There was no notion of a **kind of caller** (a person in the window, an MCP connection, an API key), no **scopes**,
and no second credential type. The executor already carried `origin` (`window`, `assistant`, `mcp:<connection>`), so
the seam existed on the action side but not on the request side. Keys were encrypted with `SecretBox` (Fernet) under
`MEDIA_SECRETS_KEY` on the web and a `secrets.key` file on the desktop; there was no interface, no keychain, and the
Hugging Face token was read from the environment only. The MCP server (M1), the agent (G1), API keys (K1) and the MCP
client (C1) all need both seams.

## Decision

1. **A `Principal` at the request edge.** `Principal(kind, tenant_id, user_id, role, scopes, origin, connection_id)`
   with `kind` in `person`, `connection`, `api_key`. `Identity` stays as the tenant-and-user pair product code works
   with (`principal.identity`); nothing below the request edge changes. A person has every scope their role allows
   (`admin` only with the admin role); a connection or a key has the scopes it was given and acts **as the person who
   made it** (the audit and usage rows carry that person's `user_id` and the credential's `origin`).
2. **Scopes are the catalogue's groups plus `read`:** `read`, `make`, `library`, `notebooks`, `voices`, `models`,
   `admin`. An action needs its domain's group when the domain has one (`library.*` → `library`, `notebook.*` →
   `notebooks`, `voice.*` → `voices`, `models.*` → `models`); otherwise `read` for a read and `make` for the rest
   (`scope_of` in the SDK). The executor refuses an action outside a principal's scopes with `not_offered` and one
   sentence; a route with `require_scope(...)` answers 403 with the same sentence; the admin area needs the admin
   role **and** the `admin` scope. A person is never refused by scope: the window behaves as before.
3. **One `get_principal` that dispatches on the credential.** A bearer that starts with a registered prefix goes to
   that verifier (`app.state.credential_verifiers`, by prefix: `wsk_` for API keys in K1, the connection secret for
   MCP in M1); anything else is a person's HS256 token as before. A credential nobody accepts is a 401 without a hint.
   `origin` gains `api:<key id>`; an API key is not a "surface" in the `surfaces` sense until K1 says what it is
   offered (today: everything in its scopes, with the default approval policy, so a `make` still asks).
4. **A `SecretStore` interface:** `put(name, value)`, `get(name)`, `delete(name)`, `names()`, `ready`. Names are
   `area.thing` (`hf.token`, `web.search.exa`, later `mcp.client.<server>`, `hosted.<provider>`). It never lists
   values; logs, audit and settings rows never hold one. Implementations: `FileSecretStore` (one 0600 JSON file of
   Fernet tokens under `secrets.key`; the desktop without a keychain, and tests), `KeychainSecretStore` (the macOS
   keychain through the Security framework with ctypes, no subprocess and no new dependency; the names in a 0600
   file so listing needs no keychain walk), `SqlSecretStore` (a `secrets` table, Fernet under `MEDIA_SECRETS_KEY`;
   Alembic 0022 on Postgres, created on first use on SQLite), `EnvSecretStore` (read-only: `WASIFYAI_SECRET_<NAME>`
   and well-known aliases such as `HF_TOKEN`, for External Secrets and a developer's shell), `LayeredSecretStore`
   (a writable store in front of read-only ones).
5. **Who owns the keychain: the engine, through the framework, when the shell asks for it.** Spike S4 of
   `docs/phase4-agent-plan.md` is answered: not Python `keyring` (a dependency) and not the shell (which would need an
   IPC path for every secret). The shell sets `DESKTOP_SECRET_STORE=keychain` on macOS; an engine started by hand or
   by a test keeps the file, so nothing ever writes a test value into a person's keychain. Keys saved inside the web
   search settings row before this ADR move into the store once (`legacy_box`), then the row holds choices only.
6. **What goes through the store now:** the web search keys (desktop and web) and the person's Hugging Face token
   (Settings > Hugging Face token on the desktop: typed once, kept in the keychain, sent only to huggingface.co, shown
   only as "saved"). Next: hosted-model keys, MCP client secrets and agent tokens, as their stages land. Media provider
   keys (ADR-0025) stay per binding row for now.
7. **K1 (to decide): API keys.** Format `wsk_<env>_<key id>_<secret>`; an argon2id or salted SHA-256 hash in an
   `api_keys` table with scopes from decision 2, expiry, rotation and revoke; keys call the API host directly on the
   web (`/v1` ingress) and the loopback on the desktop; no OAuth and no OpenAI-compatible chat endpoint in v1. Details in
   section 8 of the improvement plan.

## Consequences

- Every surface stage (M1, G1, K1, C1) starts from `Principal`, `require_scope` and `SecretStore`; none touches
  identity or secrets again.
- A connection or key can never do more than the person who made it, and never approves for itself (ADR-0068
  decision 4 holds: `person_approved` is the window's alone).
- A 403 or a `not_offered` says which scope was missing, in words; a 401 says nothing about why.
- The keychain code is ours to maintain (about 150 lines of ctypes); the one real test (`WASIFYAI_TEST_KEYCHAIN=1`)
  writes and removes an item under "Wasify AI (test)".
- Windows and Linux desktops keep the encrypted file until a keychain store is written for them.

## Alternatives considered

- **Scopes per action id** (fine-grained): more to explain, more to get wrong in a config file; the groups match
  what a person can say ("let it make pictures, not read my library").
- **Python `keyring`:** one more dependency, and its macOS backend does the same ctypes calls.
- **The shell as keychain owner:** right by licence boundary and process identity, but every secret would cross a
  new IPC path; the engine already runs as the app's identity and the framework grants the login keychain to it.
