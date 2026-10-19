# ADR-0076: Make my own character or style: image LoRA from nothing but pictures

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. **Revised the same day** after the owner's
  clarifications (see ADR-0073): the person only uploads images, and the app writes the descriptions and suggests the
  trigger word. The first draft of the "diffusion model beyond LoRA" ADR is folded in here as the last section.
- **Date:** 2026-10-18
- **Depends on:** ADR-0073 (training platform and the simplicity rules), ADR-0059 (ComfyUI sidecar, LoRA chain),
  ADR-0062 (reuse matrix), ADR-0056 (inventory from `wasifyai-art`), ADR-0038 (prompt and caption aids), ADR-0035
  (upload hardening), ADR-0047, ADR-0044 (a person's word about a picture), ADR-0012 (licences).
- **Re-opens and replaces:** ADR-0054 (withdrawn) for the desktop.
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages T3 and T3b.

## Context

People want a LoRA of **their** character, mascot, pet, product, face or art style, then use it in Create image
(`lora_chain` is built, ADR-0059). The owner's rule: **the person uploads pictures and nothing else**; the app writes
the captions and suggests the trigger word.

What the training engines expect, which is what we must hide:

- **Every trainer wants a caption per image** and a **trigger word** in it. Unsloth Studio's diffusion trainer reads a
  sidecar `.txt` per image or a `metadata.jsonl`, and **skips images without a caption** (read 2026-10-18).
  Ostris AI Toolkit's format is the same (image plus same-named `.txt`, a `[trigger]` token replaced from the config).
  Neither writes captions for you; both train on whatever you give them.
- Where each engine runs (ADR-0073): **mflux** on the Mac (measured: FLUX.2 klein base 4B at about 7.5 s per step;
  the trigger word binds only with the **full timestep range**, at 150 to 300 steps; the adapter needs **one key
  rename** for ComfyUI; mflux lists Z-Image and FLUX.2 as trainable and FLUX.1 as not). **Unsloth's diffusion
  trainer** (SDXL, FLUX.1, Qwen-Image, Z-Image, Krea 2, FLUX.2 klein and dev) picks CUDA, then Intel XPU, then CPU:
  **no Mac path**. **AI Toolkit** is NVIDIA-only with an experimental Mac script that did not converge (ADR-0054).
- The platform has a multimodal alias (`text.describe_image`, ADR-0038), so captions need no new model. Captions are
  English because the text encoders are English-trained: a recorded limit.
- FLUX.1-dev weights are non-commercial and so is anything trained on them (ADR-0012). klein 4B is Apache-2.0.

## Decision

1. **One card, "Make my own character or style", three steps, then Use it** (ADR-0073 decision 5):
   1. **Add pictures.** Drag in 10 to 40 pictures (more is allowed; the screen says "15 to 25 good ones is plenty").
      Nothing else is asked yet. The app **checks each picture as it arrives** and marks it in place with a plain
      tag: *Good*, *Too small*, *Blurry*, *Looks like a copy of another*, *Several people* (for a character).
      Bad ones are suggested for removal with one click. Upload hardening is ADR-0035's (decode, EXIF rotate, strip
      metadata, size cap).
   2. **Check.** Four short things on one screen, all with sensible defaults:
      - **What is it?** *A character, pet, person or thing* / *A style* / *An idea or object*. (The kind sets the
        caption instructions and the preset.)
      - **A name for it** (optional, one word: "Marlo"), used in the library and to build the magic word.
      - **The magic word.** The app **suggests three** (decision 3); the first is selected; "type my own" and "choose
        for me" are there. A line explains it: *"When you write this word in a prompt, the app draws your Marlo."*
      - **Whose is it?** The statement of ADR-0073 decision 7 (*"It's me" / "I have permission" / "It's a drawing, a
        character or an animal" / "It's my own artwork"*), required for a person's face.
      Then **the descriptions**: the app writes a caption for every picture (decision 2) and shows them as a grid of
      thumbnails with text under each; the person can read them, edit any, or press **Describe again** on one or all.
      One sentence of estimate sits below: *"About 25 minutes. Chat and image making pause while it learns."*
   3. **Train.** One button. Progress, and **a new sample picture every few minutes** made with the magic word, so the
      person watches it learn; stop and resume.
   Then **Use it**: a grid of eight test pictures made **with** the LoRA and, below, the same eight **without**; a box to
      type your own test; **"Looks right"** (adds it to Create image as a chip named "Marlo" that inserts the magic word
      for you) or **"Not quite yet"** (trains for more steps from where it stopped, or offers to change the pictures).
2. **The app writes the descriptions.** The multimodal alias (the person's chosen vision model on the desktop)
   describes each picture with an instruction set by the kind:
   - *Character:* what is in the scene, clothing, pose, setting, light and camera angle, **not** the identity features
     that the LoRA should learn (the face, the colours that define the mascot).
   - *Style:* what is shown (the subject and composition), **not** the style.
   - *Idea or object:* the object in each context.
   Every caption starts with **the magic word and a class noun** (*"zorvik dog, running on a beach at sunset ..."*); the
   class noun is the most common noun across the first pass ("dog", "woman", "robot", "painting"), checked with the
   person only if the answers disagree. Captions are normalised to English, 1 to 3 sentences, no brand or real
   names. The writing is a background job with progress (rule 6); a picture the model cannot describe is flagged,
   not skipped silently. When the engine wants files, the app writes the `.txt` sidecars and a `metadata.jsonl`
   itself; the person never sees a dataset folder.
3. **The app suggests the magic word.** From the name ("Marlo") and the class noun, build candidates that are
   **rare, short, pronounceable and carry no prior meaning**: a made-up token of 5 to 8 letters, optionally with the
   name's initials ("mrlzo", "zorvik"). A candidate is **rejected** if it is a dictionary word in any of the common
   languages we ship a word list for, if it tokenises as a single common token or as common subword pieces in the
   **text encoder's own tokenizer** of the chosen base model (the check uses the real tokenizer), if it collides
   with the magic word of a LoRA already in the library, or if it matches a blocklist. The three that pass are
   offered. The word is stored with the model, put in every caption, and **inserted automatically** when the LoRA is
   chosen in Create image (the person can turn that off). In the UI it is called **"magic word"**; "trigger word"
   appears in Advanced.
4. **The app chooses the rest.** Family and engine (decision 5), resolution, steps (150 to 300 at the measured full
   timestep range for klein 4B), rank, learning rate and the evaluation prompts, from the descriptor and the measured
   preset for this machine; the person sees "Quick" or "Better" and the time. The timestep range is **always the full
   range** by default and is locked in Advanced behind a warning (it is what makes the word bind).
5. **Engines (ADR-0073):** the **Mac**: **mflux** with the measured defaults (FLUX.2 klein base 4B first, Z-Image after
   its spike); **NVIDIA (own or rented)**: **Unsloth's diffusion trainer** through the component for the families it
   lists, with **AI Toolkit** as an alternative engine added by descriptor only if the spike finds a family or quality
   it does better. FLUX.1-dev is **not offered** (non-commercial). If nothing can run here (an Intel Mac, no GPU),
   the screen offers the rented-GPU tier or explains.
6. **Evaluation, always shown, in pictures:** the with-and-without grid at fixed seeds; the **magic-word test** (the
   same prompt with and without the word: a LoRA that looks the same either way did not bind; the page says "It
   doesn't respond to its magic word yet: train a bit more"); and the **memorisation test** (a training picture's
   caption at the same seed: a near copy is flagged "This may reproduce your own pictures"). Results are stored with
   the card.
7. **Publishing.** The adapter is written into ComfyUI's `loras` folder with the key rename applied by the app
   (`diffusion_model.*` naming), added to the catalogue with `source: trained`, family, magic word, a preview and the
   model card with the person's statements. A LoRA of a real person's likeness carries a label ("a person's likeness,
   made with their permission") that stays in the recipe of images made with it.
8. **Time and memory** are shown from measurement only. klein 4B at about 7.5 s per step means 150 to 300 steps is
   roughly 19 to 38 minutes on the measured Mac; image generation is unavailable meanwhile (one slot).
9. **Advanced** (collapsed, "For experts"): the engine, rank, steps, learning rate, resolution, timestep range, batch,
   the dataset folder and captions as files, the magic word as text, a saved configuration (YAML), and the loss curve.

## Beyond LoRA: training a whole diffusion model

Changing a model's base weights (a full fine-tune, a DreamBooth of the whole network, domain training, distillation,
merging) is **not offered on the person's computer**. A full fine-tune of a multi-billion-parameter diffusion
transformer needs several times the memory of a LoRA (AI Toolkit's own FLUX guidance starts at a 24 GB NVIDIA card
**for a LoRA**), produces a multi-gigabyte checkpoint, inherits the base's licence, and can drop the safeguards of the
model it came from. For almost every goal a LoRA is the right size. It is offered, later, **only on the remote tiers**
(the person's NVIDIA machine or a rented GPU) behind a questionnaire that sends most people back to the LoRA ("How many
pictures? Under about 200: use a LoRA"), with the consent and licence rules above, a cost cap, an evaluation that
includes a regression grid on prompts the base did well, and the label "not covered by the safeguards of its base
model". Whether AI Toolkit or Unsloth's DiT trainer can do a full fine-tune per family is **not verified**; stage T4
checks it. It is the lowest priority and can be dropped without cost.

## Consequences

- A person makes a LoRA of their own character in about half an hour on a Mac without leaving the app, and without
  seeing a caption, a dataset folder or a hyper-parameter; the same screen drives an NVIDIA box or a rented GPU.
- We own two things no engine provides: **captions** and **the magic word**. Both are small, testable, and make the
  difference for non-technical users.
- Two engines per tier, one dataset format, one result format: the descriptor hides the difference.
- The consent and licence rules make some requests slower or impossible (real-person photos with the safeguards on;
  non-commercial families). That is intended.
- Captions in English only is a visible limit; the caption grid is where a person corrects them.

## Alternatives considered

- **Unsloth Studio's diffusion page, restyled.** Needs captions made by hand, has no Mac path, and shows every setting.
- **AI Toolkit's UI.** Good for NVIDIA people, again captions and settings by hand; no Mac path.
- **Kohya, SimpleTuner, OneTrainer.** More NVIDIA trainers with the same shape; none better on a Mac.
- **Draw Things** (an app that trains FLUX LoRAs on macOS). A closed app, not a component we can ship.
- **Train a LoRA inside ComfyUI with custom nodes.** Custom nodes run arbitrary code in the engine process (ADR-0059).
- **Let the person write captions.** What every other tool does; exactly what the owner wants to remove.

## Open questions

1. How good automatic captions are, and where they hurt (faces, mascots with unusual features, styles): measured on the
   mascot and external-character sets of the `wasifyai-art` spike (T0).
2. The magic-word check against each family's tokenizer, and whether a measured "binds in N steps" test per candidate is
   worth the minutes it costs (probably not in v1).
3. Z-Image's measured recipe and time on the Mac; mflux resume after a pause.
4. Training for **edit** models (pairs of images): a different flow; later.
5. The rented-GPU path: the person's own account first (RunPod and Modal are AI Toolkit's paths).
6. Whether a LoRA of a real person should be allowed at all on the hosted web product (probably not without verification).

## Not in v1

Video LoRAs; LoRAs for edit models; training from a single picture; stacking and merging LoRAs in the trainer (the
LoRA chain stacks at generation time); sharing or selling LoRAs; collecting pictures from the web; a full diffusion
fine-tune.

## Amendment after spike T0 (2026-10-19; `docs/spikes/training-t0.md`)

- **Z-Image (base) LoRA trains with mflux 0.22.0 on the Mac:** 9 to 12 s per step when memory is free (30 s or worse when
  swap is full), 768 px, 8-bit, gradient checkpointing, rank 16, full timestep range, **39.9 GB peak footprint** (12.6 GB
  resident). Binding, quality and loading in ComfyUI are **not tested**. FLUX.2 klein base 4B stays at 7.5 s/step.
- **Automatic captions (decision 2):** about 3 s per picture with Qwen3.5-9B; scenes were described correctly but **the
  mascot's own design leaked into 5 of 6 captions**. The caption step therefore needs a **trait-stripping pass** (remove
  what the LoRA should learn) before captions are used; the editable caption grid stays.
- **Magic-word check (decision 3):** works; both text encoders use the same Qwen3 tokenizer, so one check serves both.
- **Verdict: T3 Go in principle.** Not measured: the NVIDIA paths (Unsloth diffusion, AI Toolkit) and rented GPUs.
