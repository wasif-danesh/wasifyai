# ADR-0034: Song downloads: audio with its cover inside, and a video

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The Download buttons linked to the storage server, and browsers ignore the `download` attribute on a
link to another origin, so files opened in a tab instead of saving. Users also wanted what Suno gives
them: one file that shows the cover while the song plays.

## Decision

- **Downloads come from the app's own origin**, through
  `GET /products/wasifyai-music/songs/{id}/download/{audio|cover|video}` (API) and the same path under
  `/api/` (web). The response carries `Content-Disposition: attachment` and a readable file name. The
  song is looked up for the signed-in user only, so another user's song, a missing file or a song with
  no cover are all a plain 404. This is the one place the API streams file bytes (rule 10); events and
  JSON still carry URLs.
- **`audio` is the MP3 with an ID3v2.3 tag**: title, artist ("WasifyAI Studio"), album, lyrics, a comment
  and the cover as front-cover art (a JPEG of at most 1000 px, about 200 KB, made from the stored PNG).
  Phone, desktop and car players and file thumbnails then show the cover. The audio frames are not
  re-encoded, the stored file is not changed, and the tag is added on each download. If the cover or
  tagging fails the plain MP3 is served. The tag writer is our own (about 80 lines) because the usual
  libraries, `mutagen` and `eyeD3`, are GPL; its output is checked against `ffmpeg`.
- **`video` is the cover as a still picture with the song playing**: H.264 and AAC in an MP4, even
  dimensions and `yuv420p`, which phones and social apps accept. It is made on the first request,
  stored next to the song (`video.mp4`) and served from storage afterwards. One encode runs at a time
  per song and two at once overall. It takes about a second for a minute of music. A song with no cover
  has no video.
- **ffmpeg comes from the `imageio-ffmpeg` package**: a static binary of about 50 MB inside the Python
  environment, the same on every machine and in the image, and `ffmpeg` on the PATH only as a fallback.
  Debian's `ffmpeg` package was tried and rejected: it added about 414 MB to the API image (LLVM, Mesa,
  speech libraries). It has no `ffprobe`, so the audio's length is read from `ffmpeg -i`.
- **The video is cut at the audio's exact length** (`-t`). `-shortest` alone let the looped picture
  run about 5 seconds past a 60-second song. The cover is first re-saved as a plain RGB PNG: an
  unreadable picture makes `ffmpeg -loop 1` wait for its timeout, and a JPEG would make the video
  full-range.
- **Licence.** `imageio-ffmpeg` is BSD-2-Clause, but the binary it bundles is an unmodified GPL build of
  ffmpeg (it includes x264). We run it as a separate program and never link it. Images that contain it
  and are published must make its source available; the source for the bundled version is the
  imageio-ffmpeg and ffmpeg.org releases, which is the written offer to keep with the images. Pillow
  (HPND) is a permissive dependency.

## Consequences

- New dependencies in `wasifyai-music`: `pillow` and `imageio-ffmpeg`. No system packages.
- A downloaded MP3 is about 200 KB larger than the stored one.
- A video is stored for each song someone downloads it for (about 2 MB); there is no clean-up yet.
- The first "Download video" click takes a second or two. Cached video is not invalidated if a cover
  is ever replaced.
- The browser's own audio player does not show embedded art; the song page shows the cover next to it.
