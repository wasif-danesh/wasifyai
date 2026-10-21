// SPDX-License-Identifier: AGPL-3.0-only
// Create, Animate and Extend (ADR-0037): a clip from words, from a picture and what should move, or one of
// your videos carried on. The shared workspace with this window's model chip and setup notices.
import type { VideoMode } from "@wasifyai/client";
import { Notice, VideoWorkspace, cn } from "@wasifyai/ui";
import { FitBadge } from "../FitBadge";
import { client } from "../api";
import { useImageEngine, useModelOf } from "../engine-hooks";
import type { Route } from "../router";
import { videos } from "../videos";

const LINK = "underline underline-offset-4";

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
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">{model?.title ?? "Video model"}</span>
          {model ? (
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-xs",
                model.status === "ready" ? "text-ok" : "text-muted-foreground",
              )}
            >
              {model.status === "ready" ? "ready" : "not downloaded"}
            </span>
          ) : null}
          {model?.fit ? <FitBadge fit={model.fit} /> : null}
        </div>
      </header>
      <VideoWorkspace
        mode={mode}
        runs={client}
        videos={videos}
        canSave
        onOpenLibrary={() => go("videos")}
        blockedReason={
          tooBig && model?.fit ? `${model.title} will not fit. ${model.fit.reason}` : null
        }
        notices={
          <>
            {tight && model?.fit ? (
              <Notice tone="warn" title="This computer is tight on memory">
                {model.fit.reason}
              </Notice>
            ) : null}
            {engine?.state === "not_installed" ? (
              <Notice tone="info" title="Placeholder clips">
                Real videos need the image engine set up once.{" "}
                <button type="button" className={LINK} onClick={() => go("settings")}>
                  Open Settings
                </button>
                .
              </Notice>
            ) : null}
            {model && model.status !== "ready" && engine?.state === "installed" ? (
              <Notice tone="warn" title="The model is not on this computer yet">
                Get it in{" "}
                <button type="button" className={LINK} onClick={() => go("models")}>
                  Models
                </button>{" "}
                before making real videos ({Math.round(model.bytes_missing / 1e9)} GB to get).
              </Notice>
            ) : null}
          </>
        }
      />
    </div>
  );
}
