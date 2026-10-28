// SPDX-License-Identifier: AGPL-3.0-only
// Every optional part of the engine in one list (stage F2): the image and language engines, the speech runtime,
// lip sync, 3D, Motion graphics, the trainers and the notebooks reader. Each says whether it is here, what setting
// it up would fetch, and how far an install is; set up, stop, repair and remove are the same for all of them.
import type { ComponentView } from "@wasifyai/client";
import { Button, ConfirmDialog, JobMeter } from "@wasifyai/ui";
import { useCallback, useEffect, useState } from "react";
import { componentsApi } from "./api";
import { onComponentStatus } from "./components";
import { humanBytes, installFraction } from "./engine";

const REFRESH_MS = 2000; // while something is being set up: not every part sends its progress

export function ComponentsPanel() {
  const [items, setItems] = useState<ComponentView[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [removing, setRemoving] = useState<ComponentView | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await componentsApi.list()).components);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    let off: (() => void) | undefined;
    let gone = false;
    void onComponentStatus((id, status) => {
      setItems((now) => now?.map((c) => (c.id === id ? { ...c, status } : c)) ?? now);
    }).then((stop) => {
      off = stop;
      if (gone) stop();
    });
    return () => {
      gone = true;
      off?.();
    };
  }, [load]);

  const busy = items?.some((c) => c.status.state === "installing") ?? false;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [busy, load]);

  async function act(run: () => Promise<unknown>) {
    try {
      await run();
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
    await load();
  }

  if (items === null) return problem ? <p className="text-destructive text-sm">{problem}</p> : null;
  return (
    <div className="grid gap-3">
      <p className="m-0 text-muted-foreground text-sm">
        Parts of the app that are added only when you use what needs them. Each is fetched once,
        checked against its pinned checksum, and kept on this computer.
      </p>
      {problem ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {problem}
        </p>
      ) : null}
      <ul className="m-0 grid list-none gap-2 p-0" aria-label="Optional parts">
        {items.map((c) => (
          <li key={c.id} className="grid gap-2 rounded-md border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{c.title}</span>
              <span className="text-muted-foreground text-sm">{said(c)}</span>
            </div>
            {c.status.state === "installing" ? (
              <JobMeter
                title={`Step ${c.status.progress.index} of ${c.status.progress.count}: ${c.status.progress.label}`}
                text={`${Math.round(installFraction(c.status.progress) * 100)}%`}
                value={installFraction(c.status.progress)}
                label={`${c.title} setup progress`}
              />
            ) : null}
            <div className="flex flex-wrap gap-2">
              {c.status.state === "not_installed" ? (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => {
                    const s = c.status;
                    if (s.state === "not_installed")
                      void act(() => componentsApi.install(c.id, s.needs_bytes));
                  }}
                >
                  Set up
                </Button>
              ) : null}
              {c.status.state === "failed" ? (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void act(() => componentsApi.install(c.id, null, true))}
                >
                  Try again
                </Button>
              ) : null}
              {c.status.state === "installing" && c.can.stop ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void act(() => componentsApi.cancel(c.id))}
                >
                  Stop
                </Button>
              ) : null}
              {c.status.state === "installed" && c.can.repair ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void act(() => componentsApi.install(c.id, null, true))}
                >
                  Repair
                </Button>
              ) : null}
              {c.status.state === "installed" && c.can.remove ? (
                <Button type="button" size="sm" variant="outline" onClick={() => setRemoving(c)}>
                  Remove
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      {removing ? (
        <ConfirmDialog
          title={`Remove ${removing.title}?`}
          message="What needs it stops working until it is set up again. Your own work is not touched."
          confirmLabel="Remove"
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            const id = removing.id;
            setRemoving(null);
            void act(() => componentsApi.uninstall(id));
          }}
        />
      ) : null}
    </div>
  );
}

/** One short phrase for where a part stands. */
function said(c: ComponentView): string {
  const s = c.status;
  switch (s.state) {
    case "installed":
      return ["Set up", s.version, s.accelerator && `on ${s.accelerator}`]
        .filter(Boolean)
        .join(" · ");
    case "not_installed":
      return s.needs_bytes ? `Not set up · about ${humanBytes(s.needs_bytes)}` : "Not set up";
    case "installing":
      return "Setting up";
    case "failed":
      return s.message;
    case "unsupported":
      return s.reason;
  }
}
