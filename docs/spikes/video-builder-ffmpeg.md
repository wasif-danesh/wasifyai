# Video Builder: shipping FFmpeg and ffprobe (plan 2026-10-21; **option B built and tested the same day**, see the end)

**Why.** HyperFrames needs `ffmpeg` and `ffprobe` and brings neither. Today the engine finds Homebrew's and says
"run `brew install ffmpeg`" when they are missing (ADR-0079 correction). A person without Homebrew cannot use Video Builder,
so "set up" should be the whole job.

## What HyperFrames asks of FFmpeg (read from its code, locally)

Encoders named in `hyperframes/dist`: `libx264` (MP4), `libvpx-vp9` (WebM with alpha), `prores_ks` (ProRes 4444 MOV), `aac`,
`libopus`, and `h264_videotoolbox` as an option; `libx265` is named too. It locates the tools in this order: the environment
(`HYPERFRAMES_FFMPEG_PATH`, `HYPERFRAMES_FFPROBE_PATH`), `PATH`, `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`, `/bin`, then
**the npm packages `@ffmpeg-installer/ffmpeg` and `@ffprobe-installer/ffprobe` of the project**. The owner's Homebrew build is
FFmpeg 8.1.1 with `--enable-gpl --enable-libx264 --enable-libvpx --enable-libx265`.

## Options

| | What | Size | Licence of what we ship | Work | Risk |
|---|---|---|---|---|---|
| **A** | Keep Homebrew, say so in words (built) | 0 | none | done | people without Homebrew are stuck |
| **B** | Add `@ffmpeg-installer/ffmpeg` and `@ffprobe-installer/ffprobe` to the component's npm lock (HyperFrames finds them by itself) | about 55 MB on disk (36.8 MB and 18.2 MB for darwin-arm64) | packages say LGPL-2.1; the **ffmpeg binary's own licence is FFmpeg's `LICENSE.md`**, and a static build with x264 is GPL (to be read from the real binary) | about a day | the build is old (the platform package is 4.1.5) and may lack an encoder or flag HyperFrames uses; has to be tested |
| **C** | Pinned static arm64 builds downloaded by us with a SHA-256 (like Node and the browser) from a third-party build site | about 30 to 80 MB | GPL (x264/x265 builds) | 1 to 2 days | trusting one site; a new download host |
| **D** | Our own LGPL-only FFmpeg build (no x264/x265: `h264_videotoolbox`, `libvpx`, `prores_ks`), hosted on our release page | about 25 MB | LGPL-2.1+, the cleanest | 3 to 4 days, a build in CI | MP4s come from the hardware encoder (different size and look; the "byte-identical" claim changes) |
| `ffmpeg-static` | npm, GPL-3.0-or-later | | | | **rejected**: it downloads its binary in an install script and we install with `--ignore-scripts` |

Recommended: **B if its binary passes the checks below, else C; D later if GPL is not acceptable.**

## Licence reading (not legal advice; counsel to confirm, with D10)

- FFmpeg is LGPL-2.1-or-later by default. `--enable-gpl` (needed for x264 and x265) makes the whole **binary** GPL-2.0-or-later;
  `--enable-version3` makes it version 3; `--enable-nonfree` binaries cannot be redistributed at all (check the config line).
- We run it as a **separate program** (HyperFrames starts it; we never link it), which is the normal "aggregation" case: the
  AGPL desktop shell and the Apache-2.0 rest do not become GPL. What follows from shipping a GPL binary: ship its licence text
  and a source offer (a link to the exact FFmpeg source and the builder's repository), do not forbid anyone from replacing it, and
  list it in the setup card and the app's notices. A binary fetched from npm on the person's request makes the publisher the
  first distributor and us the second, so the notice is ours to show.
- The patent side is separate from copyright: H.264/AAC encoders (x264, `aac`) carry patent pools; VP9 and Opus are royalty-free;
  ProRes is Apple's format (`prores_ks` is a clean-room encoder). An app that ships an H.264 encoder is the kind of thing counsel
  should read once. Option D without x264 uses the Mac's own hardware encoder, which Apple licenses.
- `ffprobe` is only a reader: its `@ffprobe-installer` binaries are LGPL builds, no encoder, no GPL question.

## Steps for B (after approval)

1. Inspect, in a scratch folder outside the repo: download the two darwin-arm64 tarballs (`@ffmpeg-installer/darwin-arm64@4.1.5`,
   `@ffprobe-installer/darwin-arm64@5.0.1`), read `ffmpeg -version` (configuration line: `--enable-gpl`? `--enable-nonfree`?),
   `ffmpeg -encoders` for `libx264`, `libvpx-vp9`, `prores_ks`, `aac`, and that they run (ad-hoc signed; not blocked by Gatekeeper).
2. Run the gated suite with only those tools (`HYPERFRAMES_FFMPEG_PATH` and `HYPERFRAMES_FFPROBE_PATH` set, no Homebrew on the path):
   the five templates, 90 seconds, WebM alpha decoding, ProRes 4444.
3. If they pass: add the two packages (exact versions) to `package.json`, regenerate the lock, update the pins (hash, bytes), and
   put the two parts in the setup card's list with version, licence and source.
4. `find_media_tools()` prefers the component's copies, then the computer's; the render environment names the exact paths.
5. Notices: licence text and source links in the component folder and in the app's licence page; `docs/desktop-profile.md` and the
   ADR-0077 amendment updated; CI drops the Homebrew step and runs on a runner with no FFmpeg.
6. Tests: unit (order of preference, fallback), gated (a render with the component's tools only), and the existing "FFmpeg is
   missing" message stays for a failed install.

If B fails a check, the same steps follow with C (a pinned download in `video_builder_pins.json`, SHA-256 checked like Node).

## Needs the owner

1. Approve downloading the two packages above (about 55 MB unpacked, a few seconds) into a scratch folder to read the real build
   and test it, nothing installed anywhere else.
2. Decide whether a GPL FFmpeg run as a separate program, with notices and a source link, is acceptable, or whether it must be
   LGPL-only (option D).

## Outcome (2026-10-21): option B, built

The owner approved downloading and decided "install the right version automatically, the licence does not matter".

- **Inspected** (scratch folder outside the repo): `@ffmpeg-installer/darwin-arm64` 4.1.5 holds **FFmpeg 4.4** (config: `--enable-gpl
  --enable-version3 --enable-nonfree`, libx264, libx265, libvpx, libvpx-vp9, libopus, libaom, VideoToolbox; encoders `libx264`,
  `libvpx-vp9`, `prores_ks`, `aac` all present), an arm64 Mach-O, ad-hoc signed, runs; `@ffprobe-installer/darwin-arm64` 5.0.1 holds
  **ffprobe 4.4.1**, whose executable bit is set by an install script (`chmod u+x`) that the component does not run.
- **Tested with only those tools** (a render's file says `Lavf58.76.100`, FFmpeg 4.4): all five templates, the 20 hostile slot
  cases, WebM alpha and ProRes 4444 decoding, 90 second videos, the hostile sandbox corpus: 328 gated tests pass, on a component
  installed from nothing by the real installer in 38 s (no Homebrew tool used).
- **Built:** both packages in `package.json` and the lock (exact versions), pins updated (the download is 318 MB), the finder
  prefers the component's copies and falls back to the computer's, the installer sets the executable bit and checks FFmpeg starts
  and lists the four encoders and that ffprobe starts, the setup card lists "FFmpeg and ffprobe" as a part, CI no longer
  installs Homebrew's FFmpeg and its gated tests use the component's tools.
- **Cost:** FFmpeg 4.4 is about **twice as slow** as the 8.1 on this Mac for the longest videos (53 s against 26 s for a 90 second
  transparent WebM). If that matters, option C (a pinned FFmpeg 7 or 8 static arm64 build with a SHA-256) replaces the two packages.
