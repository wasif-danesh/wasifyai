// SPDX-License-Identifier: AGPL-3.0-only
import { createRunClient } from "@wasifyai/client";
import { Button, CreateImage, Notice, PageHero, Spinner, page } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import {
  type EngineStatus,
  engineRestart,
  engineSession,
  engineStatus,
  onEngineStatus,
} from "./engine";
import { runSmoke, smokeEnabled } from "./smoke";
import { createEngineTransport } from "./transport";

// One transport and one client for the window, so the screens' hooks see stable functions.
const transport = createEngineTransport(engineSession);
const client = createRunClient(transport);

function EngineState({ status }: { status: Exclude<EngineStatus, { state: "ready" }> }) {
  if (status.state === "failed") {
    return (
      <Notice
        tone="error"
        title="The engine could not start"
        actions={
          <Button type="button" onClick={() => void engineRestart()}>
            Try again
          </Button>
        }
      >
        {status.message}
      </Notice>
    );
  }
  if (status.state === "stopped") {
    return (
      <Notice
        title="The engine is stopped"
        actions={
          <Button type="button" onClick={() => void engineRestart()}>
            Start it
          </Button>
        }
      />
    );
  }
  return (
    <output className="flex items-center gap-3 text-muted-foreground">
      <Spinner />
      {status.attempt > 1
        ? `Starting the engine (attempt ${status.attempt})`
        : "Starting the engine"}
    </output>
  );
}

export function App() {
  const [status, setStatus] = useState<EngineStatus>({ state: "starting", attempt: 1 });

  useEffect(() => {
    let stop: (() => void) | undefined;
    let gone = false;
    const apply = (s: EngineStatus) => {
      // a restarted engine has a new address and a new secret
      transport.invalidate();
      if (!gone) setStatus(s);
    };
    engineStatus().then(apply);
    onEngineStatus(apply).then((off) => {
      stop = off;
      if (gone) off();
    });
    return () => {
      gone = true;
      stop?.();
    };
  }, []);

  // `WASIFYAI_SMOKE=1` (see smoke.ts): once the screen is up, use it like a person would and report.
  useEffect(() => {
    if (status.state !== "ready") return;
    smokeEnabled()
      .then((on) => (on ? runSmoke() : undefined))
      .catch(() => {});
  }, [status.state]);

  return (
    <main id="main" className={page}>
      {status.state === "ready" ? (
        <CreateImage client={client} readyNote="It's saved on this computer." />
      ) : (
        <>
          <PageHero title="wasifyai" />
          <EngineState status={status} />
        </>
      )}
    </main>
  );
}
