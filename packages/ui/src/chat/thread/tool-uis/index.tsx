"use client";
// Tool UIs, registered by the tool's name (ADR-0082 decision 5). Each is a thin adapter: assistant-ui hands it the call and
// its result, and it renders the card the old screen already had. A tool that is not registered shows nothing, as before.
import type { ToolCallMessagePartProps } from "@assistant-ui/react";
import type { ChatPart } from "@wasifyai/client";
import type { ComponentType } from "react";
import {
  ImageToolCard,
  LibrarySearchCard,
  MusicToolCard,
  NotebookSearchCard,
  type ToolCardProps,
  VideoPlayer,
  WebReadCard,
  WebSearchCard,
} from "../../ToolCard";
import type { ToolArtifact, ToolResult } from "../convert";
import { useThreadEnv } from "../env";
import { ActionResultCard, FollowUps, GuideCard, OpenScreenCard, creationOf } from "./ActionCards";
import { ConfirmActionCard } from "./ConfirmActionCard";

type Tool = Extract<ChatPart, { type: "tool" }>;

/** The call as the old cards read it: one `tool` part with its status, output and progress. */
export function toolOf(p: ToolCallMessagePartProps): Tool {
  const result = p.result as ToolResult | undefined;
  const art = p.artifact as ToolArtifact | undefined;
  return {
    type: "tool",
    id: p.toolCallId,
    name: p.toolName,
    arguments: (p.args ?? {}) as Record<string, unknown>,
    status: result ? result.status : "running",
    output: result?.output,
    progress: art?.progress,
    jobStatus: art?.jobStatus,
    queuePosition: art?.queuePosition,
    approval: art?.card,
  };
}

function adapt(Card: ComponentType<ToolCardProps>) {
  function ToolUI(p: ToolCallMessagePartProps) {
    const { images, tracks, onOpenCreation, onOpenSettings, onDecide, onAutoRun } = useThreadEnv();
    const tool = toolOf(p);
    // a call that waits for the person (or was just answered and is still running) shows its card, not its result
    if (tool.approval && tool.status === "running")
      return <ConfirmActionCard tool={tool} onDecide={onDecide} onAutoRun={onAutoRun} />;
    return (
      <Card
        tool={tool}
        images={images}
        tracks={tracks}
        onOpenCreation={onOpenCreation}
        onOpenSettings={onOpenSettings}
      />
    );
  }
  return ToolUI;
}

/** A tool call named `confirm_action` (the card of a model that proposes an action): the same card. */
function Confirm(p: ToolCallMessagePartProps) {
  const { onDecide, onAutoRun } = useThreadEnv();
  const tool = toolOf(p);
  if (!tool.approval) return null;
  return <ConfirmActionCard tool={tool} onDecide={onDecide} onAutoRun={onAutoRun} />;
}

/** `propose_action` (ADR-0071): the card while the person decides, then the result drawn for the action it ran: a
 * picture or a player for the actions that have one, a plain result card for the rest. */
function Propose(p: ToolCallMessagePartProps) {
  const {
    images,
    tracks,
    videos,
    onOpenCreation,
    onOpenSettings,
    onDecide,
    onOpenScreen,
    onAutoRun,
  } = useThreadEnv();
  const tool = toolOf(p);
  if (tool.approval && tool.status === "running")
    return <ConfirmActionCard tool={tool} onDecide={onDecide} onAutoRun={onAutoRun} />;
  const actionId = String(tool.arguments.action_id ?? tool.output?.action_id ?? "");
  // every action that makes a picture or a song draws it, not only image.generate and music.generate (CE3)
  const made = tool.status === "ok" ? creationOf(tool.output) : null;
  const drawn =
    made && tool.output
      ? { ...tool, output: { ...tool.output, [`${made[0]}_id`]: made[1] } }
      : tool;
  const shared = { tool: drawn, images, tracks, onOpenCreation, onOpenSettings };
  if (actionId === "image.generate" || made?.[0] === "image")
    return (
      <div className="grid gap-2">
        <ImageToolCard {...shared} />
        {made ? <FollowUps kind="image" /> : null}
      </div>
    );
  if (actionId === "music.generate" || made?.[0] === "track")
    return (
      <div className="grid gap-2">
        <MusicToolCard {...shared} />
        {made ? <FollowUps kind="track" /> : null}
      </div>
    );
  if (made?.[0] === "video" && videos) {
    const id = made[1];
    return (
      <div className="grid gap-2">
        <VideoPlayer
          videoId={id}
          videos={videos}
          onOpen={onOpenCreation ? () => onOpenCreation("video", id) : undefined}
        />
        <FollowUps kind="video" />
      </div>
    );
  }
  return (
    <ActionResultCard tool={tool} onOpenCreation={onOpenCreation} onOpenScreen={onOpenScreen} />
  );
}

function HowTo(p: ToolCallMessagePartProps) {
  const { onOpenScreen } = useThreadEnv();
  return <GuideCard tool={toolOf(p)} onOpenScreen={onOpenScreen} />;
}

function OpenScreen(p: ToolCallMessagePartProps) {
  const { onOpenScreen } = useThreadEnv();
  return <OpenScreenCard tool={toolOf(p)} onOpenScreen={onOpenScreen} />;
}

export const toolUIs = {
  propose_action: Propose,
  how_to: HowTo,
  open_screen: OpenScreen,
  search_creations: adapt(LibrarySearchCard),
  search_notebooks: adapt(NotebookSearchCard),
  web_search: adapt(WebSearchCard),
  web_read: adapt(WebReadCard),
  confirm_action: Confirm,
} as const;

/** A tool nobody registered a card for. */
export function UnknownTool() {
  return null;
}
