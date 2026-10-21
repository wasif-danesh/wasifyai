// What the web app does for every item of the desktop's side menu (docs/web-parity-ledger.md). One row per item, so a
// new desktop feature cannot be added without a decision for the web: `parity.test.ts` fails when an item is missing here,
// or when the menu does something other than what the row says.
//   live         the menu opens a page on the web
//   soon         not built for the web yet: the menu shows "Soon" (the plan says what it needs)
//   desktop-only hidden on purpose, with the reason
export type Parity = { status: "live" | "soon" | "desktop-only"; note: string };

export const PARITY: Record<string, Parity> = {
  chat: { status: "live", note: "the shared chat" },
  library: { status: "live", note: "My creations" },
  models: {
    status: "desktop-only",
    note: "an admin chooses the models of a deployment (Models in the admin area); the person's own model picker is for local models",
  },
  train: { status: "soon", note: "not built on either app" },

  "notebook.create": { status: "live", note: "the shared notebooks, with the notebooks worker" },
  "notebook.list": { status: "live", note: "the shared notebooks" },

  "images.create": { status: "live", note: "shared ImageWorkspace" },
  "images.edit": { status: "live", note: "shared ImageWorkspace" },
  "images.inpaint": { status: "live", note: "shared ImageWorkspace, mode inpaint" },
  "images.reference": { status: "live", note: "shared ImageWorkspace, mode reference" },
  "images.model3d": {
    status: "soon",
    note: "needs the 3D engine (Pixal3D) as a job on a GPU host (ADR-0080); on the desktop it is a local component",
  },
  "images.library": { status: "live", note: "shared ImageLibrary" },

  "video.create": { status: "live", note: "shared VideoWorkspace" },
  "video.animate": { status: "live", note: "shared VideoWorkspace" },
  "video.extend": {
    status: "live",
    note: "shared VideoWorkspace, mode extend; needs ffmpeg in the API image",
  },
  "video.builder": {
    status: "soon",
    note: "needs the sandboxed browser render as a job on a worker (ADR-0077); on the desktop it is a local component",
  },
  "video.library": { status: "live", note: "shared VideoLibrary" },

  "voice.speak": { status: "live", note: "shared voice page, hosted models" },
  "voice.transcribe": { status: "live", note: "shared voice page, hosted models" },
  "voice.lipsync": { status: "live", note: "shown when a ready model can do it (a GPU host)" },
  "voice.voices": { status: "live", note: "shown when a ready model can do it" },
  "voice.convert": { status: "live", note: "shown when a ready model can do it" },
  "voice.edit": { status: "live", note: "shown when a ready model can do it" },
  "voice.dub": { status: "live", note: "shown when a ready model can do it" },
  "voice.audiobook": { status: "live", note: "shown when a ready model can do it" },

  "music.create": { status: "live", note: "shown when a ready model can do it" },
  "music.library": { status: "live", note: "shown when a ready model can do it" },
  "music.lyrics": { status: "live", note: "shown when a ready model can do it" },
  "music.separate": { status: "live", note: "shown when a ready model can do it" },
};
