"use client";

import { webAssistant, webImages } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import { AssistantHome, useChatNext } from "@wasifyai/ui";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Where a creation the assistant made opens on the web. */
function openCreation(kind: string, id: string): string | null {
  if (kind === "image") return `/image/creations/${id}`;
  if (kind === "video") return `/video/creations/${id}`;
  return null;
}

/** The home screen: the assistant (ADR-0057), the shared screen the desktop window also shows (the new chat behind Labs). A new chat gets
 * its address (`/chat/<id>`) after its first answer without the page being reloaded. */
export function ChatHome({ conversationId }: { conversationId: string | null }) {
  const router = useRouter();
  // Labs (ADR-0082): the new chat is off until asked for. `?chat=next` turns it on and `?chat=classic` back off; the choice is
  // remembered in this browser.
  const [next, setNext] = useChatNext();
  useEffect(() => {
    const asked = new URLSearchParams(window.location.search).get("chat");
    if (asked === "next") setNext(true);
    else if (asked === "classic") setNext(false);
  }, [setNext]);
  return (
    <div data-workspace className="h-[calc(100dvh-3.5rem)] min-h-[32rem]">
      <AssistantHome
        runs={webClient}
        assistant={webAssistant}
        images={webImages}
        conversationId={conversationId}
        screen={next ? "next" : "classic"}
        onAdopt={(id) => window.history.replaceState(null, "", `/chat/${id}`)}
        onNewChat={() => router.push("/")}
        onOpenCreation={(kind, id) => {
          const to = openCreation(kind, id);
          if (to) router.push(to);
        }}
      />
    </div>
  );
}
