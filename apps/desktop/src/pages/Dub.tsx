// SPDX-License-Identifier: AGPL-3.0-only
// Dubbing (ADR-0066, stage V6): a recording said again in another language, with the translation read and
// changed by the person before anything is spoken.
import { DubbingWorkspace } from "@wasifyai/ui";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";
import type { Route } from "../router";

const KEY = "wasifyai.dub.model";

export function DubPage({ go, goModels }: { go: (r: Route) => void; goModels: () => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Dub a recording</h1>
        <p className="text-muted-foreground">
          Hear a recording in another language, in the speaker's voice or one you choose. The result
          is kept in Your music.
        </p>
      </header>
      <DubbingWorkspace
        api={voiceApi}
        runs={client}
        onGetModel={goModels}
        initialModel={remembered.get(KEY)}
        onModelChosen={(id) => remembered.set(KEY, id)}
        onOpenLibrary={() => go("tracks")}
      />
    </div>
  );
}
