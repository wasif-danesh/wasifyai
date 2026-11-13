"""The catalogue's prices kept current (ADR-0100, stage CP12), against fake price lists: a changed
price becomes a diff of the catalogue's offer line, never applied; a price in another unit or an
offer the provider does not list is reported and left alone; fal.ai's list is read with the key in
batches; a provider whose list cannot be read is named and the others still compared."""

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
    assert cp.compare([m], {"runware": {}}) == []  # fal.ai not read: not compared
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


async def test_runware_schemas_and_wavespeed_pages():
    def answer(req: httpx.Request) -> httpx.Response:
        if req.url.host == "runware.ai":
            if "z-image" in str(req.url):
                return httpx.Response(200, json={"pricing": {"amount": 0.0025, "unit": "image"}})
            return httpx.Response(404)
        return httpx.Response(200, text="<h2>Pricing</h2><p>Only <b>$0.05</b> per image</p>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        rw = await cp.runware_fetch(http, ["runware:z-image@turbo", "google:nano-banana@2.1"])
        ws = await cp.wavespeed_fetch(http, ["google/nano-banana-2.1/text-to-image"])
    assert rw == {"runware:z-image@turbo": cp.Listed(0.0025, "image")}
    assert ws["google/nano-banana-2.1/text-to-image"] == cp.Listed(0.05, "image")
    assert cp.price_on_page("$0.08 per 1,000 characters") == cp.Listed(0.08, "1000 characters")
    assert cp.price_on_page("no price here") is None


async def test_a_list_that_cannot_be_read_is_named_and_the_others_still_compared():
    async def broken(http: httpx.AsyncClient, endpoints: list[str]) -> dict[str, cp.Listed]:
        raise httpx.ConnectError("down")

    async def fal(http: httpx.AsyncClient, endpoints: list[str]) -> dict[str, cp.Listed]:
        return {"fal-ai/kokoro": cp.Listed(0.03, "1000 characters")}

    async with httpx.AsyncClient() as http:
        changes, failed = await cp.refresh(http, {"runware": broken, "fal": fal}, [kokoro()])
    assert failed == ["runware: ConnectError"]
    assert [(c.endpoint, c.new) for c in changes] == [("fal-ai/kokoro", 0.03)]
    assert "fal-ai/kokoro" in cp.summary(changes) and "$0.02 -> $0.03" in cp.summary(changes)
    assert cp.summary([]) == "Every listed price is the catalogue's."
