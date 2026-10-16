// SPDX-License-Identifier: AGPL-3.0-only
// The home screen is the assistant (ADR-0057): a greeting and "Ask anything", then the conversation.
import { Button, ChatScreen, Notice } from "@wasifyai/ui";
import { Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { assistantApi, client } from "../api";
import { conversationsChanged } from "../conversations";
import { images } from "../images";
import { type Route, openChat, openNotebook } from "../router";
import { useChatModel } from "../useChatModel";

export function greeting(hour: number): string {
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

const EXAMPLES = [
  "Draw a lighthouse at sunrise",
  "What did I make last week?",
  "Explain how a transistor works",
];

export function HomePage({
  go,
  conversationId,
  onAdopt,
}: {
  go: (r: Route) => void;
  conversationId: string | null;
  onAdopt: (id: string) => void;
}) {
  const model = useChatModel();
  const [title, setTitle] = useState("");

  useEffect(() => {
    if (!conversationId) {
      setTitle("");
      return;
    }
    let gone = false;
    assistantApi
      .list(100)
      .then((l) => !gone && setTitle(l.find((c) => c.id === conversationId)?.title ?? ""))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [conversationId]);

  async function rename() {
    if (!conversationId) return;
    const next = window.prompt("Name this chat", title)?.trim();
    if (!next) return;
    try {
      const c = await assistantApi.rename(conversationId, next);
      setTitle(c.title);
      conversationsChanged();
    } catch {
      // the name stays as it was
    }
  }

  async function remove() {
    if (!conversationId) return;
    if (!window.confirm("Delete this chat? Pictures it made stay in your library.")) return;
    try {
      await assistantApi.remove(conversationId);
      conversationsChanged();
      openChat(null);
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
      {greeting(new Date().getHours())}
    </h1>
  );

  const notices =
    model.chosen === false ? (
      <Notice
        tone="info"
        title="Choose a chat model"
        actions={
          <>
            <Button
              type="button"
              onClick={() => {
                window.location.hash = "/models?tab=discover";
              }}
            >
              Get a recommended model
            </Button>
            <Button type="button" variant="outline" onClick={() => go("models")}>
              Use one I have
            </Button>
          </>
        }
      >
        Wasify AI answers with a model that runs on this computer. Pick one you already have, or get
        one in Discover.
      </Notice>
    ) : null;

  return (
    <ChatScreen
      runs={client}
      assistant={assistantApi}
      images={images}
      conversationId={conversationId}
      onConversation={(id) => {
        conversationsChanged();
        if (!conversationId) onAdopt(id); // a new chat now has an address, and stays as it is
      }}
      hero={hero}
      examples={conversationId ? [] : EXAMPLES}
      notices={notices}
      onNeedModel={() => go("models")}
      onOpenCreation={(kind, id) => {
        if (kind === "image") go("library");
        else if (kind === "notebook") openNotebook(id);
      }}
      title={conversationId ? title || "Chat" : undefined}
      actions={
        conversationId ? (
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
        ) : undefined
      }
    />
  );
}
