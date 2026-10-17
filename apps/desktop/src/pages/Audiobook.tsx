// SPDX-License-Identifier: AGPL-3.0-only
// Audiobook (ADR-0066, stage V7): a long text read aloud, chapter by chapter, in a voice the person
// chooses. Every chapter is kept in Your music as soon as it is done.
import { AudiobookWorkspace } from "@wasifyai/ui";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";
import type { Route } from "../router";

const KEY = "wasifyai.audiobook.model";

export function AudiobookPage({ go, goModels }: { go: (r: Route) => void; goModels: () => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Audiobook</h1>
        <p className="text-muted-foreground">
          Read a long text aloud, chapter by chapter, in a voice you choose. It runs on this
          computer.
        </p>
      </header>
      <AudiobookWorkspace
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
