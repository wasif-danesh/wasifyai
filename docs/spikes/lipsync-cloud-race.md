# Cloud lip sync: four fal.ai models timed (2026-11-12)

Why: the first real InfiniteTalk run on fal.ai took 24 minutes for 5 s (11.5 min waiting to start, 12 min making
129 frames at 720p; fal.ai's request log). The owner asked for a faster cloud lip sync and for four models to be
timed at 480p on 3 s of voice.

How: one portrait (the app's own, cut to 532x480) and 3.00 s of Kokoro speech, uploaded once to fal.ai's file store,
then sent to the four models at the same moment with the owner's key. Times are fal.ai's own request log
(`api.fal.ai/v1/models/requests/by-endpoint`: `sent_at`, `started_at`, `ended_at`) and the wall time seen here.
Clips: `docs/listening/samples/lipsync-cloud-race/` (`compare.mp4`: Fabric top left, Kling top right, OmniHuman
bottom left, InfiniteTalk bottom right).

| Model (endpoint) | Asked | Made | Wait before start | Making | Wall | Price | This clip |
|---|---|---|---|---|---|---|---|
| VEED Fabric 1.0 Fast (`veed/fabric-1.0/fast`) | 480p | 640x640, 25 fps, 3.00 s | 0.2 s | 14.4 s | **16.8 s** | $0.10/s at 480p | $0.30 |
| Kling AI Avatar v2 Standard (`fal-ai/kling-video/ai-avatar/v2/standard`) | no size setting | 1008x912, 30 fps, 3.20 s | 0.1 s | 128 s | 130 s | $0.056/s | $0.18 |
| OmniHuman v1.5 turbo (`fal-ai/bytedance/omnihuman/v1.5`) | 720p (its smallest), turbo | 960x960, 25 fps, 3.08 s | 0.2 s | 132 s | 134 s | $0.16/s | $0.49 |
| InfiniteTalk, acceleration high (`fal-ai/infinitalk`) | 480p, 73 frames | 704x576, 25 fps, 2.92 s | 0.2 s | 153 s | 156 s | $0.20/s | $0.58 |

About $1.55 in all. InfiniteTalk's first try waited 2.5 min and was refused: 77 frames need 3.08 s of voice. The app
rounded the same way; it now rounds down (`lipsync_body`).

What the frames show (every half second, `compare.mp4`): all four keep the face and move the lips with the voice.
Fabric crops to a square and its eyes look a little wide and fixed; Kling keeps the picture's shape and moves the
head most; OmniHuman blinks and moves naturally; InfiniteTalk blinks and smiles, a little soft at 480p. The owner
judges by watching and listening.

What it says:
- **The 24 minutes was mostly InfiniteTalk at 720p and a cold queue.** Today nothing waited; at 480p with
  acceleration high InfiniteTalk made 2.9 s in 2.5 min, still about 50 times the clip's length.
- **Fabric 1.0 Fast is the one that is fast:** about 5 s of work per second of video, under 20 s for this clip.
- Kling and OmniHuman take about 2 minutes for 3 s; how they grow with longer voices is not measured here.

## Quicker settings each model has (fal.ai schemas, 2026-11-12)

| Model | Quicker setting | What the app sends |
|---|---|---|
| VEED Fabric | a separate Fast model (`veed/fabric-1.0/fast`; the full one is `veed/fabric-1.0`) | Fast, 480p by default |
| Kling AI Avatar v2 | none; Standard and Pro (Pro dearer, not timed) | Standard |
| OmniHuman 1.5 | `turbo_mode` ("a slight quality trade-off"); 720p is quicker than 1080p | turbo, 720p |
| InfiniteTalk | `acceleration`: none, regular (fal.ai's default), high | high, 480p by default |

## In the app

The four are on the Lip sync picker's Cloud tab under "With your fal.ai key". Each row says its price and the time per
video second measured here; the screen says, before Make, the time and cost for the chosen voice and size. A size
not timed says "Its time is not measured". No length is forced: the person decides.

## LongCat Avatar on fal.ai (2026-11-12, owner asked: 480p, 3 s)

Same face and 3.00 s voice, `num_segments: 1`, 480p. fal.ai's log: **9 min 19 s waiting** before it started, 217 s
making, 777 s in all. It returned a 5.82 s video at 16 fps, 704x576, and **every frame but one is black** (average
brightness 16, the black level; one frame at 95). fal.ai's answer had no safety flag, only the video and a seed.
A first segment is always about 5.8 s, so the voice was shorter than the segment; whether that blanks the video is not
known. At $0.15 a second the 5.8 s video is about $0.87. **The owner took LongCat off the cloud list (fal.ai and WaveSpeed) the same day.** A person who
had chosen it gets this computer's lip sync again; their key stays.

## Walked in the window (2026-11-12, the owner's key and app data)

Engine on the app's own data with the keychain (`DESKTOP_SECRET_STORE=keychain`, as the shell sets it), the window on
Vite with the shell stubbed. Lip sync › model button › Cloud lists the four fal.ai models with price and time;
choosing Fabric 1.0 Fast puts "Fabric 1.0 Fast · fal.ai" on the button, 480p, and the line "About 35 seconds on fal.ai
and about $0.72 for 0:07 of video at 480p" (the words' length is guessed before the speech is made).

Made from words: speech here ~11 s, two uploads ~5 s, then fal.ai **started at once and took 138 s** for a 5.56 s
voice, 157 s in all. The video is 640x640 (Fabric makes a square, whatever the shape chosen; the screen had said
528x480), lips with the voice, face kept. It is in the Recent strip and My creations finds it by its words.

Found on the way: the stale LongCat choice showed as "In use" in Settings (fixed: a model off the list is not in use);
"the picture and the voice is sent there" (fixed); the lead still said "It runs on this computer" (fixed).
Then fixed (owner's yes, 2026-11-12): Fabric took about 25 s per video second here against 5 s in the 3 s race, so
the screen now uses 25 s and the picker says "5 to 25 s per second of video at 480p (two runs)". Each cloud model
carries its measured frame (`frame`, `frame_short` in `LIPSYNC_MODELS`): Fabric (640x640 at 480p) and OmniHuman
(960x960 at 720p) make a square whatever they are sent, so the screen hides the shape choice, says so, and sends a
square picture; Kling (912 on the short side) and InfiniteTalk (576 at 480p) keep the picture's shape at a size they
pick, so the screen says "about WxH; the model picks the exact size". A size not measured says only "square" or
"keeping this shape".
