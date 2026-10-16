// SPDX-License-Identifier: AGPL-3.0-only
// Text to speech: the shared screen with this window's engine, run client and remembered model.
import { SpeakWorkspace } from "@wasifyai/ui";
import { useState } from "react";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";
import { takeVoice } from "./Voices";

const KEY = "wasifyai.voice.model.speak";

export function SpeakPage({ goModels }: { goModels: () => void }) {
  // read once: a render that runs twice must not lose the voice that was sent here
  const [voice] = useState(takeVoice);
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Text to speech</h1>
        <p className="text-muted-foreground">
          Type something and hear it. It is made on this computer; nothing is sent away.
        </p>
      </header>
      <SpeakWorkspace
        api={voiceApi}
        runs={client}
        onGetModel={goModels}
        initialModel={remembered.get(KEY)}
        onModelChosen={(id) => remembered.set(KEY, id)}
        initialSavedVoice={voice}
      />
    </div>
  );
}
