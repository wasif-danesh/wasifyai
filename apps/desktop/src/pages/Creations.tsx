// SPDX-License-Identifier: AGPL-3.0-only
import { MyCreations } from "@wasifyai/ui";
import type { CreationsNav } from "@wasifyai/ui";
import { creationsApi } from "../api";
import type { Route } from "../router";

/** Where an entry of My creations opens in this window, and the screens that make something new. */
export function navFor(go: (r: Route) => void): CreationsNav {
  const screen = {
    image: "library",
    video: "videos",
    song: "tracks",
    speech: "speak",
    transcript: "transcribe",
    lipsync: "lipsync",
  } as const satisfies Record<string, Route>;
  const make = {
    music: "music",
    image: "create",
    video: "video",
    speech: "speak",
    transcribe: "transcribe",
    lipsync: "lipsync",
  } as const satisfies Record<string, Route>;
  return { open: (entry) => go(screen[entry.kind]), make: (to) => go(make[to]) };
}

/** My creations: everything made on this computer, with search by meaning (the web's Library, the same screen). */
export function CreationsPage({ go }: { go: (r: Route) => void }) {
  return <MyCreations api={creationsApi} nav={navFor(go)} />;
}
