"use client";

import type { AssistantApi, ConversationSummary } from "@wasifyai/client";
import { useCallback, useEffect, useState } from "react";

const CHANGED = "wasifyai:conversations-changed";

/** Tell the Recents list that a conversation was made, renamed or deleted. */
export function conversationsChanged(): void {
  window.dispatchEvent(new Event(CHANGED));
}

/** The latest conversations (for the Recents list), read again whenever a screen says one changed. */
export function useConversations(
  api: Pick<AssistantApi, "list">,
  limit = 8,
): ConversationSummary[] {
  const [list, setList] = useState<ConversationSummary[]>([]);
  const refresh = useCallback(() => {
    api
      .list(limit)
      .then(setList)
      .catch(() => {});
  }, [api, limit]);
  useEffect(() => {
    refresh();
    window.addEventListener(CHANGED, refresh);
    return () => window.removeEventListener(CHANGED, refresh);
  }, [refresh]);
  return list;
}
