// SPDX-License-Identifier: AGPL-3.0-only
// Every optional part of the engine in one list (stage F2): the image and language engines, the speech runtime,
// lip sync, 3D, Motion graphics, the trainers and the notebooks reader. Each says whether it is here, what setting
// it up would fetch, and how far an install is; set up, stop, repair and remove are the same for all of them. Each
// part is one short row (the Settings redesign of 2026-11-15): the parts set up, being set up or failed are shown, and
// the ones not set up wait behind "Show all".
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
  const [all, setAll] = useState(false);

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
  const here = items.filter(
    (c) => c.status.state !== "not_installed" && c.status.state !== "unsupported",
  );
  const shown = all ? items : here;
  return (
    <div className="grid gap-3">
      <p className="m-0 text-muted-foreground text-sm">
        Added only when you use what needs them, fetched once and checked.
      </p>
      {problem ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {problem}
        </p>
      ) : null}
      <ul className="m-0 list-none divide-y rounded-lg border p-0" aria-label="Optional parts">
        {shown.length === 0 ? (
          <li className="px-3 py-2.5 text-muted-foreground text-sm">
            No optional part is set up yet.
          </li>
        ) : null}
        {shown.map((c) => (
          <li key={c.id} className="grid gap-2 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="min-w-0 flex-1 text-sm">
                {c.title}
                <span
                  className={`block ${c.status.state === "failed" ? "text-destructive" : "text-muted-foreground"}`}
                >
                  {said(c)}
                </span>
              </span>
              <div className="flex flex-wrap gap-2">
                {c.status.state === "not_installed" ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
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
            </div>
            {c.status.state === "installing" ? (
              <JobMeter
                title={`Step ${c.status.progress.index} of ${c.status.progress.count}: ${c.status.progress.label}`}
                text={`${Math.round(installFraction(c.status.progress) * 100)}%`}
                value={installFraction(c.status.progress)}
                label={`${c.title} setup progress`}
              />
            ) : null}
          </li>
        ))}
      </ul>
      {here.length < items.length ? (
        <div>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0"
            aria-expanded={all}
            onClick={() => setAll((v) => !v)}
          >
            {all ? "Show only the parts set up" : `Show all ${items.length} parts`}
          </Button>
        </div>
      ) : null}
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
