"""The local embedder gives creations a searchable vector when no gateway is configured."""

import math

from wasifyai_api.local_embedder import DIMENSIONS, embed_one, hashing_embed


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_vectors_are_fixed_size_unit_length_and_repeatable():
    (a, b) = await hashing_embed(["a red teapot", "a red teapot"])
    assert len(a) == DIMENSIONS and a == b
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0, rel_tol=1e-9)
    assert embed_one("") == [0.0] * DIMENSIONS


def test_shared_words_are_close_and_unrelated_text_is_far():
    teapot = embed_one("a red ceramic teapot on a wooden table")
    assert cos(teapot, embed_one("red teapot")) > 0.5
    assert cos(teapot, embed_one("teapots")) > 0.3  # a plural shares most word pieces
    assert cos(teapot, embed_one("a lighthouse at dusk")) < 0.2


def test_other_scripts_are_split_into_words_too():
    bengali = embed_one("একটি লাল চায়ের কেটলি")
    assert cos(bengali, embed_one("লাল কেটলি")) > 0.3
    assert cos(bengali, embed_one("a red teapot")) < 0.1
