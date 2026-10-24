# Train: the plan for the first day

**Desktop first, the web afterwards (owner, 2026-10-24).** Today and the next days build Train on the desktop only; the web follows
as its own stage once the desktop works, so nothing is built twice or half. What that changes in the table below is marked
"desktop only"; the pieces the web will reuse (the types in `packages/platform-sdk`, the screens in `packages/ui`, the actions)
are written so that it can.

Why: Train is the one menu item neither app has, and the part of the product a recruiter can see working end to end: pictures in,
a model that draws your character out. Decisions already made: ADR-0073 (the platform and the simplicity rules), ADR-0076 (image
LoRA from nothing but pictures), the spike `docs/spikes/training-t0.md` (T1 Go; Z-Image with mflux 9 to 12 s per step on the
Mac). Order in `docs/phase5-agent-training-video-builder-plan.md`: **T1 (platform and simple screens), then T3 (image LoRA on the
Mac), then T2 (language), then T5 (sorter)**. Today is the start of T1 with the image card as its first customer, so that the
first thing a person can do is the best demo.

## The goal for the end of the day

A person opens **Train**, picks **Make my own character or style**, drops in pictures, and sees the checks, the written captions
and three magic-word suggestions; presses Train and watches a run go through the real screens with a **fake trainer** (the
real mflux run is tomorrow); the result appears in **My models** with its card and is searchable. All of it works on the
desktop window and is a decided, tested row on the web. CI runs the same flow with the fake trainer.

## Order of work (each step ends in something that runs)

| # | Work | Where | Done when |
|---|---|---|---|
| 1 | **The data model**: datasets (a folder with items, targets, manifest, content hash), runs, model cards; store with a **SQLite side only** (the Postgres side and the object-storage files are the web stage; the store keeps the same interface as 3D's so adding it is small) | `packages/platform-sdk` (types), the new product `products/wasifyai-training` | tests on the SQLite store; a dataset round trip |
| 2 | **The picture checks and the person's word**: decode, EXIF, size, too small, near-copy, several people; the rights statement stored with the dataset; the picture moderator while safeguards are on | the product; reuse the 3D `guardrail.py` and ADR-0035's upload hardening | a bad picture is tagged in words; a refused picture is not kept |
| 3 | **Captions and magic words**: the multimodal alias writes a caption per picture (kind-dependent instruction, traits stripped for a character); three trigger-word suggestions checked against the tokenizer | the product; the alias is `text.describe_image` | the captions of a fixture set; three words, the first checked |
| 4 | **The run as a job**: `train.*` job kinds on the engine queue with progress, samples, cancel, resume; a **fake trainer** that writes a tiny adapter and sample pictures on a timer | the desktop engine only (in process, as the desktop's other components); the worker handlers and `RemoteTrainEngine` are the web stage | a run goes start, progress, samples, done; an app restart marks a run that was working as stopped, in words (resume from the last checkpoint comes with the real trainer) |
| 5 | **The actions** (ADR-0068): `dataset.*`, `train.start`, `train.status`, `train.cancel`, `train.publish`, `model.list`; `docs/contracts/actions.json` regenerated; the help files | the product's `actions.py` | the catalogue test and the parity gate pass |
| 6 | **The screens**: the Train front door with the three cards (only the image card is live today, the other two say "coming next" in words), the three steps (Add pictures, Check, Train), the progress with sample pictures, **Use it** (before and after grid), **My models** with the card | `packages/ui` (shared), the desktop page (the web page is the web stage) | the flow works in the browser pane on the desktop dev shim and in jsdom tests |
| 7 | **Searchable and safe**: every dataset and trained model is a creation kind indexed for My creations (ADR-0041); usage events `train.run` and `engine.seconds`; quota keys; one job per person (ADR-0088 pending) | the product, `index.py` | a model is found by its name and magic word |
| 8 | **Parity and docs**: the `train` row in `parity.ts` stays `soon` for the web with its accepted reason, now saying "desktop first, then the web (owner 2026-10-24)"; the desktop menu item becomes live; the ledger, an ADR note, the backlog | web, docs | `parity.test.ts` and the menu walk pass |

## What I will not do today

- No real training run (tomorrow: mflux Z-Image, then publish into ComfyUI's `loras` folder with the key rename).
- No language or sorter card (T2, T5), no Unsloth component install (it is 2.1 GB; T2).
- No rented GPU, no web training on a worker (P7).

## The web stage (after the desktop works)

The Postgres store and files in object storage, the `train.*` job kinds on the engine queue with `RemoteTrainEngine` (as 3D), the same
screens on the web with `place="service"`, a Train row that is live when a worker can train (a GPU worker; the Mac worker does it
today, the cloud GPU needs P7 and an NVIDIA trainer), usage and quotas, the one-job rule. It starts when the desktop flow is
checked for real with the mflux run.

## Day two, so the plan is visible

T3 for real: the mflux runner as a separate process speaking JSON lines, Z-Image at 9 to 12 s per step, a LoRA of a small mascot set
in under an hour, published into ComfyUI and used from Create image, the memorisation and magic-word tests, the before and after
grid for real. Then the licence read and the 9B measurement before T2.

## Decisions I need from you tomorrow morning (five minutes)

1. **Name:** the menu says Train; ADR-0073 says the front door is **Teach** with plain-word cards. I would keep **Train** in the menu
   and use the plain cards inside. OK?
2. **Base model for the first LoRA:** Z-Image (measured on this Mac) or FLUX.2 klein 4B (Apache-2.0, in the app already, 7.5 s a
   step). I would start with **klein 4B**, because it is the model Create image already uses and its licence is clear.
3. **Approve the downloads** the real run needs (the base model is already on this Mac for klein; Z-Image would be a download).
4. **The one-job-per-person rule** (ADR-0088) applies to a training run: a run takes the person's one place for its whole length.

## Risks

- Memory on the Mac: a training run holds the one memory slot (ADR-0056); the screen must say what pauses. A 16 GB Mac may not be
  able to train at all: the check says so in words.
- Captions of people's faces (the spike used none): the instruction strips identity traits; the caption grid stays editable.
- The licence headers of the Unsloth component are mixed (spike section 1): that matters for T2, not for the mflux path.
- The fake trainer must not hide a real problem: it writes real files in the real layout, and the real run is tomorrow's first
  hour.

## Check at the end of the day

`pnpm lint && pnpm typecheck && pnpm test` (the real commands, not `-r`), ruff, pyright, the whole Python suite, the Playwright menu
walk, `git add`, and one commit line.

## What was done (2026-10-24)

Steps 1 to 8 of the table above are built on the desktop with the preview trainer (details in ADR-0073, "Built (2026-10-24)"). The
product has 21 tests (stores, checks, captions, magic words, runs, safeguards and usage), the client 6, the screen 8; a browser walk
against the real engine (`Train` in the window, twelve pictures, a run to a model) worked. Left for the next day: the real mflux run
(a separate process speaking JSON lines), Use it with before and after pictures, publishing into ComfyUI with the key rename, the
tokenizer check of magic words, the 16 and 32 GB Macs.
