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
} from "../../ToolCard";
import type { ToolArtifact, ToolResult } from "../convert";
import { useThreadEnv } from "../env";
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
  };
}

function adapt(Card: ComponentType<ToolCardProps>) {
  function ToolUI(p: ToolCallMessagePartProps) {
    const { images, tracks, onOpenCreation } = useThreadEnv();
    return (
      <Card tool={toolOf(p)} images={images} tracks={tracks} onOpenCreation={onOpenCreation} />
    );
  }
  return ToolUI;
}

export const toolUIs = {
  generate_image: adapt(ImageToolCard),
  make_music: adapt(MusicToolCard),
  search_creations: adapt(LibrarySearchCard),
  search_notebooks: adapt(NotebookSearchCard),
  confirm_action: ConfirmActionCard,
} as const;

/** A tool nobody registered a card for. */
export function UnknownTool() {
  return null;
}
