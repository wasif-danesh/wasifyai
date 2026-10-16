// SPDX-License-Identifier: AGPL-3.0-only
// Music: make a song or a sound effect with the model chosen from the list, and the music made before.
import { MusicWorkspace, TrackList } from "@wasifyai/ui";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";
import type { Route } from "../router";

const KEY = "wasifyai.music.model";

export function MusicPage({ goModels }: { goModels: () => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Create music</h1>
        <p className="text-muted-foreground">
          Songs, instrumentals and sound effects, made on this computer. Pick the model; what the
          form asks for follows from it.
        </p>
      </header>
      <MusicWorkspace
        api={voiceApi}
        runs={client}
        onGetModel={goModels}
        initialModel={remembered.get(KEY)}
        onModelChosen={(id) => remembered.set(KEY, id)}
      />
    </div>
  );
}

export function TracksPage({ go }: { go: (r: Route) => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto flex w-full max-w-3xl flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-semibold text-2xl">Your music</h1>
        <button
          type="button"
          className="text-sm underline underline-offset-4"
          onClick={() => go("music")}
        >
          Make something new
        </button>
      </header>
      <div className="mx-auto w-full max-w-3xl">
        <TrackList api={voiceApi} heading="Everything you made" />
      </div>
    </div>
  );
}
