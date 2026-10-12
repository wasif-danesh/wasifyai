"""Copy stored files from the former bucket to the new one, rewriting each key's product segment.

Keys are `{tenant}/{product}/{user}/{path}`. The product ids were renamed
(wd-music-ai -> wasifyai-music ...) and the bucket was renamed (wd-ai -> wasifyai), so existing
files would otherwise be unreachable. Objects are copied, never deleted or overwritten. Run with
the stack up (make dev), after scripts/migrate-from-wd.sh:

    uv run python scripts/migrate_storage.py [--dry-run]
"""

import os
import sys
from pathlib import Path

import obstore
from obstore.store import S3Store

OLD_BUCKET, NEW_BUCKET = "wd-ai", "wasifyai"
PRODUCTS = {
    "wd-music-ai": "wasifyai-music",
    "wd-image-ai": "wasifyai-image",
    "wd-video-ai": "wasifyai-video",
    "wd-tts-ai": "wasifyai-tts",
    "wd-stt-ai": "wasifyai-stt",
    "wd-lipsync-ai": "wasifyai-lipsync",
}


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


def store(cfg: dict[str, str], bucket: str) -> S3Store:
    endpoint = cfg.get("STORAGE_PUBLIC_ENDPOINT") or "http://localhost:8333"
    return S3Store(
        bucket,
        endpoint=endpoint,
        access_key_id=cfg["STORAGE_ACCESS_KEY"],
        secret_access_key=cfg["STORAGE_SECRET_KEY"],
        region=cfg.get("STORAGE_REGION", "us-east-1"),
        client_options={"allow_http": endpoint.startswith("http://")},
        virtual_hosted_style_request=False,
    )


def new_key(key: str) -> str:
    parts = key.split("/")
    if len(parts) >= 2 and parts[1] in PRODUCTS:
        parts[1] = PRODUCTS[parts[1]]
    return "/".join(parts)


def main() -> None:
    dry = "--dry-run" in sys.argv
    cfg = env()
    if not cfg.get("STORAGE_ACCESS_KEY"):
        sys.exit("STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY are not set (.env or environment)")
    old, new = store(cfg, OLD_BUCKET), store(cfg, NEW_BUCKET)
    copied = skipped = 0
    for batch in obstore.list(old):
        for item in batch:
            src, dst = item["path"], new_key(item["path"])
            try:
                obstore.head(new, dst)
                skipped += 1
                continue
            except FileNotFoundError:
                pass
            if not dry:
                res = obstore.get(old, src)
                obstore.put(new, dst, res.bytes(), attributes=res.attributes)
            copied += 1
    print(f"{'would copy' if dry else 'copied'}: {copied}, already there: {skipped}")


if __name__ == "__main__":
    main()
