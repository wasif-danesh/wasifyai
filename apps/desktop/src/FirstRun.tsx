// SPDX-License-Identifier: AGPL-3.0-only
// The first run (ADR-0109 decisions 1 to 5, stage FR5): one button that says what it costs and sets up chat only.
// A chat model already on the computer (Ollama, LM Studio, a found file) is used instead of a download; on a computer
// too small for one, the key comes first. "I'd rather use an API key" is always offered. Nothing else is asked:
// every other part of the menu sets itself up the first time it is opened, with its group's one card.
import type { SetupGroup } from "@wasifyai/client";
import { Bar, Button, type ModelChoice, formatBytes, useChoicesFor } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { refresh, useGroups, useRun } from "./SetupGate";
import { openYourKeys } from "./choices/keyed";
import { remembered } from "./remember";
import { chatOffer, setupPorts, startSetup, stopSetup } from "./setup-groups";

const DONE_KEY = "wasify.first-run.done";

/** Whether to show the first run: once, and only while chat is not set up (a person who had chat before this
 * screen existed never sees it). Once shown it stays until the person leaves it, so "You're ready" is seen; it is
 * marked done as soon as chat works, so it never comes back. */
export function useFirstRun(): { show: boolean; done: () => void } {
  const groups = useGroups();
  const [over, setOver] = useState(() => remembered.get(DONE_KEY) === "1");
  const [shown, setShown] = useState(false);
  const chat = groups?.find((g) => g.id === "chat") ?? null;
  const ready = chat?.state === "ready";
  useEffect(() => {
    if (over || chat === null) return;
    if (!ready) setShown(true);
    else {
      remembered.set(DONE_KEY, "1");
      if (!shown) setOver(true); // chat works and the first run was never on the screen: it is not needed
    }
  }, [over, chat, ready, shown]);
  return {
    show: !over && (shown || (chat !== null && !ready)),
    done: () => {
      remembered.set(DONE_KEY, "1");
      setOver(true);
    },
  };
}

/** The chat model the button would use, and what it costs. */
function useChatOffer(): { offer: ModelChoice | null; loaded: boolean } {
  const api = useChoicesFor("chat");
  const [state, setState] = useState<{ offer: ModelChoice | null; loaded: boolean }>({
    offer: null,
    loaded: false,
  });
  useEffect(() => {
    if (!api) return;
    let gone = false;
    api
      .list()
      .then((l) => !gone && setState({ offer: chatOffer(l.choices), loaded: true }))
      .catch(() => !gone && setState({ offer: null, loaded: true }));
    return () => {
      gone = true;
    };
  }, [api]);
  return state;
}

/** Where a model already on the computer comes from, in words. */
function fromWhere(c: ModelChoice): string {
  if (c.source === "server") return c.foundIn ? ` from ${c.foundIn}` : " already running here";
  return c.foundIn ? ` from ${c.foundIn}` : " already on this computer";
}

/** The Get started buttons: on the first run, and on the home while chat is not set up. */
export function GetStarted({
  group,
  onStarted,
  onKey,
}: {
  group: SetupGroup;
  onStarted?: () => void;
  onKey: () => void;
}) {
  const chatApi = useChoicesFor("chat");
  const { offer, loaded } = useChatOffer();
  const found = offer && offer.state === "ready" ? offer : null;
  const bytes = offer ? offer.downloadBytes + offer.engineBytes : 0;
  const keyFirst = group.key.first && !found;
  const start = () => {
    onStarted?.();
    void startSetup(group, false, setupPorts(chatApi), () => void refresh());
  };
  if (!loaded) return null;
  if (keyFirst)
    return (
      <div className="grid justify-items-center gap-3">
        <Button type="button" size="lg" onClick={onKey}>
          Get started with an API key · Nothing to download
        </Button>
        <Button type="button" variant="outline" onClick={start}>
          Download a chat model instead{bytes ? ` · ${formatBytes(bytes)}` : ""}
        </Button>
      </div>
    );
  return (
    <div className="grid justify-items-center gap-3">
      <Button type="button" size="lg" onClick={start}>
        Get started
      </Button>
      <p className="m-0 text-muted-foreground text-sm">
        {found
          ? `Uses ${found.title}${fromWhere(found)} · no download`
          : `Downloads a ${formatBytes(bytes)} chat model${offer ? ` (${offer.title})` : ""}`}
      </p>
      <button type="button" className="text-primary text-sm underline" onClick={onKey}>
        I&rsquo;d rather use an API key
      </button>
    </div>
  );
}

export function FirstRun({ onDone }: { onDone: () => void }) {
  const groups = useGroups();
  const chat = groups?.find((g) => g.id === "chat") ?? null;
  const run = useRun("chat");
  const [started, setStarted] = useState(false);
  const ready = chat?.state === "ready";
  const toKeys = () => {
    onDone();
    openYourKeys();
  };
  return (
    <section
      aria-label="Welcome"
      className="mx-auto grid min-h-full w-full max-w-xl content-center justify-items-center gap-5 px-4 py-10 text-center"
    >
      {ready && started ? (
        <>
          <h1 className="m-0 font-semibold text-3xl">You&rsquo;re ready</h1>
          <p className="m-0 text-muted-foreground">
            Ask anything in the chat. Open any part of the menu and it says what it needs, once,
            with one button.
          </p>
          <Button type="button" size="lg" onClick={onDone}>
            Start chatting
          </Button>
        </>
      ) : run.state === "running" ? (
        <>
          <h1 className="m-0 font-semibold text-3xl">Getting ready</h1>
          <div className="grid w-full gap-2" aria-live="polite">
            <Bar value={run.fraction} />
            <p className="m-0 text-muted-foreground text-sm">{run.label}</p>
          </div>
          <Button type="button" variant="outline" onClick={() => stopSetup("chat")}>
            Stop
          </Button>
        </>
      ) : (
        <>
          <h1 className="m-0 font-semibold text-3xl">Welcome to Wasify AI</h1>
          <p className="m-0 text-muted-foreground">
            Chat, pictures, video, voice, music and more, on this computer. Start with a chat model;
            every other part sets itself up the first time you open it.
          </p>
          {run.state === "failed" ? (
            <p role="alert" className="m-0 text-destructive text-sm">
              {run.message} Press Get started again to carry on from where it stopped.
            </p>
          ) : null}
          {chat ? (
            <GetStarted group={chat} onStarted={() => setStarted(true)} onKey={toKeys} />
          ) : null}
          <button
            type="button"
            className="text-muted-foreground text-sm underline"
            onClick={onDone}
          >
            Not now
          </button>
        </>
      )}
    </section>
  );
}
