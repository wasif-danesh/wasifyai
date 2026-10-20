"use client";

import {
  ActionBarPrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  type ReasoningMessagePartProps,
  type TextMessagePartProps,
  useAuiState,
} from "@assistant-ui/react";
import type { AttachmentInfo } from "@wasifyai/client";
import { Check, ChevronLeft, ChevronRight, Copy, Pencil, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { Reasoning } from "../Reasoning";
import { MessageAttachments } from "../attachments/AttachmentChip";
import { ReadAloudButton, ReadAloudNotice } from "../read-aloud/use-read-aloud";
import { useThreadEnv } from "./env";
import { Markdown } from "./markdown/Markdown";
import { LabelContext } from "./markdown/labels";
import { UnknownTool, toolUIs } from "./tool-uis";

function UserText({ text }: TextMessagePartProps) {
  return (
    <p
      dir="auto"
      className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-accent px-4 py-2.5"
    >
      {text}
    </p>
  );
}

// these are defined once, outside any render: a component made inside a render is a new component each time and every message
// would start over on every token
function AssistantText({ text }: TextMessagePartProps) {
  const animating = useAuiState((s) => s.message.status?.type === "running");
  const { imageOrigins, renderLabel } = useThreadEnv();
  const id = useAuiState((s) => s.message.id);
  const draw = useMemo(
    () => (renderLabel ? (n: number) => renderLabel(id, n) : null),
    [renderLabel, id],
  );
  const body = (
    <Markdown
      text={text}
      animating={animating}
      imageOrigins={imageOrigins}
      labels={Boolean(renderLabel)}
    />
  );
  return draw ? <LabelContext.Provider value={draw}>{body}</LabelContext.Provider> : body;
}

function AssistantReasoning({ text, status }: ReasoningMessagePartProps) {
  return <Reasoning text={text} running={status.type === "running"} />;
}

const NOTHING = () => null;

const ASSISTANT_PARTS = {
  Text: AssistantText,
  Reasoning: AssistantReasoning,
  Empty: NOTHING,
  tools: { by_name: toolUIs as never, Fallback: UnknownTool },
};

const USER_PARTS = { Text: UserText, Empty: NOTHING };

const ACTION = "rounded-md p-2 text-muted-foreground hover:bg-accent";

/** "2 / 3" with arrows, only when a message has more than one version (an edit, or an answer made again). */
function Versions() {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      // biome-ignore lint/a11y/useSemanticElements: the library's root is a div; a fieldset would add a border and a legend
      role="group"
      aria-label="Versions of this message"
      className="flex items-center text-muted-foreground text-xs"
    >
      <BranchPickerPrimitive.Previous aria-label="Previous version" className={ACTION}>
        <ChevronLeft className="size-4 rtl:rotate-180" />
      </BranchPickerPrimitive.Previous>
      <span className="tabular-nums">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next aria-label="Next version" className={ACTION}>
        <ChevronRight className="size-4 rtl:rotate-180" />
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
}

function EditBox() {
  return (
    <ComposerPrimitive.Root className="grid w-full max-w-[85%] gap-2 rounded-2xl border bg-card p-3 ms-auto">
      <ComposerPrimitive.Input
        aria-label="Edit your message"
        dir="auto"
        className="max-h-48 min-h-10 w-full resize-none bg-transparent outline-none"
      />
      <div className="flex justify-end gap-2">
        <ComposerPrimitive.Cancel className="rounded-md px-3 py-1.5 text-sm hover:bg-accent">
          Cancel
        </ComposerPrimitive.Cancel>
        <ComposerPrimitive.Send className="rounded-md bg-primary px-3 py-1.5 text-primary-foreground text-sm">
          Send
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  );
}

/** What the person attached to this message (kept as the message's own data, not as text). */
function SentFiles() {
  const files = useAuiState(
    (s) =>
      (s.message.metadata?.custom as { attachments?: AttachmentInfo[] } | undefined)?.attachments,
  );
  return files?.length ? <MessageAttachments files={files} /> : null;
}

export function UserMessage() {
  const { linear } = useThreadEnv();
  return (
    <MessagePrimitive.Root className="grid justify-items-end gap-1">
      <AuiIf condition={(s) => s.message.composer.isEditing}>
        <EditBox />
      </AuiIf>
      <AuiIf condition={(s) => !s.message.composer.isEditing}>
        <SentFiles />
        <MessagePrimitive.Parts components={USER_PARTS} />
        <div className="flex items-center">
          <Versions />
          {linear ? null : (
            <ActionBarPrimitive.Root hideWhenRunning>
              <ActionBarPrimitive.Edit aria-label="Edit message" className={ACTION}>
                <Pencil className="size-4" />
              </ActionBarPrimitive.Edit>
            </ActionBarPrimitive.Root>
          )}
        </div>
      </AuiIf>
    </MessagePrimitive.Root>
  );
}

function PendingNote() {
  const { thinkingOn, pending } = useThreadEnv();
  return (
    <output className="text-muted-foreground">
      {pending ?? (thinkingOn ? "Thinking… this takes longer than usual." : "Thinking…")}
    </output>
  );
}

/** What a reply says, for reading it aloud: its text, not its thinking or its tool cards. */
function useSaid(): string {
  return useAuiState((s) =>
    s.message.content.map((p) => (p.type === "text" ? p.text : "")).join(""),
  );
}

export function AssistantMessage() {
  const { linear, lead, extras } = useThreadEnv();
  const id = useAuiState((s) => s.message.id);
  const said = useSaid();
  return (
    <MessagePrimitive.Root className="grid grid-cols-1 gap-3">
      {lead?.(id)}
      <AuiIf
        condition={(s) => s.message.status?.type === "running" && s.message.parts.length === 0}
      >
        <PendingNote />
      </AuiIf>
      <MessagePrimitive.Parts components={ASSISTANT_PARTS} />
      <div className="-mt-1 flex items-center">
        <Versions />
        <ActionBarPrimitive.Root hideWhenRunning className="flex">
          <ActionBarPrimitive.Copy aria-label="Copy reply" className={ACTION}>
            <AuiIf condition={(s) => s.message.isCopied}>
              <Check className="size-4" />
            </AuiIf>
            <AuiIf condition={(s) => !s.message.isCopied}>
              <Copy className="size-4" />
            </AuiIf>
          </ActionBarPrimitive.Copy>
          {linear ? null : (
            <ActionBarPrimitive.Reload aria-label="Answer again" className={ACTION}>
              <RefreshCw className="size-4" />
            </ActionBarPrimitive.Reload>
          )}
          <ReadAloudButton id={id} text={said} className="p-2" />
          {extras?.(id)}
        </ActionBarPrimitive.Root>
      </div>
      <ReadAloudNotice id={id} />
    </MessagePrimitive.Root>
  );
}
