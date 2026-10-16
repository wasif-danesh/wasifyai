// SPDX-License-Identifier: AGPL-3.0-only
// Your voices: described in words or cloned from a recording, then used in Text to speech.
import { VoicesWorkspace } from "@wasifyai/ui";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";
import type { Route } from "../router";

const USE_KEY = "wasifyai.voice.use";

/** The saved voice the Voices screen sent to Text to speech; used once, then forgotten. */
export function takeVoice(): string | null {
  const id = remembered.get(USE_KEY);
  if (id) remembered.set(USE_KEY, "");
  return id || null;
}

export function VoicesPage({ go }: { go: (r: Route) => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Voices</h1>
        <p className="text-muted-foreground">
          Describe a voice or copy one from a short recording, then use it in Text to speech. Voices
          stay on this computer.
        </p>
      </header>
      <VoicesWorkspace
        api={voiceApi}
        runs={client}
        onUseVoice={(id) => {
          remembered.set(USE_KEY, id);
          go("speak");
        }}
      />
    </div>
  );
}
