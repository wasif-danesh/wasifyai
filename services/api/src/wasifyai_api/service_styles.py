"""The service's styles on the web (ADR-0091 decision 13, stage S5).

A person on the web brings no files: an **admin** adds a style from Hugging Face (Admin > Styles).
The API fetches the exact file at its commit, checks its size, checksum and header as the desktop
does, and keeps it in object storage under the service's own part
(`<tenant>/wasifyai-image/service/styles/<id>.safetensors`). Everyone signed in sees the list read
only and may choose from it; a request names a style by id, the graph asks here for its file, and
the media worker fetches that file for the one job (the path a person's taught looks take).

    ServiceStyles   the records (settings store, per tenant), adding from the Hub, delete, resolve
    admin_router    `/admin/styles` (admins)
    router          `/styles` (everyone signed in, read only)
"""

import asyncio
import contextlib
import hashlib
import re
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, object_key, require_context

from wasifyai_api.desktop_hub import HF, HubClient, HubError
from wasifyai_api.desktop_styles import (
    MAX_FILE_BYTES,
    MAX_STYLES,
    StyleRefused,
    card_of,
    read_style_header,
    repo_of,
    style_files_of,
)
from wasifyai_api.identity import get_identity, require_admin
from wasifyai_api.services import services_of

PRODUCT = "wasifyai-image"
SERVICE_USER = "service"  # the owner part of the service's own files (no person)
KEY = "service.styles"


def style_key(tenant: str, style_id: str) -> str:
    return object_key(tenant, PRODUCT, SERVICE_USER, "styles", f"{style_id}.safetensors")


def public(r: dict[str, Any]) -> dict[str, Any]:
    """What everyone may see of a style: a desktop style's record, without the storage key."""
    return {
        "id": r["id"], "title": r["title"],
        "source": {"kind": "hub", "repo": r["repo"], "file": r["file"]},
        "sha256": r["sha256"], "size": r["size"], "model": r["model"], "fit": r["fit"],
        "made_for_base": bool(r.get("base")), "rank": r.get("rank"),
        "unused_parts": r.get("unused_parts", 0),
        "trigger": r.get("trigger"), "added_at": r["added_at"], "selectable": r["fit"] != "other",
    }  # fmt: skip


class ServiceStyles:
    def __init__(
        self,
        settings: Any,
        storage: Any,
        hub: HubClient | None = None,
        client: Any = None,
    ):
        self._settings = settings  # a SettingsStore: the records, one list per tenant
        self._storage = storage  # the raw object storage (keys are whole object keys)
        self._hub = hub or HubClient()
        self._client = client or (
            lambda: httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, read=120))
        )
        self.jobs: dict[str, dict[str, Any]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def all(self, tenant: str) -> list[dict[str, Any]]:
        saved = await self._settings.get(f"{KEY}.{tenant}")
        return [dict(r) for r in saved] if isinstance(saved, list) else []

    async def _put(self, tenant: str, rows: list[dict[str, Any]]) -> None:
        await self._settings.put(f"{KEY}.{tenant}", rows, "admin")

    async def files(self, text: str) -> dict[str, Any]:
        repo = repo_of(text)
        if repo is None:
            raise HubError("bad_repo", "Write a name like owner/name, or paste its address.", 422)
        data, stale = await self._hub.get(f"/api/models/{repo}", {"blobs": "true"}, fresh=True)
        return style_files_of(repo, {**data, "_stale": stale})

    async def add(self, tenant: str, repo: str, file: str, size: int, actor: str) -> dict[str, Any]:
        """Start getting one confirmed file for the whole service; follow it with `job`."""
        if repo_of(repo) != repo:
            raise HubError("bad_repo", "That is not a model name.", 422)
        data, _ = await self._hub.get(f"/api/models/{repo}", {"blobs": "true"}, fresh=True)
        commit = str(data.get("sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise HubError("no_revision", "The model's revision could not be read.", 502)
        if data.get("gated") and not self._hub.has_token:
            raise HubError(
                "needs_token", "This style is gated: it needs a Hugging Face account.", 403
            )
        sib = next((x for x in data.get("siblings", []) if x.get("rfilename") == file), None)
        lfs = (sib or {}).get("lfs") or {}
        real, sha = int(lfs.get("size") or 0), str(lfs.get("sha256") or "")
        if sib is None or not file.lower().endswith(".safetensors") or real != size:
            raise HubError(
                "changed", "The files changed. Look at the style again and confirm.", 409
            )
        if size > MAX_FILE_BYTES or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise HubError("refused", "That file cannot be used as a style.", 422)
        if any(r["sha256"] == sha for r in await self.all(tenant)):
            raise HubError("already_here", "That style is already on the service.", 409)
        job = secrets.token_hex(8)
        self.jobs[job] = {
            "id": job,
            "status": "running",
            "bytes_done": 0,
            "bytes_total": size,
            "error": "",
        }
        url = f"{HF}/{repo}/resolve/{commit}/{quote(file)}"
        source = {"repo": repo, "file": file, "commit": commit, "card": data}
        task = asyncio.get_running_loop().create_task(
            self._get(job, tenant, url, size, sha, source, actor)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return dict(self.jobs[job])

    async def _get(
        self,
        job: str,
        tenant: str,
        url: str,
        size: int,
        sha: str,
        source: dict[str, Any],
        actor: str,
    ) -> None:
        state = self.jobs[job]
        with tempfile.TemporaryDirectory(prefix="wasifyai-style-") as tmp:
            part = Path(tmp) / "style.safetensors"
            try:
                digest = hashlib.sha256()
                headers = {"Authorization": f"Bearer {self._hub.token}"} if self._hub.token else {}
                async with self._client() as http, http.stream("GET", url, headers=headers) as r:
                    if r.status_code != 200:
                        raise StyleRefused(f"Hugging Face answered {r.status_code}.")
                    with part.open("wb") as out:
                        async for chunk in r.aiter_bytes(1 << 20):
                            state["bytes_done"] += len(chunk)
                            if state["bytes_done"] > size:
                                raise StyleRefused("The file is bigger than Hugging Face said.")
                            digest.update(chunk)
                            await asyncio.to_thread(out.write, chunk)
                if state["bytes_done"] != size or digest.hexdigest() != sha:
                    raise StyleRefused("The file that arrived is not the one Hugging Face listed.")
                h = await asyncio.to_thread(read_style_header, part)
                if h.fit == "other":
                    made = h.model or "another model"
                    raise StyleRefused(f"This style was made for {made}: it would give noise here.")
                style_id = secrets.token_hex(6)
                key = style_key(tenant, style_id)
                await self._storage.put(
                    key, await asyncio.to_thread(part.read_bytes), "application/octet-stream"
                )
                base, word = card_of(source["card"])
                title = Path(source["file"]).stem.replace("_", " ").replace("-", " ")[:80]
                record = {
                    "id": style_id, "title": title,
                    "repo": source["repo"], "file": source["file"], "commit": source["commit"],
                    "sha256": sha, "size": size, "model": h.model, "fit": h.fit,
                    "base": base if h.base is None else h.base, "rank": h.rank,
                    "unused_parts": h.unused_parts, "trigger": word or h.trigger, "key": key,
                    "added_by": actor, "added_at": time.time(),
                }  # fmt: skip
                await self._put(tenant, [*await self.all(tenant), record])
                state.update(status="done", style=public(record))
            except StyleRefused as e:
                state.update(status="failed", error=str(e))
            except (httpx.HTTPError, OSError):
                state.update(status="failed", error="The download was interrupted. Try again.")

    def job(self, job_id: str) -> dict[str, Any] | None:
        """The download and, once it is over, the style kept or why not (the desktop's shape)."""
        found = self.jobs.get(job_id)
        if found is None:
            return None
        state = "running" if found["status"] == "running" else "done"
        out: dict[str, Any] = {
            "download": {k: found[k] for k in ("id", "bytes_done", "bytes_total", "error")}
            | {"status": state},
        }
        if found["status"] == "done":
            out["style"] = found["style"]
        elif found["status"] == "failed":
            out["refused"] = found["error"]
        return out

    async def delete(self, tenant: str, style_id: str) -> None:
        rows = await self.all(tenant)
        found = next((r for r in rows if r["id"] == style_id), None)
        if found is None:
            raise KeyError(style_id)
        with contextlib.suppress(FileNotFoundError):
            await self._storage.delete(found["key"])
        await self._put(tenant, [r for r in rows if r["id"] != style_id])

    async def files_for(self, wanted: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        """The image graph's resolver on the web: style ids to their files (by storage key), or
        why not. The tenant is the run's."""
        if len(wanted) > MAX_STYLES:
            return [], f"Please use at most {MAX_STYLES} styles."
        rows = {r["id"]: r for r in await self.all(require_context().tenant_id)}
        out = []
        for w in wanted:
            r = rows.get(str(w.get("id")))
            if r is None:
                return [], "One of those styles is not on this service any more."
            if r["fit"] == "other":
                return [], f"{r['title']} was made for another model and would give noise here."
            out.append({
                "name": f"service-{r['id']}.safetensors", "weight": w.get("strength", 1.0),
                "sha256": r["sha256"], "title": r["title"], "key": r["key"],
            })  # fmt: skip
        return out, ""


# ---- routes -----------------------------------------------------------------------------------

admin_router = APIRouter(prefix="/admin/styles", tags=["admin"])
router = APIRouter(prefix="/styles", tags=["styles"])


def _svc(request: Request) -> ServiceStyles:
    svc = services_of(request).service_styles
    if svc is None:
        raise HTTPException(404, "not available in this deployment")
    return svc


def _hub_error(e: HubError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message})


class Look(BaseModel):
    repo: str = Field(min_length=1, max_length=300)


class Get(BaseModel):
    repo: str = Field(max_length=200)
    file: str = Field(min_length=1, max_length=300)
    bytes: int = Field(ge=1)


@router.get("")
async def list_styles(request: Request, who: Identity = Depends(get_identity)) -> dict[str, Any]:
    """The styles an admin added, for everyone signed in: chosen in a picture, not changed."""
    rows = await _svc(request).all(who.tenant_id)
    return {"styles": [public(r) for r in rows], "found": [], "max": MAX_STYLES}


@admin_router.get("")
async def admin_list(request: Request, who: Identity = Depends(require_admin)) -> dict[str, Any]:
    rows = await _svc(request).all(who.tenant_id)
    styles = [{**public(r), "added_by": r.get("added_by")} for r in rows]
    return {"styles": styles, "found": [], "max": MAX_STYLES}


@admin_router.post("/hub/files")
async def admin_files(
    body: Look, request: Request, _: Identity = Depends(require_admin)
) -> dict[str, Any]:
    try:
        return await _svc(request).files(body.repo)
    except HubError as e:
        raise _hub_error(e) from None


@admin_router.post("/hub/download", status_code=202)
async def admin_download(
    body: Get, request: Request, who: Identity = Depends(require_admin)
) -> dict[str, Any]:
    try:
        return await _svc(request).add(who.tenant_id, body.repo, body.file, body.bytes, who.user_id)
    except HubError as e:
        raise _hub_error(e) from None


@admin_router.get("/hub/downloads/{job_id}")
async def admin_job(
    job_id: str, request: Request, _: Identity = Depends(require_admin)
) -> dict[str, Any]:
    found = _svc(request).job(job_id)
    if found is None:
        raise HTTPException(404, "unknown download")
    return found


@admin_router.delete("/{style_id}", status_code=204)
async def admin_delete(
    style_id: str, request: Request, who: Identity = Depends(require_admin)
) -> None:
    try:
        await _svc(request).delete(who.tenant_id, style_id)
    except KeyError:
        raise HTTPException(404, "no such style") from None
