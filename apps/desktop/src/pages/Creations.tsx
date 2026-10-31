// SPDX-License-Identifier: AGPL-3.0-only
import type { CreationEntry, CreationFilter, CreationUse, CreationsNav } from "@wasifyai/ui";
import { MyCreations } from "@wasifyai/ui";
import { creationsApi } from "../api";
import { type Route, openNotebook } from "../router";

/** What the window does to hand an entry to a tool ("Edit this", "Extend this"…): the shell owns those hand-offs. */
export type HandOff = (entry: CreationEntry, action: CreationUse) => void;

/** The tool an entry can be handed to for an action, as this window's screen. */
export function toolFor(entry: CreationEntry, action: CreationUse): Route | null {
  switch (action) {
    case "edit":
      return entry.kind === "image" ? "edit" : null;
    case "animate":
      return entry.kind === "image" ? "animate" : null;
    case "extend":
      return entry.kind === "video" ? "extend" : null;
    case "again":
      return entry.kind === "image" ? "create" : entry.kind === "song" ? "music" : null;
    case "split":
      return entry.kind === "song" ? "separate" : null;
    case "convert":
      return entry.kind === "song" || entry.kind === "speech" ? "convert" : null;
    case "speechedit":
      return entry.kind === "song" || entry.kind === "speech" ? "speechedit" : null;
  }
}

/** Where an entry of the Library opens "in its tool" in this window, and the screens that make something new. */
export function navFor(go: (r: Route) => void, handOff?: HandOff): CreationsNav {
  const screen = {
    image: "create",
    video: "video",
    song: "music",
    speech: "speak",
    transcript: "transcribe",
    lipsync: "lipsync",
    model3d: "model3d",
    composition: "videobuilder",
    creative_project: "creative",
    taught: "train",
  } as const satisfies Record<string, Route>;
  const make = {
    music: "music",
    image: "create",
    video: "video",
    speech: "speak",
    transcribe: "transcribe",
    lipsync: "lipsync",
  } as const satisfies Record<string, Route>;
  return {
    open: (entry) => {
      if (entry.kind === "notebook") {
        openNotebook(entry.id);
        go("notebook");
      } else go(screen[entry.kind]);
    },
    make: (to) => go(make[to]),
    ...(handOff
      ? {
          canUse: (entry, action) => toolFor(entry, action) !== null,
          use: (entry, action) => handOff(entry, action),
        }
      : {}),
  };
}

/** The Library: everything made on this computer, with search by meaning (the web's Library, the same screen). The
 * routes that were "Your images", "Your videos" and "Your music" open it with their filter (ADR-0093, U8). */
export function CreationsPage({
  go,
  handOff,
  filter = "all",
  open = null,
}: {
  go: (r: Route) => void;
  handOff?: HandOff;
  filter?: CreationFilter;
  /** an entry to open as the Library opens (the home's Recent) */
  open?: { kind: string; id: string } | null;
}) {
  return (
    <MyCreations
      key={`${filter}:${open?.id ?? ""}`}
      api={creationsApi}
      nav={navFor(go, handOff)}
      initialFilter={filter}
      initialOpen={open}
    />
  );
}
