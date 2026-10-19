"use client";

import type { AskState, AskedMessage, NotebookCitation } from "@wasifyai/client";
import { isWorking } from "@wasifyai/client";
import { ArrowUp, Copy, NotebookPen, Search, Square } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { Markdown } from "../chat/markdown";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";

const MAX_CHARS = 4000;

/** A `[n]` label as a button that opens the passage it points at. */
export function CitationPill({
  n,
  citation,
  onOpen,
}: {
  n: number;
  citation: NotebookCitation | undefined;
  onOpen: (c: NotebookCitation) => void;
}) {
  if (!citation) return <span className="text-muted-foreground">[{n}]</span>;
  const where =
    citation.start_line && citation.end_line
      ? `, lines ${citation.start_line} to ${citation.end_line}`
      : "";
  return (
    <button
      type="button"
      onClick={() => onOpen(citation)}
      title={`${citation.title}${where}`}
      aria-label={`Source ${n}: ${citation.title}`}
      className="mx-0.5 inline-grid h-5 min-w-5 -translate-y-px place-items-center rounded-full bg-primary/15 px-1.5 align-middle font-semibold text-2xs text-primary hover:bg-primary/25"
    >
      {n}
    </button>
  );
}

function Message({
  message,
  onOpenCitation,
  onSaveNote,
}: {
  message: AskedMessage;
  onOpenCitation: (c: NotebookCitation) => void;
  onSaveNote?: (message: AskedMessage) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-accent px-4 py-2.5">
          {message.text}
        </p>
      </div>
    );
  }
  const byN = new Map(message.citations.map((c) => [c.n, c]));
  const waiting = message.streaming && !message.text;
  return (
    <div className="grid gap-2">
      {message.searched ? (
        <p className="flex items-center gap-1.5 text-muted-foreground text-xs">
          <Search className="size-3.5" aria-hidden="true" />
          {message.searched.passages > 0
            ? `Searched ${message.searched.sources} source${message.searched.sources === 1 ? "" : "s"}, found ${message.searched.passages} passages`
            : `Searched ${message.searched.sources} source${message.searched.sources === 1 ? "" : "s"}`}
        </p>
      ) : null}
      {waiting ? <output className="text-muted-foreground">Reading your sources…</output> : null}
      {message.text ? (
        <Markdown
          text={message.text}
          renderLabel={(n) => <CitationPill n={n} citation={byN.get(n)} onOpen={onOpenCitation} />}
        />
      ) : null}
      {!message.streaming && message.text ? (
        <div>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => void navigator.clipboard?.writeText(message.text)}
          >
            <Copy /> Copy
          </Button>
          {onSaveNote ? (
            <Button type="button" variant="ghost" size="xs" onClick={() => onSaveNote(message)}>
              <NotebookPen /> Save as note
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export type NotebookChatProps = {
  state: AskState;
  onSend: (text: string) => void;
  onStop: () => void;
  onRetry: () => void;
  onOpenCitation: (c: NotebookCitation) => void;
  /** "12 of 14 sources, 2 being read" */
  scope: string;
  /** Why asking is not possible now (the box stays usable for typing). */
  blockedReason?: string | null;
  /** Shown above the box (a setup notice). */
  notices?: ReactNode;
  /** Instead of the empty thread: the add-sources screen of a new notebook. */
  empty?: ReactNode;
  /** The model chip, beside the scope. */
  chip?: ReactNode;
  /** Where a "No language model" error should send the person. */
  onNeedModel?: () => void;
  /** A conversation switcher and "new chat". */
  header?: ReactNode;
  /** Shown above an empty thread: the guide to the notebook. */
  guide?: ReactNode;
  /** Keep an answer as a note, which is a source like the others. */
  onSaveNote?: (message: AskedMessage) => void;
  /** Fill the box with this text (a question from the guide) when it changes. */
  draftSeed?: { text: string; id: number } | null;
};

/** The conversation with a notebook: questions, answers with citations, and the box. */
export function NotebookChat({
  state,
  onSend,
  onStop,
  onRetry,
  onOpenCitation,
  scope,
  blockedReason,
  notices,
  empty,
  chip,
  onNeedModel,
  header,
  guide,
  onSaveNote,
  draftSeed,
}: NotebookChatProps) {
  const [draft, setDraft] = useState("");
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new seed (its id) is the trigger
  useEffect(() => {
    if (draftSeed) setDraft(draftSeed.text);
  }, [draftSeed?.id]);
  const boxId = useId();
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const working = isWorking(state);
  const none = state.messages.length === 0 && state.phase === "idle";

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
    onSend(text);
  }

  return (
    <section aria-label="Chat" className="flex h-full min-h-0 flex-col">
      {header ? (
        <div className="flex items-center justify-end gap-2 border-b px-4 py-2">{header}</div>
      ) : null}
      {none && empty ? (
        <div className="grid min-h-0 flex-1 place-items-center overflow-auto p-6">{empty}</div>
      ) : (
        <div
          ref={scroller}
          className="min-h-0 flex-1 overflow-auto px-5 py-5"
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
        >
          <div className="mx-auto grid w-full max-w-3xl gap-6" aria-live="polite">
            {none ? (
              <>
                {guide}
                <p className="text-center text-muted-foreground">
                  Ask a question about your sources. Answers cite the passages they came from.
                </p>
              </>
            ) : null}
            {state.messages.map((m) => (
              <Message
                key={m.id}
                message={m}
                onOpenCitation={onOpenCitation}
                onSaveNote={onSaveNote}
              />
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
                    <Button type="button" variant="outline" onClick={onRetry}>
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

      <div className={cn("grid shrink-0 gap-3 px-5 pt-2 pb-4")}>
        {notices ? <div className="mx-auto w-full max-w-3xl">{notices}</div> : null}
        <form
          className="mx-auto w-full max-w-3xl"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="rounded-3xl border bg-card px-4 py-2.5 shadow-card focus-within:ring-[3px] focus-within:ring-ring/40">
            <label htmlFor={boxId} className="sr-only">
              Ask about your sources
            </label>
            <textarea
              id={boxId}
              rows={1}
              maxLength={MAX_CHARS}
              value={draft}
              placeholder="Ask about your sources"
              className="max-h-40 min-h-9 w-full resize-none bg-transparent py-1 text-base outline-none placeholder:text-muted-foreground"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <div className="mt-1 flex items-center gap-2">
              <span className="min-w-0 truncate text-muted-foreground text-xs">{scope}</span>
              <span className="ms-auto flex items-center gap-2">
                {chip}
                {working ? (
                  <Button type="button" variant="outline" size="sm" onClick={onStop}>
                    <Square className="size-3.5" /> Stop
                  </Button>
                ) : null}
                <button
                  type="submit"
                  aria-label="Send"
                  disabled={!draft.trim() || working || Boolean(blockedReason)}
                  className="grid size-9 place-items-center rounded-full bg-primary text-primary-foreground transition-opacity disabled:opacity-40"
                >
                  <ArrowUp className="size-5" />
                </button>
              </span>
            </div>
          </div>
          {blockedReason ? (
            <output className="mt-2 block text-center text-muted-foreground text-sm">
              {blockedReason}
            </output>
          ) : null}
        </form>
      </div>
    </section>
  );
}
