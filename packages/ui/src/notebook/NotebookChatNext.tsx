"use client";

import { AssistantRuntimeProvider, ThreadPrimitive, useAui } from "@assistant-ui/react";
import type { AskedMessage, ChatMessage } from "@wasifyai/client";
import { isWorking } from "@wasifyai/client";
import { NotebookPen, Search } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { Composer } from "../chat/thread/Composer";
import { AssistantMessage, UserMessage } from "../chat/thread/Message";
import { Announcer } from "../chat/thread/announcer";
import { ThreadEnvProvider } from "../chat/thread/env";
import { preloadMarkdown } from "../chat/thread/markdown/Markdown";
import { useLinearRuntime } from "../chat/thread/use-chat-runtime";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { CitationPill } from "./CitationPill";
import type { NotebookChatProps } from "./NotebookChat";

/** One `ChatMessage` per `AskedMessage` object, so a message that did not change keeps its identity between tokens. */
function useChatMessages(messages: AskedMessage[]): ChatMessage[] {
  const cache = useRef(new WeakMap<AskedMessage, ChatMessage>());
  return useMemo(
    () =>
      messages.map((m) => {
        let made = cache.current.get(m);
        if (!made) {
          made = {
            id: m.id,
            role: m.role,
            parts: [
              ...(m.reasoning ? [{ type: "reasoning" as const, text: m.reasoning }] : []),
              ...(m.text || m.role === "user" ? [{ type: "text" as const, text: m.text }] : []),
            ],
            streaming: Boolean(m.streaming),
          };
          cache.current.set(m, made);
        }
        return made;
      }),
    [messages],
  );
}

const MESSAGE = ({ message }: { message: { role: string } }) =>
  message.role === "user" ? <UserMessage /> : <AssistantMessage />;

/** A question from the guide lands in the box when its id changes. */
function SeedBridge({ seed }: { seed: { text: string; id: number } | null | undefined }) {
  const aui = useAui();
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new seed (its id) is the trigger
  useEffect(() => {
    if (seed) aui.composer().setText(seed.text);
  }, [seed?.id]);
  return null;
}

/**
 * The notebook chat on the same primitives as the assistant's new chat (ADR-0082, stage CU4), with the props of `NotebookChat`:
 * the scope in the box's bar, `[n]` citation pills that open the passage, the search line above an answer, "Save as note", and a
 * model's thinking collapsed under "Thinking". Behind the Labs switch; the old `NotebookChat` stays the default.
 */
export function NotebookChatNext({
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
  // the markdown renderer is a separate chunk: fetch it while the person is still typing the first question
  useEffect(() => {
    void preloadMarkdown().catch(() => {});
  }, []);
  const working = isWorking(state);
  const none = state.messages.length === 0 && state.phase === "idle";
  const messages = useChatMessages(state.messages);
  const runtime = useLinearRuntime({
    messages,
    running: working,
    blocked: Boolean(blockedReason),
    onSend,
    onStop,
  });

  const env = useMemo(() => {
    const byId = new Map(state.messages.map((m) => [m.id, m]));
    return {
      // there are no picture cards in a notebook chat: the library is never asked
      images: undefined as never,
      linear: true,
      pending: "Reading your sources…",
      lead: (id: string) => {
        const s = byId.get(id)?.searched;
        if (!s) return null;
        const sources = `${s.sources} source${s.sources === 1 ? "" : "s"}`;
        return (
          <p className="flex items-center gap-1.5 text-muted-foreground text-xs">
            <Search className="size-3.5" aria-hidden="true" />
            {s.passages > 0
              ? `Searched ${sources}, found ${s.passages} passages`
              : `Searched ${sources}`}
          </p>
        );
      },
      extras: (id: string) => {
        const m = byId.get(id);
        return onSaveNote && m?.text ? (
          <Button type="button" variant="ghost" size="xs" onClick={() => onSaveNote(m)}>
            <NotebookPen /> Save as note
          </Button>
        ) : null;
      },
      renderLabel: (id: string, n: number) => (
        <CitationPill
          n={n}
          citation={byId.get(id)?.citations.find((c) => c.n === n)}
          onOpen={onOpenCitation}
        />
      ),
    };
  }, [state.messages, onSaveNote, onOpenCitation]);

  const last = state.messages[state.messages.length - 1];
  const lastAnswer = last && last.role === "assistant" ? last.text : "";
  const error = state.error;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <SeedBridge seed={draftSeed} />
      <ThreadEnvProvider value={env}>
        <section aria-label="Chat" className="flex h-full min-h-0 flex-col">
          <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
            {header ? (
              <div className="flex items-center justify-end gap-2 border-b px-4 py-2">{header}</div>
            ) : null}
            {none && empty ? (
              <div className="grid min-h-0 flex-1 place-items-center overflow-auto p-6">
                {empty}
              </div>
            ) : (
              <ThreadPrimitive.Viewport className="min-h-0 flex-1 overflow-auto px-5 py-5">
                <div className="mx-auto grid w-full max-w-3xl grid-cols-1 gap-6">
                  {none ? (
                    <>
                      {guide}
                      <p className="text-center text-muted-foreground">
                        Ask a question about your sources. Answers cite the passages they came from.
                      </p>
                    </>
                  ) : null}
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

            <div className="grid shrink-0 gap-3 px-5 pt-2 pb-4">
              {notices ? <div className="mx-auto w-full max-w-3xl">{notices}</div> : null}
              <Composer
                empty={false}
                blockedReason={blockedReason}
                label="Ask about your sources"
                placeholder="Ask about your sources"
                start={
                  <span className="min-w-0 truncate text-muted-foreground text-xs">{scope}</span>
                }
                chip={chip}
              />
            </div>
            <Announcer working={working} error={error?.message ?? null} answer={lastAnswer} />
          </ThreadPrimitive.Root>
        </section>
      </ThreadEnvProvider>
    </AssistantRuntimeProvider>
  );
}
