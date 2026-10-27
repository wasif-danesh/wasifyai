"""What each job kind does: fetch the inputs from storage, call the engine, put the outputs back.

A job never names a path on the worker: the engine's calls that take a `Path` get a file in a
temporary folder that is removed on every exit path. Every key a job names must be under the job's
own prefix (the person's), or the job is refused."""

import asyncio
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import (
    EngineError,
    EngineJob,
    EngineOutcome,
    VoiceEngineError,
    VoiceRequestError,
    admin_wire,
    builder_wire,
    model3d_wire,
    speech_wire,
    train_wire,
)

Storage = Any  # wasifyai_platform_sdk.Storage: get(key) / put(key, data, content_type)
Report = Callable[[float, str], Awaitable[None]]


class Refused(Exception):
    pass


class Failed(Exception):
    """A component said no, with the code and the sentence to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class Work:
    """One job's inputs and outputs."""

    def __init__(
        self, job: EngineJob, storage: Storage, folder: Path, report: Report | None = None
    ):
        self.job = job
        self._storage = storage
        self.folder = folder
        self._report = report
        self.outputs: dict[str, str] = {}
        self._pending: set[asyncio.Future[None]] = set()

    def report_soon(self, fraction: float, label: str) -> None:
        """Tell the API how far the job is, from code that is not async (a progress callback)."""
        if self._report is not None:
            self._pending.add(task := asyncio.ensure_future(self._report(fraction, label)))
            task.add_done_callback(self._pending.discard)

    @property
    def storage(self) -> Storage:
        return self._storage

    def _checked(self, key: str) -> str:
        if not key.startswith(self.job.prefix) or ".." in key:
            raise Refused("That file is not part of this job.")
        return key

    async def file(self, name: str) -> Path:
        """An input as a file on this machine."""
        key = self.job.files.get(name)
        if key is None:
            raise Refused(f"The job has no {name}.")
        path = self.folder / name
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        data = await self._storage.get(self._checked(key))
        await asyncio.to_thread(path.write_bytes, data)
        return path

    async def read(self, name: str) -> bytes:
        return await asyncio.to_thread((await self.file(name)).read_bytes)

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        key = self._checked(f"{self.job.prefix}/out/{name}")
        await self._storage.put(key, data, content_type)
        self.outputs[name] = key


Handler = Callable[[Any, Work], Awaitable[dict[str, Any]]]


def _model(engine: Any, kind: str, p: dict[str, Any]) -> Any:
    return engine.resolve(speech_wire.TASK[kind], p.get("model_id"))


async def _speak(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.speak(
        _model(engine, speech_wire.SPEAK, p), p["text"], p.get("voice"), p.get("options") or {},
        beside=bool(p.get("beside")),
    )  # fmt: skip
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _design(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.design(
        _model(engine, speech_wire.DESIGN, p), p["text"], p["description"], p.get("options") or {}
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _clone(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.clone(
        _model(engine, speech_wire.CLONE, p), p["text"], await w.file("reference"),
        p.get("reference_text"), p.get("options") or {},
    )  # fmt: skip
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _music(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.music(
        _model(engine, speech_wire.MUSIC, p), speech_wire.music_request(p["request"])
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.music_meta(r)


async def _music_edit(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.music_edit(
        _model(engine, speech_wire.MUSIC_EDIT, p),
        speech_wire.music_edit_request(p["request"]),
        await w.file("source"),
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.music_meta(r)


async def _transcribe(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.transcribe(
        _model(engine, speech_wire.TRANSCRIBE, p), await w.read("audio"), p.get("options") or {},
        beside=bool(p.get("beside")),
    )  # fmt: skip
    return speech_wire.transcript_meta(r)


async def _separate(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.separate(
        _model(engine, speech_wire.SEPARATE, p),
        speech_wire.separate_request(p["request"]),
        await w.file("source"),
    )
    for i, stem in enumerate(r.stems):
        await w.put(f"stem_{i}", stem.wav, "audio/wav")
    return speech_wire.separate_meta(r)


async def _convert(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.convert(
        _model(engine, speech_wire.CONVERT, p),
        speech_wire.convert_request(p["request"]),
        await w.file("source"),
        await w.file("reference"),
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _speech_edit(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.speech_edit(
        _model(engine, speech_wire.SPEECH_EDIT, p),
        speech_wire.speech_edit_request(p["request"]),
        await w.file("source"),
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _lipsync(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.lipsync(
        _model(engine, speech_wire.LIPSYNC, p),
        speech_wire.lipsync_request(p["request"]),
        await w.file("picture"),
        await w.file("voice"),
    )
    await w.put("video", r.mp4, "video/mp4")
    return speech_wire.lipsync_meta(r)


async def _matte(service: Any, w: Work) -> dict[str, Any]:
    picture = await w.file("picture")
    res = await service.matte(picture, w.folder)
    if not res.ok or res.output is None:
        raise Failed(res.reason or "engine_failed", res.message or "The cut-out did not work.")
    await w.put("cutout", await asyncio.to_thread(res.output.read_bytes), "image/png")
    return {"seconds": res.seconds, "peak_gb": res.peak_gb}


async def _generate(service: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    cutout = await w.file("cutout")
    glb = w.folder / "model.glb"
    res = await service.generate(
        cutout, glb, seed=int(p.get("seed", 42)), detail=str(p.get("detail", "standard")),
        on_progress=w.report_soon,
    )  # fmt: skip
    if not res.ok or not glb.is_file():
        raise Failed(res.reason or "engine_failed", res.message or "The 3D run did not finish.")
    await w.put("glb", await asyncio.to_thread(glb.read_bytes), "model/gltf-binary")
    return {"seconds": res.seconds, "peak_gb": res.peak_gb}


def _page(service: Any, w: Work, template: str, slots: dict[str, Any]) -> Path:
    """The composition's folder, made here from its template and slots: the worker has the library
    and the fonts, the API only has the words."""
    from wasifyai_video.builder import projects, templates

    gsap = service.gsap()
    if gsap is None:
        raise Failed("not_ready", "Motion graphics is not set up on the worker.")
    fonts = service.fonts(templates.FONT_FILES)
    folder = w.folder / "project"
    projects.write_project(folder, template, slots, gsap, fonts)
    return folder


async def _inspect(service: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    folder = await asyncio.to_thread(_page, service, w, p["template"], p["slots"])
    report = await service.inspect(folder, p["spec"])
    return {"report": report}


async def _snapshot(service: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    folder = await asyncio.to_thread(_page, service, w, p["template"], p["slots"])
    work = w.folder / "still"
    res = await service.snapshot(folder, work, float(p["at"]))
    pngs = sorted(work.rglob("*.png")) if res.ok else []
    if not pngs:
        raise Failed(res.reason or "preview_failed", res.message or "No preview.")
    await w.put("still", await asyncio.to_thread(pngs[0].read_bytes), "image/png")
    return {"seconds": res.seconds}


async def _render(service: Any, w: Work) -> dict[str, Any]:
    import re

    p = w.job.params
    fmt = str(p.get("format", "mp4"))
    folder = await asyncio.to_thread(_page, service, w, p["template"], p["slots"])
    out = w.folder / f"video.{fmt}"
    seen = re.compile(r"(\d{1,3})\s*%")

    def on_progress(line: str) -> None:
        hits = seen.findall(line)
        if hits:
            w.report_soon(min(int(hits[-1]), 100) / 100, "Drawing")

    res = await service.render(folder, out, on_progress, ("--format", fmt))
    numbers = {
        "seconds": res.seconds, "peak_rss_bytes": res.peak_rss_bytes,
        "blocked_count": res.blocked_count, "reason": res.reason, "message": res.message,
        "ok": res.ok,
    }  # fmt: skip
    if res.ok and out.is_file():
        await w.put("video", await asyncio.to_thread(out.read_bytes), f"video/{fmt}")
    return numbers


async def _lint(service: Any, w: Work) -> dict[str, Any]:
    folder = w.folder / "lint"
    await asyncio.to_thread(folder.mkdir)
    await asyncio.to_thread((folder / "index.html").write_text, str(w.job.params["html"]))
    return {"findings": await asyncio.to_thread(service.lint, folder)}


async def _train_video(train: Any, w: Work) -> dict[str, Any]:
    """Teach the video model from the job's pictures and clips; the adapter goes back to storage."""
    from wasifyai_training.trainer import Stopped
    from wasifyai_training.video import VideoJob, VideoMedia

    trainer = train.video
    if trainer is None or not trainer.ready():
        raise Failed(
            "not_ready",
            (trainer.problem() if trainer else None)
            or "Video training is not set up on this worker.",
        )
    p = w.job.params
    media = [
        VideoMedia(
            await w.file(it["name"]), it["kind"], it["caption"], float(it.get("seconds") or 0)
        )
        for it in p["items"]
    ]
    job = VideoJob(
        str(p["word"]), media, int(p["width"]), int(p["height"]), int(p["window_frames"]),
        int(p["steps"]), bool(p["checkpointing"]), rank=int(p["rank"]), lr=float(p["lr"]),
    )  # fmt: skip
    steps = max(1, job.steps)

    def report(step: int, stage: str) -> None:
        w.report_soon(min(1.0, step / steps), stage)

    try:
        res = await trainer.train(job, w.folder / "run", report)
    except Stopped:
        raise Failed("cancelled", "Stopped.") from None
    except RuntimeError as e:  # the tool's own sentence
        raise Failed("train_failed", str(e)) from None
    await w.put(
        "adapter", await asyncio.to_thread(res.adapter.read_bytes), "application/octet-stream"
    )
    return {
        "seconds": res.seconds,
        "peak_bytes": res.peak_bytes,
        "loss_first": res.loss_first,
        "loss_last": res.loss_last,
    }


async def _train_image(train: Any, w: Work) -> dict[str, Any]:
    """Teach the picture model from the job's pictures; the samples go to storage as they appear."""
    from wasifyai_training.trainer import Stopped, TrainJob

    trainer = train.image
    if trainer is None or not trainer.ready():
        raise Failed(
            "not_ready",
            (trainer.problem() if trainer else None)
            or "Picture training is not set up on this worker.",
        )
    p = w.job.params
    pictures = [await w.file(name) for name in p["pictures"]]
    run = w.folder / "run"
    job = TrainJob(
        kind=str(p["kind"]), word=str(p["word"]), steps=int(p["steps"]), pictures=pictures,
        captions=list(p["captions"]), samples=run / "samples",
        settings=dict(p.get("settings") or {}),
    )  # fmt: skip
    steps = max(1, job.steps)
    loop = asyncio.get_running_loop()
    uploads: list[Any] = []

    def report(step: int, stage: str) -> None:
        w.report_soon(min(1.0, step / steps), stage)

    def sample(name: str) -> None:
        """Called from the trainer's own thread: the picture goes to storage at once."""

        async def up() -> None:
            data = await asyncio.to_thread((job.samples / name).read_bytes)
            await w.put(f"samples/{name}", data, "image/png")

        uploads.append(asyncio.run_coroutine_threadsafe(up(), loop))

    try:
        res = await trainer.train(job, report, sample)
    except Stopped:
        raise Failed("cancelled", "Stopped.") from None
    except RuntimeError as e:  # the tool's own sentence
        raise Failed("train_failed", str(e)) from None
    await asyncio.gather(*(asyncio.wrap_future(f) for f in uploads))
    await w.put(
        "adapter", await asyncio.to_thread(res.adapter.read_bytes), "application/octet-stream"
    )
    return {"seconds": res.seconds, "peak_bytes": res.peak_bytes}


async def _tokenize(train: Any, w: Work) -> dict[str, Any]:
    trainer = train.image
    if trainer is None:
        raise Failed("not_ready", "Picture training is not set up on this worker.")
    return {"words": await trainer.tokenize([str(x) for x in w.job.params["words"]]) or {}}


async def _train_decision(train: Any, w: Work) -> dict[str, Any]:
    """Teach a decision model from the job's rows; its files go to storage as the job's outputs."""
    from wasifyai_training.decision import DecisionJob, Row, question_of
    from wasifyai_training.decisions import said_out
    from wasifyai_training.language import Stopped

    trainer = train.decision
    p = w.job.params
    base = str(p["base"])
    if trainer is None or not trainer.ready(base):
        raise Failed(
            "not_ready",
            (trainer.problem(base) if trainer else None)
            or "Decision training is not set up on this worker.",
        )
    job = DecisionJob(
        question_of(p["question"]), [Row(t, a) for t, a in p["train"]],
        [Row(t, a) for t, a in p["held"]], int(p["epochs"]), int(p["steps"]), list(p["peek"]),
    )  # fmt: skip
    steps = max(1, job.steps)

    def report(step: int, stage: str) -> None:
        w.report_soon(min(1.0, step / steps), stage)

    try:
        res = await trainer.train(job, base, w.folder / "run", report)
    except Stopped:
        raise Failed("cancelled", "Stopped.") from None
    except RuntimeError as e:  # the tool's own sentence
        raise Failed("train_failed", str(e)) from None
    folder = Path(res.folder)
    files = await asyncio.to_thread(lambda: sorted(p for p in folder.rglob("*") if p.is_file()))
    for f in files:
        data = await asyncio.to_thread(f.read_bytes)
        await w.put(f"model/{f.relative_to(folder).as_posix()}", data, "application/octet-stream")
    return {
        "seconds": res.seconds, "peak_bytes": res.peak_bytes, "bytes": res.bytes, "loss": res.loss,
        "before": [said_out(s) for s in res.before], "after": [said_out(s) for s in res.after],
        "peek_before": [said_out(s) for s in res.peek_before],
        "peek_after": [said_out(s) for s in res.peek_after],
    }  # fmt: skip


async def _decision_answer(train: Any, w: Work) -> dict[str, Any]:
    """A decision model (the person's own, or its base) answering the texts of the job."""
    from wasifyai_training.decision import question_of
    from wasifyai_training.decisions import said_out

    trainer = train.decision
    if trainer is None or train.cache is None:
        raise Failed("not_ready", "Decision models are not set up on this worker.")
    p = w.job.params
    if p.get("base"):
        folder = trainer.base_folder(str(p["base"]))
        if folder is None:
            raise Failed("not_ready", "The model it started from is not on this worker.")
    else:
        try:
            folder = await train.cache.folder(
                w.storage, w.job.tenant_id, w.job.user_id, str(p["model_id"])
            )
        except (FileNotFoundError, ValueError):
            raise Failed("gone", "The taught model's files are gone.") from None
    try:
        said = await trainer.answer(
            folder, question_of(p["question"]), [str(t) for t in p["texts"]]
        )
    except RuntimeError as e:
        raise Failed("not_ready", str(e)) from None
    return {"answers": [said_out(s) for s in said]}


async def _train_writing(train: Any, w: Work) -> dict[str, Any]:
    """Teach a writing model from the job's examples; its adapter goes back as the job's outputs."""
    from wasifyai_training.language import LanguageJob, Stopped

    trainer = train.writing
    p = w.job.params
    base = str(p["base"])
    if trainer is None or not trainer.ready(base):
        raise Failed(
            "not_ready",
            (trainer.problem(base) if trainer else None)
            or "Writing models are not set up on this worker.",
        )
    job = LanguageJob(
        list(p["train"]), list(p["valid"]), int(p["steps"]), list(p["questions"]),
        batch=int(p.get("batch") or 2),
    )  # fmt: skip
    steps = max(1, job.steps)

    def report(step: int, stage: str) -> None:
        w.report_soon(min(1.0, step / steps), stage)

    try:
        res = await trainer.train(job, base, w.folder / "run", report)
    except Stopped:
        raise Failed("cancelled", "Stopped.") from None
    except RuntimeError as e:  # the tool's own sentence
        raise Failed("train_failed", str(e)) from None
    folder = Path(res.adapter)
    files = await asyncio.to_thread(lambda: sorted(p for p in folder.iterdir() if p.is_file()))
    for f in files:
        await w.put(
            f"adapter/{f.name}", await asyncio.to_thread(f.read_bytes), "application/octet-stream"
        )
    return {
        "seconds": res.seconds, "peak_bytes": res.peak_bytes, "first_val": res.first_val,
        "last_val": res.last_val, "last_train": res.last_train,
    }  # fmt: skip


async def _writing_answer(train: Any, w: Work) -> dict[str, Any]:
    """The base model (or with the adapter the job brings) answering the job's questions."""
    trainer = train.writing
    if trainer is None:
        raise Failed("not_ready", "Writing models are not set up on this worker.")
    p = w.job.params
    adapter = None
    names = [n for n in w.job.files if n.startswith("a/")]
    if names:
        adapter = w.folder / "adapter"
        await asyncio.to_thread(adapter.mkdir, parents=True, exist_ok=True)
        for n in names:
            src = await w.file(n)
            await asyncio.to_thread(src.replace, adapter / n.removeprefix("a/"))
    try:
        answers = await trainer.answer(
            str(p["base"]),
            [str(q) for q in p["questions"]],
            adapter,
            int(p.get("max_tokens") or 120),
        )
    except RuntimeError as e:
        raise Failed("not_ready", str(e)) from None
    return {"answers": answers}


async def _fetch_model(admin: Any, w: Work) -> dict[str, Any]:
    async def report(fraction: float, label: str) -> None:
        w.report_soon(fraction, label)

    return await admin.fetch_model(str(w.job.params["model_id"]), report)  # type: ignore[no-any-return]


async def _fetch_engine(admin: Any, w: Work) -> dict[str, Any]:
    async def report(fraction: float, label: str) -> None:
        w.report_soon(fraction, label)

    return await admin.fetch_engine(str(w.job.params["name"]), report)  # type: ignore[no-any-return]


HANDLERS: dict[str, Handler] = {
    admin_wire.FETCH_MODEL: _fetch_model,
    admin_wire.FETCH_ENGINE: _fetch_engine,
    builder_wire.INSPECT: _inspect,
    builder_wire.SNAPSHOT: _snapshot,
    builder_wire.RENDER: _render,
    builder_wire.LINT: _lint,
    model3d_wire.MATTE: _matte,
    model3d_wire.GENERATE: _generate,
    train_wire.VIDEO: _train_video,
    train_wire.IMAGE: _train_image,
    train_wire.IMAGE_TOKENIZE: _tokenize,
    train_wire.DECISION: _train_decision,
    train_wire.DECISION_ANSWER: _decision_answer,
    train_wire.WRITING: _train_writing,
    train_wire.WRITING_ANSWER: _writing_answer,
    speech_wire.SPEAK: _speak,
    speech_wire.DESIGN: _design,
    speech_wire.CLONE: _clone,
    speech_wire.MUSIC: _music,
    speech_wire.MUSIC_EDIT: _music_edit,
    speech_wire.TRANSCRIBE: _transcribe,
    speech_wire.SEPARATE: _separate,
    speech_wire.CONVERT: _convert,
    speech_wire.SPEECH_EDIT: _speech_edit,
    speech_wire.LIPSYNC: _lipsync,
}


def _engine_for(engines: Any, kind: str) -> Any:
    """The component a kind runs on: `speech.*` on the speech engine, `model3d.*` on the 3D service,
    `admin.*` on the worker's own set-up component, `train.*` on its trainers.
    A single engine (not a mapping) is the speech engine."""
    if isinstance(engines, Mapping):
        return engines[kind.split(".", 1)[0]]
    return engines


async def run_job(
    engines: Any, storage: Storage, job: EngineJob, worker: str, report: Report | None = None
) -> EngineOutcome:
    """Run one job to an outcome. Nothing escapes: a failure is an outcome with a safe message."""
    import logging
    import time

    log = logging.getLogger("wasifyai_engine_worker")
    t0 = time.monotonic()
    handler = HANDLERS.get(job.kind)
    if handler is None:
        return EngineOutcome(
            id=job.id, ok=False, worker=worker,
            error=EngineError(code="unknown_job", message="This worker cannot do that."),
        )  # fmt: skip
    try:
        with tempfile.TemporaryDirectory(prefix="wasifyai-engine-") as tmp:
            work = Work(job, storage, Path(tmp), report)
            meta = await handler(_engine_for(engines, job.kind), work)
            return EngineOutcome(
                id=job.id, ok=True, outputs=work.outputs, meta=meta, worker=worker,
                seconds=time.monotonic() - t0,
            )  # fmt: skip
    except (VoiceEngineError, VoiceRequestError) as e:
        return EngineOutcome(
            id=job.id, ok=False, worker=worker, seconds=time.monotonic() - t0,
            error=EngineError(code=e.code, message=str(e)),
        )  # fmt: skip
    except Failed as e:
        return EngineOutcome(
            id=job.id, ok=False, worker=worker, seconds=time.monotonic() - t0,
            error=EngineError(code=e.code, message=e.message),
        )  # fmt: skip
    except Refused as e:
        return EngineOutcome(
            id=job.id, ok=False, worker=worker,
            error=EngineError(code="refused", message=str(e)),
        )  # fmt: skip
    except Exception:
        log.exception("job %s (%s) failed", job.id, job.kind)
        return EngineOutcome(
            id=job.id, ok=False, worker=worker, seconds=time.monotonic() - t0,
            error=EngineError(code="engine_failed", message="The speech worker could not do that."),
        )  # fmt: skip
