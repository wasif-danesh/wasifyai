// SPDX-License-Identifier: AGPL-3.0-only
// The home screen is the assistant (ADR-0057): the shared home (packages/ui) with this window's setup notice.
import {
  AssistantHome,
  type CreationEntry,
  ModelSelect,
  type ModelSelectHandle,
  type QuickStartId,
  handDraft,
  useChoicesFor,
} from "@wasifyai/ui";
import { useRef } from "react";
import { assistantApi, client, creationsApi, externalApi, modelsApi, voiceApi } from "../api";
import { ChatStart } from "../choices/ChatStart";
import { images } from "../images";
import { runningJobs } from "../jobs";
import { ROUTES } from "../menu";
import { type Route, newNotebook, openChat, openNotebook } from "../router";

/** Where each quick start goes in this window. */
const START: Record<Exclude<QuickStartId, "notebook">, Route> = {
  picture: "create",
  video: "video",
  speech: "speak",
  song: "music",
  model3d: "model3d",
  motion: "videobuilder",
  train: "train",
};
import { getSpeechModel } from "../speech-model";

export function HomePage({
  go,
  conversationId,
  onAdopt,
  onOpenEntry,
}: {
  go: (r: Route) => void;
  conversationId: string | null;
  onAdopt: (id: string) => void;
  /** open a recent creation in the Library */
  onOpenEntry?: (entry: CreationEntry) => void;
}) {
  const choices = useChoicesFor("chat");
  const picker = useRef<ModelSelectHandle>(null);

  return (
    <AssistantHome
      runs={client}
      assistant={assistantApi}
      external={externalApi}
      images={images}
      tracks={(id) => voiceApi.track(id)}
      voice={voiceApi}
      getSpeechModel={(id, onProgress) => getSpeechModel(modelsApi, id, onProgress)}
      conversationId={conversationId}
      onAdopt={onAdopt}
      onNewChat={() => openChat(null)}
      notices={<ChatStart picker={picker} />}
      modelPicker={<ModelSelect group="chat" api={choices} handleRef={picker} />}
      onNeedModel={() => picker.current?.open()}
      onOpenSettings={() => go("settings")}
      onOpenScreen={(id) => {
        const route = ROUTES[id];
        if (route) go(route);
      }}
      onOpenNotebooks={() => go("notebooks")}
      onQuickStart={(id, text) => {
        handDraft(text); // the make screen starts with what was typed
        if (id === "notebook") newNotebook();
        else go(START[id]);
      }}
      running={runningJobs}
      creations={creationsApi}
      onOpenEntry={onOpenEntry}
      onOpenLibrary={() => go("creations")}
      onOpenCreation={(kind, id) => {
        if (kind === "image") go("library");
        else if (kind === "notebook") openNotebook(id);
        else if (kind === "track") go("tracks");
      }}
    />
  );
}
