// Our messages (`ChatMessage`, folded from the engine's events) into the shape assistant-ui reads. Pure, and free of the
// library's runtime: `use-chat-runtime.ts` is the only file that hands the result to it.
import type { ChatMessage, ChatPart } from "@wasifyai/client";

type Tool = Extract<ChatPart, { type: "tool" }>;

/** What a finished tool call carries to its tool UI: our status and the engine's output, kept apart. */
export type ToolResult = { status: Tool["status"]; output: Record<string, unknown> };

/** A running job's progress, handed to the tool UI beside the call (UI only, not part of the result). */
export type ToolArtifact = { progress?: number; jobStatus?: string; queuePosition?: number };

export type LikePart =
  | { type: "text"; text: string }
  | { type: "reasoning"; text: string }
  | {
      type: "tool-call";
      toolCallId: string;
      toolName: string;
      args: Record<string, unknown>;
      result?: ToolResult;
      isError: boolean;
      artifact?: ToolArtifact;
      approval?: { id: string; prompt: string; approved?: boolean };
    };

export type LikeMessage = {
  id: string;
  role: "user" | "assistant";
  content: LikePart[];
  status?:
    | { type: "running" }
    | { type: "requires-action"; reason: "interrupt" }
    | { type: "complete"; reason: "stop" };
};

function toolPart(p: Tool): LikePart {
  const done = p.status !== "running";
  const progress =
    p.status === "running" &&
    (p.progress !== undefined || p.jobStatus || p.queuePosition !== undefined)
      ? { progress: p.progress, jobStatus: p.jobStatus, queuePosition: p.queuePosition }
      : undefined;
  const a = p.approval;
  return {
    type: "tool-call",
    toolCallId: p.id,
    toolName: p.name,
    args: p.arguments,
    ...(done
      ? { result: { status: p.status as ToolResult["status"], output: p.output ?? {} } }
      : {}),
    isError: p.status === "error",
    ...(progress ? { artifact: progress } : {}),
    ...(a
      ? {
          approval: {
            id: a.id,
            prompt: String((p.arguments as { title?: unknown }).title ?? "Confirm"),
            ...(a.state === "pending" ? {} : { approved: a.state === "approved" }),
          },
        }
      : {}),
  };
}

export function toLikeMessage(m: ChatMessage): LikeMessage {
  if (m.role === "user") {
    return {
      id: m.id,
      role: "user",
      content: m.parts.map((p) => ({ type: "text", text: p.type === "text" ? p.text : "" })),
    };
  }
  const waiting = m.parts.some((p) => p.type === "tool" && p.approval?.state === "pending");
  return {
    id: m.id,
    role: "assistant",
    content: m.parts.map((p) =>
      p.type === "text" || p.type === "reasoning" ? { type: p.type, text: p.text } : toolPart(p),
    ),
    status: m.streaming
      ? { type: "running" }
      : waiting
        ? { type: "requires-action", reason: "interrupt" }
        : { type: "complete", reason: "stop" },
  };
}

/** The plain text of a message: what Copy puts on the clipboard. */
export function textOf(m: ChatMessage): string {
  return m.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
}
