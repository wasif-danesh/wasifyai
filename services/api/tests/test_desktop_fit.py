"""Will it fit? (ADR-0063): the machine, what a model asks for, and the verdict."""

import pytest
from wasifyai_api.desktop_fit import (
    GB,
    Machine,
    assess_fit,
    kv_cache_bytes,
    need_declared,
    need_of_image,
    need_of_language,
    parse_nvidia_smi,
    parse_vm_stat,
)

MAC = Machine("unified", 36 * GB, 20 * GB)


def test_the_mac_free_memory_is_read_from_vm_stat():
    text = (
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free:                               100000.\n"
        "Pages active:                             500000.\n"
        "Pages inactive:                            50000.\n"
        "Pages speculative:                         10000.\n"
    )
    assert parse_vm_stat(text) == 160_000 * 16384
    assert parse_vm_stat("nothing useful") is None


def test_the_card_with_the_most_memory_is_the_one_used():
    out = "8192, 7000\n24576, 20000\n"
    assert parse_nvidia_smi(out) == (24576 * 1024 * 1024, 20000 * 1024 * 1024)
    assert parse_nvidia_smi("not, numbers") is None


def test_the_kv_cache_is_keys_and_values_in_sixteen_bits():
    # 32 layers, 8 kv heads of 128, 8192 tokens: 2 * 32 * 8 * 128 * 8192 * 2 bytes = 1 GiB
    assert kv_cache_bytes(32, 8, 128, 8192) == 1_073_741_824


def test_a_language_model_is_its_weights_plus_cache_plus_runtime():
    need = need_of_language(4 * GB, layers=32, kv_heads=8, head_dim=128, context=131072)
    assert need.estimate is True and need.spills is True
    # context is judged at the chat default (8192), not at the model's largest
    assert need.bytes == 4 * GB + 1_073_741_824 + int(0.6 * GB)


def test_a_model_that_fits_says_how_much_it_needs_and_how_much_is_free():
    fit = assess_fit(need_declared(12), MAC)
    assert fit.verdict == "fits" and fit.estimate is False
    assert "12 GB" in fit.reason and "free" in fit.reason


def test_tight_when_it_fits_the_computer_but_not_what_is_free_now():
    fit = assess_fit(need_declared(24), MAC)  # 36 GB total, 20 GB available, 27 GB budget cap
    assert fit.verdict == "tight"
    assert "24 GB" in fit.reason and "20 GB is free" in fit.reason


def test_too_big_when_it_cannot_fit_even_with_everything_closed():
    fit = assess_fit(need_declared(40), MAC)
    assert fit.verdict == "too_big" and fit.capacity_bytes == int(0.9 * 36 * GB)
    assert "will not run here" in fit.reason


def test_the_apps_own_loaded_model_counts_as_free():
    # 6 GB looks free, but 14 GB more is the app's own model, which is unloaded first
    loaded = Machine("unified", 36 * GB, 6 * GB, reclaimable_bytes=14 * GB)
    assert assess_fit(need_declared(17), loaded).verdict == "fits"
    assert assess_fit(need_declared(17), Machine("unified", 36 * GB, 6 * GB)).verdict == "tight"


def test_an_nvidia_card_judges_by_its_own_memory():
    card = Machine("cuda", 64 * GB, 50 * GB, gpu_total_bytes=12 * GB, gpu_free_bytes=11 * GB)
    assert assess_fit(need_declared(10), card).verdict == "fits"
    assert assess_fit(need_declared(30), card).verdict == "too_big"  # an image model cannot spill


def test_a_language_model_may_spill_from_the_card_into_memory_and_says_so():
    card = Machine("cuda", 64 * GB, 50 * GB, gpu_total_bytes=12 * GB, gpu_free_bytes=11 * GB)
    fit = assess_fit(need_of_language(20 * GB), card)
    assert fit.verdict == "fits" and fit.partly_on_cpu
    assert "processor" in fit.reason


def test_a_computer_whose_memory_cannot_be_read_is_not_blocked():
    fit = assess_fit(need_declared(24), Machine("cpu", None, None))
    assert fit.verdict == "fits" and "not checked" in fit.reason


@pytest.mark.parametrize(("video", "extra"), [(False, 3), (True, 6)])
def test_an_image_or_video_file_adds_working_memory(video, extra):
    need = need_of_image(10 * GB, video=video)
    assert need.bytes == int(10 * GB * 1.15) + extra * GB and need.estimate is True


async def test_a_real_image_job_that_cannot_fit_is_refused_before_anything_loads():
    from types import SimpleNamespace

    from wasifyai_api.desktop import FitGuardRunner

    class Refused(Exception):
        def __init__(self, code: str, message: str):
            super().__init__(message)
            self.code = code

    class Inner:
        backend = "comfyui"
        ran = 0

        async def run(self, job, on_progress, files=None):
            Inner.ran += 1
            return {}

    entry = SimpleNamespace(approx_ram_gb=24, product_id="wasifyai-image", title="FLUX.2 klein 4B")

    def models(machine: Machine):
        async def read() -> Machine:
            return machine

        return SimpleNamespace(catalogue={"k": entry}, machine=read)

    installed = SimpleNamespace(installed=True)
    guard = FitGuardRunner(Inner(), installed, models(Machine("cpu", 8 * GB, 8 * GB)), Refused)
    with pytest.raises(Refused) as e:
        await guard.run(object(), None)
    assert e.value.code == "model_too_big" and "FLUX.2 klein 4B will not fit" in str(e.value)
    assert Inner.ran == 0

    # a computer that can hold it, and the placeholder engine (nothing installed), both run
    ok = FitGuardRunner(Inner(), installed, models(Machine("cpu", 64 * GB, 60 * GB)), Refused)
    await ok.run(object(), None)
    placeholder = FitGuardRunner(
        Inner(), SimpleNamespace(installed=False), models(Machine("cpu", 8 * GB, 8 * GB)), Refused
    )
    await placeholder.run(object(), None)
    assert Inner.ran == 2
