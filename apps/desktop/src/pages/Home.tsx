// SPDX-License-Identifier: AGPL-3.0-only
// The home screen is the assistant (ADR-0057): the shared home (packages/ui) with this window's setup notice.
import { AssistantHome, Button, Notice, useChatNext } from "@wasifyai/ui";
import { assistantApi, client, modelsApi, voiceApi } from "../api";
import { images } from "../images";
import { type Route, openChat, openNotebook } from "../router";
import { getSpeechModel } from "../speech-model";
import { useChatModel } from "../useChatModel";

export function HomePage({
  go,
  conversationId,
  onAdopt,
}: {
  go: (r: Route) => void;
  conversationId: string | null;
  onAdopt: (id: string) => void;
}) {
  const model = useChatModel();
  const [next] = useChatNext(); // Settings, Labs (ADR-0082): the new chat is off until asked for

  const notices =
    model.chosen === false ? (
      <Notice
        tone="info"
        title="Choose a chat model"
        actions={
          <>
            <Button
              type="button"
              onClick={() => {
                window.location.hash = "/models?tab=discover";
              }}
            >
              Get a recommended model
            </Button>
            <Button type="button" variant="outline" onClick={() => go("models")}>
              Use one I have
            </Button>
          </>
        }
      >
        Wasify AI answers with a model that runs on this computer. Pick one you already have, or get
        one in Discover.
      </Notice>
    ) : null;

  return (
    <AssistantHome
      runs={client}
      assistant={assistantApi}
      images={images}
      tracks={(id) => voiceApi.track(id)}
      voice={voiceApi}
      getSpeechModel={(id, onProgress) => getSpeechModel(modelsApi, id, onProgress)}
      conversationId={conversationId}
      screen={next ? "next" : "classic"}
      onAdopt={onAdopt}
      onNewChat={() => openChat(null)}
      notices={notices}
      onNeedModel={() => go("models")}
      onOpenSettings={() => go("settings")}
      onOpenNotebooks={() => go("notebooks")}
      onOpenCreation={(kind, id) => {
        if (kind === "image") go("library");
        else if (kind === "notebook") openNotebook(id);
        else if (kind === "track") go("tracks");
      }}
    />
  );
}
