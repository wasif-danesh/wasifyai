// SPDX-License-Identifier: AGPL-3.0-only
import { useChoicesVersion } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { languageApi, ownKeysApi } from "./api";

/** Whether a chat model is chosen (null while it is not known) and its name: one on this computer, or Chat and
 * writing on the person's own key (ADR-0095, K2). */
export function useChatModel(): { chosen: boolean | null; name: string } {
  const [state, setState] = useState<{ chosen: boolean | null; name: string }>({
    chosen: null,
    name: "",
  });
  // a model chosen or downloaded in the picker changes the answer
  const version = useChoicesVersion();
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    let gone = false;
    Promise.all([languageApi.state(), ownKeysApi.list().catch(() => null)])
      .then(([s, keys]) => {
        if (gone) return;
        const chat = keys?.products.find((p) => p.id === "chat");
        if (chat?.mode === "key") setState({ chosen: true, name: chat.model ?? "your model" });
        else setState({ chosen: s.selected !== null, name: s.selected?.name ?? "" });
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [version]);
  return state;
}
