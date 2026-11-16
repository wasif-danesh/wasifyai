"""What the meetings product needs at run time: its store, the speaker model's file, the speech
runtime (the voice product's chosen transcription model, `state.audio`), and the one job that makes
a meeting from a recording (rule 6: it runs in the background and says where it is).

A meeting from a file goes: read the recording (one channel, 16 kHz) -> tell the speakers apart
(Sortformer, on the processor) -> write it down (the chosen speech model) -> put the two together ->
add it to search. The desktop runs one such job at a time.

On the web (stage MT6, ADR-0108 decisions 7 and 13) a meeting is made from a file only: the rows are
in Postgres, the recording in object storage, and the work in a scratch folder. There is no speaker
model there: the cloud transcription model the admin chose (Admin › Media) tells the speakers apart
as it writes the meeting down, on the provider's key. Each person makes one meeting at a time."""

import asyncio
import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    TranscriptSegment,
    VoiceEngineError,
    VoiceRequestError,
    check_transcribe,
    languages,
    search_text,
)
from wasifyai_platform_sdk.context import RunContext, reset_context, set_context
from wasifyai_platform_sdk.route_usage import RouteUsage
from wasifyai_platform_sdk.storage import object_key
from wasifyai_platform_sdk.voice_models import check_language

from wasifyai_meetings import audio, channels
from wasifyai_meetings.asking import AskJobs
from wasifyai_meetings.merge import merge, merge_two, pieces, plain_text
from wasifyai_meetings.people import make_prints
from wasifyai_meetings.reports import ReportJobs
from wasifyai_meetings.sortformer import BadAudio, Sortformer, Stopped, Turn, Wav, wav_bytes
from wasifyai_meetings.store import MeetingStore, NotFound
from wasifyai_meetings.voiceprint import Voiceprints

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-meetings"
KIND = "meeting"
# the speaker model, as the product's `models.yaml` lists it (fetched in Models, after a click)
SPEAKER_MODEL = "sortformer-4spk-v2.1"
SPEAKER_FILE = ("meetings", "diar_streaming_sortformer_4spk-v2.1.onnx")
# the voiceprint model (MT3): knows a named person again in later meetings; optional
VOICEPRINT_MODEL = "eres2net-voxceleb"
VOICEPRINT_FILE = ("meetings", "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx")
INDEX_CHARS = 4000
REPORT_INDEX_CHARS = 1500
# how the bar is shared between the steps (from MT0b: speakers ~70x real time, Parakeet ~30x)
SHARE = {"read": 0.05, "speakers": 0.35, "words": 0.55, "save": 0.05}


CLOUD_TRANSCRIBE = "key:transcribe"  # the cloud transcription model (ADR-0100), by its voice id
STALE_MIN = 60.0  # on the web, work left `working` this long by a gone replica is failed


@dataclass(frozen=True)
class WebMeetings:
    """The web's meetings (MT6): a scratch folder for the work, and the object storage the
    recordings are kept in (rule 10)."""

    tmp_dir: Path
    storage: Any  # wasifyai_platform_sdk.storage.Storage


def web_of(state: Any) -> WebMeetings | None:
    return state.meetings_web  # type: ignore[no-any-return]


def is_cloud(model: Any) -> bool:
    return getattr(model, "id", "") == CLOUD_TRANSCRIBE


class NotAvailable(Exception):
    """Meetings are not served by this deployment (no desktop engine yet)."""


class Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


RECORDINGS = (
    "recordings"  # where the window's shell writes a recording (`rec-….wav`; `.part` while on)
)
_RECORDING_NAME = re.compile(r"rec-[0-9A-Za-z-]{1,64}\.wav")


def recording_in(state: Any, name: str) -> Path | None:
    """A finished recording the shell left in the meetings folder, by its name; None for any other
    name (a path, a file of the window's own choosing, one still being written)."""
    if not _RECORDING_NAME.fullmatch(name) or web_of(state) is not None:
        return None
    path = root_for(state) / RECORDINGS / name
    return path if path.is_file() else None


def waiting_recordings(state: Any) -> list[dict[str, Any]]:
    """Recordings not made into a meeting yet (the window was closed, or making one failed to
    start): newest first, with their length. None on the web (the browser does not record yet)."""
    if web_of(state) is not None:
        return []
    folder = root_for(state) / RECORDINGS
    out = []
    for p in folder.glob("rec-*.wav") if folder.is_dir() else ():
        if not _RECORDING_NAME.fullmatch(p.name):
            continue
        st = p.stat()
        out.append({
            "name": p.name, "bytes": st.st_size,
            "seconds": round(max(0, st.st_size - 44) / 4 / 16000, 1), "modified": st.st_mtime,
        })  # fmt: skip
    return sorted(out, key=lambda r: r["modified"], reverse=True)


def root_for(state: Any) -> Path:
    """The desktop's meetings folder, or the web's scratch folder."""
    web = web_of(state)
    if web is not None:
        return web.tmp_dir
    data = state.desktop_dir
    if not data:
        raise NotAvailable("Meetings are not available here.")
    return Path(data) / "meetings"


def store_for(state: Any) -> MeetingStore:
    existing = state.meetings_store
    if existing is None:
        if web_of(state) is not None:  # made when the web starts (assemble)
            raise NotAvailable("Meetings are not ready yet. Try again in a moment.")
        existing = MeetingStore.in_folder(root_for(state))
        state.meetings_store = existing
    return existing  # type: ignore[no-any-return]


def _model_file(state: Any, where: tuple[str, str]) -> Path | None:
    models = state.desktop_models
    roots = list(models.roots()) if models is not None else []
    if state.desktop_dir:
        roots.append(Path(state.desktop_dir) / "models")
    for root in roots:
        path = Path(root) / where[0] / where[1]
        if path.is_file():
            return path
    return None


def speaker_model_path(state: Any) -> Path | None:
    """The speaker model's file when it is on this computer (any of the model folders)."""
    return _model_file(state, SPEAKER_FILE)


def voiceprint_model_path(state: Any) -> Path | None:
    """The voiceprint model's file when it is on this computer."""
    return _model_file(state, VOICEPRINT_FILE)


_VOICES: dict[Path, Voiceprints] = {}
_VOICES_LOCK = threading.Lock()


def voices_for(state: Any) -> Voiceprints | None:
    """The voiceprint model, loaded once (26 MB); None when it is not on this computer."""
    path = voiceprint_model_path(state)
    if path is None:
        return None
    with _VOICES_LOCK:
        if path not in _VOICES:
            _VOICES[path] = Voiceprints(path)
        return _VOICES[path]


def ensure_prints(state: Any, identity: Identity, row: dict[str, Any]) -> bool:
    """Make the voiceprints of a finished meeting's speakers if they are not made yet (a meeting
    made before the voiceprint model was fetched), from its kept recording. Whether there are some
    now. Runs in a thread."""
    store = store_for(state)
    t, u = identity.tenant_id, identity.user_id
    if row.get("status") != "done" or store.prints_made(t, u, row["id"]):
        return store.prints_made(t, u, row["id"])
    voices = voices_for(state)
    wav = recording_of(state, identity, row["id"])
    if voices is None or wav is None:
        return False
    try:
        prints = make_prints(
            voices, {}, wav, row["lines"], row["speakers"], row.get("source", "file")
        )
    except Exception:
        log.warning("the voiceprints of a meeting could not be made", exc_info=True)
        return False
    store.save_prints(t, u, row["id"], prints)
    return True


def speech_for(state: Any) -> Any | None:
    return state.audio


def ready_speech_models(speech: Any) -> list[dict[str, Any]]:
    """The speech-to-text models on this computer, ready to use, with the languages each writes down
    (what the screen offers a language from)."""
    listed = getattr(speech, "models", None)
    if listed is None:
        return []
    return [
        {"id": m["id"], "title": m["title"], "languages": list(m.get("languages") or [])}
        for m in listed("transcribe")
        if m.get("state") == "ready"
    ]


def model_for(speech: Any, language: str, model: str | None) -> Any:
    """The model that writes a meeting down: the one asked for; else the chosen one for Voice when
    it knows the meeting's language; else a ready one that does (Bengali goes to IndicConformer
    while English stays on Parakeet). With none that knows it, the chosen one, which refuses in
    words."""
    if model or not language:
        return speech.resolve("transcribe", model or None)
    chosen = speech.resolve("transcribe", None)
    if languages.supports(chosen.languages, language):
        return chosen
    for m in ready_speech_models(speech):
        if languages.supports(m["languages"], language):
            return speech.resolve("transcribe", m["id"])
    return chosen


def words_of(row: dict[str, Any], reports: list[dict[str, Any]] | None = None) -> str:
    """What search finds a meeting by (ADR-0041): its title, that it is a meeting (a person asks
    for "the meeting about…"), its speakers' names, what was said, and its reports (MT4: a
    summary says what it was about in fewer words)."""
    names = ", ".join(s["name"] for s in row.get("speakers") or [])
    said = (row.get("text") or "")[:INDEX_CHARS]
    written = " ".join(
        f"{r['title']}: {r['text'][:REPORT_INDEX_CHARS]}"
        for r in reports or []
        if r.get("status") == "done"
    )
    return search_text(row["title"], "A meeting.", names, written, said)


async def add_to_search(state: Any, identity: Identity, row: dict[str, Any]) -> None:
    index = state.creation_index
    if index is None:
        return
    try:
        reports = store_for(state).reports_of(identity.tenant_id, identity.user_id, row["id"])
        await index.index(
            identity.tenant_id, PRODUCT_ID, identity.user_id, KIND, row["id"],
            words_of(row, reports),
        )  # fmt: skip
    except Exception:  # the periodic check catches up
        log.warning("the meeting could not be added to search", exc_info=True)


RECORDING = "audio.wav"


def recording_key(identity: Identity, item: str) -> str:
    """The recording's key in the desktop's own file storage (ADR-0056): served from there by a
    signed link, read in ranges as it plays."""
    return object_key(identity.tenant_id, PRODUCT_ID, identity.user_id, item, RECORDING)


def folder_for(state: Any, identity: Identity, item: str) -> Path:
    """Where one meeting's files are kept: in the desktop's file storage when there is one (so a
    player reaches the recording by a link), else the store's own folder; on the web, a scratch
    folder for while it is made (the recording is then kept in object storage)."""
    if not re.fullmatch(r"[0-9a-f]{32}", item):
        raise ValueError("not an id")
    web = web_of(state)
    if web is not None:
        return web.tmp_dir / "work" / item
    files = state.local_files
    if files is not None:
        return files.path_of(recording_key(identity, item)).parent  # type: ignore[no-any-return]
    return store_for(state).folder_of(identity.tenant_id, identity.user_id, item)


def recording_of(state: Any, identity: Identity, item: str) -> Path | None:
    """The recording on this computer (None on the web, where it is in object storage)."""
    if web_of(state) is not None:
        return None
    path = folder_for(state, identity, item) / RECORDING
    return path if path.is_file() else None


async def recording_url(state: Any, identity: Identity, item: str) -> str | None:
    """A signed link a player reads the recording from in ranges: the desktop's file storage, or
    the web's object storage."""
    key = recording_key(identity, item)
    web = web_of(state)
    if web is not None:
        if not await web.storage.exists(key):
            return None
        return await web.storage.url(key, timedelta(hours=6))  # type: ignore[no-any-return]
    files = state.local_files
    if files is None or recording_of(state, identity, item) is None:
        return None
    return await files.url(key, timedelta(hours=6))  # type: ignore[no-any-return]


async def keep_recording(state: Any, identity: Identity, item: str, wav: Path) -> None:
    """On the web: the recording into object storage, and the scratch folder away."""
    web = web_of(state)
    if web is None:
        return
    data = await asyncio.to_thread(wav.read_bytes)
    await web.storage.put(recording_key(identity, item), data, "audio/wav")
    del data
    await asyncio.to_thread(shutil.rmtree, wav.parent, True)


def manager_for(deps: RouteDeps) -> "MeetingJobs":
    existing = deps.state.meetings_jobs
    if existing is None:
        existing = MeetingJobs(deps)
        deps.state.meetings_jobs = existing
    return existing  # type: ignore[no-any-return]


def reports_for(deps: RouteDeps) -> ReportJobs:
    """The one report being written (MT4); search is told when one is done."""
    existing = deps.state.meetings_reports
    if existing is None:

        async def done(identity: Identity, item: str) -> None:
            row = store_for(deps.state).get(identity.tenant_id, identity.user_id, item)
            await add_to_search(deps.state, identity, row)

        existing = ReportJobs(
            deps, PRODUCT_ID, store_for, done, per_person=web_of(deps.state) is not None
        )
        deps.state.meetings_reports = existing
    return existing  # type: ignore[no-any-return]


def asking_for(deps: RouteDeps) -> AskJobs:
    """Questions about meetings, answered through notebooks (MT5)."""
    existing = deps.state.meetings_asking
    if existing is None:
        existing = AskJobs(deps, PRODUCT_ID, store_for)
        deps.state.meetings_asking = existing
    return existing  # type: ignore[no-any-return]


class MeetingJobs:
    """One meeting being made at a time: on the desktop in all (one person, one processor to
    share; the speaker model is loaded for a job and let go after it), on the web for each person
    (the cloud does the work, ADR-0088)."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._jobs: dict[tuple[str, str], tuple[str, asyncio.Task[None], threading.Event]] = {}

    def _slot(self, identity: Identity | None) -> tuple[str, str]:
        if web_of(self._deps.state) is None or identity is None:
            return ("", "")
        return (identity.tenant_id, identity.user_id)

    def _running(
        self, identity: Identity | None
    ) -> tuple[str, asyncio.Task[None], threading.Event] | None:
        job = self._jobs.get(self._slot(identity))
        return job if job is not None and not job[1].done() else None

    def busy(self, identity: Identity | None = None) -> bool:
        """A meeting is being made (on the web: by this person)."""
        return self._running(identity) is not None

    def active(self, identity: Identity | None = None) -> str | None:
        job = self._running(identity)
        return job[0] if job else None

    def making(self, item: str) -> bool:
        """`item` is being made now."""
        return self._job_of(item) is not None

    def _job_of(self, item: str) -> tuple[str, asyncio.Task[None], threading.Event] | None:
        for job in self._jobs.values():
            if job[0] == item and not job[1].done():
                return job
        return None

    def readiness(self) -> dict[str, Any]:
        """What is missing before a meeting can be made, in words, for the screen and actions."""
        state = self._deps.state
        web = web_of(state) is not None
        speech = speech_for(state)
        model = None
        problem = None
        if speech is not None:
            try:
                model = speech.resolve("transcribe", None)
            except VoiceEngineError as e:
                problem = e.message
        if web and model is not None and not is_cloud(model):
            model, problem = None, WEB_NO_CLOUD
        if web and speech is None:
            problem = WEB_NO_CLOUD
        return {
            "hosted": web,
            "speech_models": ready_speech_models(speech),
            # on the web the cloud transcription model tells the speakers apart
            "speaker_model": web or speaker_model_path(state) is not None,
            "speaker_model_id": SPEAKER_MODEL,
            "voiceprint_model": voiceprint_model_path(state) is not None,
            "voiceprint_model_id": VOICEPRINT_MODEL,
            "speech": speech is not None and model is not None,
            "speech_model": {"id": model.id, "title": model.title} if model else None,
            "speech_problem": problem
            or (None if speech is not None else "Speech is not available here."),
        }

    def not_ready(self) -> str | None:
        r = self.readiness()
        if not r["speaker_model"]:
            return "Get the speaker model first (about 490 MB, in Models)."
        if not r["speech"]:
            return r["speech_problem"] or "Choose a speech-to-text model first, in Models."
        return None

    async def start(
        self, identity: Identity, src: Path, *, title: str, source_name: str,
        language: str = "", model: str | None = None, keep_src: bool = False,
        recorded: bool = False,
    ) -> dict[str, Any]:  # fmt: skip
        """Begin making a meeting from the recording at `src` (removed when done unless
        `keep_src`). `recorded`: the app's own two-channel recording, the microphone ("You") and
        the computer's sound. Refused when something is missing or a meeting is being made."""
        state = self._deps.state
        why = self.not_ready()
        if why:
            raise Refused("not_ready", why)
        if self.busy(identity):
            raise Refused("busy", "A meeting is being made. Wait for it to finish.")
        speech = speech_for(state)
        try:
            chosen = model_for(speech, language, model)
            if web_of(state) is not None and not is_cloud(chosen):
                raise Refused("not_ready", WEB_NO_CLOUD)
            options = check_transcribe(chosen, None)
            if language:
                options["language"] = check_language(chosen, language)
        except VoiceRequestError as e:
            raise Refused(e.code, e.message) from None
        except VoiceEngineError as e:
            raise Refused(e.code, e.message) from None
        store = store_for(state)
        row = store.add(
            identity.tenant_id, identity.user_id, title=title, source_name=source_name,
            language=language, source="recorded" if recorded else "file",
        )  # fmt: skip
        folder = folder_for(state, identity, row["id"])
        folder.mkdir(parents=True, exist_ok=True)
        stop = threading.Event()
        work = self._make(identity, row, src, folder, chosen, options, stop, keep_src, recorded)

        async def run() -> None:
            token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
            try:
                await work
            finally:
                reset_context(token)

        self._jobs[self._slot(identity)] = (row["id"], asyncio.create_task(run()), stop)
        return row

    async def _make(
        self, identity: Identity, row: dict[str, Any], src: Path, folder: Path, chosen: Any,
        options: dict[str, Any], stop: threading.Event, keep_src: bool, recorded: bool = False,
    ) -> None:  # fmt: skip
        state = self._deps.state
        store = store_for(state)
        item = row["id"]
        t0 = time.monotonic()
        timings: dict[str, float] = {}
        wav = folder / RECORDING
        sides: list[tuple[str, Path]] = []
        try:
            store.set_stage(item, "Reading the recording", 0.0)
            t = time.monotonic()
            if recorded:
                you, others = folder / "you.wav", folder / "others.wav"
                seconds = await asyncio.to_thread(channels.split, src, you, others, wav)
                for name, side in (("you", you), ("others", others)):
                    if await asyncio.to_thread(channels.loud, side):
                        sides.append((name, side))
                    else:  # nothing said there (muted, or nothing played): not written down
                        await asyncio.to_thread(side.unlink, True)
            else:
                seconds = await audio.prepare(src, wav)
                sides.append(("all", wav))
            timings["read_s"] = round(time.monotonic() - t, 2)

            cloud = web_of(state) is not None
            if not cloud and speaker_model_path(state) is None:
                raise Refused("not_ready", "The speaker model is not on this computer any more.")
            parts: dict[str, tuple[Any, Any, Any]] = {}
            share = 1 / max(1, len(sides))
            for n, (name, side) in enumerate(sides):
                base = SHARE["read"] + (SHARE["speakers"] + SHARE["words"]) * share * n
                one = self._in_the_cloud if cloud else self._one_side
                parts[name] = await one(
                    item, side, seconds, chosen, options, stop, base, share, timings
                )

            store.set_stage(item, "Putting it together", 1 - SHARE["save"])
            if recorded:
                empty: tuple[Any, Any, Any] = ([], [], [])
                speakers, lines = merge_two(parts.get("you", empty), parts.get("others", empty))
            else:
                segments, turns, words = parts["all"]
                speakers, lines = merge(segments, turns, words)
            text = plain_text(lines, speakers)
            store.finish(
                item, seconds=round(seconds, 2), model_id=chosen.id, speakers=speakers,
                lines=lines, text=text, timings=timings,
                elapsed_s=round(time.monotonic() - t0, 2),
            )  # fmt: skip
            done = store.get(identity.tenant_id, identity.user_id, item)
            await self._prints(identity, done, folder, recorded)
            await keep_recording(state, identity, item, wav)
            await add_to_search(state, identity, done)
            await RouteUsage(state, PRODUCT_ID).record(
                identity, "meetings.made", round(seconds / 60, 2), "audio_minute",
                speakers=len(speakers), model=chosen.id,
            )  # fmt: skip
        except (asyncio.CancelledError, Stopped):
            store.fail(item, "Stopped.", "cancelled")
            if not stop.is_set():
                raise
        except audio.AudioError as e:
            store.fail(item, str(e))
        except BadAudio as e:
            store.fail(item, str(e))
        except Refused as e:
            store.fail(item, e.message)
        except (VoiceEngineError, VoiceRequestError) as e:
            store.fail(item, e.message)
        except Exception:
            log.exception("making a meeting failed")
            store.fail(item, "Something went wrong while making the meeting. Try again.")
        finally:
            for name, side in sides:
                if name != "all":  # the channels were for the models; the mix is kept to play
                    await asyncio.to_thread(side.unlink, True)
            if not keep_src:
                await asyncio.to_thread(src.unlink, True)

    async def _prints(
        self, identity: Identity, row: dict[str, Any], folder: Path, recorded: bool
    ) -> None:
        """The speakers' voiceprints (MT3), from a recording's own channels while they are here:
        the microphone for You, the computer's sound for the others. A missing voiceprint model
        or a failure leaves the meeting as it is."""
        state = self._deps.state
        voices = voices_for(state)
        if voices is None:
            return
        wav_of: dict[str, Path] = {}
        if recorded:
            you, others = folder / "you.wav", folder / "others.wav"
            for s in row["speakers"]:
                side = you if s["key"] == "S1" else others
                if side.is_file():
                    wav_of[s["key"]] = side
        try:
            prints = await asyncio.to_thread(
                make_prints, voices, wav_of, folder / RECORDING, row["lines"], row["speakers"],
                row.get("source", "file"),
            )  # fmt: skip
            store_for(state).save_prints(identity.tenant_id, identity.user_id, row["id"], prints)
        except Exception:
            log.warning("the voiceprints of a meeting could not be made", exc_info=True)

    async def _one_side(
        self, item: str, wav: Path, seconds: float, chosen: Any, options: dict[str, Any],
        stop: threading.Event, base: float, share: float, timings: dict[str, float],
    ) -> tuple[list[TranscriptSegment], list[Any], list[TranscriptSegment]]:  # fmt: skip
        """(segments, turns, words) of one recording: who spoke when, then what was said."""
        state = self._deps.state
        store = store_for(state)
        path = speaker_model_path(state)
        if path is None:
            raise Refused("not_ready", "The speaker model is not on this computer any more.")
        span = SHARE["speakers"] * share
        store.set_stage(item, "Telling the speakers apart", base)

        def told(f: float) -> None:
            store.set_stage(item, "Telling the speakers apart", base + span * f)

        def heard() -> Any:
            return Sortformer(path).run(wav, told, stop.is_set)

        t = time.monotonic()
        diar = await asyncio.to_thread(heard)
        timings["speakers_s"] = round(timings.get("speakers_s", 0) + time.monotonic() - t, 2)

        base += span
        span = SHARE["words"] * share
        writing = f"Writing it down with {chosen.title}"
        store.set_stage(item, writing, base)
        t = time.monotonic()
        segments, words = await self._write_down(
            wav, pieces(diar.turns, seconds), chosen, options,
            lambda f: store.set_stage(item, writing, base + span * f),
        )  # fmt: skip
        timings["words_s"] = round(timings.get("words_s", 0) + time.monotonic() - t, 2)
        if stop.is_set():
            raise Stopped
        return segments, diar.turns, words

    async def _in_the_cloud(
        self, item: str, wav: Path, seconds: float, chosen: Any, options: dict[str, Any],
        stop: threading.Event, base: float, share: float, timings: dict[str, float],
    ) -> tuple[list[TranscriptSegment], list[Turn], list[TranscriptSegment]]:  # fmt: skip
        """On the web: the cloud model writes the whole recording down and says who spoke each
        word (ADR-0108 decision 13). A model that gives no speakers leaves everyone Speaker 1."""
        store = store_for(self._deps.state)
        store.set_stage(
            item, f"Writing it down with {chosen.title}, telling the speakers apart", base
        )
        t = time.monotonic()
        data = await asyncio.to_thread(wav.read_bytes)
        result = await self._deps.state.audio.transcribe(chosen, data, options | {"diarize": True})
        del data
        timings["words_s"] = round(time.monotonic() - t, 2)
        if stop.is_set():
            raise Stopped
        words: list[TranscriptSegment] = list(getattr(result, "words", ()))
        return list(result.segments), turns_of(words), words

    async def _write_down(
        self, wav: Path, cuts: list[tuple[float, float]], chosen: Any, options: dict[str, Any],
        progress: Any,
    ) -> tuple[list[TranscriptSegment], list[TranscriptSegment]]:  # fmt: skip
        """(segments, words) of the whole recording, written down a piece at a time (the speech
        model takes a few minutes at once), with their times in the whole recording. `words` is
        empty when the model gives no word times."""
        out: list[TranscriptSegment] = []
        words: list[TranscriptSegment] = []
        audio_file = await asyncio.to_thread(Wav, wav)
        try:
            for i, (a, b) in enumerate(cuts):
                data = await asyncio.to_thread(wav_bytes, audio_file.samples, a, b)
                result = await self._deps.state.audio.transcribe(chosen, data, options)
                del data
                out += [
                    TranscriptSegment(round(s.start + a, 3), round(s.end + a, 3), s.text)
                    for s in result.segments
                ]
                words += [
                    TranscriptSegment(round(w.start + a, 3), round(w.end + a, 3), w.text)
                    for w in getattr(result, "words", ())
                ]
                progress((i + 1) / len(cuts))
        finally:
            audio_file.close()
        return out, words

    async def wait(self, item: str) -> None:
        job = self._job_of(item)
        if job is not None:
            await asyncio.shield(job[1])

    async def cancel(self, item: str) -> bool:
        """Stop the meeting being made, if it is `item`."""
        job = self._job_of(item)
        if job is None:
            return False
        _, task, stop = job
        stop.set()  # the speaker model stops before its next chunk
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def stop_all(self) -> None:
        for item, _, _ in list(self._jobs.values()):
            await self.cancel(item)


WEB_NO_CLOUD = (
    "Meetings need a transcription model in the cloud. An admin chooses one in Admin › Media."
)


def turns_of(words: list[TranscriptSegment]) -> list[Turn]:
    """Who spoke when, from words a cloud model gave a speaker each: a turn for each run of words
    of one speaker, the speakers numbered in the order they first speak."""
    order: dict[str, int] = {}
    turns: list[Turn] = []
    for w in words:
        if w.speaker is None:
            continue
        idx = order.setdefault(w.speaker, len(order))
        if turns and turns[-1].speaker == idx and w.start - turns[-1].end < 2.0:
            turns[-1] = Turn(turns[-1].start, max(turns[-1].end, w.end), idx)
        else:
            turns.append(Turn(w.start, w.end, idx))
    return turns


async def delete_meeting(deps: RouteDeps, identity: Identity, item: str) -> bool:
    """Delete a meeting with its recording and its search entry; one being made is stopped first."""
    state = deps.state
    store = store_for(state)
    try:
        store.get(identity.tenant_id, identity.user_id, item)
    except NotFound:
        return False
    await manager_for(deps).cancel(item)
    store.delete(identity.tenant_id, identity.user_id, item)
    await asyncio.to_thread(shutil.rmtree, folder_for(state, identity, item), True)
    web = web_of(state)
    if web is not None:
        await web.storage.delete(recording_key(identity, item))
    await deps.unindex(identity, PRODUCT_ID, item)
    return True


__all__ = [
    "KIND", "PRODUCT_ID", "SPEAKER_MODEL", "VOICEPRINT_MODEL", "ensure_prints", "voices_for",
    "reports_for", "MeetingJobs", "NotAvailable", "Refused",
    "add_to_search", "delete_meeting", "manager_for", "recording_in", "recording_key",
    "recording_of", "root_for", "waiting_recordings",
    "speaker_model_path", "store_for", "words_of",
]  # fmt: skip
