"""The model hub (ADR-0064): browse open-weight models on Hugging Face and fetch one.

    HubClient     the Hugging Face API, with a cache and a stale answer when offline
    HubService    consent, the curated shelf, search, one repository with its variants and
                  their fit, and the confirmed download (re-checked here: the window's numbers
                  are not trusted)
    router        `/desktop/hub/...` routes the window uses

The window never talks to the internet (ADR-0064 decision 2): everything goes through here.
Nothing is requested before the person has agreed (decision 4), and nothing is fetched without
the confirmation of the exact files and size (the download manager, ADR-0059). Pickle formats
are never offered.
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, SecretStore, SecretsUnavailable

from wasifyai_api.desktop_fit import Fit, Machine, assess_fit, need_of_image, need_of_language
from wasifyai_api.desktop_models import DownloadError, ModelEntry, ModelFile
from wasifyai_api.identity import get_identity
from wasifyai_api.safeguards import SettingsStore
from wasifyai_api.services import services_of

log = logging.getLogger(__name__)

HF = "https://huggingface.co"
KEY = "desktop.hub"
TOKEN = "hf.token"  # the person's Hugging Face token in the secret store (ADR-0092)
# the environment variables that answer `hf.token` when the store has none (a developer's shell)
TOKEN_ALIASES: dict[str, tuple[str, ...]] = {TOKEN: ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")}
TOKEN_PATTERN = re.compile(r"^hf_[A-Za-z0-9]{20,200}$")
SHELF_FILE = Path(__file__).with_name("hub-shelf.yaml")
CACHE_TTL_S = 600
SEARCH_FIELDS = (
    "downloads",
    "likes",
    "pipeline_tag",
    "gated",
    "lastModified",
    "library_name",
    "tags",
)
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SHARD = re.compile(r"^(?P<stem>.+)-(?P<n>\d{5})-of-(?P<of>\d{5})\.gguf$")
QUANT = re.compile(r"(?:^|[-_.])((?:I?Q\d(?:_[A-Z0-9]+)*)|BF16|F16|F32)(?:[-_.]|$)", re.I)

LANGUAGE_PIPES = {"text-generation", "image-text-to-text", "text2text-generation", "conversational"}
EMBEDDING_PIPES = {"feature-extraction", "sentence-similarity"}
CAPABILITIES = ("language", "embedding", "image", "video")
SORTS = {"downloads": "downloads", "likes": "likes", "recent": "lastModified"}


class HubError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def capability_of(pipeline: str | None, tags: list[str], name: str = "") -> str:
    """What a repository is for, from its pipeline tag and tags (language, embedding, image...)."""
    pipe = pipeline or ""
    if (
        pipe in EMBEDDING_PIPES
        or "embedding" in name.lower()
        or "text-embeddings-inference" in tags
    ):
        return "embedding"
    if pipe in LANGUAGE_PIPES:
        return "language"
    if pipe in ("text-to-image", "image-to-image", "image-text-to-image"):
        return "image"
    if pipe in ("text-to-video", "image-to-video", "video-to-video"):
        return "video"
    return "other"


def license_of(tags: list[str], card: dict[str, Any] | None) -> str:
    lic = (card or {}).get("license")
    if isinstance(lic, str) and lic:
        return lic
    return next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")


def quant_of(name: str) -> str:
    m = QUANT.search(name)
    return m.group(1).upper() if m else ""


def variants_of(siblings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `.gguf` files of a repository as things a person picks: one per quantisation, the shards
    of one model grouped, vision projectors left out. Each has the checksum the Hub publishes."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in siblings:
        name = str(s.get("rfilename", ""))
        if not name.lower().endswith(".gguf") or "mmproj" in name.lower():
            continue
        m = SHARD.match(name.rsplit("/", 1)[-1])
        key = (name.rsplit("/", 1)[0] + "/" if "/" in name else "") + (m["stem"] if m else name)
        groups.setdefault(key, []).append(s)
    out = []
    for key, parts in groups.items():
        parts.sort(key=lambda p: p["rfilename"])
        lfs = [p.get("lfs") or {} for p in parts]
        if not all(x.get("sha256") for x in lfs):
            continue  # a file without a published checksum is never offered
        out.append(
            {
                "id": key,
                "name": key.rsplit("/", 1)[-1].removesuffix(".gguf"),
                "quant": quant_of(parts[0]["rfilename"]),
                "files": [p["rfilename"] for p in parts],
                "sizes": [
                    int(x.get("size") or p.get("size") or 0)
                    for x, p in zip(lfs, parts, strict=True)
                ],
                "size": sum(
                    int(x.get("size") or p.get("size") or 0)
                    for x, p in zip(lfs, parts, strict=True)
                ),
                "sha256": [x["sha256"] for x in lfs],
            }
        )
    return sorted(out, key=lambda v: v["size"])


def clean_readme(text: str) -> str:
    """A model card as plain text: no front matter, no HTML, no pictures (nothing is loaded from the
    card's hosts, ADR-0064 decision 9)."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.I)
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:20_000]


class HubClient:
    """The Hugging Face API. Answers are kept for ten minutes; when the network fails the last
    answer is returned, marked stale, so Discover still shows something offline."""

    def __init__(
        self,
        base: str = HF,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        ttl_s: float = CACHE_TTL_S,
    ):
        self._base = base.rstrip("/")
        self._token = token
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15, read=30))
        self._ttl = ttl_s
        self._cache: dict[str, tuple[float, Any]] = {}

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    @property
    def token(self) -> str | None:
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        self._token = value or None

    async def get(self, path: str, params: Any = None, *, fresh: bool = False) -> tuple[Any, bool]:
        """(json, stale)."""
        key = path + "?" + repr(sorted(params.items()) if isinstance(params, dict) else params)
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and not fresh and now - hit[0] < self._ttl:
            return hit[1], False
        headers = {"authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            r = await self._client.get(self._base + path, params=params, headers=headers)
        except httpx.HTTPError:
            if hit:
                return hit[1], True
            raise HubError(
                "offline", "Hugging Face could not be reached. Check the connection and try again."
            ) from None
        if r.status_code == 404:
            raise HubError("not_found", "That model is not on Hugging Face.", 404)
        if r.status_code in (401, 403):
            raise HubError(
                "needs_token",
                "This model needs a Hugging Face account that has accepted its terms.",
                403,
            )
        if r.status_code == 429:
            if hit:
                return hit[1], True
            raise HubError(
                "rate_limited", "Hugging Face asked us to slow down. Try again in a minute.", 429
            )
        if r.status_code >= 400:
            raise HubError("hub_error", f"Hugging Face answered {r.status_code}.", 502)
        value = r.json()
        self._cache[key] = (now, value)
        return value, False

    async def text(self, path: str) -> str:
        headers = {"authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            r = await self._client.get(self._base + path, headers=headers)
        except httpx.HTTPError:
            raise HubError("offline", "Hugging Face could not be reached.") from None
        if r.status_code != 200:
            return ""
        return r.text[:200_000]

    async def close(self) -> None:
        await self._client.aclose()


def load_shelf(path: Path = SHELF_FILE) -> list[dict[str, Any]]:
    """The curated shelf; the recommended model comes first (chosen by measurement)."""
    raw = yaml.safe_load(path.read_text()) or {}
    out: list[dict[str, Any]] = []
    for m in raw.get("models") or []:
        if REPO.match(str(m.get("repo", ""))):
            row: dict[str, Any] = {
                k: str(m.get(k, "")) for k in ("repo", "title", "capability", "note")
            }
            row["recommended"] = bool(m.get("recommended", False))
            out.append(row)
    return sorted(
        out, key=lambda r: not r["recommended"]
    )  # a stable sort: the rest keep their order


class HubService:
    def __init__(
        self,
        store: SettingsStore,
        client: HubClient | None = None,
        secrets: SecretStore | None = None,
    ):
        self._store = store
        self._secrets = secrets  # where the token lives; the environment answers when it has none
        self.client = client or HubClient()
        self.token_set = False  # a token is in the store (not merely in the environment)
        self.enabled = False
        self.shelf = load_shelf()
        self.models: Any = None  # ModelsService: the folder, the download manager
        self.language: Any = None  # LanguageService: the machine as the engine sees it, the context

    async def load(self) -> None:
        saved = await self._store.get(KEY)
        if isinstance(saved, dict):
            self.enabled = bool(saved.get("enabled", False))
        await self._apply_token()

    # ---- the token (ADR-0092): kept in the secret store, shown as set or not, never read back ---

    @property
    def can_save_token(self) -> bool:
        return bool(self._secrets is not None and self._secrets.ready)

    async def _apply_token(self) -> None:
        """Give the hub client and the downloader the token the store (or the environment) has."""
        token: str | None = None
        if self._secrets is not None:
            try:
                token = await self._secrets.get(TOKEN)
            except SecretsUnavailable as e:
                log.warning("the Hugging Face token cannot be read: %s", e)
            self.token_set = TOKEN in await self._secrets.names()
        if token is None:
            token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None
        self.client.token = token
        if self.models is not None:
            self.models.downloads._token = token  # noqa: SLF001 - one place for the token

    async def set_token(self, value: str) -> None:
        value = value.strip()
        if not TOKEN_PATTERN.match(value):
            raise HubError(
                "bad_token",
                "That does not look like a Hugging Face token: it starts with hf_ and has no "
                "spaces.",
                400,
            )
        if not self.can_save_token:
            raise HubError("no_store", "Tokens cannot be saved on this computer.", 400)
        assert self._secrets is not None
        await self._secrets.put(TOKEN, value)
        await self._apply_token()

    async def clear_token(self) -> None:
        if self._secrets is not None:
            await self._secrets.delete(TOKEN)
        await self._apply_token()

    async def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self._store.put(KEY, {"enabled": enabled}, "window")

    def require(self) -> None:
        if not self.enabled:
            raise HubError(
                "consent_needed",
                "Browsing models contacts huggingface.co. Turn it on first.",
                403,
            )

    # ---- browsing ------------------------------------------------------------------------

    async def search(
        self, query: str, capability: str = "language", sort: str = "downloads", limit: int = 30
    ) -> dict[str, Any]:
        self.require()
        params: list[tuple[str, str]] = [
            ("sort", SORTS.get(sort, "downloads")),
            ("direction", "-1"),
            ("limit", str(min(max(limit, 1), 50))),
        ]
        if query.strip():
            params.append(("search", query.strip()[:100]))
        if capability in ("language", "embedding"):
            params.append(("filter", "gguf"))  # what the app's engine can read
        elif capability == "image":
            params.append(("pipeline_tag", "text-to-image"))
        elif capability == "video":
            params.append(("pipeline_tag", "text-to-video"))
        params += [("expand[]", f) for f in SEARCH_FIELDS]
        data, stale = await self.client.get("/api/models", params)
        items = []
        for m in data if isinstance(data, list) else []:
            tags = [t for t in m.get("tags", []) if isinstance(t, str)]
            cap = capability_of(m.get("pipeline_tag"), tags, str(m.get("id", "")))
            if capability in ("language", "embedding") and "gguf" not in tags:
                continue  # the engine reads GGUF; the Hub's filter is trusted, not relied on
            if capability in ("language", "embedding") and cap not in ("language", "embedding"):
                continue
            if capability == "language" and cap != "language":
                continue
            if capability == "embedding" and cap != "embedding":
                continue
            repo = str(m.get("id", ""))
            if not REPO.match(repo):
                continue
            items.append(
                {
                    "id": repo, "publisher": repo.split("/")[0], "name": repo.split("/")[1],
                    "downloads": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0),
                    "updated": m.get("lastModified"), "capability": cap,
                    "pipeline": m.get("pipeline_tag"), "gated": bool(m.get("gated")),
                    "license": license_of(tags, None),
                    "gguf": "gguf" in tags or m.get("library_name") == "gguf",
                    # only the app's engine can run what is a GGUF language or embedding model
                    "runnable": cap in ("language", "embedding") and ("gguf" in tags),
                }
            )  # fmt: skip
        return {"items": items, "stale": stale, "capability": capability}

    async def detail(self, repo: str, fresh: bool = False) -> dict[str, Any]:
        self.require()
        if not REPO.match(repo):
            raise HubError("bad_repo", "That is not a model name.", 422)
        data, stale = await self.client.get(
            f"/api/models/{quote(repo, safe='/')}", {"blobs": "true"}, fresh=fresh
        )
        tags = [t for t in data.get("tags", []) if isinstance(t, str)]
        cap = capability_of(data.get("pipeline_tag"), tags, repo)
        gguf = data.get("gguf") or {}
        variants = variants_of(data.get("siblings", []))
        return {
            "id": repo, "commit": data.get("sha"), "stale": stale,
            "capability": cap, "pipeline": data.get("pipeline_tag"),
            "license": license_of(tags, data.get("cardData")), "gated": bool(data.get("gated")),
            "downloads": int(data.get("downloads") or 0), "likes": int(data.get("likes") or 0),
            "updated": data.get("lastModified"), "tags": [t for t in tags if ":" not in t][:12],
            "architecture": gguf.get("architecture"), "context_length": gguf.get("context_length"),
            "parameters": gguf.get("total"), "has_chat_template": bool(gguf.get("chat_template")),
            "variants": variants,
            "runnable": cap in ("language", "embedding") and bool(variants),
        }  # fmt: skip

    async def readme(self, repo: str) -> str:
        self.require()
        if not REPO.match(repo):
            raise HubError("bad_repo", "That is not a model name.", 422)
        return clean_readme(await self.client.text(f"/{quote(repo, safe='/')}/raw/main/README.md"))

    # ---- fit -----------------------------------------------------------------------------

    def fit_of(
        self, detail: dict[str, Any], variant: dict[str, Any], machine: Machine | None, context: int
    ) -> Fit | None:
        if machine is None:
            return None
        if detail["capability"] in ("language", "embedding"):
            need = need_of_language(variant["size"], chosen=context)
        else:
            need = need_of_image(variant["size"], video=detail["capability"] == "video")
        return assess_fit(need, machine)

    # ---- getting a model -----------------------------------------------------------------

    async def build_download(self, repo: str, names: list[str], total: int) -> ModelEntry:
        """The catalogue entry for exactly the files the person confirmed, from a fresh look at the
        repository at its current commit. The window's sizes and checksums are not used."""
        detail = await self.detail(repo, fresh=True)
        commit = detail["commit"]
        if not commit or not re.fullmatch(r"[0-9a-f]{40}", str(commit)):
            raise HubError("no_revision", "The model's revision could not be read.", 502)
        if detail["gated"] and not self.client.has_token:
            raise HubError(
                "needs_token",
                "This model is gated: it needs a Hugging Face account that accepted its terms. "
                "Account sign-in is not set up in this version.",
                403,
            )
        wanted = set(names)
        match = next((v for v in detail["variants"] if set(v["files"]) == wanted), None)
        if match is None or match["size"] != total:
            raise HubError(
                "changed", "The files changed. Look at the model again and confirm.", 409
            )
        folder = "language/" + repo.replace("/", "--")
        files = tuple(
            ModelFile(
                folder, name.rsplit("/", 1)[-1],
                f"{HF}/{quote(repo, safe='/')}/resolve/{commit}/{quote(name)}", size, sha,
            )
            for name, size, sha in zip(
                match["files"], match["sizes"], match["sha256"], strict=True
            )
        )  # fmt: skip
        return ModelEntry(
            id=f"hub:{repo}",
            product_id="hub",
            title=repo,
            licence=detail["license"] or "unknown",
            source=f"huggingface.co/{repo}",
            note="",
            approx_ram_gb=0,
            files=files,
        )


# ---- routes -----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/hub", tags=["desktop"])


def _hub(request: Request) -> HubService:
    svc = services_of(request).desktop_hub
    if svc is None:
        raise HTTPException(404, "not available in this deployment")
    return svc


def _http(exc: HubError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


class Consent(BaseModel):
    enabled: bool


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=300)


class DownloadRequest(BaseModel):
    repo: str
    files: list[str] = Field(min_length=1)
    bytes: int
    accept_memory: bool = False


@router.get("/state")
async def hub_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    svc = _hub(request)
    return {
        "enabled": svc.enabled, "has_token": svc.client.has_token, "shelf": svc.shelf,
        "capabilities": list(CAPABILITIES),
        "token_set": svc.token_set, "can_save_token": svc.can_save_token,
    }  # fmt: skip


@router.put("/token")
async def hub_token(
    body: TokenIn, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    """Keep the person's Hugging Face token. It is never answered back, only whether one is set."""
    svc = _hub(request)
    try:
        await svc.set_token(body.token)
    except HubError as exc:
        raise _http(exc) from None
    return {"token_set": svc.token_set}


@router.delete("/token")
async def hub_token_delete(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    svc = _hub(request)
    await svc.clear_token()
    return {"token_set": svc.token_set}


@router.put("/consent")
async def hub_consent(
    body: Consent, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    svc = _hub(request)
    await svc.set_enabled(body.enabled)
    return {"enabled": svc.enabled}


@router.get("/search")
async def hub_search(
    request: Request,
    q: str = "",
    capability: str = "language",
    sort: str = "downloads",
    limit: int = 30,
    _: Identity = Depends(get_identity),
) -> dict[str, Any]:
    svc = _hub(request)
    try:
        return await svc.search(q, capability, sort, limit)
    except HubError as exc:
        raise _http(exc) from None


@router.get("/models/{publisher}/{name}")
async def hub_model(
    publisher: str, name: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _hub(request)
    repo = f"{publisher}/{name}"
    try:
        d = await svc.detail(repo)
    except HubError as exc:
        raise _http(exc) from None
    machine = await svc.language.machine() if svc.language is not None else None
    sel = svc.language.selected if svc.language is not None else None
    context = sel.context if sel else 8192
    for v in d["variants"]:
        fit = svc.fit_of(d, v, machine, context)
        v["fit"] = fit.public() if fit else None
    return d


@router.get("/models/{publisher}/{name}/readme")
async def hub_readme(
    publisher: str, name: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, str]:
    svc = _hub(request)
    try:
        return {"text": await svc.readme(f"{publisher}/{name}")}
    except HubError as exc:
        raise _http(exc) from None


@router.post("/download")
async def hub_download(
    body: DownloadRequest, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _hub(request)
    models = svc.models
    if models is None:
        raise HTTPException(404, "not available in this deployment")
    try:
        entry = await svc.build_download(body.repo, body.files, body.bytes)
    except HubError as exc:
        raise _http(exc) from None
    if not body.accept_memory and svc.language is not None:
        machine = await svc.language.machine()
        total = sum(f.size for f in entry.files)
        if machine is not None:
            fit = assess_fit(need_of_language(total), machine)
            if fit.verdict == "too_big":
                raise HTTPException(409, f"This model will not fit on this computer. {fit.reason}")
    try:
        d = models.downloads.start(entry, list(entry.files), models.models_dir)
    except DownloadError as exc:
        raise HTTPException(409, str(exc)) from None
    return d.public()


async def remove_downloaded(models: Any, path: Path) -> bool:
    """Delete a file the hub downloaded (under the app's `language` folder, nowhere else)."""
    root = (models.models_dir / "language").resolve()

    def go() -> bool:
        p = path.resolve()
        if not p.is_relative_to(root) or not p.is_file():
            return False
        p.unlink()
        parent = p.parent
        if parent != root and not any(parent.iterdir()):
            parent.rmdir()
        return True

    return await asyncio.to_thread(go)


@router.delete("/files/{item_id}")
async def hub_remove(
    item_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    """Delete a model this app downloaded. Only files under the app's own `language` folder; a file
    another tool keeps is never touched."""
    svc = _hub(request)
    discovery = services_of(request).desktop_discovery
    item = next((i for i in (discovery.items if discovery else []) if i.id == item_id), None)
    if svc.models is None or item is None or item.tool != "app":
        raise HTTPException(404, "That file is not one this app downloaded.")
    language = svc.language
    if language is not None and language.selected and language.selected.path == item.path:
        await language.clear()  # it was the chat model: nothing is chosen any more
    removed = await remove_downloaded(svc.models, Path(item.path))
    if discovery is not None and not discovery.running:
        asyncio.create_task(discovery.scan())
    return {"removed": removed}
