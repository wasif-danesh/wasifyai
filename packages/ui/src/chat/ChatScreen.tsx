"use client";

import type { AssistantApi, ChatMessage, ImagesApi, RunClient } from "@wasifyai/client";
import { ArrowUp, Square } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { ToolCard } from "./ToolCard";
import { Markdown } from "./markdown";
import { useAssistantChat } from "./use-assistant-chat";

const MAX_CHARS = 4000;

export type ChatScreenProps = {
  runs: Pick<RunClient, "startRun" | "watchRun">;
  assistant: AssistantApi;
  images: ImagesApi;
  /** A saved conversation to open; null starts a new chat. */
  conversationId?: string | null;
  /** The turn finished and the conversation has an id and a title. */
  onConversation?: (id: string, title: string) => void;
  /** Shown above the box while the chat is empty (the greeting). */
  hero?: ReactNode;
  /** Suggestions under the box while the chat is empty. */
  examples?: string[];
  /** Setup notices (no model chosen yet, and so on). */
  notices?: ReactNode;
  /** Why sending is not possible right now. The box stays usable for typing. */
  blockedReason?: string | null;
  /** Open a creation in its own screen. */
  onOpenCreation?: (kind: string, id: string) => void;
  /** Where a "No language model" error should send the person. */
  onNeedModel?: () => void;
  /** Title bar actions (rename, delete). */
  actions?: ReactNode;
  title?: string;
};

function Bubble({
  message,
  images,
  onOpenCreation,
}: {
  message: ChatMessage;
  images: ImagesApi;
  onOpenCreation?: (kind: string, id: string) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-accent px-4 py-2.5">
          {message.parts.map((p) => (p.type === "text" ? p.text : "")).join("")}
        </p>
      </div>
    );
  }
  const thinking = message.streaming && message.parts.length === 0;
  return (
    <div className="grid gap-3">
      {thinking ? <output className="text-muted-foreground">Thinking…</output> : null}
      {message.parts.map((p, n) =>
        p.type === "text" ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: the parts of a message only ever grow at the end
          <Markdown key={`t${n}`} text={p.text} />
        ) : (
          <ToolCard key={p.id} tool={p} images={images} onOpenCreation={onOpenCreation} />
        ),
      )}
    </div>
  );
}

/**
 * The assistant's chat (ADR-0057): a thread, a box, tool cards, stop and try again. It knows nothing
 * of the desktop or the web; the app supplies the clients, the greeting and the places to go.
 */
export function ChatScreen({
  runs,
  assistant,
  images,
  conversationId,
  onConversation,
  hero,
  examples = [],
  notices,
  blockedReason,
  onOpenCreation,
  onNeedModel,
  actions,
  title,
}: ChatScreenProps) {
  const { state, send, stop, retry } = useAssistantChat({
    runs,
    api: assistant,
    conversationId,
    onConversation,
  });
  const [draft, setDraft] = useState("");
  const boxId = useId();
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const empty = state.messages.length === 0 && state.phase === "idle";
  const working = state.phase === "working";

  // follow the answer as it grows, unless the person scrolled up to read
  // biome-ignore lint/correctness/useExhaustiveDependencies: the thread's length and text are the trigger
  useEffect(() => {
    const el = scroller.current;
    if (stick.current && el) el.scrollTop = el.scrollHeight;
  }, [state.messages, state.phase]);

  function submit() {
    const text = draft.trim();
    if (!text || working || blockedReason) return;
    setDraft("");
    stick.current = true;
    void send(text);
  }

  const box = (
    <form
      className="mx-auto w-full max-w-3xl"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="rounded-3xl border bg-card px-5 py-3 shadow-card focus-within:ring-[3px] focus-within:ring-ring/40">
        <label htmlFor={boxId} className="sr-only">
          Message
        </label>
        <textarea
          id={boxId}
          rows={empty ? 3 : 1}
          maxLength={MAX_CHARS}
          value={draft}
          placeholder="Ask anything"
          className="max-h-48 min-h-10 w-full resize-none bg-transparent py-1 text-lg outline-none placeholder:text-muted-foreground"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="mt-1 flex items-center justify-end gap-2">
          {working ? (
            <Button type="button" variant="outline" size="sm" onClick={stop}>
              <Square className="size-3.5" /> Stop
            </Button>
          ) : null}
          <button
            type="submit"
            aria-label="Send"
            disabled={!draft.trim() || working || Boolean(blockedReason)}
            className="grid size-10 place-items-center rounded-full bg-primary text-primary-foreground transition-opacity disabled:opacity-40"
          >
            <ArrowUp className="size-5" />
          </button>
        </div>
      </div>
      {blockedReason ? (
        <output className="mt-2 block text-center text-muted-foreground text-sm">
          {blockedReason}
        </output>
      ) : null}
    </form>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      {title || actions ? (
        <header
          data-tauri-drag-region
          className="flex h-14 shrink-0 items-center justify-between gap-3 border-b px-6 pt-1"
        >
          <h1 className="min-w-0 truncate ps-2 font-medium text-sm">{title}</h1>
          <div className="flex items-center gap-1">{actions}</div>
        </header>
      ) : null}

      {empty ? (
        <div
          key="hero"
          className="grid min-h-0 flex-1 content-end justify-items-center gap-8 overflow-auto px-8 pb-8"
        >
          {hero}
        </div>
      ) : (
        <div
          key="thread"
          ref={scroller}
          className="min-h-0 flex-1 overflow-auto px-6 py-6"
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
        >
          <div className={cn("mx-auto grid w-full max-w-3xl gap-6")} aria-live="polite">
            {state.messages.map((m) => (
              <Bubble key={m.id} message={m} images={images} onOpenCreation={onOpenCreation} />
            ))}
            {state.error ? (
              <Notice
                tone="error"
                title="That did not work"
                actions={
                  state.error.code === "no_language_model" && onNeedModel ? (
                    <Button type="button" onClick={onNeedModel}>
                      Choose a model
                    </Button>
                  ) : state.error.retryable ? (
                    <Button type="button" variant="outline" onClick={retry}>
                      Try again
                    </Button>
                  ) : undefined
                }
              >
                {state.error.message}
              </Notice>
            ) : null}
          </div>
        </div>
      )}

      {/* the same element in both states, so typing is never interrupted when the first answer starts */}
      <div key="composer" className={cn("grid shrink-0 gap-4 px-6", empty ? "" : "pt-2 pb-5")}>
        {notices ? <div className="mx-auto w-full max-w-3xl">{notices}</div> : null}
        {box}
      </div>

      {empty ? (
        <div key="examples" className="min-h-0 flex-1 px-8 pt-4">
          {examples.length ? (
            <ul className="mx-auto flex max-w-3xl flex-wrap justify-center gap-2">
              {examples.map((ex) => (
                <li key={ex}>
                  <button
                    type="button"
                    className="rounded-full border px-3 py-1.5 text-muted-foreground text-sm hover:bg-accent"
                    onClick={() => setDraft(ex)}
                  >
                    {ex}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
