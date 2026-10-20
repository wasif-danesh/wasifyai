"use client";

import type { AssistantApi, ImagesApi } from "@wasifyai/client";
import { Pencil, Trash2 } from "lucide-react";
import { type ReactNode, Suspense, lazy, useEffect, useState } from "react";
import { ChatScreen, type ChatScreenProps } from "./ChatScreen";
import type { TrackLookup } from "./ToolCard";
import { conversationsChanged } from "./use-conversations";

export function greeting(hour: number): string {
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

// The new chat is a separate chunk: it brings assistant-ui and streamdown, which a person who has not turned it on never needs.
const ChatScreenNext = lazy(() =>
  import("./ChatScreenNext").then((m) => ({ default: m.ChatScreenNext })),
);

const EXAMPLES = [
  "Draw a lighthouse at sunrise",
  "What did I make last week?",
  "Explain how a transistor works",
];

export type AssistantHomeProps = {
  runs: ChatScreenProps["runs"];
  assistant: AssistantApi;
  images: ImagesApi;
  tracks?: TrackLookup;
  /** The saved conversation open; null is a new chat. */
  conversationId: string | null;
  /** A new chat got its first answer and so an id: the app gives it an address. */
  onAdopt: (id: string) => void;
  /** The open chat was deleted: the app goes to a new one. */
  onNewChat: () => void;
  /** Setup notices (no model chosen yet, and so on). */
  notices?: ReactNode;
  blockedReason?: string | null;
  onNeedModel?: () => void;
  onOpenCreation?: (kind: string, id: string) => void;
  /** Which chat screen to show: the one built on our own components (the default) or the new one on assistant-ui (Labs). */
  screen?: "classic" | "next";
};

/** The assistant is the home screen (ADR-0057): a greeting and "Ask anything", then the conversation, with
 * rename and delete once it is saved. Shared by the desktop window and the web app. */
export function AssistantHome({
  runs,
  assistant,
  images,
  tracks,
  conversationId,
  onAdopt,
  onNewChat,
  notices,
  blockedReason,
  onNeedModel,
  onOpenCreation,
  screen = "classic",
}: AssistantHomeProps) {
  const [title, setTitle] = useState("");
  // the hour is read in the browser, so a page rendered on a server says the same as the person's clock
  const [hour, setHour] = useState<number | null>(null);
  useEffect(() => setHour(new Date().getHours()), []);

  useEffect(() => {
    if (!conversationId) {
      setTitle("");
      return;
    }
    let gone = false;
    assistant
      .list(100)
      .then((l) => !gone && setTitle(l.find((c) => c.id === conversationId)?.title ?? ""))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [conversationId, assistant]);

  async function rename() {
    if (!conversationId) return;
    const next = window.prompt("Name this chat", title)?.trim();
    if (!next) return;
    try {
      const c = await assistant.rename(conversationId, next);
      setTitle(c.title);
      conversationsChanged();
    } catch {
      // the name stays as it was
    }
  }

  async function remove() {
    if (!conversationId) return;
    if (!window.confirm("Delete this chat? What it made stays in your library.")) return;
    try {
      await assistant.remove(conversationId);
      conversationsChanged();
      onNewChat();
    } catch {
      // still there: nothing to do
    }
  }

  const hero = (
    <h1 className="flex items-center gap-4 font-medium text-4xl tracking-tight">
      <span
        aria-hidden="true"
        className="grid size-14 place-items-center rounded-full bg-primary font-bold text-2xl text-primary-foreground"
      >
        w
      </span>
      {hour === null ? "Hello" : greeting(hour)}
    </h1>
  );

  const shared: ChatScreenProps = {
    runs,
    assistant,
    images,
    tracks,
    conversationId,
    onConversation: (id) => {
      conversationsChanged();
      if (!conversationId) onAdopt(id); // a new chat now has an address, and stays as it is
    },
    hero,
    examples: conversationId ? [] : EXAMPLES,
    notices,
    blockedReason,
    onNeedModel,
    onOpenCreation,
    title: conversationId ? title || "Chat" : undefined,
    actions: conversationId ? (
      <>
        <button
          type="button"
          aria-label="Rename this chat"
          className="rounded-md p-2 text-muted-foreground hover:bg-accent"
          onClick={() => void rename()}
        >
          <Pencil className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Delete this chat"
          className="rounded-md p-2 text-muted-foreground hover:bg-accent"
          onClick={() => void remove()}
        >
          <Trash2 className="size-4" />
        </button>
      </>
    ) : undefined,
  };

  return screen === "next" ? (
    <Suspense fallback={null}>
      <ChatScreenNext {...shared} />
    </Suspense>
  ) : (
    <ChatScreen {...shared} />
  );
}
