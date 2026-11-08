"""The AI Toolkit launcher: offline, a split model's parts are looked up in the cache only."""

import importlib
import sys
import types

import pytest
from wasifyai_api import training_aitk_run as run


def stand_in_diffusers(monkeypatch: pytest.MonkeyPatch) -> tuple[types.ModuleType, list[dict]]:
    calls: list[dict] = []

    def shards(name, index, local_files_only=False, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append({"local_files_only": local_files_only, **kwargs})
        return [], {}

    def module(name: str, **attrs: object) -> types.ModuleType:
        mod = types.ModuleType(name)
        vars(mod).update(attrs)
        return mod

    hub_utils = module("diffusers.utils.hub_utils", _get_checkpoint_shard_files=shards)
    modeling_utils = module("diffusers.models.modeling_utils", _get_checkpoint_shard_files=shards)
    utils = module("diffusers.utils", hub_utils=hub_utils)
    models = module("diffusers.models", modeling_utils=modeling_utils)
    root = module("diffusers", utils=utils, models=models)
    for name, mod in {
        "diffusers": root, "diffusers.utils": utils, "diffusers.utils.hub_utils": hub_utils,
        "diffusers.models": models, "diffusers.models.modeling_utils": modeling_utils,
    }.items():  # fmt: skip
        monkeypatch.setitem(sys.modules, name, mod)
    return modeling_utils, calls


def test_offline_the_parts_of_a_split_model_come_from_the_cache(monkeypatch: pytest.MonkeyPatch):
    modeling_utils, calls = stand_in_diffusers(monkeypatch)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    run.cache_only_shards()
    modeling_utils._get_checkpoint_shard_files("ostris/x", "index.json", local_files_only=False)  # noqa: SLF001
    assert calls == [{"local_files_only": True}]


def test_online_nothing_is_changed(monkeypatch: pytest.MonkeyPatch):
    modeling_utils, calls = stand_in_diffusers(monkeypatch)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    run.cache_only_shards()
    modeling_utils._get_checkpoint_shard_files("ostris/x", "index.json")  # noqa: SLF001
    assert calls == [{"local_files_only": False}]


def test_offline_a_file_not_in_the_cache_is_one_the_repo_does_not_have(
    monkeypatch: pytest.MonkeyPatch,
):
    import huggingface_hub
    from huggingface_hub import file_download
    from huggingface_hub.errors import EntryNotFoundError, LocalEntryNotFoundError

    def not_cached(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise LocalEntryNotFoundError("not in the cache")

    monkeypatch.setattr(file_download, "hf_hub_download", not_cached)
    # put back after the test: missing_is_absent replaces these too
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", huggingface_hub.hf_hub_download)
    try:
        transformers_hub = importlib.import_module("transformers.utils.hub")  # when installed
    except ImportError:
        pass
    else:
        monkeypatch.setattr(transformers_hub, "hf_hub_download", transformers_hub.hf_hub_download)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    run.missing_is_absent()
    with pytest.raises(EntryNotFoundError) as caught:
        file_download.hf_hub_download("Tongyi-MAI/Z-Image-Turbo", "tokenizer/config.json")
    assert not isinstance(caught.value, LocalEntryNotFoundError)


def test_the_mac_rope_is_used_only_for_flux3():
    flux3 = {"config": {"process": [{"model": {"arch": "flux3"}}]}}
    klein = {"config": {"process": [{"model": {"arch": "flux2_klein_4b"}}]}}
    assert run.uses_arch(flux3, "flux3") and not run.uses_arch(klein, "flux3")
