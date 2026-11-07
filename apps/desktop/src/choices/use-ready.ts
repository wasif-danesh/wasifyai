// SPDX-License-Identifier: AGPL-3.0-only
import { type ChoicesApi, type ModelSelectHandle, useChoicesVersion } from "@wasifyai/ui";
import { type RefObject, useCallback, useEffect, useState } from "react";
import { isKeyed } from "./keyed";

/** The window's self-test (smoke.ts) makes placeholder pictures with no model on the computer: it asks the gate to let it. */
export const gate = { open: false };

/**
 * Whether a model of the group is ready to use (null while it is read), read again whenever a model is chosen or
 * downloaded. `ensure` is for a main action ("Make"): true when ready; otherwise it opens the picker and says no.
 */
export function useGroupReady(api: ChoicesApi | null, picker: RefObject<ModelSelectHandle | null>) {
  const [ready, setReady] = useState<boolean | null>(null);
  // the chosen row is the person's own key (ADR-0095): this computer's memory does not matter then
  const [keyed, setKeyed] = useState(false);
  // the id of the chosen row (a catalogue model's id, or `key:<product>`), null before one is chosen
  const [chosen, setChosen] = useState<string | null>(null);
  const version = useChoicesVersion();
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    let gone = false;
    api
      ?.list()
      .then((l) => {
        if (gone) return;
        setReady(l.choices.some((c) => c.chosen && c.state === "ready"));
        const row = l.choices.find((c) => c.chosen);
        setKeyed(isKeyed(row?.id));
        setChosen(row?.id ?? null);
      })
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
  return { ready, ensure, keyed, chosen };
}
