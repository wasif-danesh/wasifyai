// SPDX-License-Identifier: AGPL-3.0-only
import { useChoicesVersion } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { languageApi } from "./api";

/** Whether a chat model is chosen (null while it is not known) and its name. */
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
    languageApi
      .state()
      .then((s) => !gone && setState({ chosen: s.selected !== null, name: s.selected?.name ?? "" }))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [version]);
  return state;
}
