// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import { languageApi } from "./api";

/** Whether a chat model is chosen (null while it is not known) and its name. */
export function useChatModel(): { chosen: boolean | null; name: string } {
  const [state, setState] = useState<{ chosen: boolean | null; name: string }>({
    chosen: null,
    name: "",
  });
  useEffect(() => {
    let gone = false;
    languageApi
      .state()
      .then((s) => !gone && setState({ chosen: s.selected !== null, name: s.selected?.name ?? "" }))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, []);
  return state;
}
