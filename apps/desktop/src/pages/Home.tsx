// SPDX-License-Identifier: AGPL-3.0-only
// The home screen is the assistant (ADR-0057): the shared home (packages/ui) with this window's setup notice.
import {
  AssistantHome,
  Bar,
  type ChoicesApi,
  type CreationEntry,
  ModelSelect,
  type ModelSelectHandle,
  Notice,
  type QuickStartId,
  handDraft,
  useChoicesFor,
  useChoicesVersion,
} from "@wasifyai/ui";
import { useEffect, useRef, useState } from "react";
import { FirstRun, GetStarted, useFirstRun } from "../FirstRun";
import { useGroups, useRun } from "../SetupGate";
import { assistantApi, client, creationsApi, externalApi, modelsApi, voiceApi } from "../api";
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
import { ASSISTANT_TASK } from "../choices/chat-choices";
import { getSpeechModel } from "../speech-model";

/** Whether the main chat answers on the person's own plan now (ADR-0110). */
function useOnPlan(api: ChoicesApi | null): boolean {
  const version = useChoicesVersion();
  const [on, setOn] = useState(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    let gone = false;
    api
      ?.list()
      .then((l) => !gone && setOn(l.choices.some((c) => c.chosen && c.place === "agent")))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [api, version]);
  return on;
}

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
  // the main chat may also answer on the person's own plan (ADR-0110): its button has a Your plan tab
  const choices = useChoicesFor("chat", ASSISTANT_TASK);
  const picker = useRef<ModelSelectHandle>(null);
  const first = useFirstRun();
  const chat = useGroups()?.find((g) => g.id === "chat") ?? null;
  const run = useRun("chat");
  const onPlan = useOnPlan(choices);
  // "I'd rather use my Claude or ChatGPT plan" on the first run: the home's model button opens on Your plan once
  // the home is on the screen
  const [toPlan, setToPlan] = useState(false);
  useEffect(() => {
    if (!toPlan || first.show) return;
    picker.current?.openOn("agent");
    setToPlan(false);
  }, [toPlan, first.show]);

  // the first run, once (ADR-0109): one button that sets up chat, and nothing else
  if (first.show) return <FirstRun onDone={first.done} onPlan={() => setToPlan(true)} />;

  // after it, while chat is not set up, the same button on the home
  const notice =
    // a chat on the person's plan needs no model here (ADR-0110)
    chat && chat.state !== "ready" && !onPlan ? (
      <Notice tone="info" title="Get a chat model">
        {run.state === "running" ? (
          <span className="grid gap-1" aria-live="polite">
            <Bar value={run.fraction} />
            <span className="text-sm">{run.label}</span>
          </span>
        ) : (
          <GetStarted
            group={chat}
            onKey={() => picker.current?.openOn("cloud")}
            onPlan={() => picker.current?.openOn("agent")}
          />
        )}
      </Notice>
    ) : null;

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
      notices={notice}
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
