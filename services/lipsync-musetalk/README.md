# lipsync-musetalk: the Lip Sync server (ADR-0044)

`POST /v1/lipsync` (multipart: `image`, `audio`, optional `fps`) answers with an MP4 of the voice's length: the
picture's face with its mouth redrawn by **MuseTalk v1.5** (MIT). `GET /health` says the device and whether
the models are loaded (they load on the first request and stay). A picture with no face gets a 422.

Not part of the uv workspace: it runs in its own virtualenv next to the MuseTalk code.

    services/lipsync-musetalk/setup.sh     # once: clones MuseTalk, installs, downloads about 4 GB
    scripts/lipsync-server.sh              # native, port 8191, MPS on a Mac

Then `LIPSYNC_SERVER_URL=http://host.containers.internal:8191` in `.env`. On a CUDA host the same code runs
(`LIPSYNC_DEVICE=cuda`, fp16); a container image for it is still to be written.

`LIPSYNC_MAX_SIDE` (default 768) scales the picture down; blending time grows with the picture's size.
Measured on a 64 GB Apple M-series Mac: a 5 second clip in about 30 seconds after the models are loaded, 11.8 GB
at peak (ADR-0044).

`mark` (optional form field, at most 40 characters) is drawn in the corner of every frame and written into the
file's metadata; the desktop always sends "AI-generated". The two source files here are copied into the engine's
package (`services/api/src/wasifyai_api/lipsync_server/`), which the desktop app runs; a test fails when they differ,
so change both together.
