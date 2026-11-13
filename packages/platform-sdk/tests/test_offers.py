"""The cheapest provider for each media job (ADR-0100, stage CP3): prices for a job's settings, the
cheapest first, ties to Runware, then WaveSpeed, then fal.ai; only what can do the job; a pinned
result stays where it was made; a refusal before running goes to the next offer, and a job that
may have run is never sent again."""

import httpx
import pytest
from wasifyai_platform_sdk.cloud_queues import RunwareTasks, WaveSpeedQueue
from wasifyai_platform_sdk.fal import FalError, FalQueue
from wasifyai_platform_sdk.offers import (
    NoOffer,
    Price,
    cheapest_words,
    no_offer,
    offer,
    order,
    run_cheapest,
)

KLEIN = (
    offer("fal", "fal-ai/flux-3/klein", 0.009, "picture", "edit", "lora"),
    offer("wavespeed", "wavespeed-ai/flux-3-klein", 0.01, "picture", "edit", "lora"),
    offer("runware", "bfl:7@1", 0.006, "picture", "edit"),
)


def ids(priced) -> list[str]:
    return [p.offer.provider for p in priced]


def test_a_price_is_counted_in_its_unit_and_by_a_setting():
    assert Price(0.07, "second").of({"seconds": 5}) == 0.35
    assert (
        Price(0.07, "second", "resolution", {"1080p": 0.14}).of(
            {"seconds": 5, "resolution": "1080p"}
        )
        == 0.7
    )
    assert Price(0.6, "minute").of({"seconds": 90}) == 0.9
    assert Price(0.08, "1k_chars").of({"characters": 2500}) == 0.2
    assert Price(0.15, "song").of({"seconds": 200}) == 0.15  # one price for a song
    assert Price(0.002, "second", minimum=0.05).of({"seconds": 3}) == 0.05
    assert Price(0.009, "picture").of({}) == 0.009  # one picture when it does not say
    with pytest.raises(ValueError):
        Price(1, "parsec")


def test_the_cheapest_comes_first_and_only_those_with_a_key():
    assert ids(order(KLEIN, lambda o: o, {})) == ["runware", "fal", "wavespeed"]
    keyed = [o for o in KLEIN if o.provider != "runware"]
    assert ids(order(keyed, lambda o: o, {})) == ["fal", "wavespeed"]


def test_a_tie_goes_to_runware_then_wavespeed_then_fal():
    same = [offer(p, "m", 0.04, "picture") for p in ("fal", "wavespeed", "runware")]
    assert ids(order(same, lambda o: o, {})) == ["runware", "wavespeed", "fal"]


def test_only_offers_that_can_do_the_job_and_a_pinned_result_stays_where_it_was_made():
    assert ids(order(KLEIN, lambda o: o, {}, needs={"lora"})) == ["fal", "wavespeed"]
    assert ids(order(KLEIN, lambda o: o, {}, only="wavespeed")) == ["wavespeed"]
    assert order(KLEIN, lambda o: o, {}, needs={"extend"}) == []


def test_the_price_depends_on_the_job_so_the_pick_can_change():
    # MiniMax Music: fal.ai by the second, WaveSpeed a song: fal.ai is cheaper for a short song
    music = (offer("fal", "fal-ai/minimax-music/v3", 0.002, "second"),
             offer("wavespeed", "minimax/music-3", 0.15, "song"))  # fmt: skip
    assert ids(order(music, lambda o: o, {"seconds": 60})) == ["fal", "wavespeed"]
    assert ids(order(music, lambda o: o, {"seconds": 120})) == ["wavespeed", "fal"]


def test_the_cloud_tab_says_from_the_lowest_price():
    assert cheapest_words(KLEIN) == "from $0.006 per picture"
    assert cheapest_words([offer("fal", "x", 0.06, "model")]) == "$0.06 per model"


def test_words_when_no_keyed_provider_can_do_it():
    e = no_offer("FLUX.3 klein", KLEIN, {"lora"}, None)
    assert isinstance(e, NoOffer)
    assert e.message == (
        "FLUX.3 klein needs a key for WaveSpeed or fal.ai to do this: Settings › Your keys."
    )
    assert "cannot do extend" in no_offer("FLUX.3 klein", KLEIN, {"extend"}, None).message


async def test_a_refusal_before_running_goes_to_the_next_offer():
    tried: list[str] = []

    async def attempt(p):
        tried.append(p.offer.provider)
        if p.offer.provider == "runware":
            raise FalError("provider_refused", "Runware did not accept the key.", True)
        return "picture"

    made, used = await run_cheapest(order(KLEIN, lambda o: o, {}), attempt)
    assert (made, used.offer.provider, used.cost) == ("picture", "fal", 0.009)
    assert tried == ["runware", "fal"]


async def test_a_job_that_may_have_run_is_never_sent_again():
    tried: list[str] = []

    async def attempt(p):
        tried.append(p.offer.provider)
        raise FalError("provider_refused", "Runware could not make it: the model failed.")

    with pytest.raises(FalError, match="the model failed"):
        await run_cheapest(order(KLEIN, lambda o: o, {}), attempt)
    assert tried == ["runware"]


async def test_the_last_refusal_is_said_when_every_offer_refuses():
    async def attempt(p):
        raise FalError("provider_refused", f"{p.offer.provider} said no", True)

    with pytest.raises(FalError, match="wavespeed said no"):
        await run_cheapest(order(KLEIN, lambda o: o, {}), attempt)
    with pytest.raises(NoOffer):
        await run_cheapest([], attempt)


# ---- which answers count as "before running", from each provider's client ---------------------


def http(answer) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def nothing(_p: float) -> None:
    return None


@pytest.mark.parametrize(("status", "before"), [(401, True), (422, True), (429, True),
                                                (500, False), (503, False)])  # fmt: skip
async def test_a_4xx_to_the_request_is_before_running_and_a_5xx_is_not(status, before):
    def answer(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "no", "message": "no", "errors": [{}]})

    for client in (FalQueue("k", http(answer), 5), WaveSpeedQueue("k", http(answer), 5),
                   RunwareTasks("k", http(answer), 5)):  # fmt: skip
        with pytest.raises(FalError) as e:
            await client.call("m", {"prompt": "x"}, nothing)
        assert e.value.before_running is before, type(client).__name__


async def test_no_connection_is_before_running_but_a_lost_answer_is_not():
    def refuse(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    def lost(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer")

    with pytest.raises(FalError) as e:
        await FalQueue("k", http(refuse), 5).call("m", {}, nothing)
    assert e.value.before_running is True
    with pytest.raises(FalError) as e:
        await WaveSpeedQueue("k", http(lost), 5).call("m", {}, nothing)
    assert e.value.before_running is False


async def test_a_failure_while_running_is_not_before_running():
    calls = {"n": 0}

    def answer(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"id": "p1"}})
        return httpx.Response(200, json={"data": {"status": "failed", "error": "bad prompt"}})

    with pytest.raises(FalError) as e:
        await WaveSpeedQueue("k", http(answer), 5, poll_s=0).call("m", {}, nothing)
    assert e.value.before_running is False and "bad prompt" in e.value.message


async def test_a_runware_task_refused_at_once_is_before_running():
    def answer(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Invalid model"}]})

    with pytest.raises(FalError) as e:
        await RunwareTasks("k", http(answer), 5).call("bad:1@1", {"taskType": "imageInference"},
                                                       nothing)  # fmt: skip
    assert e.value.before_running is True and "Invalid model" in e.value.message


async def test_a_name_fal_has_no_model_at_is_said_so_not_blamed_on_the_key():
    """fal.ai's queue takes any name, then refuses the job with 403 (CP13)."""

    def answer(req: httpx.Request) -> httpx.Response:
        detail = "Endpoint fal-ai/x is not available: no billing definition."
        return httpx.Response(403, json={"detail": detail, "type": "endpoint_not_priced"})

    with pytest.raises(FalError) as e:
        await FalQueue("k", http(answer), 5).call("fal-ai/x", {}, nothing)
    assert e.value.message.startswith("fal.ai has no such model: Endpoint fal-ai/x")
    assert "key" not in e.value.message
