"use client";

import {
  ActionBarPrimitive,
  AuiIf,
  MessagePrimitive,
  type TextMessagePartProps,
  useAuiState,
} from "@assistant-ui/react";
import { Check, Copy } from "lucide-react";
import { useThreadEnv } from "./env";
import { Markdown } from "./markdown/Markdown";
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
  const { imageOrigins } = useThreadEnv();
  return <Markdown text={text} animating={animating} imageOrigins={imageOrigins} />;
}

const NOTHING = () => null;

const ASSISTANT_PARTS = {
  Text: AssistantText,
  Empty: NOTHING,
  tools: { by_name: toolUIs as never, Fallback: UnknownTool },
};

const USER_PARTS = { Text: UserText, Empty: NOTHING };

export function UserMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-end">
      <MessagePrimitive.Parts components={USER_PARTS} />
    </MessagePrimitive.Root>
  );
}

const ACTION = "rounded-md p-2 text-muted-foreground hover:bg-accent";

export function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="grid grid-cols-1 gap-3">
      <AuiIf
        condition={(s) => s.message.status?.type === "running" && s.message.parts.length === 0}
      >
        <output className="text-muted-foreground">Thinking…</output>
      </AuiIf>
      <MessagePrimitive.Parts components={ASSISTANT_PARTS} />
      <ActionBarPrimitive.Root hideWhenRunning className="-mt-1 flex">
        <ActionBarPrimitive.Copy aria-label="Copy reply" className={ACTION}>
          <AuiIf condition={(s) => s.message.isCopied}>
            <Check className="size-4" />
          </AuiIf>
          <AuiIf condition={(s) => !s.message.isCopied}>
            <Copy className="size-4" />
          </AuiIf>
        </ActionBarPrimitive.Copy>
      </ActionBarPrimitive.Root>
    </MessagePrimitive.Root>
  );
}
