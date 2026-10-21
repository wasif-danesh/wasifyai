// SPDX-License-Identifier: AGPL-3.0-only
// The first-run offer for chat (ADR-0086): when no chat model is in use, one card names the best one for this
// computer, what it costs and where it runs. A click opens the same dialog as the picker; nothing downloads by itself.
import {
  Button,
  type ModelChoice,
  type ModelSelectHandle,
  Notice,
  formatBytes,
  timeText,
  useChoicesFor,
  useChoicesVersion,
} from "@wasifyai/ui";
import { type RefObject, useEffect, useState } from "react";

/** The row to offer: the model that was chosen but needs setting up, else the recommended one that fits. */
export function offerOf(choices: ModelChoice[]): { choice: ModelChoice; finish: boolean } | null {
  if (choices.some((c) => c.chosen && c.state === "ready")) return null;
  const chosen = choices.find((c) => c.chosen);
  if (chosen) return { choice: chosen, finish: true };
  const best =
    choices.find((c) => c.tier === "recommended" && c.state === "needs_download") ??
    choices.find((c) => c.state === "needs_download") ??
    null;
  return best ? { choice: best, finish: false } : null;
}

export function ChatStart({ picker }: { picker: RefObject<ModelSelectHandle | null> }) {
  const api = useChoicesFor("chat");
  const version = useChoicesVersion();
  const [offer, setOffer] = useState<ReturnType<typeof offerOf>>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    let gone = false;
    api
      ?.list()
      .then((l) => !gone && setOffer(offerOf(l.choices)))
      .catch(() => !gone && setOffer(null));
    return () => {
      gone = true;
    };
  }, [api, version]);

  if (!offer) return null;
  const { choice, finish } = offer;
  const total = choice.downloadBytes + choice.engineBytes;
  return (
    <Notice
      tone="info"
      title={finish ? "Finish setting up chat" : "Get a chat model"}
      actions={
        <>
          <Button type="button" onClick={() => picker.current?.ask(choice.id)}>
            {finish ? `Finish setting up ${choice.title}` : `Get ${choice.title}`}
          </Button>
          <Button type="button" variant="outline" onClick={() => picker.current?.open()}>
            Choose another
          </Button>
        </>
      }
    >
      {finish
        ? `${choice.title} needs the chat engine first (${formatBytes(total)}, ${timeText(total)}).`
        : `${choice.title} is the one we suggest for this computer. ${choice.plain} It is ${formatBytes(total)} to download (${timeText(total)}) and runs here: nothing you write is sent away.`}
    </Notice>
  );
}
