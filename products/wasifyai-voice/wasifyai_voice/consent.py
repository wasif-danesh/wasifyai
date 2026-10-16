# SPDX-License-Identifier: Apache-2.0
"""The record kept with a cloned voice (ADR-0044's rule for voices of real people, ADR-0066): the
person who saved it said whose voice it is. Plain local use never needs more; the record travels
with the voice so a later feature (sharing, an assistant tool) can ask for it."""

from wasifyai_voice.store import now

STATEMENTS = {
    "own": "This is my own voice.",
    "permission": "I have the permission of the person whose voice this is.",
}


def record(basis: str) -> dict[str, str]:
    """The consent record for `basis` ("own" or "permission"); KeyError for anything else."""
    return {"basis": basis, "statement": STATEMENTS[basis], "accepted_at": now()}
