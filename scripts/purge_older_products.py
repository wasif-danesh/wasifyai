"""Delete the stored files of the older music, speech, transcript and lip sync products.

The database rows go with migration 0019 (`make migrate`); the files they pointed at stay in
object storage until this runs. Keys are `{tenant}/{product}/{user}/{path}`; every key whose
product segment is one of the four is deleted, nothing else. It only lists unless told to delete:

    uv run python scripts/purge_older_products.py            # what would go
    uv run python scripts/purge_older_products.py --yes      # delete it

This cannot be undone. Run with the stack up (make dev)."""

import os
import sys
from pathlib import Path

import obstore
from obstore.store import S3Store

BUCKET = "wasifyai"
OLDER = {"wasifyai-music", "wasifyai-tts", "wasifyai-stt", "wasifyai-lipsync"}


def env() -> dict[str, str]:
    """STORAGE_* from the environment, else the repo's .env (values are never printed)."""
    out: dict[str, str] = {}
    f = Path(__file__).resolve().parents[1] / ".env"
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.startswith("STORAGE_") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    out.update({k: v for k, v in os.environ.items() if k.startswith("STORAGE_")})
    return out


def open_store(cfg: dict[str, str]) -> S3Store:
    endpoint = cfg.get("STORAGE_PUBLIC_ENDPOINT") or "http://localhost:8333"
    return S3Store(
        cfg.get("STORAGE_BUCKET", BUCKET),
        endpoint=endpoint,
        access_key_id=cfg["STORAGE_ACCESS_KEY"],
        secret_access_key=cfg["STORAGE_SECRET_KEY"],
        region=cfg.get("STORAGE_REGION", "us-east-1"),
        client_options={"allow_http": endpoint.startswith("http://")},
        virtual_hosted_style_request=False,
    )


def is_older(key: str) -> bool:
    parts = key.split("/")
    return len(parts) >= 3 and parts[1] in OLDER


def main(argv: list[str]) -> int:
    delete = "--yes" in argv
    store = open_store(env())
    keys: list[str] = []
    size = 0
    for batch in obstore.list(store):
        for item in batch:
            if is_older(item["path"]):
                keys.append(item["path"])
                size += item["size"]
    print(f"{len(keys)} files, {size / 1024**2:.1f} MB belong to the older products")
    if not delete:
        print("nothing deleted; run again with --yes to delete them")
        return 0
    for i in range(0, len(keys), 500):
        obstore.delete(store, keys[i : i + 500])
    print(f"deleted {len(keys)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
