"use client";

import { AuiIf, ComposerPrimitive, useAui } from "@assistant-ui/react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "../../components/button";
import { type ComposerOption, ComposerOptions } from "../composer-options";

const MAX_CHARS = 4000;

/**
 * The message box. One element for the whole life of the chat, so typing is never interrupted when the first answer starts:
 * Enter sends, Shift+Enter is a new line, the text is laid out right to left when it is written that way. While an answer
 * is arriving Stop takes the place of nothing: it sits beside Send, which waits.
 */
export function Composer({
  empty,
  blockedReason,
  options = [],
}: {
  empty: boolean;
  blockedReason?: string | null;
  /** the options bar: Thinking, and in time Attach, Search and Mic (ADR-0083) */
  options?: ComposerOption[];
}) {
  return (
    <ComposerPrimitive.Root className="mx-auto w-full max-w-3xl">
      <div className="rounded-3xl border bg-card px-5 py-3 shadow-card focus-within:ring-[3px] focus-within:ring-ring/40">
        <ComposerPrimitive.Input
          aria-label="Message"
          placeholder="Ask anything"
          dir="auto"
          maxLength={MAX_CHARS}
          minRows={empty ? 3 : 1}
          maxRows={8}
          submitMode="enter"
          className="min-h-10 w-full resize-none bg-transparent py-1 text-lg outline-none placeholder:text-muted-foreground"
        />
        <div className="mt-1 flex items-center justify-between gap-2">
          <ComposerOptions options={options} />
          <div className="ms-auto flex items-center gap-2">
            <AuiIf condition={(s) => s.thread.isRunning}>
              <ComposerPrimitive.Cancel asChild>
                <Button type="button" variant="outline" size="sm">
                  <Square className="size-3.5" /> Stop
                </Button>
              </ComposerPrimitive.Cancel>
            </AuiIf>
            <ComposerPrimitive.Send
              aria-label="Send"
              className="grid size-10 place-items-center rounded-full bg-primary text-primary-foreground transition-opacity disabled:opacity-40"
            >
              <ArrowUp className="size-5" />
            </ComposerPrimitive.Send>
          </div>
        </div>
      </div>
      {blockedReason ? (
        <output className="mt-2 block text-center text-muted-foreground text-sm">
          {blockedReason}
        </output>
      ) : null}
    </ComposerPrimitive.Root>
  );
}

/** A suggestion under the box: a click puts it in the box for the person to send or change. */
export function ExampleChip({ text }: { text: string }) {
  const aui = useAui();
  return (
    <button
      type="button"
      className="rounded-full border px-3 py-1.5 text-muted-foreground text-sm hover:bg-accent"
      onClick={() => aui.composer().setText(text)}
    >
      {text}
    </button>
  );
}
