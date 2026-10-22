// What the web app does for every item of the desktop's side menu (docs/web-parity-ledger.md). One row per item, so a
// new desktop feature cannot be added without a decision for the web: `parity.test.ts` fails when an item is missing here,
// or when the menu does something other than what the row says.
//   live         the menu opens a page on the web
//   soon         not built for the web yet: the menu shows "Soon" (the plan says what it needs)
//   desktop-only hidden on purpose, with the reason
//
// A row that is not `live` must say who accepted that and when (`accepted`): the release gate (`parity.test.ts`, the
// `parity` job of .github/workflows/desktop.yml) fails on a gap nobody has accepted, and the desktop's actions are held to
// the same rows (`docs/contracts/actions.json`: an action's `ui` is a menu item that needs a row here).
export type Parity = {
  status: "live" | "soon" | "desktop-only";
  note: string;
  /** who accepted that this is not live on the web, and when; required unless `live` */
  accepted?: string;
};

export const PARITY: Record<string, Parity> = {
  chat: { status: "live", note: "the shared chat" },
  library: { status: "live", note: "My creations" },
  models: {
    status: "desktop-only",
    note: "the picker is on the voice, music and lip sync screens and an admin gets models onto a worker in Admin > Workers (P5); chat models are the admin's Models page; the nine-card Models page is the desktop's",
    accepted:
      "owner, 2026-10-21: an admin chooses a deployment's models; the person's own disk is the desktop's. The models.* actions need the desktop's model service, so the web assistant does not offer them",
  },
  train: {
    status: "soon",
    note: "not built on either app",
    accepted: "owner, 2026-10-21: training is not built on the desktop either (ADR-0073 onwards)",
  },

  "notebook.create": { status: "live", note: "the shared notebooks, with the notebooks worker" },
  "notebook.list": { status: "live", note: "the shared notebooks" },

  "images.create": { status: "live", note: "shared ImageWorkspace" },
  "images.edit": { status: "live", note: "shared ImageWorkspace" },
  "images.inpaint": { status: "live", note: "shared ImageWorkspace, mode inpaint" },
  "images.reference": { status: "live", note: "shared ImageWorkspace, mode reference" },
  "images.model3d": {
    status: "live",
    note: "shared Model3d screen; Pixal3D runs as a job on an engine worker (ADR-0087, P3), rows in Postgres, files in storage",
  },
  "images.library": { status: "live", note: "shared ImageLibrary" },

  "video.create": { status: "live", note: "shared VideoWorkspace" },
  "video.animate": { status: "live", note: "shared VideoWorkspace" },
  "video.extend": {
    status: "live",
    note: "shared VideoWorkspace, mode extend; needs ffmpeg in the API image",
  },
  "video.builder": {
    status: "live",
    note: "shared VideoBuilder screen; the sandboxed render runs as a job on an engine worker (ADR-0087, P4), rows in Postgres, videos are library clips",
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
