# Coding agent: Claude Haiku 5.5, measured

Written 2026-11-15 on the owner's Mac (M5 Pro, macOS 27.0), on the owner's request ("Run the tests with Claude
Haiku 5.5 to determine the capability of it"), and after it "Yes, add Haiku". The decision is ADR-0101's
amendment of 2026-11-15.

## The result

The 36 evaluation tasks (`docs/spikes/coding-eval-tasks.json`), each with a hidden check the agent never sees,
on the real coding engine in its sandbox, the model through the gateway, the key through the app's own secret
store. Haiku was run twice.

| | Haiku 5.5, run 1 | Haiku 5.5, run 2 | Sonnet 5.5 (the v1 gate) | Qwen 27B on this computer (stage C3) |
|---|---|---|---|---|
| Tasks passed | 35 of 36 | 36 of 36 | 36 of 36 | 33 of 36 |
| The six hard tasks | 5 | 6 | 6 | |
| Every change undone exactly, and brought back | 36 of 36 | 36 of 36 | 36 of 36 | |
| Time for all 36 | 15 min 22 s | 15 min 30 s | 12 min 19 s | |
| Median time a task | 19 s | 17 s | 15 s | |
| Steps taken in all | 188 | 194 | 142 | |
| Tasks in which the terminal was used | 33 | 32 | 34 | |
| Counted cost | $0.14 | $0.15 | $1.95 | none |

- **The one failure** was `hard-bug-hunt` in run 1: Haiku changed a file and said it had finished, and the
  hidden check still failed. It passed the same task in run 2.
- **It takes about a third more steps than Sonnet** for the same tasks.

## What this does not show

- **Long sessions and large projects.** These are 36 small tasks. Nothing here says how Haiku holds up over
  hours, or in a project too large to read at once.
- **The counted cost was a little low.** The runs counted a cache read at half its real price ($0.005 a
  million tokens; it is $0.01). The entry that is shipped has the provider's published prices, read on
  2026-11-15: $0.10 in, $0.50 out, $0.01 a cache read, $0.125 and $0.20 a cache write; five times each for a
  call whose prompt is over 100,000 tokens. The provider's bill is the real figure.
- **No task had a prompt over 100,000 tokens**, so the higher price was not met in a real run. It is tested
  with numbers (`test_coding_gateway.py`).
- **The window.** Haiku was run by the evaluation, not chosen in the app's own model list by a person.

## Money

The two runs and a trial of two tasks cost about 30 cents. About $6 of the $25 the owner allowed is used.

## How to run it again

```
uv run python products/wasifyai-code/evals/run_eval.py --data "<app data with the coding engine>" \
    --model claude-haiku-5-5 --app-keys --limit-usd 2 --out results.json
```
