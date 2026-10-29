// SPDX-License-Identifier: AGPL-3.0-only
// The 3D group's one model (ADR-0080): it is a component of the engine, set up with its size shown first.
import type { Model3dApi } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, ModelChoice } from "@wasifyai/ui";
import { pause, runSteps } from "./steps";

export const MODEL3D_ID = "pixal3d";

export function model3dRow(c: Awaited<ReturnType<Model3dApi["component"]>>): ModelChoice {
  const state: ModelChoice["state"] = c.installed
    ? "ready"
    : !c.plan.supported
      ? "unavailable"
      : c.fit?.verdict === "too_big"
        ? "too_big"
        : "needs_download";
  return {
    id: MODEL3D_ID,
    title: "Pixal3D",
    plain: "Turns one picture into a 3D model you can turn around and save. Experimental.",
    tier: "recommended",
    state,
    chosen: c.installed,
    downloadBytes: c.installed ? 0 : c.plan.bytes,
    engineBytes: 0,
    engineName: null,
    fit: c.fit?.verdict ?? null,
    fitReason: c.fit?.reason ?? null,
    source: "app",
    sizeBytes: c.installed ? c.plan.bytes : 0,
    removable: c.installed,
    unavailableReason: state === "unavailable" ? "Not available on this computer" : null,
  };
}

export function model3dChoices(api: Model3dApi): ChoicesApi {
  return {
    async list(): Promise<ChoiceList> {
      const c = await api.component();
      return { choices: [model3dRow(c)], diskFreeBytes: null, memoryBytes: null };
    },
    async choose() {},
    async remove() {
      await api.uninstall();
    },
    async get(_id, on, signal) {
      const c = await api.component();
      await runSteps(
        [
          {
            label: "Setting up 3D models",
            bytes: c.plan.bytes,
            async run(report, signal2) {
              const stop = () => void api.cancelInstall().catch(() => {});
              signal2.addEventListener("abort", stop, { once: true });
              try {
                if (c.progress.state !== "installing") await api.install(c.plan.bytes);
                for (;;) {
                  const now = await api.component();
                  const p = now.progress;
                  report(
                    p.total_bytes > 0 ? p.done_bytes / p.total_bytes : 0,
                    p.message || undefined,
                  );
                  if (now.installed) return;
                  if (p.state === "failed")
                    throw new Error(p.message || "The setup did not finish.");
                  if (signal2.aborted) throw new Error("Stopped.");
                  await pause(1000, signal2);
                }
              } finally {
                signal2.removeEventListener("abort", stop);
              }
            },
          },
        ],
        on,
        signal,
      );
    },
  };
}
