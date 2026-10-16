# SPDX-License-Identifier: Apache-2.0
"""The notebooks API under /products/wasifyai-notebooks/ (ADR-0065).

Every query is scoped by tenant and user; another person's notebook is a plain 404. The desktop
profile is the only one served so far: without an app data folder the routes answer 503.
"""

import asyncio
import hashlib
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import Identity, RouteDeps, VoiceEngineError
from wasifyai_platform_sdk.search import search_text

from wasifyai_notebooks import hardening
from wasifyai_notebooks.components import Unavailable
from wasifyai_notebooks.ingest import original_path
from wasifyai_notebooks.overview import AUDIO_FILE, NotPossible, Voicer, choose_voices
from wasifyai_notebooks.reader_install import InstallError
from wasifyai_notebooks.retrieval import retrieve
from wasifyai_notebooks.runtime import NotAvailable, Runtime, runtime_for
from wasifyai_notebooks.store import (
    BULK,
    INTERACTIVE,
    Conflict,
    NotFound,
)

PRODUCT_ID = "wasifyai-notebooks"
log = logging.getLogger(__name__)
BULK_AFTER = 20  # an upload of more files than this is read at bulk priority


class NotebookOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    opened_at: str | None
    sources: int
    ready: int
    reading: int
    failed: int


class Title(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class NewNotebook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Untitled notebook", min_length=1, max_length=200)


class NewNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=hardening.MAX_TITLE)
    content: str = Field(min_length=1, max_length=1_000_000)
    folder_id: str | None = None


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=hardening.MAX_TITLE)
    content: str | None = Field(default=None, min_length=1, max_length=1_000_000)


class NewFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    parent_id: str | None = None


class Move(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[str] = Field(min_length=1, max_length=1000)
    folder_id: str | None = None


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4096)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = None
    mode: Literal["hybrid", "dense", "lexical"] = "hybrid"


class OverviewVoices(BaseModel):
    """Which model speaks the overview and which built-in voice each host has (both optional)."""

    model_config = ConfigDict(extra="forbid")
    model: str | None = Field(default=None, max_length=100)
    voices: dict[str, str] | None = None


class ConfirmReader(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_bytes: int


def build_routes(deps: RouteDeps, runtime: Runtime | None = None) -> APIRouter:
    """`runtime` is injectable for tests; production builds it from the app's data folder."""
    router = APIRouter(tags=[PRODUCT_ID])
    holder: dict[str, Runtime] = {}
    if runtime is not None:
        holder["rt"] = runtime

    def rt() -> Runtime:
        if "rt" not in holder:
            try:
                holder["rt"] = runtime_for(deps.state)
            except NotAvailable as e:
                raise HTTPException(503, str(e)) from None
        r = holder["rt"]
        r.worker.start()
        return r

    async def reindex(identity: Identity, nid: str) -> None:
        """Keep the notebook findable in My creations search by its title and its sources' names
        (ADR-0041): at once, so it does not wait for the platform's periodic check. Best effort."""
        index = getattr(deps.state, "creation_index", None)
        if index is None:
            return
        try:
            r = rt()
            nb = await asyncio.to_thread(
                r.store.get_notebook, identity.tenant_id, identity.user_id, nid
            )
            docs = await asyncio.to_thread(
                r.store.list_documents, identity.tenant_id, identity.user_id, nid
            )
            arts = await asyncio.to_thread(
                r.store.list_artifacts, identity.tenant_id, identity.user_id, nid
            )
            names = [d["title"] for d in docs[:40]] + [a["title"] for a in arts[:20] if a["title"]]
            text = search_text(nb["title"], *names)
            await index.index(
                identity.tenant_id, PRODUCT_ID, identity.user_id, "notebook", nid, text
            )
        except Exception:  # the periodic check will catch up
            log.warning("the notebook could not be added to search", exc_info=True)

    async def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except NotFound as e:
            raise HTTPException(404, str(e)) from None
        except Conflict as e:
            raise HTTPException(409, str(e)) from None

    # ---- components ------------------------------------------------------------------------

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        r = rt()
        state = r.components.state()
        state["reader"]["setup"] = _setup(r)
        return {**state, "index": await call(r.store.stats)}

    @router.post("/setup/reader", status_code=202)
    async def setup_reader(
        body: ConfirmReader, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        r = rt()
        if r.installer is None:
            raise HTTPException(409, {"code": "reader_unavailable", "message": r.installer_problem})
        try:
            r.installer.start(body.confirm_bytes)
        except InstallError as e:
            raise HTTPException(409, {"code": "stale_size", "message": str(e)}) from None
        return r.installer.progress.public()

    # ---- notebooks -------------------------------------------------------------------------

    @router.get("/notebooks", response_model=list[NotebookOut])
    async def list_notebooks(identity: Identity = Depends(deps.identity)) -> list[dict[str, Any]]:
        return await call(rt().store.list_notebooks, identity.tenant_id, identity.user_id)

    @router.post("/notebooks", response_model=NotebookOut, status_code=201)
    async def create_notebook(
        body: NewNotebook, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        made = await call(
            rt().store.create_notebook, identity.tenant_id, identity.user_id, body.title.strip()
        )
        await reindex(identity, made["id"])
        return made

    @router.get("/notebooks/{nid}", response_model=NotebookOut)
    async def get_notebook(nid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        return await call(rt().store.open_notebook, identity.tenant_id, identity.user_id, nid)

    @router.patch("/notebooks/{nid}", response_model=NotebookOut)
    async def rename_notebook(
        nid: str, body: Title, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        out = await call(
            rt().store.rename_notebook,
            identity.tenant_id,
            identity.user_id,
            nid,
            body.title.strip(),
        )
        await reindex(identity, nid)
        return out

    @router.delete("/notebooks/{nid}", status_code=204)
    async def delete_notebook(nid: str, identity: Identity = Depends(deps.identity)) -> Response:
        r = rt()
        await call(r.store.delete_notebook, identity.tenant_id, identity.user_id, nid)
        await asyncio.to_thread(shutil.rmtree, r.files_dir / nid, True)
        await asyncio.to_thread(shutil.rmtree, r.artifacts_dir / nid, True)
        await deps.unindex(identity, PRODUCT_ID, nid)  # out of search too (ADR-0041)
        return Response(status_code=204)

    # ---- folders ---------------------------------------------------------------------------

    @router.get("/notebooks/{nid}/folders")
    async def list_folders(nid: str, identity: Identity = Depends(deps.identity)) -> list[dict]:
        return await call(rt().store.list_folders, identity.tenant_id, identity.user_id, nid)

    @router.post("/notebooks/{nid}/folders", status_code=201)
    async def create_folder(
        nid: str, body: NewFolder, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        return await call(
            rt().store.create_folder, identity.tenant_id, identity.user_id, nid,
            body.name.strip(), body.parent_id,
        )  # fmt: skip

    @router.patch("/notebooks/{nid}/folders/{fid}", status_code=204)
    async def rename_folder(
        nid: str, fid: str, body: NewFolder, identity: Identity = Depends(deps.identity)
    ) -> Response:
        await call(
            rt().store.rename_folder,
            identity.tenant_id,
            identity.user_id,
            nid,
            fid,
            body.name.strip(),
        )
        return Response(status_code=204)

    @router.delete("/notebooks/{nid}/folders/{fid}", status_code=204)
    async def delete_folder(
        nid: str, fid: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        r = rt()
        docs = await call(r.store.delete_folder, identity.tenant_id, identity.user_id, nid, fid)
        for did in docs:
            await asyncio.to_thread(shutil.rmtree, r.files_dir / nid / did, True)
        await reindex(identity, nid)
        return Response(status_code=204)

    # ---- sources ---------------------------------------------------------------------------

    @router.get("/notebooks/{nid}/documents")
    async def list_documents(
        nid: str,
        status: list[str] | None = Query(None),  # noqa: B008
        folder_id: str | None = None,
        identity: Identity = Depends(deps.identity),
    ) -> list[dict[str, Any]]:
        return await call(
            rt().store.list_documents, identity.tenant_id, identity.user_id, nid,
            statuses=status, folder_id=folder_id,
        )  # fmt: skip

    @router.post("/notebooks/{nid}/documents", status_code=201)
    async def add_note(
        nid: str, body: NewNote, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        r = rt()
        doc = await call(
            r.store.add_note, identity.tenant_id, identity.user_id, nid,
            title=body.title.strip(), content=body.content, folder_id=body.folder_id,
        )  # fmt: skip
        r.worker.wake()
        await reindex(identity, nid)
        return doc

    @router.post("/notebooks/{nid}/documents/upload", status_code=201)
    async def upload(
        nid: str,
        files: list[UploadFile] = File(...),  # noqa: B008
        folder_id: str | None = Form(None),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        r = rt()
        if not await call(r.store.owns, identity.tenant_id, identity.user_id, nid):
            raise HTTPException(404, "notebook not found")
        priority = BULK if len(files) > BULK_AFTER else INTERACTIVE
        created: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        for upload_file in files:
            name = upload_file.filename or "document"
            temp = r.tmp_dir / f"{hashlib.sha1(name.encode()).hexdigest()[:8]}-{id(upload_file):x}"
            try:
                size, digest = await _spool(upload_file, temp)
                if size > hardening.MAX_BYTES:
                    raise hardening.Refused(
                        f"The file is larger than {hardening.MAX_BYTES // (1024 * 1024)} MB."
                    )
                checked = await asyncio.to_thread(hardening.check_file, temp, name)
                from wasifyai_notebooks.store import new_id

                did = new_id()
                title = hardening.safe_name(name)
                target = r.files_dir / nid / did / title
                await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.move, str(temp), str(target))
                try:
                    doc, existed = await call(
                        r.store.add_file, identity.tenant_id, identity.user_id, nid,
                        title=title, suffix=checked.suffix, mime=checked.mime, size_bytes=size,
                        sha256=digest, folder_id=folder_id, priority=priority, doc_id=did,
                    )  # fmt: skip
                except BaseException:
                    await asyncio.to_thread(shutil.rmtree, target.parent, True)
                    raise
                if existed:
                    await asyncio.to_thread(shutil.rmtree, target.parent, True)
                    duplicates.append(doc)
                else:
                    created.append(doc)
            except hardening.Refused as e:
                rejected.append({"name": name, "reason": str(e)})
            finally:
                temp.unlink(missing_ok=True)
        if created:
            r.worker.wake()
            await reindex(identity, nid)
        return {"created": created, "duplicates": duplicates, "rejected": rejected}

    @router.get("/notebooks/{nid}/documents/{did}")
    async def get_document(
        nid: str, did: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        return await call(
            rt().store.get_document, identity.tenant_id, identity.user_id, nid, did, content=True
        )

    @router.patch("/notebooks/{nid}/documents/{did}")
    async def patch_document(
        nid: str, did: str, body: DocumentPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        r = rt()
        if body.title is None and body.content is None:
            raise HTTPException(422, "nothing to change")
        if body.title is not None:
            await call(
                r.store.rename_document, identity.tenant_id, identity.user_id, nid, did,
                body.title.strip(),
            )  # fmt: skip
        if body.content is not None:
            await call(
                r.store.edit_note, identity.tenant_id, identity.user_id, nid, did, body.content
            )
            r.worker.wake()
        await reindex(identity, nid)
        return await call(r.store.get_document, identity.tenant_id, identity.user_id, nid, did)

    @router.delete("/notebooks/{nid}/documents/{did}", status_code=204)
    async def delete_document(
        nid: str, did: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        r = rt()
        await call(r.store.delete_document, identity.tenant_id, identity.user_id, nid, did)
        await asyncio.to_thread(shutil.rmtree, r.files_dir / nid / did, True)
        await reindex(identity, nid)
        return Response(status_code=204)

    @router.post("/notebooks/{nid}/documents/{did}/retry", status_code=202)
    async def retry(nid: str, did: str, identity: Identity = Depends(deps.identity)) -> Response:
        r = rt()
        await call(r.store.retry_document, identity.tenant_id, identity.user_id, nid, did)
        r.worker.wake()
        return Response(status_code=202)

    @router.post("/notebooks/{nid}/documents/{did}/cancel", status_code=202)
    async def cancel(nid: str, did: str, identity: Identity = Depends(deps.identity)) -> Response:
        await call(rt().store.cancel_document, identity.tenant_id, identity.user_id, nid, did)
        return Response(status_code=202)

    @router.post("/notebooks/{nid}/documents/move")
    async def move(
        nid: str, body: Move, identity: Identity = Depends(deps.identity)
    ) -> dict[str, int]:
        moved = await call(
            rt().store.move_documents, identity.tenant_id, identity.user_id, nid,
            body.document_ids, body.folder_id,
        )  # fmt: skip
        return {"moved": moved}

    @router.get("/notebooks/{nid}/documents/{did}/original")
    async def original(
        nid: str, did: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        r = rt()
        doc = await call(r.store.get_document, identity.tenant_id, identity.user_id, nid, did)
        if doc["kind"] != "file":
            raise HTTPException(404, "this source has no file")
        path = original_path(r.files_dir, nid, doc)
        if not path.is_file():
            raise HTTPException(404, "the file is no longer on this computer")
        # always an attachment: an HTML or SVG file shown inline would run in the app's origin
        return FileResponse(
            path, media_type=doc["mime"] or "application/octet-stream", filename=doc["title"]
        )

    @router.get("/notebooks/{nid}/passages/{chunk_id}")
    async def passage(
        nid: str, chunk_id: int, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        return await call(rt().store.get_chunk, identity.tenant_id, identity.user_id, nid, chunk_id)

    @router.get("/notebooks/{nid}/guide")
    async def guide(nid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The guide to the notebook (summary, topics, questions to start with), `stale` once its
        sources have changed. Made by a run with `studio: {format: "guide"}`."""
        return await call(rt().store.get_guide, identity.tenant_id, identity.user_id, nid)

    # ---- outputs (Studio) --------------------------------------------------------------------
    # An output is made by a run of the product's graph (`{notebook_id, studio: {format, prompt},
    # document_ids?}`); these routes list and read what it saved.

    @router.get("/notebooks/{nid}/artifacts")
    async def list_artifacts(
        nid: str, identity: Identity = Depends(deps.identity)
    ) -> list[dict[str, Any]]:
        return await call(rt().store.list_artifacts, identity.tenant_id, identity.user_id, nid)

    @router.get("/notebooks/{nid}/artifacts/{aid}")
    async def get_artifact(
        nid: str, aid: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        return await call(
            rt().store.get_artifact, identity.tenant_id, identity.user_id, nid, aid, content=True
        )

    @router.patch("/notebooks/{nid}/artifacts/{aid}", status_code=204)
    async def rename_artifact(
        nid: str, aid: str, body: Title, identity: Identity = Depends(deps.identity)
    ) -> Response:
        await call(
            rt().store.rename_artifact, identity.tenant_id, identity.user_id, nid, aid,
            body.title.strip(),
        )  # fmt: skip
        return Response(status_code=204)

    @router.post("/notebooks/{nid}/artifacts/{aid}/cancel", status_code=202)
    async def cancel_artifact(
        nid: str, aid: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        await call(rt().store.cancel_artifact, identity.tenant_id, identity.user_id, nid, aid)
        return Response(status_code=202)

    @router.delete("/notebooks/{nid}/artifacts/{aid}", status_code=204)
    async def delete_artifact(
        nid: str, aid: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        r = rt()
        await call(r.store.delete_artifact, identity.tenant_id, identity.user_id, nid, aid)
        await asyncio.to_thread(shutil.rmtree, r.artifacts_dir / nid / aid, True)
        return Response(status_code=204)

    @router.get("/notebooks/{nid}/artifacts/{aid}/file")
    async def artifact_file(
        nid: str, aid: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        r = rt()
        art = await call(r.store.get_artifact, identity.tenant_id, identity.user_id, nid, aid)
        if not art["file_name"]:
            raise HTTPException(404, "this output has no file")
        path = r.artifacts_dir / nid / aid / Path(art["file_name"]).name
        if not path.is_file():
            raise HTTPException(404, "the file is no longer on this computer")
        # always an attachment, like a source's original
        return FileResponse(
            path, media_type=art["file_mime"] or "application/octet-stream",
            filename=art["file_name"],
        )  # fmt: skip

    # ---- the audio overview's voices (ADR-0066, V2) ------------------------------------------

    voicer = Voicer()

    async def overview_art(identity: Identity, nid: str, aid: str) -> dict[str, Any]:
        art = await call(
            rt().store.get_artifact, identity.tenant_id, identity.user_id, nid, aid, content=True
        )
        if art["format"] != "audio" or art["status"] != "ready" or not art.get("data"):
            raise HTTPException(409, "This output is not a finished audio overview.")
        return art

    @router.post("/notebooks/{nid}/artifacts/{aid}/voices", status_code=202)
    async def speak_overview(
        nid: str,
        aid: str,
        body: OverviewVoices,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        r = rt()
        art = await overview_art(identity, nid, aid)
        engine = getattr(deps.state, "audio", None)
        if engine is None:
            raise HTTPException(503, "Speech is not available in this deployment yet.")
        try:
            model = engine.resolve("speak", body.model)
            voices = choose_voices(model, body.voices)
        except VoiceEngineError as e:
            raise HTTPException(409, {"code": e.code, "message": e.message}) from None
        except NotPossible as e:
            raise HTTPException(409, str(e)) from None
        data = art["data"]

        async def finished(model_id: str, chosen: dict[int, str]) -> None:
            await call(
                r.store.set_artifact_data, identity.tenant_id, identity.user_id, nid, aid,
                {**data, "audio": True, "audio_file": AUDIO_FILE, "audio_model": model_id,
                 "audio_voices": {str(k): v for k, v in chosen.items()}},
            )  # fmt: skip

        try:
            job = voicer.start(
                engine=engine, model=model, voices=voices, turns=data["turns"],
                out_dir=r.artifacts_dir / nid / aid, key=(nid, aid), on_done=finished,
            )  # fmt: skip
        except NotPossible as e:
            raise HTTPException(409, str(e)) from None
        return job.public()

    @router.get("/notebooks/{nid}/artifacts/{aid}/voices")
    async def overview_state(
        nid: str, aid: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        await call(rt().store.get_artifact, identity.tenant_id, identity.user_id, nid, aid)
        job = voicer.job(nid, aid)
        return job.public() if job else {"state": "idle", "done": 0, "total": 0, "message": ""}

    @router.get("/notebooks/{nid}/artifacts/{aid}/audio")
    async def overview_audio(
        nid: str, aid: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        r = rt()
        await call(r.store.get_artifact, identity.tenant_id, identity.user_id, nid, aid)
        path = r.artifacts_dir / nid / aid / AUDIO_FILE
        if not path.is_file():
            raise HTTPException(404, "this overview has no voices yet")
        return FileResponse(path, media_type="audio/wav", filename="audio-overview.wav")

    # ---- conversations ---------------------------------------------------------------------
    # A question is a run of this product's graph (`POST /products/wasifyai-notebooks/runs` with
    # `{text, notebook_id, conversation_id?, document_ids?}`); these routes read what it saved.

    @router.get("/notebooks/{nid}/conversations")
    async def list_conversations(
        nid: str, identity: Identity = Depends(deps.identity)
    ) -> list[dict[str, Any]]:
        return await call(rt().store.list_conversations, identity.tenant_id, identity.user_id, nid)

    @router.get("/notebooks/{nid}/conversations/{cid}")
    async def get_conversation(
        nid: str, cid: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        r = rt()
        conv = await call(r.store.get_conversation, identity.tenant_id, identity.user_id, nid, cid)
        msgs = await call(r.store.messages, identity.tenant_id, identity.user_id, nid, cid)
        return {**conv, "messages": msgs}

    @router.patch("/notebooks/{nid}/conversations/{cid}", status_code=204)
    async def rename_conversation(
        nid: str, cid: str, body: Title, identity: Identity = Depends(deps.identity)
    ) -> Response:
        await call(
            rt().store.rename_conversation, identity.tenant_id, identity.user_id, nid, cid,
            body.title.strip(),
        )  # fmt: skip
        return Response(status_code=204)

    @router.delete("/notebooks/{nid}/conversations/{cid}", status_code=204)
    async def delete_conversation(
        nid: str, cid: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        await call(rt().store.delete_conversation, identity.tenant_id, identity.user_id, nid, cid)
        return Response(status_code=204)

    # ---- search ----------------------------------------------------------------------------

    @router.post("/notebooks/{nid}/search")
    async def search(
        nid: str, body: Search, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        r = rt()
        if not await call(r.store.owns, identity.tenant_id, identity.user_id, nid):
            raise HTTPException(404, "notebook not found")
        try:
            embedder = r.components.embedder()
        except Unavailable as e:
            raise HTTPException(409, {"code": e.code, "message": e.message}) from None
        from wasifyai_notebooks.embedding import Purpose

        vector = (await asyncio.to_thread(embedder.embed, [body.query], Purpose.QUERY))[0]

        def run() -> list[Any]:
            with r.store.connect() as db:
                return retrieve(
                    db, nid, body.query, vector, weight=embedder.spec.semantic_weight,
                    top_k=body.top_k, document_ids=body.document_ids, mode=body.mode,
                )  # fmt: skip

        hits = await asyncio.to_thread(run)
        return {
            "hits": [
                {
                    "chunk_id": h.chunk_id,
                    "document_id": h.document_id,
                    "title": h.title,
                    "content": h.content,
                    "start_line": h.start_line,
                    "end_line": h.end_line,
                    "score": round(h.score, 4),
                }  # fmt: skip
                for h in hits
            ]
        }

    return router


def _setup(r: Runtime) -> dict[str, Any]:
    if r.installer is None:
        return {"available": False, "message": r.installer_problem}
    return {
        "available": True,
        "installed": r.installer.is_installed(),
        "offer": r.installer.offer(),
        "progress": r.installer.progress.public(),
    }


async def _spool(upload_file: UploadFile, target: Path) -> tuple[int, str]:
    """Stream an upload to a file in 1 MB reads, hashing on the way; never held whole in memory."""
    digest = hashlib.sha256()
    size = 0
    handle = await asyncio.to_thread(target.open, "wb")
    try:
        while True:
            block = await upload_file.read(1 << 20)
            if not block:
                break
            size += len(block)
            if size > hardening.MAX_BYTES:
                break  # the caller refuses it by size; nothing more is written
            digest.update(block)
            await asyncio.to_thread(handle.write, block)
    finally:
        await asyncio.to_thread(handle.close)
    return size, digest.hexdigest()
