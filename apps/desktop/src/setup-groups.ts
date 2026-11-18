// SPDX-License-Identifier: AGPL-3.0-only
// A menu group's one setup (ADR-0109, stages FR2 and FR4): the engine says what the group needs
// (`/desktop/setup/groups`); here its parts are run as steps of one progress bar, each through the route that already
// sets it up (a component's installer, a model's confirm-first download, the chat choice's "get and use"). Each of
// those is the engine's own job and picks up where it stopped, so a group stopped half way, or an app closed half
// way, carries on from the part it was at when the button is pressed again. One run per group, kept here, so leaving
// the screen does not stop it.
import type { SetupGroup, SetupPart } from "@wasifyai/client";
import type { ChoicesApi, GetProgress, ModelChoice, SetupRun } from "@wasifyai/ui";
import { modelsApi, setupApi } from "./api";
import { offerOf } from "./choices/ChatStart";
import { type ComponentPort, enginePort, installStep } from "./choices/engines";
import { type Step, modelStep, runSteps } from "./choices/steps";
import type { ModelEntry } from "./models";
import type { Route } from "./router";

/** The menu item a screen belongs to (the reverse of menu.ts's ROUTES), for the screens a group gates. */
export function itemOfRoute(
  route: Route,
  routes: Record<string, Route>,
  notebook: string | null,
): string | null {
  if (route === "notebook") return notebook === "new" ? "notebook.create" : "notebook.list";
  for (const [item, r] of Object.entries(routes)) if (r === route) return item;
  return null;
}

export function groupOfItem(groups: SetupGroup[], item: string): SetupGroup | null {
  return groups.find((g) => g.items.some((i) => i.id === item)) ?? null;
}

/** The chat model to get when a group needs chat: one already on the computer first (Ollama, LM Studio, a found
 * file: nothing to download, ADR-0109 decision 2), else the one recommended for this computer. */
export function chatOffer(choices: ModelChoice[]): ModelChoice | null {
  if (choices.some((c) => c.chosen && c.state === "ready")) return null;
  // of the models already here, one that fits this computer, the recommended first, then the smallest: the
  // quickest to answer, which is what a first chat needs
  const fit = (c: ModelChoice) => (c.fit === "fits" || c.fit === null ? 0 : 1);
  const tier = (c: ModelChoice) => (c.tier === "recommended" ? 0 : 1);
  const here = choices
    .filter((c) => c.state === "ready" && c.source !== "app" && c.fit !== "too_big")
    .sort(
      (a, b) => fit(a) - fit(b) || tier(a) - tier(b) || (a.sizeBytes ?? 0) - (b.sizeBytes ?? 0),
    );
  return here[0] ?? offerOf(choices)?.choice ?? null;
}

/** The parts a press of the button sets up: the group's download, or with `instead` also what only "Download
 * instead" fetches. Small parts first, so the first items work while a big model is still coming. */
export function partsToRun(group: SetupGroup, instead: boolean): SetupPart[] {
  return group.parts
    .filter(
      (p) =>
        !p.set_up &&
        p.available &&
        (p.included || (instead && p.fit !== "cannot_run" && !p.included)),
    )
    .sort((a, b) => a.bytes - b.bytes);
}

export type SetupPorts = {
  components: ComponentPort;
  models: {
    entry(id: string): Promise<ModelEntry | null>;
    step(e: ModelEntry, accept: boolean): Step;
  };
  chat: ChoicesApi | null;
};

export const setupPorts = (chat: ChoicesApi | null): SetupPorts => ({
  components: enginePort,
  models: {
    async entry(id) {
      return (await modelsApi.overview()).models.find((m) => m.id === id) ?? null;
    },
    step: (e, accept) => modelStep(modelsApi, e, { acceptMemory: accept }),
  },
  chat,
});

/** The steps of one press of the button. */
export async function stepsFor(
  group: SetupGroup,
  instead: boolean,
  ports: SetupPorts,
): Promise<Step[]> {
  const steps: Step[] = [];
  for (const p of partsToRun(group, instead)) {
    if (p.kind === "component") {
      steps.push(installStep(ports.components, p.ref, `Setting up ${p.title}`, p.bytes));
    } else if (p.kind === "model") {
      const e = await ports.models.entry(p.ref);
      if (e && e.bytes_missing > 0) steps.push(ports.models.step(e, !p.included));
    } else if (p.kind === "chat" && ports.chat) {
      const chat = ports.chat;
      const offer = chatOffer((await chat.list()).choices);
      if (offer) {
        steps.push({
          label: `Setting up ${offer.title}`,
          bytes: offer.downloadBytes + offer.engineBytes,
          run: (report, signal) =>
            offer.state === "ready"
              ? chat.choose(offer.id)
              : chat.get(offer.id, (g: GetProgress) => report(g.fraction ?? 0, g.label), signal),
        });
      }
    }
  }
  return steps;
}

// ---- one run per group, kept while the window is open ---------------------------------------

type Listener = (run: SetupRun) => void;
const runs = new Map<
  string,
  { run: SetupRun; stop: AbortController | null; listeners: Set<Listener> }
>();

function slot(groupId: string) {
  let s = runs.get(groupId);
  if (!s) {
    s = { run: { state: "idle" }, stop: null, listeners: new Set() };
    runs.set(groupId, s);
  }
  return s;
}

function tell(groupId: string, run: SetupRun) {
  const s = slot(groupId);
  s.run = run;
  for (const l of s.listeners) l(run);
}

export function runOf(groupId: string): SetupRun {
  return slot(groupId).run;
}

export function watchRun(groupId: string, fn: Listener): () => void {
  const s = slot(groupId);
  s.listeners.add(fn);
  return () => s.listeners.delete(fn);
}

/** Set a group up; `done` is called when it finished (or stopped, or failed), to read the groups again. */
export async function startSetup(
  group: SetupGroup,
  instead: boolean,
  ports: SetupPorts,
  done: () => void,
): Promise<void> {
  const s = slot(group.id);
  if (s.run.state === "running") return;
  const stop = new AbortController();
  s.stop = stop;
  tell(group.id, { state: "running", label: "Getting ready", fraction: 0 });
  try {
    const steps = await stepsFor(group, instead, ports);
    await runSteps(
      steps,
      (p) =>
        tell(group.id, { state: "running", label: p.label, fraction: p.fraction ?? undefined }),
      stop.signal,
    );
    tell(group.id, { state: "idle" });
  } catch (e) {
    const message = e instanceof Error ? e.message : "It did not finish.";
    tell(group.id, stop.signal.aborted ? { state: "idle" } : { state: "failed", message });
  } finally {
    s.stop = null;
    done();
  }
}

export function stopSetup(groupId: string) {
  slot(groupId).stop?.abort();
}

export const readGroups = () => setupApi.groups();
