// SPDX-License-Identifier: AGPL-3.0-only
import { type ChoicesApi, type ModelSelectHandle, useChoicesVersion } from "@wasifyai/ui";
import { type RefObject, useCallback, useEffect, useState } from "react";

/** The window's self-test (smoke.ts) makes placeholder pictures with no model on the computer: it asks the gate to let it. */
export const gate = { open: false };

/**
 * Whether a model of the group is ready to use (null while it is read), read again whenever a model is chosen or
 * downloaded. `ensure` is for a main action ("Make"): true when ready; otherwise it opens the picker and says no.
 */
export function useGroupReady(api: ChoicesApi | null, picker: RefObject<ModelSelectHandle | null>) {
  const [ready, setReady] = useState<boolean | null>(null);
  const version = useChoicesVersion();
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    let gone = false;
    api
      ?.list()
      .then((l) => !gone && setReady(l.choices.some((c) => c.chosen && c.state === "ready")))
      .catch(() => !gone && setReady(null));
    return () => {
      gone = true;
    };
  }, [api, version]);
  const ensure = useCallback(() => {
    if (ready === true || gate.open) return true;
    picker.current?.open();
    return false;
  }, [ready, picker]);
  return { ready, ensure };
}
