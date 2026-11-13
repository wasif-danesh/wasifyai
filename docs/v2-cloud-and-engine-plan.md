# Wasify AI v2: the cloud for teams, and the plan for the three OpenHands parts

Written 2026-11-13. This is a plan for the owner to accept or change: nothing here is built and no ADR
is accepted. It follows `docs/v2-coding-agent-guideline.md` (version 2), which advises building the
coding agent on OpenHands' engine. The owner then asked for two things:

1. A **Wasify AI Cloud** on the same idea as OpenHands' architecture picture, where a team buys a
   licence and works as a group.
2. A plan for how **Agent Server and SDK**, **Automation** and **Extensions** sit in this project.

Where a point is not known yet it is written as a spike or a decision, not as a fact.

## 1. In short

1. **Three places, one engine.** A coding session or a schedule runs on this computer, on a team's own
   server, or in Wasify AI Cloud. The same Agent Server runs in all three. The window can be connected
   to more than one place and the person picks where each session runs.
2. **A team is a tenant.** Wasify already stamps a tenant on every table, job and file. Teams, members,
   roles and seats are built on that, not beside it.
3. **The cloud layer is ours to build.** OpenHands' own cloud (sign-in, teams, licences, the
   integrations hub) is not in the open parts I read. Its screen only calls it. What we reuse in the
   cloud is the engine in a container per session, and the automation service.
4. **People sign in; nobody types a key.** The desktop connects to the cloud by signing in. The dropped
   product API keys stay dropped.
5. **A licence is seats.** A team pays per seat per month. Model costs go to the provider keys the
   team's admin enters, which the web already does per tenant.
6. **The three parts are taken as pinned packages, never forked.** Our own code sits around them in
   three new folders (section 8).
7. **Order.** The one-person desktop product first (stages C1 to C4 of the guideline), with the "place"
   seam in it from the first day. Then teams, then sessions in the cloud, then licences.

## 2. The picture

```
        Team server (the team's own machine)                 Wasify AI Cloud (ours)
        ┌──────────────────────────────────┐        ┌───────────────────────────────────────────┐
        │ Wasify API + web                 │        │ Wasify API + web                          │
        │ Agent Server (a container        │        │ Agent Server  Agent Server  Agent Server  │
        │   per session)                   │        │   (one container per session)             │
        │ Automations                      │        │ Automations        Integrations hub       │
        │ one team                         │        │ Sign-in, teams, seats, billing            │
        └──────────────▲───────────────────┘        └───────────────▲───────────────────────────┘
                       │  sign in                                   │  sign in
                       └───────────────────┬────────────────────────┘
                                           │
                     ┌─────────────────────┴───────────────────────┐
                     │ The person's computer                       │
                     │  Wasify AI (desktop window, or the web app) │
                     │      │                     │                │
                     │      ▼                     ▼                │
                     │  Agent Server  ◄───────  Automations        │
                     │  (optional part, inside the sandbox)        │
                     └─────────────────────────────────────────────┘
```

The difference from OpenHands' picture: their window talks to each Agent Server directly. Ours always
goes through the Wasify API of that place. That is where the team, the role, the approval rules, the
audit and the billing live, and it means an Agent Server is never reachable from outside.

## 3. What Wasify already has for this

| Need | What exists | Where |
|---|---|---|
| Tenants | `tenant_id` and `product_id` on every table, job, cache key and file | ADR-0011 |
| Sign-in | Auth.js in the web app (Google, GitHub, Microsoft); the web server signs a short token the API checks | ADR-0013, ADR-0030 |
| Roles | `user` and `admin` | ADR-0030 |
| Who may do what | Principals and scopes; the secret store | ADR-0092 |
| Usage | A `usage_events` row for every billable action | ADR-0011 |
| Admin screens | Models, media providers, workers; provider keys kept per tenant | ADR-0100 (stage CP11) |
| Heavy work off the API | Engine workers and a job queue | ADR-0087 |
| Deployment | A Helm chart, Postgres, Redis, object storage, the LiteLLM gateway | `deploy/helm/wasifyai` |
| Billing design | Stripe with prepaid credits, proposed and not built | ADR-0029 |

What is missing:

- **More than one tenant in one deployment.** Today the tenant is one fixed value per deployment.
- **Teams**: members, invitations, roles beyond two, a team switcher.
- **Seats and licences.**
- **Shared things**: projects, sessions others can see, team skills, team connectors, team secrets.
- **A place to run people's code**: a container per session.
- **The desktop connected to a server.** Today the desktop only uses its own engine.
- **An integrations hub**: one GitHub or Slack connection for the whole team, and an address outside
  services can call.

## 4. Wasify AI Cloud

### Teams and roles

- A **team** is a tenant. A person can be in several teams and switches between them.
- A person who signs up alone gets a team of one. Nothing else in the product changes for them.
- Roles: **owner** (billing, delete the team), **admin** (members, provider keys, connectors, what may
  be installed), **member** (works). The scopes of ADR-0092 already express this; `admin` splits in two.
- **Service accounts**: a team-owned identity for schedules and outside events, so a schedule does not
  stop when the person who made it leaves. OpenHands' automation service has the same idea.
- Invitations by email, a seat taken when the invitation is accepted, a seat freed when a member is
  removed.

### What group work means

Kept small on purpose. The unit of shared work is a project and its git history, not a shared cursor.

| Shared in a team | How |
|---|---|
| **Projects** | A project is a repository (from the team's GitHub or GitLab connection, or one Wasify keeps) plus its sessions and schedules |
| **Sessions** | Each session belongs to the member who started it and works on its own branch. Team members can open it to read. A share link shows it to someone outside, read-only |
| **Results** | A session ends as changes to review: a pull request when the project is on GitHub or GitLab, otherwise a branch to merge in the Changes tab |
| **Skills, plugins, connectors** | A team catalogue the admin manages (section 7). Members get them without setting anything up |
| **Secrets** | Team secrets in the secret store, given to sessions by name, never shown |
| **Schedules** | Owned by the team, run as a service account |
| **Audit and usage** | Admins see who ran what, and the usage per member |

Left out of v2: two people typing in the same session at once, comments on sessions, and chat between
members.

### Where sessions run in the cloud

- **One container per session**, each with its own Agent Server, its own workspace disk and nothing
  from another team. The container is the sandbox here, so the operating-system sandbox of the desktop
  plan is not needed in the cloud.
- A **sandbox service** in the Wasify API starts it, stops it when idle, wakes it when the session is
  opened again and deletes it with the session. OpenHands' workspace package has classes for Docker
  and for Kubernetes that do this; the spike decides between those and our own pod template.
- The browser never reaches a container. The Wasify API forwards the calls and the event stream after
  checking the team and the role.
- Outgoing network from a container goes through an allow list the admin can change.
- Limits per seat: sessions at once, hours per month. ADR-0088 (one job per person) is the starting
  rule.

### Models and cost

- **Model costs are the team's own.** The admin enters the team's provider keys (already built per
  tenant). The seat does not include tokens. This keeps the owner's rule of no reseller fees.
- **Our cost is the containers.** A seat includes a number of container hours; more is metered from
  `usage_events`.
- A team limit per month and per member, shown before it is reached.

### Licences

Two things can be sold, and they are separate decisions.

| | What the team gets | How it is checked |
|---|---|---|
| **Wasify AI Cloud seats** | The hosted service: sign-in, teams, sessions in containers, schedules with outside events, the integrations hub | A subscription per seat per month in Stripe. The team's row holds the plan, the seats and the paid-until date |
| **Team server licence** | The same stack on the team's own machine, one team | A signed licence file that the server reads: seats and an end date. Works offline. The server shows its state to admins |

ADR-0029 proposed prepaid credits first and subscriptions later. Seats reverse that order for teams, so
it needs a new ADR; the ledger in ADR-0029 still serves for metered container hours.

The desktop app for one person stays free and open as it is today.

### Signing in from the desktop

- The window keeps a list of **places**: "This computer" always, plus any cloud or team server the
  person signed in to.
- Signing in opens the browser, the person approves, and the desktop receives a token it keeps in the
  system key store. No key is typed or shown.
- In v2 the place is chosen **per coding session and per schedule**. Pictures, video, sound and the
  rest of the desktop keep running on this computer as today.

### The integrations hub

- One connection per service for the whole team (GitHub first, then Slack), made by an admin.
- An address outside services can call, which feeds events to Automations (section 6). This is what
  the desktop cannot have and the cloud can.
- Built on the MCP client's connections and trust levels (ADR-0070), with team scope added.

## 5. The plan for Agent Server and SDK

**What we take.** Four packages from PyPI at one pinned version: `openhands-agent-server`,
`openhands-sdk`, `openhands-tools`, `openhands-workspace`. In the cloud, the matching container image.
No fork and no copied source.

**How our code meets it.**

| Piece | What it is | Runs where |
|---|---|---|
| **The policy module** | A small Python package loaded into the Agent Server at start: our rules by pattern, the hook that refuses, the unattended profile | Inside the engine, in all three places |
| **The coding product** | `wasifyai-code`: the actions (start, send, approve, stop, undo), the client to the Agent Server, sessions as creations for search, the help files | Inside the Wasify API |
| **The place seam** | One interface, three implementations: this computer (a child program in the sandbox), a server (a container per session on one machine), the cloud (a container per session on the cluster) | Inside the Wasify API |
| **The screens** | The session view and the panel, shared by the desktop and the web | `packages/ui` |

**Rules.**

- The Wasify API never imports the SDK. It talks to the Agent Server over its API. The SDK is used only
  inside the engine's own environment (the policy module, automation scripts).
- The Agent Server's own session key is a secret between our API and the engine. People never see it.
- One version pin in one file, read by the desktop installer, the container build and the tests.
- Types for the events we show are generated from the Agent Server's API description at the pinned
  version, so a change shows up as a failing build, not as a broken screen.
- Upgrades are their own small stage, about monthly: move the pin, run the endpoint tests and the
  coding evaluation, read their change notes. We never follow their main branch.
- When we need a change in the engine, we propose it to them. Until it lands, the need is met in our
  module or not at all. We never patch their packages.

**What we expect to ask them for**: an "ask" answer for hooks (today only allow and deny), and passing
an outside agent's permission requests to the app instead of approving them.

## 6. The plan for Automation

**What we take.** The `openhands-automation` package at a pinned version that matches the engine's.

| Place | How it runs | Triggers |
|---|---|---|
| This computer | In the same optional part as the engine, with a SQLite file, one person | Schedules only |
| Team server | One instance beside the API, with the server's Postgres, one team | Schedules, and outside events if the server has a public address |
| Wasify AI Cloud | Its own deployment with Postgres and object storage; it already supports several workers | Schedules and outside events through the integrations hub |

**The open point: identity.** In its team mode the service checks every call by asking OpenHands' own
cloud who the caller is (`GET /api/v1/users/me`, at an address that can be changed). In its local mode
there is one fixed person and one fixed team. So for many teams in our cloud there are three ways:

1. Our API answers that one call in the shape the service expects. Smallest, if the shape is stable.
2. One instance per team in local mode. Simple and wasteful.
3. Our own scheduler on our job queue for the cloud, keeping theirs on the desktop.

The spike tries the first. If it fails, the third is the fallback.

**What we add in every place**: our Scheduled screen; the unattended profile (anything that would ask
is refused and reported); a run on a copy of the project; schedules owned by a service account in a
team; limits from the seat.

**Later**: their "git sync" keeps automations as files in a repository. For a team that is a good way
to review changes to schedules. Not in the first version.

## 7. The plan for Extensions

**What it is.** A catalogue, not a program: 76 skills, 14 plugins, 9 automation templates, a list of
ready connectors, 7 "apps" (pages for their own screen) and 2 marketplace lists. About 10 MB.

**Three catalogues, one format.**

| Catalogue | What is in it | Who manages it |
|---|---|---|
| **OpenHands' public one** | Taken as it is, pinned, read from disk. Most of it is for developers on GitHub, so we show a short chosen set first and the rest under "More" | They do; we choose what to show |
| **Wasify's own** | Skills for our people: the starters (web app, 2D game, 3D game), "use Wasify to make the pictures and sound", how to explain work to someone who is not a developer; automation templates that fit them; connectors we have tested | We do, in this repository |
| **A team's** | The team's own skills, plugins and templates, kept in a repository the admin registers | The team's admin |

**Rules.**

- We keep their formats unchanged (Agent Skills, their plugin layout, their catalogue files), so a
  skill written for OpenHands or Claude Code works here.
- A skill is text: it is outside content until the workspace or the team trusts it. A plugin runs code:
  installing one is an approval, and in the cloud it runs only inside the session's container.
- A team's admin can limit what members may install to the team catalogue and a chosen list.
- Their "apps" need their screen. They are left out of v2.
- Catalogues are read from disk or a registered repository at a pinned version. Nothing is fetched at
  run time behind the person's back.

## 8. Where it lives in the repository

| Folder | New or existing | Holds |
|---|---|---|
| `services/coding-engine/` | new | The version pins, the policy module, the container build for server and cloud, the manifest for the desktop optional part |
| `products/wasifyai-code/` | new | The coding product: actions, the Agent Server client, the place seam, sessions as creations |
| `extensions/` | new | Wasify's own catalogue in the OpenHands format, and the chosen list from theirs |
| `packages/ui/src/code/` | new | Session view, Changes, Files, Terminal, Preview, Scheduled, the places list |
| `services/api/` | existing | Teams, members, seats, the sandbox service, the forwarding of engine calls, the integrations hub |
| `apps/web/` | existing | Team admin screens, billing, invitations |
| `apps/desktop/` | existing | Sign-in to a place, the terminal and the preview in the Rust shell |
| `deploy/helm/wasifyai/` | existing | The automation deployment, the session containers, network rules |

## 9. Stages

These come after or beside the guideline's stages (C0 to C10). Each has a gate.

| Stage | What is built | Gate |
|---|---|---|
| **WC0 Spikes** | The Agent Server image with our module in a container, driven through a forwarding route. A container per session on the local test cluster. Automation on Postgres with our identity (way 1 of section 6). A Stripe subscription with seats in test mode | A go or no-go for each |
| **C1 to C4** (guideline) | The one-person desktop product, with the place seam in it and only "This computer" behind it | As in the guideline |
| **WC1 Teams** | Several tenants in one deployment, membership, invitations, the three roles, the team switcher, service accounts | Two teams on one deployment cannot see anything of each other in a hostile test |
| **WC2 Sessions in the cloud** | The sandbox service, forwarding, workspace disks, idle stop, the coding screens in the web app | A session survives its container being stopped and started. No container can reach another |
| **WC3 Group work** | Team projects, sessions others can read, share links, pull requests through the GitHub connection, team secrets, team catalogue, audit | Two members work on one project in separate sessions and both results merge |
| **WC4 Places in the desktop** | Sign-in to a cloud or a team server, the places list, the place chosen per session | A session started on the desktop runs in the cloud and its changes show in the same Changes tab |
| **WC5 Automations for teams** | The automation deployment, schedules run by a service account, outside events from GitHub and Slack | A nightly schedule and a "new issue" event each run for a week without a missed or doubled run |
| **WC6 Seats and billing** | Subscription per seat, container hours metered, limits, the billing screen | A team can buy, add and remove seats; a team over its limit is stopped with a clear message, never billed by surprise |
| **WC7 Team server** | The stack packaged for a team's own machine, the licence file | A fresh machine reaches a working team from the documents alone |
| **WC8 Release gate** | Isolation tests between teams, load, the real cost per seat measured | The measured cost sets the seat price |

## 10. What it costs and what can go wrong

| Risk | What reduces it |
|---|---|
| Running strangers' code on our servers | A container per session, no shared engine between teams, the network allow list, the isolation gate in WC1 and WC2 |
| Container cost eats the seat price | Idle stop, hours per seat, the measured cost in WC8 before a price is set |
| The automation service does not accept our identities | Tried first in WC0; the fallback is our own scheduler for the cloud |
| OpenHands changes its engine API | The pin, generated types, endpoint tests, upgrades as their own stage |
| Teams is a large change to a product built for one person | A team of one is the default, so the single-person paths do not change |
| A paid service has duties the free desktop does not | Terms, a privacy statement, tax and support are the owner's decisions before WC6 (the v1 rule of no terms was for the free desktop) |
| The scope is very large for one owner | Nothing in WC1 onward starts before C1 to C4 ship; each stage ships alone |

## 11. Decisions for the owner

1. **Three places with one engine**, and every call through the Wasify API of that place?
2. **A team is a tenant**, a lone person is a team of one?
3. **Roles**: owner, admin, member, plus service accounts?
4. **Group work as in section 4** (projects, readable sessions, pull requests; no live co-editing)?
5. **Seats per month** for the cloud, with model costs on the team's own provider keys?
6. **A team server licence** as a second thing to sell, or cloud only at first?
7. **Is the team server's code open** like the desktop, or kept closed?
8. **The place chosen per coding session and schedule only**, the rest of the desktop staying local?
9. **The three parts as pinned packages, never forked**, with the folders of section 8?
10. **Extensions**: their catalogue shown as a chosen short list, our own beside it, a team's on top?
11. **The order**: one-person desktop first (C1 to C4), then WC1 onward?
12. **May WC0 start** together with C0? Both live outside the repository and add nothing to the app.

## 12. Sources

- The owner's picture of OpenHands' architecture.
- OpenHands' screen (`~/Projects/OpenHands`, commit `754abee4f`): `src/api/backend-registry` (a backend
  is local or cloud, with a key or a cookie), `src/api/cloud` (organisations, members, service
  accounts, licence state, sandboxes), `helm/`, `docs/SELF_HOSTING.md`.
- The installed packages: `openhands/agent_server` (session keys, the per-session Docker runtime),
  `openhands/workspace` (Docker, Kubernetes and remote workspaces), `openhands/automation` (`auth.py`,
  `models.py`, `scheduler.py`, the local and cloud backends).
- `@openhands/extensions` 0.42.0 as installed in the clone.
- Wasify: ADR-0011, 0013, 0029, 0030, 0087, 0088, 0092, 0100; `principal.py`; `deploy/helm`.
