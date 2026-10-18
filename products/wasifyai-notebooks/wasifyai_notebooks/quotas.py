# SPDX-License-Identifier: Apache-2.0
"""What one person may hold in their notebooks (ADR-0047: quotas apply only while the safeguards are
on, so the desktop, where they are off, has none).

The limits are in the product's configuration (`quotas:` in `product.yaml`):

    notebooks_per_user      how many notebooks
    sources_per_notebook    how many sources in one notebook
    bytes_per_user          the size of every source (files and notes) together

A person is a user of a tenant (rule 7), so the counts are per tenant and user. A limit left out
does not apply.
"""

from dataclasses import dataclass
from typing import Any

from wasifyai_notebooks.store import NotebookStore

PRODUCT_ID = "wasifyai-notebooks"


class QuotaExceeded(Exception):
    """`str(e)` is a sentence safe to show."""


@dataclass(frozen=True)
class Limits:
    notebooks: int | None = None
    sources_per_notebook: int | None = None
    bytes: int | None = None

    def __bool__(self) -> bool:
        return any(v is not None for v in (self.notebooks, self.sources_per_notebook, self.bytes))


def megabytes(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB" if n < 1024**3 else f"{n / 1024**3:.1f} GB"


async def active_limits(state: Any) -> Limits:
    """The limits in force now: none unless the product has them and the safeguards are on (asked
    each time: an admin can switch them)."""
    caps = (getattr(state, "caps", None) or {}).get(PRODUCT_ID)
    config = getattr(caps, "config", None)
    quotas = getattr(config, "quotas", None) or {}
    if caps is None or not quotas or not await caps.safeguards_on():
        return Limits()
    return Limits(
        notebooks=quotas.get("notebooks_per_user"),
        sources_per_notebook=quotas.get("sources_per_notebook"),
        bytes=quotas.get("bytes_per_user"),
    )


def check_new_notebook(limits: Limits, store: NotebookStore, tenant: str, user: str) -> None:
    if limits.notebooks is None:
        return
    if store.usage(tenant, user)["notebooks"] >= limits.notebooks:
        raise QuotaExceeded(
            f"You have reached the limit of {limits.notebooks} notebooks. "
            "Delete one you no longer need to make another."
        )


def check_new_source(
    limits: Limits, store: NotebookStore, tenant: str, user: str, nid: str, size: int,
    *, adding: int = 0, adding_bytes: int = 0,
) -> None:  # fmt: skip
    """Whether one more source of `size` bytes fits; `adding` and `adding_bytes` are what the same
    request has already taken (an upload of several files)."""
    if limits.sources_per_notebook is not None:
        if store.source_count(tenant, user, nid) + adding >= limits.sources_per_notebook:
            raise QuotaExceeded(
                f"A notebook holds at most {limits.sources_per_notebook} sources. "
                "Start another notebook or remove some."
            )
    if limits.bytes is not None:
        used = store.usage(tenant, user)["bytes"] + adding_bytes
        if used + size > limits.bytes:
            raise QuotaExceeded(
                f"That would go over your {megabytes(limits.bytes)} of sources. "
                "Remove some you no longer need."
            )
