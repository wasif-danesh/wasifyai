// SPDX-License-Identifier: AGPL-3.0-only
// The 3D group's one model (ADR-0080): it is a component of the engine, set up with its size shown first.
import type { Model3dApi, OwnKeysApi } from "@wasifyai/client";
import type { ChoiceList, ChoicesApi, ModelChoice } from "@wasifyai/ui";
import { keyedRow, leaveKey, withKeyed } from "./keyed";
import { pause, runSteps } from "./steps";

export const MODEL3D_ID = "pixal3d";

export function model3dRow(component: Awaited<ReturnType<Model3dApi["component"]>>): ModelChoice {
  // with the key the engine says "installed" for the 3D screen; the row is about this computer
  const c = { ...component, installed: component.here ?? component.installed };
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

export function model3dChoices(api: Model3dApi, keys?: OwnKeysApi): ChoicesApi {
  return {
    async list(): Promise<ChoiceList> {
      const [c, own] = await Promise.all([api.component(), keys?.list().catch(() => null)]);
      return {
        choices: withKeyed([model3dRow(c)], keyedRow(own ?? null, "model3d")),
        diskFreeBytes: null,
        memoryBytes: null,
      };
    },
    async choose(id) {
      // choosing the one on this computer takes 3D off the key (the key stays saved)
      await leaveKey(keys, "model3d", id);
    },
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
