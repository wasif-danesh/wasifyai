# ADR-0088: One job per person across everything before go live, built so the rule can loosen

- **Status:** Accepted (owner, 2026-10-22: "a per-person limit on waiting jobs which should be 1 … before go live", and the design
  must stay flexible for a multi-user concurrent service later). **Not built yet.** No code has changed.
- **Date:** 2026-10-22
- **Depends on:** ADR-0021 (event log and queue), ADR-0047 (safeguards, quotas), ADR-0087 (engine workers: P6 usage and quotas,
  P7 the GPU host), ADR-0080 (3D) and ADR-0077 (Video Builder, which already allow one job per person)
- **Plan:** `docs/phase6-web-identical-plan.md` (P7 comes before go live; this is a go-live requirement of the same stage)

## Context

Live will have a small pool of workers: serverless GPU containers or a few rented cards (P7), and a hosted service for images
and video. A worker does one job at a time, and the queue gives jobs out in the order they arrive. With no limit, one person
who sends ten jobs makes everyone behind them wait, and on a hosted service or a rented GPU each job costs money.

Today only 3D and Video Builder hold a person to one job. Images, video, music and speech do not: a second press of Create
queues a second job. The daily limits (ADR-0047) cap the total per day, not how many are in line at once.

## Decision

1. **Before go live, a person has at most one job in the line at a time, counted across everything.** Waiting and running both
   count; a finished, failed or cancelled job does not. A person who asks for a second thing while the first is still going is
   told so in plain words and shown where their first job stands ("You already have something being made. Wait for it to
   finish, then try again.").
2. **One policy point, not many checks.** A single function decides whether a new job may enter the line, from: who is asking,
   what kind of job it is, and what that person already has in the line. Every way in (the media queue, the engine queue and
   the product job managers) asks it before queuing. The first policy is "at most N across everything, N = 1". Nothing else in
   the code may assume the number is 1.
3. **The number is a deployment setting, not a constant.** `MAX_JOBS_PER_USER` (0 means no limit; the desktop is not limited).
   Admins and the admin jobs that fetch models are exempt. It is read at the moment a job asks to enter, so changing it needs no
   release.
4. **How it is counted.** Each job in the line holds a lease for its person: a record in Redis with an expiry a little longer
   than the job's own time-out, written when the job enters the line and removed when it finishes, fails or is cancelled. A
   crashed service cannot lock someone out for ever, because the lease runs out. Counting reads the leases, not the queue, so it
   is the same for every kind of job. The lease also carries the job's kind and cost class, unused at N = 1 but there for the
   changes below.
5. **A person can always get out.** Every job a person has in the line can be cancelled, and a cancelled job frees the place at
   once. Every kind of job has a time-out. The refusal names the job that is in the way.
6. **Products keep their own rules.** 3D and Video Builder keep their one-at-a-time managers (they also protect memory on a
   machine); the policy point sits in front of them and does not replace them.

## Built so it can loosen

The owner expects the business to grow into a service where many people run many jobs at once, as the popular model-hub
platforms do. The decision above is the safe start. These are the changes it must allow without a redesign:

| Later change | What it needs | Why decision 2 to 4 allows it |
|---|---|---|
| Raise N (2, 3, 5) | change a setting | N is read at entry |
| Different N per plan (free 1, paid 3) | the policy reads the person's plan | the policy knows who is asking |
| Different N per kind (1 slow job, 3 quick ones) | the lease records the kind and cost class | leases carry kind and cost class |
| Cost-based limits (a 3D model counts 5, a sentence counts 1) | a weight on each lease | leases carry a cost class |
| Priority and fair share in the line | the line orders by who has least running, then by plan | the queue is behind one entry point |
| Credits instead of limits | the policy charges credits before entry | one place decides |
| More workers, autoscaling | add workers per kind (slow and quick pools) | independent of this rule |

None of these is built or promised. They are why the rule is one function, one setting and one kind of lease.

## Consequences

- Fairness and a bounded cost: nobody waits behind more than one job of each other person, and a stuck script cannot run up
  the bill. The longest wait is about (people ahead) x (one job).
- It is stricter than most tools: someone who wants four pictures waits for each. The daily limit and this limit together are
  the price of a small pool; raising N is the relief valve.
- One person with two tabs or two devices is blocked by their own job. A stuck job blocks its owner until it ends, times out or
  is cancelled, so Cancel and time-outs are part of the work, not extras.
- It protects the line, not the front door: many accounts still fill it. Sign-up limits and the daily quotas cover that.
- A single number across everything makes a short job (a sentence) wait behind a long one (a 3D model) for the same person. The
  per-kind change in the table is the likely first relaxation.
- It needs a real load test with several people before go live.

## Alternatives considered

- **No limit, daily quotas only.** Cheapest to build; one person can hold the line for everyone else. Rejected for live.
- **One job per kind per person** (a picture, a song and a model at once). Fairer to a person with mixed work, and allows three
  jobs for the price of one worker each. Kept as the first relaxation, not the start, because the pool is small.
- **A fixed limit in each product.** Simple, but five places to change and drift. Rejected for decision 2.
- **Full multi-user concurrency now** (priority, credits, autoscaling). The right end state if the business grows; too much to
  build and to run before there are users. The table shows the path.

## Open questions

- Which time-out applies to each kind of job, and what the person sees when one expires.
- Whether a job that waits for a worker that is not running counts, and for how long.
- The wording of the refusal for each kind of job, and whether the screens show the line position of the job in the way.
- The counted unit for the desktop's runners (ADR-0058), if a person's own computer takes jobs: probably not limited.
