# ADR-0100: Text on Claude Haiku 5.5 with the person's choice of vendor; media on the cheapest of Runware, WaveSpeed and fal.ai

- **Status:** Accepted (2026-11-12, by the owner). The owner's words:
  - "We will go with Haiku 5.5 in v1 for cloud option in desktop and web, although it will be better to make it
    flexible for users so they can enter their preferred vendor like Anthropic/ChatGPT/Gemini/DeepSeek/GLM."
  - "Can we have Runware, WaveSpeed, and fal.ai, but include a check to use the cheapest among the providers?"
  - The plan's nine decisions: "Yes, accept all" (every recommendation).
- **Date:** 2026-11-12
- **Plan:** `docs/cloud-v1-plan.md` (stages CP0 to CP13). The cost comparison behind it is
  `docs/spikes/provider-cost-2026-11.md`.
- **Changes:** ADR-0099, decisions 1, 2, 3 and 7 and its Consequences:
  - the two providers;
  - one OpenRouter key and one fal.ai key;
  - text on OpenRouter only;
  - the "third provider is a new ADR" line.
- **Keeps:**
  - from ADR-0099: the desktop runs local and cloud models, and the web only cloud models; tools that are not models
    stay on the web's CPU workers (decision 4); the models chosen per product (decision 5); what is not on the web
    (decision 6);
  - rule 5 (on the web every LLM call goes through LiteLLM), ADR-0041 (every creation searchable), ADR-0068 (every
    feature an action), ADR-0094 (no safeguards of our own).

## Context

ADR-0099 put text on OpenRouter and media on fal.ai. The owner then asked for the cheapest way to run both
(`docs/spikes/provider-cost-2026-11.md`, 2026-11-12):

- **Every provider is prepaid.** Google too has moved new accounts to prepaid credits. Only OpenRouter adds a fee, 5.5%
  when credits are bought.
- **No reseller sells text below the model maker's price.** Bought directly from its maker, Claude Haiku 5.5
  ($0.10 / $0.50 per million tokens up to a 100K-token prompt) costs less than GLM-5.3 Flash ($0.15 / $0.50) or
  DeepSeek V4.1 Flash ($0.30 / $1.20, half off-peak). Lower prices for those two exist only on small hosts that run
  compressed copies.
- **Media prices differ a lot by provider for the same model:**
  - Seedance 2.5 costs $0.23 per second on Runware, $0.36 on WaveSpeed and $0.46 on fal.ai.
  - fal.ai adds about 17.6% to Google's models.
  - InfiniteTalk costs $0.03 per second on WaveSpeed and $0.20 on fal.ai.
- **No one provider has every model.** Only fal.ai has the trainers, Pixal3D, Demucs and Stable Audio. Runware has
  little audio. WaveSpeed lacks MiniMax H3 Max.
- In a sample month, fal.ai alone cost $107. Picking the cheapest provider for each item cost about $65.

## Decision

1. **Text: Claude Haiku 5.5 is the default cloud model on the desktop and the web,** bought from Anthropic directly
   (no reseller fee).
2. **The person can choose another text vendor:**
   - Anthropic, OpenAI, Google (Gemini), DeepSeek and Z.ai (GLM), each with its own key and the vendor's own price;
   - OpenRouter stays as one more vendor (decision 1 of the plan).

   The catalogue lists each vendor's models. The person picks one in the picker; Haiku 5.5 is chosen until they do.
3. **On the web, the admin sets the service's vendor keys** in Admin › Models, and turns on the models people may pick.
   - Haiku 5.5 is the default alias.
   - Chat and embeddings still pass through LiteLLM (rule 5), using LiteLLM's own provider for each vendor.
4. **Media runs on Runware, WaveSpeed and fal.ai, and each job goes to the cheapest provider that can do it.**
   - **Media lines list their offers.** Each media line in the catalogue lists the providers that offer the model,
     with each provider's price for each setting (size, length, quality).
   - **The cheapest offer is picked at Make.** The app works out the job's price on every offer that:
     - has a key;
     - can do what was asked (a mask, a trained look, extend);
     - can use what the job depends on (a cloned voice or a song made earlier).

     It picks the cheapest. On a tie it picks Runware, then WaveSpeed, then fal.ai.
   - **The price shown before Make names the provider.**
5. **If the chosen provider refuses a job before running it, the next cheapest offer takes it.** "Refuses" means down,
   a bad key, or out of credit. A job the provider has taken and may have charged for is never sent again: the person
   sees the error.
6. **Things made on a provider stay with it where they must:**
   - a MiniMax cloned voice and a Mureka song speak or edit only on the provider that made them;
   - a trained look is used only on providers that can load its file.
7. **Every cloud job writes a usage event (rule 9)** with its vendor or provider and its price, so the admin sees spend
   per provider. The bills stay separate.
8. **Prices live in the catalogue with the date they were checked.** A script rereads the providers' price lists and
   writes the changes for review. Prices are never fetched while someone waits.

## Consequences

- **The code FA1 removed comes back**, reshaped. FA1 is not committed, so the last commit still holds it:
  - the WaveSpeed and Runware clients (`cloud_queues.py`), runners and testers, and their tests;
  - the Anthropic, OpenAI and Gemini text vendors.

  DeepSeek and Z.ai are new. The per-product "use" choice of one provider gives way to the cheapest pick (media) and
  the vendor choice (text).
- **Each model needs its own connection for each provider** (names and inputs differ). To keep the work in bounds, v1
  builds the cheapest offer and one fallback per model (plan decision 5). More come later as catalogue lines.
- **Haiku 5.5 behaves differently from older models**, and the text path handles it:
  - it refuses a non-default temperature (four places in the code set one) and an assistant prefill;
  - it thinks before answering by default, so effort is set per job;
  - prompts over 100K tokens cost five times as much, so Notebook keeps its context under that.
- **Anthropic has no embedding model.** Notebook and My creations search need one from another vendor on the web
  (plan decision 4).
- **Three media balances and at least one text balance to keep topped up.** All are prepaid with no fee.
- **Outages:** a media provider's outage moves jobs to the next offer where there is one. A text vendor's outage stops
  the web's chat until the admin turns on another vendor. The desktop can still use its local models.
