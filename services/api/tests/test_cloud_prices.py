"""The catalogue's prices kept current (ADR-0100, stage CP12), against fake price lists: a changed
price becomes a diff of the catalogue's offer line, never applied; a price in another unit or an
offer the provider does not list is reported and left alone; fal.ai's list is read with the key in
batches, and alone when it does not know one of a batch; WaveSpeed's from its models list; a
provider whose list cannot be read is named and the others still compared."""

import subprocess
from pathlib import Path

import httpx
import pytest
from wasifyai_api import cloud_prices as cp
from wasifyai_api import own_keys_catalogue as catalogue

FAL_KEY = "fal-price-key"


def kokoro() -> catalogue.CloudModel:
    m = catalogue.media_model("voice", "fal-ai/kokoro")
    assert m is not None
    return m


def test_a_changed_price_is_a_diff_of_its_offer_line_only():
    source = Path(catalogue.__file__).read_text()
    changes = cp.compare([kokoro()], {"fal": {"fal-ai/kokoro": cp.Listed(0.03, "1000 characters")}})
    (c,) = changes
    assert (c.old, c.new, c.unit) == (0.02, 0.03, "1k_chars")
    diff = cp.catalogue_diff(source, changes, cp.CATALOGUE_PATH)
    removed = [x for x in diff.splitlines() if x.startswith("-") and not x.startswith("---")]
    added = [x for x in diff.splitlines() if x.startswith("+") and not x.startswith("+++")]
    assert len(removed) == len(added) == 1
    assert '"fal-ai/kokoro", 0.02,' in removed[0] and '"fal-ai/kokoro", 0.03,' in added[0]
    assert Path(catalogue.__file__).read_text() == source  # nothing is applied


def test_the_diff_applies_to_the_repository(tmp_path):
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists() and not (root / cp.CATALOGUE_PATH).exists():
        pytest.skip("not running from the repository")
    changes = cp.compare([kokoro()], {"fal": {"fal-ai/kokoro": cp.Listed(0.025, "1k characters")}})
    diff = tmp_path / "p.diff"
    diff.write_text(cp.catalogue_diff((root / cp.CATALOGUE_PATH).read_text(), changes,
                                      cp.CATALOGUE_PATH))  # fmt: skip
    check = subprocess.run(
        ["git", "apply", "--check", str(diff)], cwd=root, capture_output=True, text=True
    )
    assert check.returncode == 0, check.stderr


def test_the_same_price_another_unit_or_none_listed():
    m = kokoro()
    assert cp.compare([m], {"fal": {"fal-ai/kokoro": cp.Listed(0.02, "per 1k characters")}}) == []
    (other,) = cp.compare([m], {"fal": {"fal-ai/kokoro": cp.Listed(0.02, "second")}})
    assert other.new is None and "per second" in other.note
    (missing,) = cp.compare([m], {"fal": {}})
    assert missing.new is None and "not in the provider's list" in missing.note
    assert cp.compare([m], {"wavespeed": {}}) == []  # fal.ai not read: not compared
    # fal.ai prices a name it has no model at in compute seconds (CP13)
    (nowhere,) = cp.compare([m], {"fal": {"fal-ai/kokoro": cp.Listed(0.00017, "compute seconds")}})
    assert nowhere.new is None and "not in the provider's list" in nowhere.note
    assert cp.catalogue_diff("x", [other, missing], "p") == ""


async def test_fal_prices_are_read_with_the_key_in_batches():
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        ids = req.url.params.get_list("endpoint_id")
        return httpx.Response(200, json={"prices": [
            {"endpoint_id": e, "unit_price": 0.01, "unit": "image", "currency": "USD"} for e in ids
        ]})  # fmt: skip

    endpoints = [f"fal-ai/m{n}" for n in range(cp.FAL_BATCH + 3)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        got = await cp.fal_fetch(FAL_KEY)(http, endpoints)
    assert len(seen) == 2 and all(r.headers["authorization"] == f"Key {FAL_KEY}" for r in seen)
    assert got["fal-ai/m52"] == cp.Listed(0.01, "image")


async def test_a_batch_fal_does_not_know_is_asked_one_by_one():
    seen: list[list[str]] = []

    def answer(req: httpx.Request) -> httpx.Response:
        ids = req.url.params.get_list("endpoint_id")
        seen.append(ids)
        if "fal-ai/gone" in ids:  # fal.ai refuses the whole batch for one name it does not know
            return httpx.Response(404, json={"error": {"type": "not_found"}})
        prices = [{"endpoint_id": e, "unit_price": 0.005, "unit": "megapixels"} for e in ids]
        return httpx.Response(200, json={"prices": prices})

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        got = await cp.fal_fetch(FAL_KEY, pace_s=0)(http, ["fal-ai/z-image/turbo", "fal-ai/gone"])
    z, gone = "fal-ai/z-image/turbo", "fal-ai/gone"
    assert seen == [[z, gone], [z], [gone]]
    assert got == {"fal-ai/z-image/turbo": cp.Listed(0.005, "megapixels")}
    assert cp.unit_of("megapixels") == "picture"


async def test_wavespeed_prices_come_from_its_models_list():
    def answer(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer ws-key"
        return httpx.Response(200, json={"data": [
            {"model_id": "mureka-ai/stem-song", "base_price": 1.05},
            {"model_id": "someone/else", "base_price": 9},
        ]})  # fmt: skip

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        got = await cp.wavespeed_fetch("ws-key")(http, ["mureka-ai/stem-song"])
    assert got == {"mureka-ai/stem-song": cp.Listed(1.05, "")}
    stems = catalogue.media_model("split", "mureka-stems")
    assert stems is not None
    (c,) = cp.compare([stems], {"wavespeed": got})  # in the model's own unit: the amount compared
    assert (c.provider, c.new, c.unit) == ("wavespeed", 1.05, "song")


async def test_a_list_that_cannot_be_read_is_named_and_the_others_still_compared():
    async def broken(http: httpx.AsyncClient, endpoints: list[str]) -> dict[str, cp.Listed]:
        raise httpx.ConnectError("down")

    async def fal(http: httpx.AsyncClient, endpoints: list[str]) -> dict[str, cp.Listed]:
        return {"fal-ai/kokoro": cp.Listed(0.03, "1000 characters")}

    async with httpx.AsyncClient() as http:
        changes, failed = await cp.refresh(http, {"wavespeed": broken, "fal": fal}, [kokoro()])
    assert failed == ["wavespeed: ConnectError"]
    assert [(c.endpoint, c.new) for c in changes] == [("fal-ai/kokoro", 0.03)]
    assert "fal-ai/kokoro" in cp.summary(changes) and "$0.02 -> $0.03" in cp.summary(changes)
    assert cp.summary([]) == "Every listed price is the catalogue's."
