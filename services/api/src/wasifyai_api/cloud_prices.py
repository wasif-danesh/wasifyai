"""The catalogue's prices kept current (ADR-0100, stage CP12): `scripts/cloud-prices/refresh`.

Each provider's price list is read again and compared with the catalogue's offers
(`own_keys_catalogue.py`); a changed price is written as a unified diff of the catalogue for a
person to read and apply (`git apply`), never applied here. A price in another unit, or an offer the
provider does not list, is reported and left alone.

- fal.ai: its price API, with a key (`FAL_KEY`): `GET /v1/models/pricing?endpoint_id=...`.
- Runware: each model's `schema.json` (no key).
- WaveSpeed: each model's page (no key).

The addresses and fields that are not on the providers' pages are marked "(CP13)" and checked in
the real run. Nothing here prints a key."""

import argparse
import asyncio
import difflib
import os
import re
import sys
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from wasifyai_api import own_keys_catalogue as catalogue

FAL_PRICING = "https://api.fal.ai/v1/models/pricing"
RUNWARE_SCHEMA = "https://runware.ai/schemas/{air}/schema.json"  # (CP13)
WAVESPEED_PAGE = "https://wavespeed.ai/models/{model}"  # (CP13)
FAL_BATCH = 50  # endpoints asked at once

# each provider's words for what a price is counted in, as the catalogue's units
UNITS = {
    "image": "picture", "images": "picture", "picture": "picture", "megapixel": "picture",
    "second": "second", "seconds": "second", "video second": "second",
    "minute": "minute", "minutes": "minute",
    "1000 characters": "1k_chars", "1k characters": "1k_chars", "1k_chars": "1k_chars",
    "thousand characters": "1k_chars",
    "step": "step", "steps": "step", "training step": "step",
    "song": "song", "clip": "clip", "video": "clip", "model": "model", "3d model": "model",
    "voice": "voice", "run": "run", "request": "run", "generation": "run",
}  # fmt: skip


@dataclass(frozen=True)
class Listed:
    """A price as the provider lists it."""

    amount: float
    unit: str  # the provider's own word


@dataclass(frozen=True)
class Change:
    model: str
    provider: str
    endpoint: str
    old: float
    new: float | None  # None: not listed, or in another unit
    unit: str
    note: str = ""


Fetch = Callable[[httpx.AsyncClient, list[str]], Awaitable[dict[str, Listed]]]


def unit_of(word: str) -> str | None:
    return UNITS.get(word.strip().lower().removeprefix("per ").strip())


# ---- the price lists -----------------------------------------------------------------------


def fal_fetch(key: str) -> Fetch:
    async def fetch(http: httpx.AsyncClient, endpoints: list[str]) -> dict[str, Listed]:
        out: dict[str, Listed] = {}
        for n in range(0, len(endpoints), FAL_BATCH):
            batch = endpoints[n : n + FAL_BATCH]
            r = await http.get(
                FAL_PRICING, params=[("endpoint_id", e) for e in batch],
                headers={"authorization": f"Key {key}"},
            )  # fmt: skip
            r.raise_for_status()
            for p in r.json().get("prices") or []:
                if isinstance(p, dict) and isinstance(p.get("unit_price"), int | float):
                    out[str(p.get("endpoint_id"))] = Listed(
                        float(p["unit_price"]), str(p.get("unit"))
                    )
        return out

    return fetch


def _price_in(data: Any) -> Listed | None:
    """A price in a Runware schema: `pricing` or `price`, a number or {amount, unit} (CP13)."""
    if not isinstance(data, dict):
        return None
    for name in ("pricing", "price", "cost"):
        p = data.get(name)
        if isinstance(p, int | float):
            return Listed(float(p), str(data.get("unit") or "run"))
        if isinstance(p, dict) and isinstance(p.get("amount"), int | float):
            return Listed(float(p["amount"]), str(p.get("unit") or "run"))
    return None


async def runware_fetch(http: httpx.AsyncClient, airs: list[str]) -> dict[str, Listed]:
    out: dict[str, Listed] = {}
    for air in airs:
        r = await http.get(RUNWARE_SCHEMA.format(air=air))
        if r.status_code == 200 and (found := _price_in(r.json())) is not None:
            out[air] = found
    return out


PAGE_PRICE = re.compile(
    r"\$\s?(\d+(?:\.\d+)?)\s*(?:per|/)\s*(1,?000 characters|1k characters|[a-z][a-z ]{1,20}?)\b",
    re.IGNORECASE,
)


def price_on_page(html: str) -> Listed | None:
    """The first "$0.04 per image" on a WaveSpeed model page (CP13)."""
    m = PAGE_PRICE.search(re.sub(r"<[^>]+>", " ", html))
    if m is None:
        return None
    return Listed(float(m.group(1)), m.group(2).replace("1,000", "1000"))


async def wavespeed_fetch(http: httpx.AsyncClient, models: list[str]) -> dict[str, Listed]:
    out: dict[str, Listed] = {}
    for model in models:
        r = await http.get(WAVESPEED_PAGE.format(model=model))
        if r.status_code == 200 and (found := price_on_page(r.text)) is not None:
            out[model] = found
    return out


# ---- comparing and the diff ----------------------------------------------------------------


def offers(models: Iterable[catalogue.CloudModel]) -> list[tuple[str, Any]]:
    return [(m.model, o) for m in models if m.media for o in m.offers]


def compare(
    models: Iterable[catalogue.CloudModel], listed: dict[str, dict[str, Listed]]
) -> list[Change]:
    """What differs from the catalogue: a new amount, another unit, or not listed at all. Only
    the providers in `listed` are compared."""
    out: list[Change] = []
    for model, o in offers(models):
        if o.provider not in listed:
            continue
        got = listed[o.provider].get(o.endpoint)
        unit = o.price.unit
        if got is None:
            out.append(Change(model, o.provider, o.endpoint, o.price.amount, None, unit,
                              "not in the provider's list"))  # fmt: skip
        elif unit_of(got.unit) != unit:
            out.append(Change(model, o.provider, o.endpoint, o.price.amount, None, unit,
                              f"listed per {got.unit}, not per {unit}"))  # fmt: skip
        elif abs(got.amount - o.price.amount) > 1e-9:
            out.append(Change(model, o.provider, o.endpoint, o.price.amount, got.amount, unit))
    return out


def _amount(x: float) -> str:
    return format(x, ".6g")


def patched(source: str, changes: Iterable[Change]) -> str:
    """The catalogue's source with each new amount in place of the old one on its offer line."""
    lines = source.splitlines(keepends=True)
    for c in changes:
        if c.new is None:
            continue
        line = re.compile(
            rf'(offer\(\s*"{re.escape(c.provider)}",\s*"{re.escape(c.endpoint)}",\s*)([0-9.]+)'
        )
        for n, text in enumerate(lines):
            m = line.search(text)
            if m and abs(float(m.group(2)) - c.old) < 1e-9:
                lines[n] = text[: m.start(2)] + _amount(c.new) + text[m.end(2) :]
                break
    return "".join(lines)


def catalogue_diff(source: str, changes: Iterable[Change], path: str) -> str:
    after = patched(source, changes)
    return "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True), after.splitlines(keepends=True),
            f"a/{path}", f"b/{path}",
        )
    )  # fmt: skip


def summary(changes: list[Change]) -> str:
    if not changes:
        return "Every listed price is the catalogue's."
    rows = []
    for c in changes:
        what = f"${_amount(c.old)} -> ${_amount(c.new)}" if c.new is not None else c.note
        rows.append(f"{c.model} on {c.provider} ({c.endpoint}) per {c.unit}: {what}")
    return "\n".join(rows)


# ---- the script ----------------------------------------------------------------------------


async def refresh(
    http: httpx.AsyncClient, fetchers: dict[str, Fetch], models: list[catalogue.CloudModel]
) -> tuple[list[Change], list[str]]:
    """Each provider's prices compared with the catalogue; a provider whose list could not be read
    is named in the second list and left out."""
    listed: dict[str, dict[str, Listed]] = {}
    failed: list[str] = []
    for provider, fetch in fetchers.items():
        endpoints = sorted({o.endpoint for _, o in offers(models) if o.provider == provider})
        try:
            listed[provider] = await fetch(http, endpoints)
        except (httpx.HTTPError, ValueError) as e:
            failed.append(f"{provider}: {type(e).__name__}")
    return compare(models, listed), failed


CATALOGUE_PATH = "services/api/src/wasifyai_api/own_keys_catalogue.py"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="The cloud catalogue's prices, read again.")
    p.add_argument("--out", default="cloud-prices.diff", help="where the diff is written")
    p.add_argument("--only", choices=["fal", "runware", "wavespeed"], action="append")
    args = p.parse_args(argv)
    fetchers: dict[str, Fetch] = {"runware": runware_fetch, "wavespeed": wavespeed_fetch}
    key = os.environ.get("FAL_KEY", "").strip()
    if key:
        fetchers["fal"] = fal_fetch(key)
    else:
        print("FAL_KEY is not set: fal.ai's prices are not read.", file=sys.stderr)
    if args.only:
        fetchers = {k: v for k, v in fetchers.items() if k in args.only}
    models = [m for m in catalogue.CATALOGUE if m.media]

    async def run() -> tuple[list[Change], list[str]]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            return await refresh(http, fetchers, models)

    changes, failed = asyncio.run(run())
    source_file = Path(catalogue.__file__)
    diff = catalogue_diff(source_file.read_text(), changes, CATALOGUE_PATH)
    Path(args.out).write_text(diff)
    print(summary(changes))
    for f in failed:
        print(f"Could not read the prices of {f}", file=sys.stderr)
    print(
        f"\nThe diff is in {args.out}"
        + (" (empty)" if not diff else "; read it, then git apply it.")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
