// SPDX-License-Identifier: AGPL-3.0-only
// Lip sync (ADR-0066, stage V5): a picture and a voice make a talking video, with the model chosen from a
// list. The person says what the picture is and whose voice it is first, and every video is marked.
import { LipSyncWorkspace } from "@wasifyai/ui";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";

const KEY = "wasifyai.lipsync.model";

export function LipSyncPage({ goModels }: { goModels: () => void }) {
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">Lip sync</h1>
        <p className="text-muted-foreground">
          Make the face in a picture say your words or a recording. It runs on this computer, and
          every video is marked as AI-generated.
        </p>
      </header>
      <LipSyncWorkspace
        api={voiceApi}
        runs={client}
        onGetModel={goModels}
        initialModel={remembered.get(KEY)}
        onModelChosen={(id) => remembered.set(KEY, id)}
      />
    </div>
  );
}
