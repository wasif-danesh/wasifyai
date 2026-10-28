// SPDX-License-Identifier: AGPL-3.0-only
// Pieces that show the state of the engine, the image engine and updates. Used by the window's start-up
// screen and by Settings.
import { Button, JobMeter, Notice, Spinner } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { componentInstall, componentStatus, onComponentStatus } from "./components";
import {
  COMFYUI,
  type ComponentStatus,
  type EngineStatus,
  LLAMACPP,
  type UpdateStatus,
  engineRepair,
  engineRestart,
  humanBytes,
  installFraction,
  updateCheck,
  updateInstall,
} from "./engine";

export function EngineState({ status }: { status: Exclude<EngineStatus, { state: "ready" }> }) {
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
export function ImageEngineCard() {
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

/** The local language engine (llama.cpp, stage D): the same shape as the image engine's card. */
export function LanguageEngineCard() {
  const [status, setStatus] = useState<ComponentStatus | null>(null);
  useEffect(() => {
    let stop: (() => void) | undefined;
    let gone = false;
    componentStatus(LLAMACPP)
      .then((s) => !gone && setStatus(s))
      .catch(() => {});
    onComponentStatus((id, s) => id === LLAMACPP && !gone && setStatus(s)).then((off) => {
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
      return <p className="text-muted-foreground text-sm">Local chat: {status.reason}</p>;
    case "not_installed":
      return (
        <Notice
          title="Run language models on this computer"
          actions={
            <Button type="button" onClick={() => void componentInstall(LLAMACPP)}>
              Set up the language engine
            </Button>
          }
        >
          This is done once and needs an internet connection and about{" "}
          {humanBytes(status.needs_bytes)} of disk space. Models are found on this computer or
          downloaded separately.
        </Notice>
      );
    case "installing": {
      const p = status.progress;
      return (
        <section className="grid gap-3" aria-label="Setting up the language engine">
          <JobMeter
            title={`Setting up the language engine, step ${p.index} of ${p.count}: ${p.label}`}
            text={`${Math.round(installFraction(p) * 100)}%`}
            value={installFraction(p)}
            label="Language engine setup progress"
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
          Language engine installed (llama.cpp {status.version},{" "}
          {status.accelerator === "metal" ? "Apple GPU" : "processor only: models run slower"}).
        </p>
      );
    case "failed":
      return (
        <Notice
          tone="error"
          title="The language engine could not be set up"
          actions={
            <>
              <Button type="button" onClick={() => void componentInstall(LLAMACPP)}>
                Try again
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => void componentInstall(LLAMACPP, true)}
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
export function UpdateBanner() {
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
      title={`Wasify AI ${update.version} is available`}
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
