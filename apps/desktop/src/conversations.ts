// SPDX-License-Identifier: AGPL-3.0-only
// The list of conversations shown under Recents, kept fresh by one small event: a screen that changes a
// conversation says so, and the list reads again.
import type { ConversationSummary } from "@wasifyai/client";
import { useCallback, useEffect, useState } from "react";
import { assistantApi } from "./api";

const CHANGED = "wasifyai:conversations-changed";

/** Tell the Recents list that a conversation was made, renamed or deleted. */
export function conversationsChanged(): void {
  window.dispatchEvent(new Event(CHANGED));
}

export function useConversations(limit = 8): ConversationSummary[] {
  const [list, setList] = useState<ConversationSummary[]>([]);
  const refresh = useCallback(() => {
    assistantApi
      .list(limit)
      .then(setList)
      .catch(() => {});
  }, [limit]);
  useEffect(() => {
    refresh();
    window.addEventListener(CHANGED, refresh);
    return () => window.removeEventListener(CHANGED, refresh);
  }, [refresh]);
  return list;
}
