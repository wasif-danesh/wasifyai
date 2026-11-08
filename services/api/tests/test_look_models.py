"""Which video model each look was taught on (ADR-0097): a look works only with that model."""

from types import SimpleNamespace

import pytest
from wasifyai_api.person_looks import look_models


class Store:
    def list_models(self, tenant, user, limit):
        assert (tenant, user) == ("t1", "u1")
        return [
            {
                "base": "ltx-2.5",
                "card": {"family": "video", "published": {"lora_name": "a.safetensors"}},
            },
            {
                "base": "",
                "card": {"family": "video", "published": {"lora_name": "old.safetensors"}},
            },
            {
                "base": "klein-4b",
                "card": {"family": "image", "published": {"lora_name": "pic.safetensors"}},
            },
            {"base": "ltx-2.5", "card": {"family": "video", "published": None}},
        ]


@pytest.mark.asyncio
async def test_each_look_names_the_video_model_it_was_taught_on():
    resolve = look_models(SimpleNamespace(training_store=Store()))
    got = await resolve(
        "t1", "u1", ["a.safetensors", "old.safetensors", "pic.safetensors", "x.safetensors"]
    )
    # a look from before looks recorded their model was taught on the first one; a picture style or
    # a file it does not know is left out
    assert got == {"a.safetensors": "ltx-2.5", "old.safetensors": "ltx-video-2b"}
