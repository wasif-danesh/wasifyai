# SPDX-License-Identifier: Apache-2.0
# Adapted from SurfSense (Apache-2.0), surfsense_local/backend/shared/tokenizer.py,
# commit 622c1ded8. See ../PROVENANCE.md.
"""The one rule by which text becomes terms, for the index and the question alike.

A term the index keeps whole and a question cuts up matches nothing, and the keyword leg scores what
fraction of a question a chunk matched, so a disagreement does not merely miss: it votes. FTS5
itself is asked rather than a regex, which would have to track its case folding and diacritics.
"""

import sqlite3

# `M*` keeps a combining mark inside its word. Without it unicode61 ends a token at every mark, so
# Devanagari `स्कैनर` indexes as `स` + `नर`. Latin, digits and identifiers tokenise the same
# either way.
TOKENIZER = "unicode61 categories 'L* N* Co M*'"


def terms(text: str) -> list[str]:
    """The distinct terms FTS5 indexes for `text`, sorted.

    Distinct because coverage asks what fraction of a question a chunk matched, which a word
    repeated in the question must not inflate.
    """
    db = sqlite3.connect(":memory:")
    try:
        db.execute(f'CREATE VIRTUAL TABLE q USING fts5(body, tokenize="{TOKENIZER}")')
        db.execute("CREATE VIRTUAL TABLE v USING fts5vocab(q, row)")
        db.execute("INSERT INTO q(body) VALUES (?)", (text,))
        return [term for (term,) in db.execute("SELECT term FROM v")]
    finally:
        db.close()
