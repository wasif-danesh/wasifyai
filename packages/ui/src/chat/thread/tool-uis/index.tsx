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
  WebReadCard,
  WebSearchCard,
} from "../../ToolCard";
import type { ToolArtifact, ToolResult } from "../convert";
import { useThreadEnv } from "../env";
import { ActionResultCard, GuideCard, OpenScreenCard } from "./ActionCards";
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
    const { images, tracks, onOpenCreation, onOpenSettings, onDecide } = useThreadEnv();
    const tool = toolOf(p);
    // a call that waits for the person (or was just answered and is still running) shows its card, not its result
    if (tool.approval && tool.status === "running")
      return <ConfirmActionCard tool={tool} onDecide={onDecide} />;
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
  const { onDecide } = useThreadEnv();
  const tool = toolOf(p);
  if (!tool.approval) return null;
  return <ConfirmActionCard tool={tool} onDecide={onDecide} />;
}

/** `propose_action` (ADR-0071): the card while the person decides, then the result drawn for the action it ran: a
 * picture or a player for the actions that have one, a plain result card for the rest. */
function Propose(p: ToolCallMessagePartProps) {
  const { images, tracks, onOpenCreation, onOpenSettings, onDecide, onOpenScreen } = useThreadEnv();
  const tool = toolOf(p);
  if (tool.approval && tool.status === "running")
    return <ConfirmActionCard tool={tool} onDecide={onDecide} />;
  const actionId = String(tool.arguments.action_id ?? tool.output?.action_id ?? "");
  const shared = { tool, images, tracks, onOpenCreation, onOpenSettings };
  if (actionId === "image.generate") return <ImageToolCard {...shared} />;
  if (actionId === "music.generate") return <MusicToolCard {...shared} />;
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
