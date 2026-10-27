// SPDX-License-Identifier: AGPL-3.0-only
// The home screen is the assistant (ADR-0057): the shared home (packages/ui) with this window's setup notice.
import { AssistantHome, ModelSelect, type ModelSelectHandle, useChoicesFor } from "@wasifyai/ui";
import { useRef } from "react";
import { assistantApi, client, modelsApi, voiceApi } from "../api";
import { ChatStart } from "../choices/ChatStart";
import { images } from "../images";
import { ROUTES } from "../menu";
import { type Route, openChat, openNotebook } from "../router";
import { getSpeechModel } from "../speech-model";

export function HomePage({
  go,
  conversationId,
  onAdopt,
}: {
  go: (r: Route) => void;
  conversationId: string | null;
  onAdopt: (id: string) => void;
}) {
  const choices = useChoicesFor("chat");
  const picker = useRef<ModelSelectHandle>(null);

  return (
    <AssistantHome
      runs={client}
      assistant={assistantApi}
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
      onOpenCreation={(kind, id) => {
        if (kind === "image") go("library");
        else if (kind === "notebook") openNotebook(id);
        else if (kind === "track") go("tracks");
      }}
    />
  );
}
