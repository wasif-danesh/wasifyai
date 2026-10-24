"use client";

import { webAssistant, webImages, webVoice } from "@/lib/library";
import { webClient } from "@/lib/run-client";
import { AssistantHome, ModelSelect, useChoicesFor } from "@wasifyai/ui";
import { useRouter } from "next/navigation";

/** Where a creation the assistant made opens on the web. */
function openCreation(kind: string, id: string): string | null {
  if (kind === "image") return `/image/creations/${id}`;
  if (kind === "video") return `/video/creations/${id}`;
  return null;
}

/** The home screen: the assistant (ADR-0057), the shared screen the desktop window also shows (on assistant-ui). A new chat gets
 * its address (`/chat/<id>`) after its first answer without the page being reloaded. */
export function ChatHome({ conversationId }: { conversationId: string | null }) {
  const router = useRouter();
  const choices = useChoicesFor("chat");
  return (
    <div data-workspace className="h-[calc(100dvh-3.5rem)] min-h-[32rem]">
      <AssistantHome
        runs={webClient}
        assistant={webAssistant}
        images={webImages}
        voice={webVoice}
        conversationId={conversationId}
        onAdopt={(id) => window.history.replaceState(null, "", `/chat/${id}`)}
        modelPicker={choices ? <ModelSelect group="chat" api={choices} /> : undefined}
        onNewChat={() => router.push("/")}
        onOpenNotebooks={() => router.push("/notebooks")}
        onOpenCreation={(kind, id) => {
          const to = openCreation(kind, id);
          if (to) router.push(to);
        }}
      />
    </div>
  );
}
