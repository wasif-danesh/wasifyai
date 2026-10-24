// SPDX-License-Identifier: AGPL-3.0-only
// Create, Animate and Extend (ADR-0037): a clip from words, from a picture and what should move, or one of
// your videos carried on. The shared workspace with this window's model button (in the top bar) and setup notices.
import type { VideoMode } from "@wasifyai/client";
import {
  ModelSelect,
  type ModelSelectHandle,
  Notice,
  PageHeader,
  VideoWorkspace,
  useChoicesFor,
} from "@wasifyai/ui";
import { useRef } from "react";
import { client } from "../api";
import { useGroupReady } from "../choices/use-ready";
import { useImageEngine, useModelOf } from "../engine-hooks";
import type { Route } from "../router";
import { videos } from "../videos";

type PageMode = Exclude<VideoMode, "import">;

const TITLES: Record<PageMode, [string, string]> = {
  text: ["Make a video", "Describe a scene and get a short clip. It is made on this computer."],
  image: [
    "Animate a picture",
    "Choose a picture and say what should move. It is made on this computer.",
  ],
  extend: [
    "Extend a video",
    "Choose one of your videos, or add one from this computer, and carry it on for five or eight more seconds. It is made on this computer.",
  ],
};

export function VideoPage({ mode, go }: { mode: PageMode; go: (r: Route) => void }) {
  const model = useModelOf("wasifyai-video");
  const engine = useImageEngine();
  // "Select video model": the model in use, or the way to get one (ADR-0086)
  const choices = useChoicesFor("video");
  const picker = useRef<ModelSelectHandle>(null);
  const { ensure } = useGroupReady(choices, picker);

  // only a real model can be too big: the placeholder engine runs anywhere
  const real = engine?.state === "installed";
  const tooBig = real && model?.fit?.verdict === "too_big";
  const tight = real && model?.fit?.verdict === "tight";

  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto grid w-full max-w-3xl gap-2">
        <div>
          <h1 className="font-semibold text-2xl">{TITLES[mode][0]}</h1>
          <p className="text-muted-foreground">{TITLES[mode][1]}</p>
        </div>
      </header>
      <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
        <ModelSelect group="video" api={choices} handleRef={picker} />
      </PageHeader>
      <VideoWorkspace
        mode={mode}
        runs={client}
        videos={videos}
        canSave
        onOpenLibrary={() => go("videos")}
        blockedReason={
          tooBig && model?.fit ? `${model.title} will not fit. ${model.fit.reason}` : null
        }
        beforeMake={ensure}
        notices={
          tight && model?.fit ? (
            <Notice tone="warn" title="This computer is tight on memory">
              {model.fit.reason}
            </Notice>
          ) : null
        }
      />
    </div>
  );
}
