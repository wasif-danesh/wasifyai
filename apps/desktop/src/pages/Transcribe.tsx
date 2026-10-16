// SPDX-License-Identifier: AGPL-3.0-only
// Speech to text: the shared screen with this window's engine and remembered model.
import { TranscribeWorkspace } from "@wasifyai/ui";
import { voiceApi } from "../api";
import { remembered } from "../remember";

const KEY = "wasifyai.voice.model.transcribe";

export function TranscribePage({ goModels }: { goModels: () => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Speech to text</h1>
        <p className="text-muted-foreground">
          Turn a recording into text with times. It is read on this computer; nothing is sent away.
        </p>
      </header>
      <TranscribeWorkspace
        api={voiceApi}
        onGetModel={goModels}
        initialModel={remembered.get(KEY)}
        onModelChosen={(id) => remembered.set(KEY, id)}
      />
    </div>
  );
}
