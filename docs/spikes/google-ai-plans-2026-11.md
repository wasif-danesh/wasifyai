# What a Google AI Pro or Ultra subscription gives, and what Wasify AI can use (read 2026-11-24)

The owner, 2026-11-24: "You need to research about google pro and ultra subscription and identify what users get.
Only then we will know what to implement in our app." Written for ADR-0110 (chat on the person's own plan).

**Decided, the owner, 2026-11-24:** "no gemini or antigravity is needed. Only claude and chatgpt subscription in the
chat for now." ADR-0110 now covers Claude Code and Codex only; nothing Google is built for it.

Google's own pages were read on 2026-11-24 (listed at the end). Prices on Google's plan page were shown for
Australia; the US prices come from other sites and are marked so. Google gives no numbers for most limits.

## The plans

| | Google AI Plus | Google AI Pro | Google AI Ultra |
|---|---|---|---|
| Price (US, other sites) | $4.99 a month | $19.99 a month | $99.99 (5x) or $199.99 (20x) a month |
| Price (Google's page, Australia) | A$7.99 | A$32.99 | from A$149.99; A$329.99 for 20x |
| Gemini app | 2x the free limits; Gemini 4 Hydrogen | 4x the free limits; Gemini 4 Neon and Hydrogen; Deep Research; a 1 million token context | Up to 20x Pro's limits; first access to new features (Tasks in Gemini); Deep Research |
| Video (Google Flow, Veo) | 200 Flow credits | 1,000 Flow credits; a limited trial of Veo 3.1 Lite | 10,000 or 25,000 Flow credits; Veo 3.1 |
| Antigravity (Google's coding agent and its CLI, `agy`) | A quota refreshed weekly | A quota refreshed every five hours, up to a weekly limit | The highest quota, every five hours, the highest weekly limit |
| Developer credits (Google Cloud) | None named | **$10 a month** | **$100 a month** |
| Also | Gemini Notebook, Gemini in Gmail and Vids, 400 GB storage | Gemini in Gmail and Docs, Google Home Premium, YouTube Premium Lite, 5 TB storage | Project Genie, Google Home Premium Advanced, YouTube Premium family, 20 TB or more |

Antigravity's quotas have no published numbers: Google says they "are primarily determined by available capacity".
A Pro or Ultra subscriber can buy AI credits for use beyond the quota. Workspace accounts get none of the Antigravity
plans.

## What another app may use, in Google's words

1. **Gemini CLI no longer serves Pro, Ultra or free users.** Google's maintainers, 2026-05-19: "On June 18, 2026,
   Gemini CLI will stop serving requests for Google AI Pro and Ultra, as well as those using it free of charge.
   These tiers are now supported via Antigravity CLI." Gemini CLI stays only for Gemini Code Assist Standard or
   Enterprise, Google Cloud, and "paid Gemini ... API keys". **So Gemini CLI cannot carry a Pro or Ultra plan.**
2. **Antigravity may not be wrapped by another app on a consumer plan.** Antigravity's FAQ:
   - "Using third-party software, tools, or services to access Antigravity is a violation of our Terms of Service
     ... Such actions can result in suspension or termination of your account. To use a third-party coding agent
     with Gemini, we recommend using a Gemini Enterprise or Google AI Studio API key."
   - "Antigravity CLI headless mode (`agy -p`) is intended for direct scripting and CI workflows. Wrapping `agy`
     inside third-party coding agents or applications ... is not supported under consumer plans."
   A forum answer of 2026-09-15 that called this "fully supported" was not from a person marked as Google staff, and
   the FAQ says otherwise. **So Wasify AI must not start `agy` on a person's Pro or Ultra login.**
3. **The plan's developer credits pay for a Gemini API key, which any app may use.** Google, 2026-01-27: "$10 per
   month in Google Cloud credits for Google AI Pro subscribers and $100 per month for Google AI Ultra subscribers
   ... you can use the credits towards Gemini API". Google, 2026-11-13: the credits are claimed inside Google AI
   Studio, which can "Attach paid-tier API keys upon credit redemption". The rules:
   - each month's credit is valid for 12 months and rolls over;
   - "Using the Gemini API with Cloud billing requires a $5 minimum prepayment and balance in order to draw down
     promotional credits";
   - only the plan's primary subscriber can use them;
   - a Google Developer Program profile is needed (AI Studio makes one when the credits are claimed).
4. **Flow credits, Veo in Flow, Deep Research, Notebook and the Gemini app's own limits** are for Google's own apps.
   No page offers them to another app.

## What this means for Wasify AI

- **Google's plan reaches Wasify AI only as a Gemini API key paid by the plan's credits.** No program, no sign-in of
  Google's inside Wasify AI. This is the route Google itself recommends.
- **Wasify AI already takes a Gemini API key** (Settings › Cloud keys; `own_keys.py`, the Google Gemini vendor of
  ADR-0100). What is missing is the way there: a line and steps for a Pro or Ultra subscriber ("Use your Google AI
  plan's monthly credits": claim them in AI Studio, pay the $5 prepayment, make the key, paste it), and the models
  that key lists.
- **What the credits buy, roughly:** at Gemini 3.8 Flash's price in our catalogue ($0.75 in and $3.75 out per million
  tokens), $10 is about 2.6 million words out, or many thousands of chat turns. Pro's $10 covers a normal person's
  chat; Ultra's $100 covers heavy use.
- **ADR-0110 drops Google** (the owner, above): Gemini CLI no longer serves the plans and Antigravity is forbidden.
  A guided key step for the credits is possible later; it is not planned.
- **Claude and ChatGPT were not read again here.** Their providers' rules (ADR-0107, read 2026-11-15) should get the
  same reading before ADR-0110 is accepted, since rules changed several times in 2026.

## Pages read

- Google AI plans: https://gemini.google/subscriptions/
- Developer Program benefits for Pro and Ultra (2026-01-27):
  https://blog.google/innovation-and-ai/technology/developers-tools/gdp-premium-ai-pro-ultra/
- Claiming the credits in AI Studio (2026-11-13):
  https://blog.google/innovation-and-ai/technology/developers-tools/google-cloud-credits-gdp-ai-studio/
- Gemini CLI to Antigravity CLI (2026-05-19): https://github.com/google-gemini/gemini-cli/discussions/27274
- Antigravity plans: https://antigravity.google/docs/plans/
- Antigravity FAQ: https://antigravity.google/docs/faq/
- Antigravity MCP: https://antigravity.google/docs/mcp/
- Antigravity CLI headless mode: https://antigravity.google/docs/cli/headless/
- The forum answer: https://discuss.ai.google.dev/t/is-external-orchestration-of-antigravity-cli-headless-mode-supported-with-account-based-usage/183051
- US prices (not Google's): https://planlimits.org/compare/google-ai-pro-vs-ultra/ and https://www.lilachbullock.com/google-ai-ultra/
