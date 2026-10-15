# ADR-0058: Linking the web product to a user's desktop: a runner, and an optional remote UI

- **Status:** Proposed
- **Date:** 2026-10-14
- **Depends on:** ADR-0021 (event log, queue), ADR-0030 (authentication), ADR-0032 (media backends; its limit
  "per tenant and product, not per user" is lifted here), ADR-0056. Pattern from the withdrawn ADR-0054
  (a native service that only speaks to storage through presigned URLs).

## Context

The owner needs the web app to use a user's own desktop and its local models. Unsloth does this by exposing the
whole local server through a Cloudflare **quick tunnel**. Cloudflare's own documentation says quick tunnels do
not support Server-Sent Events, are limited to 200 in-flight requests, have no uptime guarantee, and are for
testing; the URL is open to anyone who has it. Our job events are SSE (ADR-0021). The web product runs on a
home-lab cluster behind its own tunnel, with no inbound port.

## Decision

1. **Primary mechanism: a runner.** The desktop opens an **outbound** authenticated connection (WebSocket) to
   the web gateway and registers as a per-user media and text backend. Nothing on the desktop listens publicly.
2. **Jobs flow like the trainer API:** the web worker sends the job (capability, inputs) and presigned GET URLs
   for inputs and presigned PUT URLs for outputs. The desktop pulls inputs, runs the job in its slot, uploads
   outputs and reports progress using the same event envelope. No file system is shared and files never pass
   through the link.
3. **Backend binding becomes per user.** `media_bindings` gains a user scope (new migration), so one user's
   desktop is that user's backend only.
4. **Pairing:** a short code shown in the web app, entered in the desktop app (the device-authorisation flow).
   The desktop keeps a per-device token in the OS keychain; the web side can list and revoke devices.
5. **Desktop controls:** off by default; an indicator when on; local use has priority over remote jobs because
   the slot is shared; the user can pause or disconnect at any time; an allowlist of capabilities offered.
6. **Secondary mechanism, remote UI (phone or another browser opening the desktop's own library):** a **named**
   tunnel or a relay we run, never a quick tunnel in production. It exposes an allowlisted remote API (no file
   browsing, no settings, no keys), requires a signed session token, and is rate limited. The transport sits
   behind a `Link` interface; WebSocket carries the events so any transport works. Built after the runner.
7. **Security rules, for both:** URL secrecy is never a control; local provider keys never leave the device;
   every remote action is logged on both sides; tokens are short lived with refresh; the engine itself still
   binds to loopback.

## Consequences

- The web product can serve users who have capable machines without any GPU of its own, and with no inbound
  exposure of a desktop.
- A new gateway endpoint and a registry of connected runners in the web product; presence and reconnect logic.
- Offline desktops mean jobs fail fast with a typed error (or queue, by user choice).
- Cost: bandwidth for presigned transfers goes through the web product's object storage.

## Alternatives considered

- **Quick tunnel per desktop (Unsloth's approach):** rejected for the reasons above.
- **Named Cloudflare tunnel per user:** needs an account, a domain and automation; kept for the remote UI.
- **Tailscale or WireGuard:** good for the owner, too much friction for users.
