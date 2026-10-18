"""The local runtime and the hosted models behind one engine (W5 b to e)."""

from types import SimpleNamespace

import pytest
from wasifyai_api.local_speech import CombinedSpeechEngine
from wasifyai_platform_sdk import VoiceEngineError


class Side:
    """A stand-in for one engine: some model ids, and a record of what it was asked."""

    def __init__(self, name, engine, ready=True):
        self.name, self.engine, self.ready = name, engine, ready
        self.asked = []
        self.stopped = False
        self.lipsync_sidecar = SimpleNamespace(closed=False)

    def models(self, task=None):
        return [{"id": f"{self.name}-model", "tasks": ["speak"]}]

    def resolve(self, task, model_id):
        if not self.ready or model_id not in (None, f"{self.name}-model"):
            raise VoiceEngineError("model_missing", f"{self.name}: not ready")
        return SimpleNamespace(id=f"{self.name}-model", engine=self.engine)

    async def speak(self, model, text, voice, options):
        self.asked.append(text)
        return self.name

    async def stop(self):
        self.stopped = True
        return True

    def state(self):
        return {"installed": self.ready}


def both(local_ready=True):
    return CombinedSpeechEngine(Side("local", "audiocpp", local_ready), Side("hosted", "remote"))


def test_it_lists_both_engines_models():
    assert [m["id"] for m in both().models("speak")] == ["local-model", "hosted-model"]


def test_a_named_model_goes_to_its_own_engine():
    engine = both()
    assert engine.resolve("speak", "hosted-model").engine == "remote"
    assert engine.resolve("speak", "local-model").engine == "audiocpp"


def test_the_local_model_is_the_default_and_the_hosted_one_the_fallback():
    assert both().resolve("speak", None).id == "local-model"
    assert both(local_ready=False).resolve("speak", None).id == "hosted-model"


def test_with_neither_ready_the_local_reason_is_given():
    engine = CombinedSpeechEngine(Side("local", "audiocpp", False), Side("hosted", "remote", False))
    with pytest.raises(VoiceEngineError, match="local: not ready"):
        engine.resolve("speak", None)


@pytest.mark.asyncio
async def test_work_goes_to_the_engine_that_owns_the_model():
    engine = both()
    assert await engine.speak(engine.resolve("speak", "hosted-model"), "hi", None, {}) == "hosted"
    assert await engine.speak(engine.resolve("speak", "local-model"), "hi", None, {}) == "local"


@pytest.mark.asyncio
async def test_stop_gives_back_local_memory_and_leaves_the_hosted_client_open():
    engine = both()
    assert await engine.stop() is True
    assert engine.local.stopped and not engine.hosted.stopped
    assert engine.state() == {"installed": True}
