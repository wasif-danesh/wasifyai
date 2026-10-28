# ADR-0092: Principals, scopes and the secret store (the seams every agent surface needs)

- **Status:** Proposed (stages F3 and F4 built 2026-10-27). API keys (stage K1), first planned here too, were dropped
  by the owner on 2026-10-28 and taken out of this ADR.
- **Date:** 2026-10-27
- **Asked by:** the owner, 2026-10-27: "Complete the F3 and F4" of `docs/improvement-plan-2026-10-27.md`.
- **Depends on:** ADR-0011 (an identity on every request), ADR-0030 (roles), ADR-0056 (the desktop profile and its
  per-launch secret), ADR-0068 (the action catalogue: `origin`, audit, approvals), ADR-0069 (MCP server: connections),
  ADR-0070 decision 7 (secrets in the OS keychain), ADR-0083 (web search keys), ADR-0025 (`SecretBox`).

## Context

`Identity(tenant_id, user_id, role)` came from one HS256 token whose subject is a sign-in provider or `desktop:local`.
There was no notion of a **kind of caller** (a person in the window or an MCP connection), no **scopes**,
and no second credential type. The executor already carried `origin` (`window`, `assistant`, `mcp:<connection>`), so
the seam existed on the action side but not on the request side. Keys were encrypted with `SecretBox` (Fernet) under
`MEDIA_SECRETS_KEY` on the web and a `secrets.key` file on the desktop; there was no interface, no keychain, and the
Hugging Face token was read from the environment only. The MCP server (M1) and the MCP client (C1) need both seams.

## Decision

1. **A `Principal` at the request edge.** `Principal(kind, tenant_id, user_id, role, scopes, origin, connection_id)`
   with `kind` in `person` or `connection`. `Identity` stays as the tenant-and-user pair product code works
   with (`principal.identity`); nothing below the request edge changes. A person has every scope their role allows
   (`admin` only with the admin role); a connection has the scopes it was given and acts **as the person who
   made it** (the audit and usage rows carry that person's `user_id` and the credential's `origin`).
2. **Scopes are the catalogue's groups plus `read`:** `read`, `make`, `library`, `notebooks`, `voices`, `models`,
   `admin`. An action needs its domain's group when the domain has one (`library.*` → `library`, `notebook.*` →
   `notebooks`, `voice.*` → `voices`, `models.*` → `models`); otherwise `read` for a read and `make` for the rest
   (`scope_of` in the SDK). The executor refuses an action outside a principal's scopes with `not_offered` and one
   sentence; a route with `require_scope(...)` answers 403 with the same sentence; the admin area needs the admin
   role **and** the `admin` scope. A person is never refused by scope: the window behaves as before.
3. **One `get_principal` that dispatches on the credential.** A bearer that starts with a registered prefix goes to
   that verifier (`app.state.credential_verifiers`, by prefix; none is registered yet, and a connection secret of the
   MCP server would be one); anything else is a person's HS256 token as before. A credential nobody accepts is a 401
   without a hint. `origin` stays `window`, `assistant` or `mcp:<connection>`.
4. **A `SecretStore` interface:** `put(name, value)`, `get(name)`, `delete(name)`, `names()`, `ready`. Names are
   `area.thing` (`hf.token`, `web.search.exa`, later `mcp.client.<server>`, `hosted.<provider>`). It never lists
   values; logs, audit and settings rows never hold one. Implementations: `FileSecretStore` (one 0600 JSON file of
   Fernet tokens under `secrets.key`; a desktop without a native store, and tests), `KeychainSecretStore` (the
   operating system's own store on every desktop platform, with no new dependency: the macOS keychain through the
   Security framework with ctypes, the Windows Credential Manager through `advapi32` with ctypes, the Linux Secret
   Service through libsecret's `secret-tool` with the value on stdin; a value is never on a command line; the names
   in a 0600 file so listing needs no store walk), `SqlSecretStore` (a `secrets` table, Fernet under `MEDIA_SECRETS_KEY`;
   Alembic 0022 on Postgres, created on first use on SQLite), `EnvSecretStore` (read-only: `WASIFYAI_SECRET_<NAME>`
   and well-known aliases such as `HF_TOKEN`, for External Secrets and a developer's shell), `LayeredSecretStore`
   (a writable store in front of read-only ones).
5. **Who owns the keychain: the engine, through each platform's own API, when the shell asks for it.** Spike S4 of
   `docs/phase4-agent-plan.md` is answered: not Python `keyring` (a dependency, and its backends make the same
   calls) and not the shell (which would need an IPC path for every secret). The shell sets
   `DESKTOP_SECRET_STORE=keychain` on every platform; the engine uses the native store when `available()` (always on
   macOS and Windows; on Linux when `secret-tool` and a session bus exist) and the encrypted file otherwise, so a
   headless Linux or a container still works. An engine started by hand or by a test keeps the file, so nothing ever
   writes a test value into a person's keychain. Keys saved inside the web
   search settings row before this ADR move into the store once (`legacy_box`), then the row holds choices only.
6. **What goes through the store now:** the web search keys (desktop and web) and the person's Hugging Face token
   (Settings > Hugging Face token on the desktop: typed once, kept in the keychain, sent only to huggingface.co, shown
   only as "saved"). Next: hosted-model keys and MCP client secrets, as their stages land. Media provider
   keys (ADR-0025) stay per binding row for now.

## Consequences

- Every surface stage (M1, C1) starts from `Principal`, `require_scope` and `SecretStore`; none touches
  identity or secrets again.
- A connection can never do more than the person who made it, and never approves for itself (ADR-0068
  decision 4 holds: `person_approved` is the window's alone).
- A 403 or a `not_offered` says which scope was missing, in words; a 401 says nothing about why.
- The native store code is ours to maintain (three small modules, about 350 lines); the one real test
  (`WASIFYAI_TEST_KEYCHAIN=1`) writes and removes an item under "Wasify AI (test)" on whichever platform runs it,
  and the Linux backend is also tested everywhere with a stand-in `secret-tool`. The Windows module was not run on a
  Windows machine yet.
- The Windows Credential Manager caps a value at 2,560 bytes (enough for any token; a file never belongs here).

## Alternatives considered

- **Scopes per action id** (fine-grained): more to explain, more to get wrong in a config file; the groups match
  what a person can say ("let it make pictures, not read my library").
- **Python `keyring`:** one more dependency (plus `secretstorage` and `jeepney` on Linux), and its backends make
  the same calls these modules make.
- **The shell as keychain owner:** right by licence boundary and process identity, but every secret would cross a
  new IPC path; the engine already runs as the app's identity and the framework grants the login keychain to it.
