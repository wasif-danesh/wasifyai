"""Finding models other tools left on this computer (ADR-0063): headers, layouts, states, routes."""

import asyncio
import json
import struct
import time
from pathlib import Path

import httpx
import pytest
from wasifyai_api.desktop_discovery import (
    Budget,
    DiscoveryService,
    Found,
    Tool,
    assess,
    classify_tensors,
    load_config,
    probe_servers,
    read_gguf,
    read_header,
    read_safetensors,
    resolve_tools,
    scan_folders,
)
from wasifyai_api.desktop_models import ModelEntry, ModelFile, ModelsService
from wasifyai_api.safeguards import InMemorySettingsStore

MB = 1_000_000


# ---- files to find ----------------------------------------------------------------------------


def gguf(path: Path, arch: str = "llama", name: str = "Demo", ftype: int = 15, *, tensors: int = 3,
         pad_to: int = 2 * MB, licence: str = "apache-2.0") -> Path:  # fmt: skip
    def s(v: str) -> bytes:
        b = v.encode()
        return struct.pack("<Q", len(b)) + b

    def kv_str(k: str, v: str) -> bytes:
        return s(k) + struct.pack("<I", 8) + s(v)

    def kv_u32(k: str, v: int) -> bytes:
        return s(k) + struct.pack("<II", 4, v)

    kvs = [
        kv_str("general.architecture", arch), kv_str("general.name", name),
        kv_u32("general.file_type", ftype), kv_str("general.license", licence),
        kv_u32(f"{arch}.context_length", 8192),
        # a tokenizer array, which the reader must not walk through
        s("tokenizer.ggml.tokens") + struct.pack("<I", 9) + struct.pack("<IQ", 8, 2)
        + s("a") + s("b"),
    ]  # fmt: skip
    body = b"GGUF" + struct.pack("<IQQ", 3, tensors, len(kvs)) + b"".join(kvs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body + b"\0" * max(0, pad_to - len(body)))
    return path


def safetensors(path: Path, names: list[str], dtype: str = "BF16", pad_to: int = 2 * MB,
                meta: dict | None = None) -> Path:  # fmt: skip
    head: dict = {n: {"dtype": dtype, "shape": [1], "data_offsets": [0, 2]} for n in names}
    if meta:
        head["__metadata__"] = meta
    raw = json.dumps(head).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * pad_to)
    return path


FLUX = ["double_blocks.0.img_attn.qkv.weight", "single_blocks.0.linear1.weight"]
WAN = ["patch_embedding.weight", "blocks.0.self_attn.q.weight", "head.head.weight"]
LORA = ["lora_unet_double_blocks_0.lora_down.weight", "lora_unet_double_blocks_0.lora_up.weight"]
VAE = ["encoder.conv_in.weight", "decoder.conv_out.weight", "quant_conv.weight"]
LLM = ["model.embed_tokens.weight", "model.layers.0.self_attn.q_proj.weight"]


# ---- headers ----------------------------------------------------------------------------------


def test_a_gguf_header_tells_what_it_is_without_reading_the_tokenizer(tmp_path):
    h = read_gguf(gguf(tmp_path / "m.gguf", arch="qwen2", name="Qwen2 7B", ftype=15))
    assert h is not None
    assert (h.kind, h.family, h.quant, h.name) == ("language", "qwen2", "Q4_K_M", "Qwen2 7B")
    assert h.licence == "apache-2.0" and h.context == 8192 and h.tensors == 3


@pytest.mark.parametrize(
    ("arch", "kind"),
    [("nomic-bert", "embedding"), ("flux", "diffusion"), ("wan", "video"), ("clip", "other")],
)
def test_gguf_architectures_that_are_not_language_models(tmp_path, arch, kind):
    h = read_gguf(gguf(tmp_path / "m.gguf", arch=arch))
    assert h is not None and h.kind == kind


def test_a_file_that_is_not_a_gguf_is_not_one(tmp_path):
    f = tmp_path / "x.gguf"
    f.write_bytes(b"not a model at all" * 100)
    assert read_gguf(f) is None
    f.write_bytes(b"GGUF\x03\x00\x00\x00")  # cut short
    assert read_gguf(f) is None


@pytest.mark.parametrize(
    ("names", "kind", "family"),
    [
        (FLUX, "diffusion", "flux"),
        (WAN, "video", "wan"),
        (LORA, "lora", "flux"),
        (
            [
                "transformer_blocks.0.attn1.to_q.lora_A.weight",
                "transformer_blocks.0.attn2.to_k.lora_B.weight",
            ],
            "lora",
            "ltx-video",
        ),
        (VAE, "vae", ""),
        (LLM, "language", "transformers"),
        (["encoder.block.0.layer.0.weight", "shared.weight"], "text_encoder", "t5"),
        (
            ["model.diffusion_model.input_blocks.0.weight", "label_emb.0.weight"],
            "diffusion",
            "sdxl",
        ),
        (["something.else"], "unknown", ""),
    ],
)
def test_tensor_names_classify_a_safetensors_file(names, kind, family):
    assert classify_tensors(names) == (kind, family)


def test_safetensors_reports_the_dominant_dtype_and_metadata(tmp_path):
    f = safetensors(
        tmp_path / "f.safetensors", FLUX, "F8_E4M3", meta={"modelspec.title": "My Flux"}
    )
    h = read_safetensors(f)
    assert (h.kind, h.quant, h.name) == ("diffusion", "F8_E4M3", "My Flux")


def test_the_folder_settles_what_the_header_cannot(tmp_path):
    f = safetensors(tmp_path / "vae" / "x.safetensors", ["a.b", "c.d"])
    assert read_header(f, "vae").kind == "vae"
    assert read_header(f, "elsewhere").kind == "unknown"


def test_a_corrupt_header_is_unknown_not_an_error(tmp_path):
    f = tmp_path / "bad.safetensors"
    f.write_bytes(struct.pack("<Q", 10**12) + b"junk")
    assert read_safetensors(f).kind == "unknown"


# ---- layouts ----------------------------------------------------------------------------------


def tools_for(home: Path, **kw) -> list[Tool]:
    return resolve_tools(load_config(), platform="darwin", env=kw.get("env", {}), home=home)


def test_the_folders_come_from_the_data_file_and_the_environment(tmp_path):
    tools = {t.id: t for t in tools_for(tmp_path)}
    assert tools["ollama"].folders == [tmp_path / ".ollama/models"]
    moved = {
        t.id: t
        for t in tools_for(tmp_path, env={"OLLAMA_MODELS": "/data/o", "HF_HUB_CACHE": "/hf"})
    }
    assert moved["ollama"].folders[0] == Path("/data/o")
    assert moved["huggingface"].folders == [Path("/hf")]
    assert tools["comfyui-documents"].needs_permission is True


def test_ollama_is_read_through_its_manifests(tmp_path):
    root = tmp_path / ".ollama" / "models"
    blob = gguf(root / "blobs" / "sha256-abc", arch="llama", name="Llama 3.2 3B", ftype=15)
    manifest = root / "manifests" / "registry.ollama.ai" / "library" / "llama3.2" / "3b"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"layers": [
        {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc", "size": 1},
        {"mediaType": "application/vnd.ollama.image.license", "digest": "sha256:zzz"},
    ]}))  # fmt: skip
    other = root / "manifests" / "registry.ollama.ai" / "someone" / "tool" / "latest"
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps({"layers": [{"mediaType": "x", "digest": "sha256:none"}]}))

    result = scan_folders(tools_for(tmp_path), [])
    (item,) = [i for i in result.items if i.tool == "ollama"]
    assert (item.name, item.kind, item.quant, item.format) == (
        "llama3.2:3b",
        "language",
        "Q4_K_M",
        "gguf",
    )
    assert item.path == str(blob)


def test_a_huggingface_repo_is_one_item_and_a_vocabulary_file_is_none(tmp_path):
    hub = tmp_path / ".cache" / "huggingface" / "hub"
    snap = hub / "models--org--flux-ish" / "snapshots" / "rev1"
    (snap / "transformer").mkdir(parents=True)
    (snap / "model_index.json").write_text(json.dumps({"_class_name": "FluxPipeline"}))
    safetensors(snap / "transformer" / "diffusion_pytorch_model.safetensors", FLUX)
    chat = hub / "models--org--chat" / "snapshots" / "rev1"
    chat.mkdir(parents=True)
    (chat / "config.json").write_text(json.dumps(
        {"architectures": ["LlamaForCausalLM"], "model_type": "llama"}
    ))  # fmt: skip
    safetensors(chat / "model.safetensors", LLM)
    gguf(hub / "models--org--vocab" / "snapshots" / "r" / "ggml-vocab.gguf", tensors=0)

    items = {i.name: i for i in scan_folders(tools_for(tmp_path), []).items}
    assert set(items) == {"org/flux-ish", "org/chat"}
    assert (items["org/flux-ish"].kind, items["org/flux-ish"].family) == ("diffusion", "flux")
    assert items["org/chat"].kind == "language" and items["org/chat"].format == "repo"


def test_shards_are_one_model_and_stubs_and_pickles_are_handled(tmp_path):
    models = tmp_path / "ComfyUI-Shared" / "models"
    for n in (1, 2):
        safetensors(models / "diffusion_models" / f"big-0000{n}-of-00002.safetensors", FLUX)
    safetensors(models / "loras" / "tiny.safetensors", LORA, pad_to=10)  # under a megabyte
    (models / "checkpoints").mkdir(parents=True)
    (models / "checkpoints" / "old.ckpt").write_bytes(b"\0" * (2 * MB))
    (models / "node_modules").mkdir()
    safetensors(models / "node_modules" / "skipped.safetensors", FLUX)

    items = scan_folders(tools_for(tmp_path), []).items
    assert len(items) == 2  # the shards are one, the stub and node_modules are none
    big = next(i for i in items if i.path.endswith("big-00001-of-00002.safetensors"))
    assert big.kind == "diffusion" and big.size > 4 * MB  # both parts counted
    old = next(i for i in items if i.name == "old")
    assert old.format == "ckpt" and old.kind == "diffusion"  # named by its folder, never opened


def test_a_file_reached_through_two_tools_is_listed_once(tmp_path):
    real = safetensors(tmp_path / "ComfyUI-Shared" / "models" / "vae" / "a.safetensors", VAE)
    link_dir = tmp_path / ".unsloth" / "x"
    link_dir.mkdir(parents=True)
    (link_dir / "a.safetensors").symlink_to(real)
    items = scan_folders(tools_for(tmp_path), []).items
    assert len(items) == 1


def test_missing_folders_are_skipped_and_the_budget_stops_the_walk(tmp_path):
    assert scan_folders(tools_for(tmp_path), []).items == []
    models = tmp_path / "ComfyUI-Shared" / "models" / "loras"
    for n in range(20):
        safetensors(models / f"l{n}.safetensors", LORA)
    result = scan_folders(tools_for(tmp_path), [], Budget(seconds=10, files=5))
    assert result.truncated is True and len(result.items) < 20


def test_a_folder_that_asks_for_permission_waits_until_it_is_added(tmp_path):
    docs = tmp_path / "Documents" / "ComfyUI" / "models" / "vae"
    safetensors(docs / "v.safetensors", VAE)
    tools = tools_for(tmp_path)
    assert scan_folders(tools, []).items == []
    added = scan_folders(tools, [tmp_path / "Documents" / "ComfyUI" / "models"])
    assert [i.name for i in added.items] == ["v"]


# ---- what can be done with it -----------------------------------------------------------------


def entry(folder: str, name: str, size: int) -> ModelEntry:
    f = ModelFile(folder, name, "https://example.test/x", size, "0" * 64)
    return ModelEntry("demo", "wasifyai-image", "Demo image model", "Apache-2.0", "x", "", 8, (f,))


def found(path: Path, kind="diffusion", **kw) -> Found:
    return Found(id=path.name, name=path.stem, kind=kind, family="", format=path.suffix[1:],
                 quant="", size=path.stat().st_size, path=str(path), tool="comfyui",
                 tool_title="ComfyUI", **kw)  # fmt: skip


def test_states_say_what_can_be_done(tmp_path):
    models = tmp_path / "shared" / "models"
    unet = safetensors(models / "diffusion_models" / "demo.safetensors", FLUX)
    other = safetensors(models / "loras" / "x.safetensors", LORA)
    pickle = tmp_path / "old.ckpt"
    pickle.write_bytes(b"\0" * 10)
    llm = gguf(tmp_path / "m.gguf")

    items = [found(unet), found(other, "lora"), found(pickle), found(llm, "language")]
    cat = [entry("diffusion_models", "demo.safetensors", unet.stat().st_size)]
    assess(items, cat, [], machine=None)
    states = {i.id: i.state for i in items}
    assert states == {"demo.safetensors": "can_use", "x.safetensors": "can_use",
                      "old.ckpt": "unsupported", "m.gguf": "later"}  # fmt: skip
    assert items[0].use_root == str(models)
    assert "language engine" in items[3].reason

    # once the folder is one the app uses, it is ready
    assess(items, cat, [models], machine=None)
    assert items[0].state == "ready" and items[0].use_root is None


def test_a_model_that_cannot_fit_is_not_offered(tmp_path):
    from wasifyai_api.desktop_fit import Machine

    llm = gguf(tmp_path / "m.gguf", pad_to=4 * MB)
    item = found(llm, "language")
    assess([item], [], [], Machine("cpu", 1 * MB, 1 * MB))
    assert item.state == "unsupported" and item.fit and item.fit["verdict"] == "too_big"
    assert "will not run here" in item.reason

    # an image file that matches the catalogue is not offered either when it will not fit
    unet = safetensors(tmp_path / "models" / "diffusion_models" / "demo.safetensors", FLUX)
    cat = [entry("diffusion_models", "demo.safetensors", unet.stat().st_size)]
    image = found(unet)
    assess([image], cat, [], Machine("cpu", 4_000_000_000, 4_000_000_000))
    assert image.state == "unsupported" and image.use_root is None


# ---- running tools ----------------------------------------------------------------------------


async def test_only_servers_that_answer_are_reported(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 11434:
            return httpx.Response(200, json={"models": []})
        if request.url.port == 1234:
            return httpx.Response(500)
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found_ = await probe_servers(tools_for(tmp_path), client)
    assert [(s["tool"], s["kind"]) for s in found_] == [("ollama", "ollama")]


async def test_the_servers_are_asked_together_so_one_that_is_down_costs_its_wait_once(tmp_path):
    asked: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.port or 0)
        await asyncio.sleep(0.2)  # every server is slow to answer
        if request.url.port == 11434:
            return httpx.Response(200, json={"models": [{"name": "qwen3.8:27b-mlx"}]})
        raise httpx.ConnectError("refused")

    tools = tools_for(tmp_path)
    count = sum(1 for t in tools for x in t.servers if x["url"].startswith("http://127.0.0.1:"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        started = time.monotonic()
        found_ = await probe_servers(tools, client)
        took = time.monotonic() - started
    assert len(asked) == count > 1
    assert took < 0.2 * count * 0.75  # together, not one after another
    assert found_[0]["models"] == ["qwen3.8:27b-mlx"]


async def test_the_running_tools_are_found_at_start_before_the_folders_are_read(tmp_path):
    """A model chosen in Ollama is there as soon as the window asks (not after the slow scan)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 11434:
            return httpx.Response(200, json={"models": [{"name": "qwen3.8:27b-mlx"}]})
        raise httpx.ConnectError("refused")

    store = InMemorySettingsStore()
    svc = DiscoveryService(
        store,
        None,
        tools_for(tmp_path / "home"),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    svc.start(delay=60)  # the folder scan waits a minute; the servers do not
    try:
        for _ in range(50):
            if svc.servers:
                break
            await asyncio.sleep(0.02)
        assert [s["tool"] for s in svc.servers] == ["ollama"]
        assert svc.scanned_at is None  # the folders have not been read yet
    finally:
        await svc.stop()


# ---- the service ------------------------------------------------------------------------------


async def test_the_service_scans_saves_and_lets_a_file_be_used_in_place(tmp_path):
    home = tmp_path / "home"
    models_dir = home / "ComfyUI-Shared" / "models"
    unet = safetensors(models_dir / "diffusion_models" / "demo.safetensors", FLUX)
    store = InMemorySettingsStore()
    catalogue = [entry("diffusion_models", "demo.safetensors", unet.stat().st_size)]
    svc_models = ModelsService(catalogue, tmp_path / "app-models", (), store)
    await svc_models.load()
    svc = DiscoveryService(store, svc_models, tools_for(home))
    await svc.load()

    await svc.scan()
    state = svc.state()
    (item,) = state["items"]
    assert item["state"] == "can_use" and state["scanned"][0]["tool"] == "ComfyUI"
    assert svc_models.locate(catalogue[0].files[0]) is None  # not used yet

    root = await svc.use(item["id"])
    assert root == str(models_dir)
    assert svc_models.locate(catalogue[0].files[0]) is not None  # now it is, where it is
    assert unet.exists()  # and nothing was moved

    # a restart keeps the last result and the switch
    await svc.set_settings(False, [str(tmp_path / "extra")])
    again = DiscoveryService(store, svc_models, tools_for(home))
    await again.load()
    assert again.enabled is False and len(again.items) == 1
    assert again.folders == [tmp_path / "extra"]
    with pytest.raises(KeyError):
        await again.use("nope")


async def test_scans_do_not_overlap_and_a_failure_does_not_stick(tmp_path):
    svc = DiscoveryService(InMemorySettingsStore(), None, tools_for(tmp_path))
    await asyncio.gather(svc.scan(), svc.scan())
    assert svc.running is False and svc.scanned_at is not None


def test_a_tools_own_format_that_llama_cpp_cannot_read_is_said_so(tmp_path):
    ollama = gguf(tmp_path / "blob", arch="gptoss", name="gpt-oss 20B")
    item = found(ollama, "language")
    item.family, item.format = "gptoss", "gguf"
    assess([item], [], [], machine=None)
    assert item.state == "unsupported" and "own format" in item.reason


def test_a_missing_chat_template_is_detected_without_loading_the_tokenizer(tmp_path):
    from wasifyai_api.desktop_discovery import gguf_has_chat_template

    plain = gguf(tmp_path / "plain.gguf")  # the helper writes no template
    assert gguf_has_chat_template(plain) is False
    junk = tmp_path / "junk.gguf"
    junk.write_bytes(b"not a model")
    assert gguf_has_chat_template(junk) is None


# ---- LoRAs (stage C) ---------------------------------------------------------------------------

LORA = ["lora_unet_double_blocks_0.lora_down.weight", "lora_unet_double_blocks_0.lora_up.weight"]


def lora_found(path: Path) -> Found:
    return found(path, "lora")


def test_a_lora_in_a_loras_folder_of_a_used_models_folder_is_ready(tmp_path):
    from wasifyai_api.desktop_discovery import lora_location

    root = tmp_path / "shared"
    ink = safetensors(root / "loras" / "style" / "ink.safetensors", LORA)
    assert lora_location(ink) == (root, "style/ink.safetensors")

    item = lora_found(ink)
    assess([item], [], [root], machine=None)
    assert item.state == "ready" and item.lora_name == "style/ink.safetensors"

    # not a folder the engine reads yet: one click adds the models folder
    other = lora_found(ink)
    assess([other], [], [], machine=None)
    assert (other.state, other.use, other.use_root) == ("can_use", "folder", str(root))
    assert "FLUX.2 klein" in other.reason


def test_a_lora_outside_a_loras_folder_or_with_an_odd_name_is_not_offered(tmp_path):
    from wasifyai_api.desktop_discovery import lora_location

    loose = safetensors(tmp_path / "somewhere" / "ink.safetensors", LORA)
    item = lora_found(loose)
    assess([item], [], [tmp_path], machine=None)
    assert item.state == "unsupported" and "`loras` folder" in item.reason

    odd = safetensors(tmp_path / "m" / "loras" / "in$k.safetensors", LORA)
    assert lora_location(odd) is None


def test_the_apps_own_loras_folder_is_looked_in(tmp_path):
    from wasifyai_api.desktop_discovery import resolve_tools

    models = tmp_path / "app-models"
    safetensors(models / "loras" / "mine.safetensors", LORA)
    tools = [Tool("app", "Wasify AI", "files", [models / "language", models / "loras"])]
    items = scan_folders(tools, []).items
    assert [(i.name, i.kind) for i in items] == [("mine", "lora")]
    assert resolve_tools  # (the data file's tools are unchanged)
