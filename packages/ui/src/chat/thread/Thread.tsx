"use client";

import { ThreadPrimitive } from "@assistant-ui/react";
import type { ReactNode } from "react";
import { cn } from "../../cn";
import { Button } from "../../components/button";
import { Notice } from "../../components/notice";
import { PageHeader } from "../../window-bar";
import type { ComposerOption } from "../composer-options";
import { type AttachBox, Composer, ExampleChip } from "./Composer";
import { AssistantMessage, UserMessage } from "./Message";
import { Announcer } from "./announcer";

export type ThreadProps = {
  /** no messages yet: the greeting, the box and the suggestions */
  empty: boolean;
  /** Shown above the box while the chat is empty (the greeting). */
  hero?: ReactNode;
  /** Suggestions under the box while the chat is empty. */
  examples?: string[];
  /** Setup notices (no model chosen yet, and so on). */
  notices?: ReactNode;
  blockedReason?: string | null;
  /** The options bar of the box (Thinking, and in time Attach, Search and Mic). */
  options?: ComposerOption[];
  /** Files attached to the next message: their chips, the picker, and what takes dropped and pasted files (ADR-0083). */
  attach?: AttachBox;
  /** Title bar actions (rename, delete). */
  actions?: ReactNode;
  title?: string;
  /** The turn went wrong. */
  error: { code: string; message: string; retryable: boolean } | null;
  onRetry: () => void;
  onNeedModel?: () => void;
  /** for the screen reader: an answer is arriving, and the last reply's text */
  working: boolean;
  lastAnswer: string;
};

const MESSAGE = ({ message }: { message: { role: string } }) =>
  message.role === "user" ? <UserMessage /> : <AssistantMessage />;

/**
 * The thread, the box and the greeting (ADR-0082), laid out as the old screen was: a title bar, then the greeting or the
 * messages, then the box, then the suggestions under it while the chat is empty. Every size and colour is a design token.
 */
export function Thread({
  empty,
  hero,
  examples = [],
  notices,
  blockedReason,
  options,
  attach,
  actions,
  title,
  error,
  onRetry,
  onNeedModel,
  working,
  lastAnswer,
}: ThreadProps) {
  return (
    <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
      {title || actions ? (
        <PageHeader
          className="flex h-14 shrink-0 items-center justify-between gap-3 border-b px-6 pt-1"
          pageOnly={<div className="flex items-center gap-1">{actions}</div>}
        >
          <h1 className="pointer-events-none min-w-0 flex-1 truncate ps-2 font-medium text-sm">
            {title}
          </h1>
        </PageHeader>
      ) : null}

      {empty ? (
        <div
          key="hero"
          className="grid min-h-0 flex-1 content-end justify-items-center gap-8 overflow-auto px-8 pb-8"
        >
          {hero}
        </div>
      ) : (
        <ThreadPrimitive.Viewport key="thread" className="min-h-0 flex-1 overflow-auto px-6 py-6">
          <div className="mx-auto grid w-full max-w-3xl grid-cols-1 gap-6">
            <ThreadPrimitive.Messages>{MESSAGE}</ThreadPrimitive.Messages>
            {error ? (
              <Notice
                tone="error"
                title="That did not work"
                actions={
                  error.code === "no_language_model" && onNeedModel ? (
                    <Button type="button" onClick={onNeedModel}>
                      Choose a model
                    </Button>
                  ) : error.retryable ? (
                    <Button type="button" variant="outline" onClick={onRetry}>
                      Try again
                    </Button>
                  ) : undefined
                }
              >
                {error.message}
              </Notice>
            ) : null}
          </div>
        </ThreadPrimitive.Viewport>
      )}

      {/* the same element in both states, so typing is never interrupted when the first answer starts */}
      <div key="composer" className={cn("grid shrink-0 gap-4 px-6", empty ? "" : "pt-2 pb-5")}>
        {notices ? <div className="mx-auto w-full max-w-3xl">{notices}</div> : null}
        <Composer empty={empty} blockedReason={blockedReason} options={options} attach={attach} />
      </div>

      {empty ? (
        <div key="examples" className="min-h-0 flex-1 px-8 pt-4">
          {examples.length ? (
            <ul className="mx-auto flex max-w-3xl flex-wrap justify-center gap-2">
              {examples.map((ex) => (
                <li key={ex}>
                  <ExampleChip text={ex} />
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <Announcer working={working} error={error?.message ?? null} answer={lastAnswer} />
    </ThreadPrimitive.Root>
  );
}
