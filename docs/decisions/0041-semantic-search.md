# ADR-0041: Semantic search in My creations

- **Status:** Accepted
- **Date:** 2026-10-09

## Context

My creations (`/creations`, ADR-0040) lists every song, image and video a user made, newest first, with a
type filter. After a few dozen items, finding "that song about rain in Madrid" or "the fox in the snow" means
scrolling. People remember what a creation was *about*, not the exact words they typed, so a keyword box would
miss "rainy night in the city" for a song titled "Lluvia en Madrid".

**The whole project is multilingual** (users write prompts, titles and lyrics in many languages, and the
interface will follow), so search must work across languages: a query in Hindi should find a Spanish song
about the same thing. That ruled out English-only embeddings and made the embedder the main question, so it was
measured before this ADR was accepted (see "Evaluation").

What the platform already has:

- **pgvector** and an `rag_chunks` table (migration 0003, 768 dimensions), and a `RagService` that chunks,
  embeds and searches (ADR-0017).
- An **`embedder` alias** (`nomic-embed-text` through LiteLLM and Ollama, 768 dimensions), seeded like the other
  model aliases and editable by an admin (ADR-0025).
- A **usage event** for embedding tokens, tenancy on every row (rule 7), and per-user rate limiters.

What it does not have: a search that spans products, one that is private to a single user, and any index of
the things users make. `rag_chunks` is scoped by tenant, product and collection but has no user column, and
every product keeps its own table (`songs`, `images`, `videos`), so a cross-product search needs its own index.

## Decision

- **A platform search over a platform index.** One table, `creation_index` (migration 0011), with one row per
  creation: `tenant_id`, `product_id`, `user_id`, `kind` (`song`, `image`, `video`), `item_id`, `text` (what was
  embedded), `embedding vector(1024)`, `model` (the embedder that made it) and `created_at`; unique on
  `(tenant_id, product_id, item_id)`. It is the platform's own table, not a product's, because it serves the
  library page, which belongs to no single product. Products keep owning their items; the index holds only a copy
  of the words.
- **A multilingual embedder of its own: `bge-m3`** (MIT licence, 1024 dimensions, 8192-token context, about
  1.2 GB), behind a new alias **`creation-embedder`** (seeded like the others, ADR-0025, editable at
  `/admin/models`). The existing `embedder` alias (`nomic-embed-text`, 768 dimensions) stays for the RAG helper,
  whose table is fixed at 768 (migration 0003); moving RAG to a multilingual model needs its own migration and is
  listed under "Fix later". Documents and queries are embedded as plain text (bge-m3 needs no task prefix).
- **What is indexed is the words the user can see and remember,** not the file:
  - song: title, style tags and lyrics (section markers like `[verse]` removed);
  - image and video: the prompt that was used (the English one if the user pressed Enhance, ADR-0038).
  Text is cut at 6000 characters.
- **Search is a vector search plus an exact-word check, not a rank merge.** For the signed-in user only
  (`WHERE tenant_id = :t AND user_id = :u`):
  1. *Exact words:* every word of the query appears in the text, ignoring case (a substring test, so it needs no
     word splitting and works in every script, including Chinese and Japanese). These results come first.
  2. *Meaning:* the nearest embeddings by cosine similarity, kept only if the similarity is at least the
     **floor, 0.57** (`SEARCH_MIN_SIMILARITY`), so that "nothing found" is possible.
  The union is returned, exact matches first, then by similarity. The evaluation showed why: a short exact word
  ("Paris") gets a low similarity and would fall under the floor, while merging a loose keyword list into the
  vector ranking by rank (reciprocal rank fusion) *lowered* recall. Postgres full-text was rejected for the
  keyword half because it finds nothing in Chinese or Japanese. No approximate index (HNSW) is added: a user has
  hundreds of rows, the query filters to one user first, and an exact scan of that slice is fast and exact.
  Revisit if one user reaches tens of thousands.
- **The API returns references, the web fetches the cards.** `GET /creations/search?q=...&kind=...&limit=20`
  (kind optional, one of `song`, `image`, `video`; limit 1 to 50) answers `{results: [{kind, product_id, id,
  score, match}], query}` in rank order, where `match` is `words` or `meaning`. Cards need signed file links that
  only each product's routes make, so the web resolves the ids with the products' existing list routes, which gain
  an `ids=` filter (up to 50 ids, still scoped to the caller). The platform never reads another product's tables
  to build a card.
- **Indexing is written in two places so a creation is searchable at once and nothing is ever missed.**
  1. *Right away:* each product's `finalise` step calls `index_creation(...)` (an SDK helper) after the item is
     saved. It is best effort: an embedding failure is logged and never fails the run, and the item is simply
     picked up by (2).
  2. *Reconciliation:* a background task in the API (like the upload sweeper, ADR-0035) runs every few minutes.
     Each product registers an "index source" (`registry.add_index_source`) that lists its items for a user
     range with their text; the task embeds any item that has no row or whose `model` differs from the
     current embedder, deletes rows whose item is gone, and works through a small batch per run so it never
     competes with a render. This also **backfills** every song and image that exists today, and re-embeds
     everything if an admin changes the `creation-embedder` alias (a different model means different vectors; a
     different number of dimensions means a new migration).
  Deleting a creation removes its row in the same request (`delete_creation_index`), with the reconciler as
  the safety net.
- **Privacy.** Search and index are per user and per tenant in every query; there is no endpoint that searches
  across users. The embedder runs locally through LiteLLM. If an admin points the `creation-embedder` alias at a hosted
  service, the users' lyrics and prompts are sent to it, which the admin screen for that alias must say. The
  query text is not stored.
- **Limits and usage.** 50 searches per user per hour (the Redis limiter used for uploads and enhancing,
  ADR-0038), a query of 2 to 200 characters (1 in Chinese, Japanese and Korean), and a 5 second timeout on the embedding call. If the embedder is
  down, search falls back to the exact-word check alone and says "Showing exact word matches only." Every
  search writes a usage event `creation.searched` plus the embedding-token event the provider already writes
  (rule 9).
- **The page.** A search box at the top of My creations (`role="search"`, a clear button, a hint "Try 'rain in
  Madrid' or 'fox in snow'"). Typing waits 300 ms, searches from 2 characters, and shows a spinner; results
  replace the grid in relevance order under "N results for 'query'"; clearing the box returns the newest-first
  library. The type filter still applies (it is sent as `kind`). A search with no results says so and offers to
  clear. Items still being made or failed (videos, ADR-0037) are not indexed and never appear in results. Errors
  show a notice and leave the library as it was.

## Alternatives considered

- **Keyword filter in the browser.** Cheap, but it only finds exact words, and it needs every item loaded first
  (the page loads 12 of each kind).
- **Embed on the fly at query time.** Every item embedded on every search: seconds per query and wasteful.
- **A search engine (Meilisearch, Typesense, OpenSearch).** Good search, but a new service and datastore to run
  and secure, for a corpus pgvector already handles (rule 12 and "ask before adding a service").
- **One search route per product, merged in the browser.** Scores from different queries cannot be compared, and
  paging across three lists is fragile.
- **`nomic-embed-text` (the existing embedder) for search.** Excellent inside one language, but it failed across
  languages in the evaluation (below).
- **A hosted embeddings API.** Better multilingual quality, but private lyrics and prompts would leave the machine.

## Evaluation

Run with `uv run python services/api/evals/search/run_search_eval.py` (the stack running, both models pulled). The
corpus (`services/api/evals/search/corpus.yaml`) is synthetic and small: 60 library items (20 concepts; 2026-10-16 added three more for tracks, voices and notebooks, not yet re-measured, each as a
song, an image prompt and a video prompt in three different languages, across ten languages: English, Spanish,
French, German, Portuguese, Arabic, Chinese, Hindi, Japanese, Russian), 60 queries (40 in a language other than
the matching items', 20 in the same language, all paraphrases), 8 queries with nothing to find, and 17 single
exact words. Numbers from 2026-10-09 on the development Mac, through LiteLLM and Ollama:

| | `nomic-embed-text` | `bge-m3` |
|---|---|---|
| Dimensions | 768 | 1024 |
| Right item in the top 5 (hit@5), all 60 queries | 0.48 | **1.00** |
| Same-language queries (20) | 1.00 | 1.00 |
| Cross-language queries (40) | **0.23** | **1.00** |
| Recall@5 (how many of the 3 matching items), all queries | 0.18 | 0.99 |
| First right item's rank (MRR) | 0.46 | 1.00 |
| Hit@5 in each query language | 0.33 to 0.70 | 1.00 in all ten |
| Highest top similarity of any no-match query | 0.690 | 0.565 |
| Lowest top similarity of a matching query | 0.538 | 0.571 |
| Time to embed 60 documents / one query | 0.5 s / 14 ms | 0.9 s / 23 ms |

- `bge-m3` is chosen: it finds the right item in every language pair tried, and a floor exists that separates
  matches from no-match queries. `nomic-embed-text` is good only within one language, and no floor works for it
  (the best no-match query scores higher than most matches).
- **Postgres full-text alone** found the right item for 32% of queries (0% for Chinese and Japanese). Merging it
  with the vector ranking by rank *reduced* `bge-m3` recall@5 from 0.99 to 0.84 and the first-rank score from 1.00
  to 0.82, because common words match unrelated items. That is why the keyword half is a strict exact-word check
  that is added to the results, not merged by rank.
- **The chosen design** (exact words first, then vectors above the 0.57 floor), measured end to end:

| | Result |
|---|---|
| Sentence queries (60): right item in the top 5 / first right item's rank | 1.00 / 1.00 |
| Sentence queries: recall@5 (the floor drops some weaker cross-language matches) | 0.91 |
| Single exact words (14 that are in the library): the item is in the top 5 | 14 of 14 |
| ...of which the vector alone would have shown (similarity at or above the floor) | 7 of 14 |
| ...of which Postgres full-text would have found | 8 of 14 (none in Chinese or Japanese) |
| ...of which the exact-word check found | 14 of 14 |
| Words that are not in the library (3) and no-match sentences (8) that returned anything | 0 of 11 |

### Built and run end to end

After the feature was built, the same synthetic library was loaded as a throwaway user into the running stack
(real Postgres, the real background indexer, `bge-m3` through LiteLLM) and the 60 queries were sent to the real
`GET /creations/search`. It matches the offline numbers: right item in the top 5 for 60 of 60 queries, first-rank
score 1.00, recall@5 0.91, 0 of 8 no-match queries and 0 of 3 absent words returned anything, 14 of 14 exact words
found, a median of 27 ms per search, and 60 items indexed in 5 seconds. The cards for results loaded through each
product's list route with `ids=`. Building and running it found two things the offline test could not:

- **How the text is assembled matters.** The first version joined a song's title, style and lyrics with line
  breaks; the same words as running text scored about 0.04 higher against the same query, and two queries lost
  their best match under the 0.57 floor (hit@5 0.97). The indexed text now runs together as sentences with line
  breaks turned into spaces (`search_text`), and the index version in `SEARCH_INDEX_MODEL` (`bge-m3/v2`) is bumped
  whenever the text format or the model changes, so the background indexer re-embeds everything by itself. This
  also shows how thin the floor margin is (known issue 1 below).
- **One character can be a whole word in Chinese, Japanese and Korean** (龙 is "dragon"), so the two-character
  minimum applies only to other scripts.

## Consequences

- New: migration 0011 and its table, the `creation-embedder` alias (already added, so setup and preflight now
  expect `bge-m3` to be pulled, a 1.2 GB download), the SDK helpers (`index_creation`, `delete_creation_index`,
  `add_index_source`), the search route and the reconciler in the API, an `ids=` filter on the three product list
  routes, a search box and hook in the library page, tests with a scripted fake embedder, and the evaluation
  kept in the repository so it can be re-run when the model, the floor or the corpus changes.
- Search matches what the user **wrote**, not what the model **drew** or composed. "Red car" finds a video whose
  prompt said so, not one that happens to show a red car. Searching the content itself (an image embedding
  such as CLIP, or the music's sound) is a separate, larger decision.
- A creation edited after it was made would need re-indexing; nothing is editable today.
- More rows in the shared database: a 1024-float vector is about 4 KB, so ten thousand creations are about 40 MB.

## Known issues, to fix later

1. **The floor margin is thin.** The best no-match query scored 0.565 and the worst matching query 0.571; the floor
   is 0.57, and a change in how the text is written (see "Built and run end to end") moved scores by 0.04. The corpus is only 60 items, so the number must be re-checked on real libraries and may need to be a
   little different per language. It is a setting (`SEARCH_MIN_SIMILARITY`), not code.
2. **The exact-word check ignores accents only by luck:** `saxofon` does not find `saxofón`. Fix with the Postgres
   `unaccent` extension (or normalising both sides) when real queries show it matters.
3. **Recall is traded for precision.** The floor drops some weaker cross-language matches (recall@5 0.91 against
   0.99 without it), though the best match is always first. A second, lower floor for "also related" results could
   bring them back.
4. **The RAG helper still uses an English-only embedder** (`nomic-embed-text`, 768 dimensions, migration 0003).
   Products that use RAG will need `bge-m3` too: a migration to 1024 dimensions and a re-embed. No product uses
   RAG yet.
5. **The synthetic corpus is written by us, mostly in well-formed sentences.** Typos, slang, mixed-language
   prompts and very long lyrics are not covered. Add real (consented) examples when they exist.
6. **No search by what a picture looks like or a song sounds like,** only by the words (see Consequences).

## A rule for everything built later

**Every new feature that lets a user make or keep something must be searchable in My creations.** A new
product, or a new kind of creation in an existing product, is not finished until it has all of these:

1. text to index: a function that returns the words a person would remember it by (title, prompt, lyrics...);
2. `caps.index_creation(kind, id, text)` called when the item is saved (best effort, never fails the run);
3. `deps.unindex(...)` called when the item is deleted;
4. an `IndexSource` registered with `registry.add_index_source(product_id, factory)`, which lets the platform
   backfill existing items and remove rows whose item is gone;
5. an `ids=` filter on its list route (so search results can fetch their cards), and a card and a filter value in
   My creations (ADR-0040);
6. a new `kind` added to the search API (`CreationKind`) and the web types, with tests for each of the above and a
   row in the evaluation corpus (`services/api/evals/search/corpus.yaml`) so the quality is measured.
   (Checked on 2026-10-17: the voice product indexed `track` and `voice`, which `CreationKind` did not list, so a
   search that found one answered with an error. Both are listed now and `/creations/search` is tested with each kind
   a product can index: a kind that is indexed but not in `CreationKind` is a bug.)

The text must be words in any language: the embedder is multilingual and the keyword check works in every script.
If a creation has no words (a drawing from a sketch, an uploaded recording), index a caption the product
produces, and say so in its ADR; do not leave it out of search.

## Not in this version

Searching other people's creations or any public gallery, search by picture, filters by date or by length,
suggestions and recent searches, and highlighting the matching words in a card.
