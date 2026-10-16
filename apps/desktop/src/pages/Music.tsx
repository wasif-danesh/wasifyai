// SPDX-License-Identifier: AGPL-3.0-only
// Music: make a song or a sound effect with the model chosen from the list, change what was made, write
// lyrics, and the music made before.
import { LyricsWriter, MusicWorkspace, TrackList } from "@wasifyai/ui";
import { useState } from "react";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";
import type { Route } from "../router";

const KEY = "wasifyai.music.model";
const LYRICS_KEY = "wasifyai.music.lyrics";
const OPEN_KEY = "wasifyai.music.open";

/** Words the Lyrics screen sent to Create music; used once, then forgotten. */
function takeLyrics(): string | null {
  const words = remembered.get(LYRICS_KEY);
  if (words) remembered.set(LYRICS_KEY, "");
  return words || null;
}

/** What Your music asked Create music to do with a track ("edit:<id>"); used once. */
function takeAction(): { kind: "edit" | "again" | "take"; trackId: string } | null {
  const raw = remembered.get(OPEN_KEY);
  if (raw) remembered.set(OPEN_KEY, "");
  const m = /^(edit|again|take):([A-Za-z0-9]{1,64})$/.exec(raw ?? "");
  return m ? { kind: m[1] as "edit" | "again" | "take", trackId: m[2] as string } : null;
}

export function MusicPage({ goModels }: { goModels: () => void }) {
  // read once: a render that runs twice must not lose what was sent here
  const [lyrics] = useState(takeLyrics);
  const [action] = useState(takeAction);
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
        initialLyrics={lyrics}
        initialAction={action}
      />
    </div>
  );
}

export function TracksPage({ go }: { go: (r: Route) => void }) {
  const open = (kind: "edit" | "again" | "take", id: string) => {
    remembered.set(OPEN_KEY, `${kind}:${id}`);
    go("music");
  };
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
        <TrackList
          api={voiceApi}
          heading="Everything you made"
          searchable
          onAgain={(t) => open("again", t.id)}
          onTake={(t) => open("take", t.id)}
          onEdit={(t) => open("edit", t.id)}
        />
      </div>
    </div>
  );
}

export function LyricsPage({ go }: { go: (r: Route) => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Lyrics</h1>
        <p className="text-muted-foreground">
          The chat model you chose writes the words; you can change them, then take them to Create
          music. Nothing leaves this computer.
        </p>
      </header>
      <div className="mx-auto w-full max-w-3xl">
        <LyricsWriter
          runs={client}
          duration={60}
          useLabel="Use in Create music"
          onUse={(words) => {
            remembered.set(LYRICS_KEY, words);
            go("music");
          }}
        />
      </div>
    </div>
  );
}
