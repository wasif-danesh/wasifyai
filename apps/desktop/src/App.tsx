// SPDX-License-Identifier: AGPL-3.0-only
import { createRunClient } from "@wasifyai/client";
import { Button, CreateImage, JobMeter, Notice, PageHero, Spinner, page } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import {
  COMFYUI,
  type ComponentStatus,
  type EngineStatus,
  type UpdateStatus,
  componentInstall,
  componentStatus,
  engineRepair,
  engineRestart,
  engineSession,
  engineStatus,
  humanBytes,
  installFraction,
  onComponentStatus,
  onEngineStatus,
  updateCheck,
  updateInstall,
} from "./engine";
import { runComponentSmoke, runSmoke, smokeComponent, smokeEnabled } from "./smoke";
import { createEngineTransport } from "./transport";

// One transport and one client for the window, so the screens' hooks see stable functions.
const transport = createEngineTransport(engineSession);
const client = createRunClient(transport);

function EngineState({ status }: { status: Exclude<EngineStatus, { state: "ready" }> }) {
  if (status.state === "installing") {
    const p = status.progress;
    return (
      <section className="grid gap-4" aria-label="Setting up">
        <p className="text-muted-foreground">
          Setting up the engine on this computer. This happens once and needs an internet
          connection.
        </p>
        <JobMeter
          title={`Step ${p.index} of ${p.count}: ${p.label}`}
          text={`${Math.round(installFraction(p) * 100)}%`}
          value={installFraction(p)}
          label="Setup progress"
        />
        {p.detail ? (
          <p className="truncate text-muted-foreground text-sm" aria-live="off">
            {p.detail}
          </p>
        ) : null}
      </section>
    );
  }
  if (status.state === "failed") {
    return (
      <Notice
        tone="error"
        title={status.step ? "The engine could not be set up" : "The engine could not start"}
        actions={
          <>
            <Button type="button" onClick={() => void engineRestart()}>
              Try again
            </Button>
            <Button type="button" variant="outline" onClick={() => void engineRepair()}>
              Repair the installation
            </Button>
          </>
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

/** The image engine (ComfyUI): set up once, on request. Quiet where it cannot be installed. */
function ImageEngineCard() {
  const [status, setStatus] = useState<ComponentStatus | null>(null);
  useEffect(() => {
    let stop: (() => void) | undefined;
    let gone = false;
    componentStatus(COMFYUI)
      .then((s) => !gone && setStatus(s))
      .catch(() => {});
    onComponentStatus((id, s) => id === COMFYUI && !gone && setStatus(s)).then((off) => {
      stop = off;
      if (gone) off();
    });
    return () => {
      gone = true;
      stop?.();
    };
  }, []);

  if (!status) return null;
  switch (status.state) {
    case "unsupported":
      return <p className="text-muted-foreground text-sm">Real images: {status.reason}</p>;
    case "not_installed":
      return (
        <Notice
          title="Make real images on this Mac"
          actions={
            <Button type="button" onClick={() => void componentInstall(COMFYUI)}>
              Set up image generation
            </Button>
          }
        >
          This is done once and needs an internet connection and about{" "}
          {humanBytes(status.needs_bytes)} of disk space. Until then the app makes placeholder
          pictures.
        </Notice>
      );
    case "installing": {
      const p = status.progress;
      return (
        <section className="grid gap-3" aria-label="Setting up image generation">
          <JobMeter
            title={`Setting up image generation, step ${p.index} of ${p.count}: ${p.label}`}
            text={`${Math.round(installFraction(p) * 100)}%`}
            value={installFraction(p)}
            label="Image engine setup progress"
          />
          {p.detail ? (
            <p className="truncate text-muted-foreground text-sm" aria-live="off">
              {p.detail}
            </p>
          ) : null}
        </section>
      );
    }
    case "installed":
      return (
        <p className="text-muted-foreground text-sm">
          Image engine installed (ComfyUI {status.version},{" "}
          {status.accelerator === "mps"
            ? "Apple GPU"
            : status.accelerator === "cuda"
              ? "NVIDIA GPU"
              : "no GPU found: it will be slow"}
          ). Models are added in the next step.
        </p>
      );
    case "failed":
      return (
        <Notice
          tone="error"
          title="The image engine could not be set up"
          actions={
            <>
              <Button type="button" onClick={() => void componentInstall(COMFYUI)}>
                Try again
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => void componentInstall(COMFYUI, true)}
              >
                Repair
              </Button>
            </>
          }
        >
          {status.message}
        </Notice>
      );
  }
}

/** An update, when this build has a feed and one is waiting. Quiet otherwise. */
function UpdateBanner() {
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    updateCheck()
      .then(setUpdate)
      .catch(() => {});
  }, []);
  if (update?.state !== "available") return null;
  return (
    <Notice
      title={`wasifyai ${update.version} is available`}
      actions={
        <Button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            updateInstall().catch(() => setBusy(false));
          }}
        >
          {busy ? "Installing…" : "Install and restart"}
        </Button>
      }
    >
      {update.notes}
    </Notice>
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
      .then(async (on) => {
        if (!on) return;
        // WASIFYAI_SMOKE_COMPONENT=comfyui: set the image engine up instead of making an image
        return (await smokeComponent()) === COMFYUI ? runComponentSmoke() : runSmoke();
      })
      .catch(() => {});
  }, [status.state]);

  return (
    <main id="main" className={page}>
      {status.state === "ready" ? (
        <>
          <UpdateBanner />
          <ImageEngineCard />
          <CreateImage client={client} readyNote="It's saved on this computer." />
        </>
      ) : (
        <>
          <PageHero title="wasifyai" />
          <EngineState status={status} />
        </>
      )}
    </main>
  );
}
