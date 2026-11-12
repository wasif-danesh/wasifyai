"""The cheapest provider for each media job (ADR-0100, stage CP3).

A cloud media model is offered by one or more providers (Runware, WaveSpeed, fal.ai). An `Offer`
is one of them: its endpoint for the model, its price, and what it can do beyond making (`can`: a
mask, a trained look, extend, ...). For each job the router:

1. keeps the offers whose provider has a key and that can do what the job needs (`needs`), or
   only the provider a result is pinned to (`only`: a cloned voice, a song or a look made there);
2. prices each for the job's settings (`Price.of`) and orders them, cheapest first; on a tie,
   Runware, then WaveSpeed, then fal.ai (`TIE_ORDER`);
3. sends the job to the first; if that provider refuses *before running it* (`FalError` with
   `before_running`), the next offer takes it. A job that may have run, and so may have been
   charged, is never sent again (`run_cheapest`).

The caller writes a usage event with the provider and the price (`CLOUD_COST`)."""

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from wasifyai_platform_sdk.fal import FalError
from wasifyai_platform_sdk.usage import UsageEvent

log = logging.getLogger(__name__)

TIE_ORDER = ("runware", "wavespeed", "fal")
PROVIDER_TITLES = {"runware": "Runware", "wavespeed": "WaveSpeed", "fal": "fal.ai"}
CLOUD_COST = "cloud.cost"  # a usage event: what a provider charged for a job, in dollars

# what a price is counted in, and the job setting that says how many
UNITS: dict[str, str] = {
    "picture": "count",  # per picture made
    "second": "seconds",  # per second of video or sound
    "minute": "seconds",  # per minute, counted in seconds
    "1k_chars": "characters",  # per 1,000 characters of text
    "step": "steps",  # per training step
    "song": "",  # one price whatever the length
    "clip": "",
    "model": "",
    "voice": "",
    "run": "",
}
UNIT_WORDS = {
    "picture": "per picture", "second": "per second", "minute": "per minute",
    "1k_chars": "per 1,000 characters", "step": "per step", "song": "per song",
    "clip": "per clip", "model": "per model", "voice": "per voice", "run": "per run",
}  # fmt: skip


@dataclass(frozen=True)
class Price:
    """`amount` dollars per `unit`; `by` gives another amount for a value of the job's `setting`
    (a resolution, say), and `minimum` is the least a job costs."""

    amount: float
    unit: str
    setting: str = ""
    by: Mapping[str, float] = field(default_factory=dict)
    minimum: float = 0.0

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise ValueError(f"unknown price unit {self.unit!r}")

    def of(self, job: Mapping[str, Any]) -> float:
        """What a job with these settings costs."""
        amount = self.amount
        if self.setting and str(job.get(self.setting)) in self.by:
            amount = self.by[str(job.get(self.setting))]
        counted = UNITS[self.unit]
        if not counted:
            quantity = 1.0
        else:
            raw = job.get(counted)
            quantity = float(raw) if isinstance(raw, int | float) and raw > 0 else 1.0
            if self.unit == "minute":
                quantity /= 60
            elif self.unit == "1k_chars":
                quantity /= 1000
        return round(max(self.minimum, amount * quantity), 6)

    def words(self) -> str:
        """ "$0.10 per second", and the settings named in `by`: "$0.10 per second at 480p, $0.20
        at 720p" (the setting the amount is for is the one in `by` at that amount)."""
        lead = next((k for k, v in self.by.items() if v == self.amount), None)
        others = "".join(f", ${_dollars(v)} at {k}" for k, v in self.by.items() if k != lead)
        at = f" at {lead}" if lead else ""
        return f"${_dollars(self.amount)} {UNIT_WORDS[self.unit]}{at}{others}"


def _dollars(x: float) -> str:
    text = f"{x:.4f}".rstrip("0").rstrip(".")
    return text if "." not in text or len(text.split(".")[1]) >= 2 else f"{x:.2f}"


@dataclass(frozen=True)
class Offer:
    provider: str  # runware | wavespeed | fal
    endpoint: str  # the provider's own name for the model: an endpoint, a model id or an AIR id
    price: Price
    can: frozenset[str] = frozenset()  # what it does beyond making: "edit", "mask", "lora", ...
    endpoints: Mapping[str, str] = field(default_factory=dict)  # another endpoint for a verb

    def endpoint_for(self, verb: str) -> str:
        return self.endpoints.get(verb, self.endpoint)


def offer(
    provider: str,
    endpoint: str,
    amount: float,
    unit: str,
    *can: str,
    setting: str = "",
    by: Mapping[str, float] | None = None,
    minimum: float = 0.0,
    endpoints: Mapping[str, str] | None = None,
) -> Offer:
    """A short way to write an offer in the catalogue."""
    if provider not in TIE_ORDER:
        raise ValueError(f"unknown media provider {provider!r}")
    return Offer(
        provider, endpoint, Price(amount, unit, setting, dict(by or {}), minimum),
        frozenset(can), dict(endpoints or {}),
    )  # fmt: skip


def cheapest_words(offers: Iterable[Offer]) -> str:
    """ "from $x per y": the lowest list price of a model, for the Cloud tab."""
    found = sorted(offers, key=lambda o: o.price.amount)
    if not found:
        return ""
    lowest = found[0].price
    same = all(o.price.unit == lowest.unit and o.price.amount == lowest.amount for o in found)
    return lowest.words() if same else f"from {lowest.words()}"


@dataclass(frozen=True)
class Priced[C]:
    choice: C
    offer: Offer
    cost: float


def order[C](
    choices: Iterable[C],
    offer_of: Callable[[C], Offer],
    job: Mapping[str, Any],
    needs: Iterable[str] = (),
    only: str | None = None,
) -> list[Priced[C]]:
    """The choices that can do the job, cheapest first (ties: Runware, WaveSpeed, fal.ai)."""
    wanted = set(needs)
    out: list[Priced[C]] = []
    for c in choices:
        o = offer_of(c)
        if only is not None and o.provider != only:
            continue
        if not wanted <= o.can:
            continue
        out.append(Priced(c, o, o.price.of(job)))
    out.sort(key=lambda p: (p.cost, TIE_ORDER.index(p.offer.provider)))
    return out


class NoOffer(FalError):
    """No provider with a key can do the job; the message says which keys would."""

    def __init__(self, message: str):
        super().__init__("not_with_key", message)


def no_offer(model_title: str, offers: Iterable[Offer], needs: Iterable[str], only: str | None):
    """Words for a job none of the keyed providers can do."""
    wanted = set(needs)
    able = [o for o in offers if wanted <= o.can and (only is None or o.provider == only)]
    if not able:
        what = ", ".join(sorted(wanted)) or "this"
        return NoOffer(f"{model_title} cannot do {what} with any provider. Choose another model.")
    names = sorted({PROVIDER_TITLES[o.provider] for o in able}, key=str)
    return NoOffer(
        f"{model_title} needs a key for {' or '.join(names)} to do this: Settings › Your keys."
    )


def refused_before_running(e: BaseException) -> bool:
    """A provider's refusal before it ran the job: a `FalError` so marked, or any error that
    carries `before_running = True` (the media worker's own errors, made from a `FalError`)."""
    return bool(getattr(e, "before_running", False))


async def run_cheapest[C, T](
    ordered: list[Priced[C]], attempt: Callable[[Priced[C]], Awaitable[T]]
) -> tuple[T, Priced[C]]:
    """Send the job to the cheapest offer; on a refusal before running, to the next. Answers what
    the job made and the offer that made it. A failure after the job may have run is raised as it
    is: that job is never sent again."""
    if not ordered:
        raise NoOffer("No provider with a key can do this.")
    for i, p in enumerate(ordered):
        try:
            return await attempt(p), p
        except Exception as e:
            if not refused_before_running(e) or i == len(ordered) - 1:
                raise
            log.info(
                "%s refused before running (%s); trying %s",
                p.offer.provider, getattr(e, "code", type(e).__name__),
                ordered[i + 1].offer.provider,
            )  # fmt: skip
    raise AssertionError("unreachable: the loop returns or raises")


def cost_meta(p: Priced[Any], model: str) -> dict[str, Any]:
    """What a `CLOUD_COST` usage event says besides the price."""
    return {"provider": p.offer.provider, "model": model, "endpoint": p.offer.endpoint}


def cost_event(
    p: Priced[Any],
    model: str,
    tenant_id: str,
    product_id: str,
    user_id: str | None = None,
    run_id: str | None = None,
    **meta: Any,
) -> UsageEvent:
    """The usage event of a job that ran on a provider: its list price for the job, in dollars."""
    return UsageEvent(
        tenant_id=tenant_id, product_id=product_id, user_id=user_id, run_id=run_id,
        kind=CLOUD_COST, quantity=p.cost, unit="dollars", meta={**cost_meta(p, model), **meta},
    )  # fmt: skip
