// SPDX-License-Identifier: AGPL-3.0-only
// The two engines a model may run on, set up by the shell on request (ADR-0086): the image engine (ComfyUI) and the
// language engine (llama.cpp). A model that needs one shows the engine's size in its dialog and gets it first.
import {
  COMFYUI,
  type ComponentStatus,
  LLAMACPP,
  componentInstall,
  componentStatus,
  installFraction,
  onComponentStatus,
} from "../engine";
import type { Step } from "./steps";
import type { EngineState, Engines } from "./types";

/** What the shell offers; a test passes a fake. */
export type ComponentPort = {
  status(id: string): Promise<ComponentStatus>;
  install(id: string): Promise<void>;
  onStatus(fn: (id: string, s: ComponentStatus) => void): Promise<() => void>;
};

export const tauriPort: ComponentPort = {
  status: componentStatus,
  install: (id) => componentInstall(id),
  onStatus: onComponentStatus,
};

export function stateOf(s: ComponentStatus, name: string): EngineState {
  switch (s.state) {
    case "installed":
      return { installed: true, supported: true, bytes: 0, name };
    case "not_installed":
      return { installed: false, supported: true, bytes: s.needs_bytes, name };
    case "unsupported":
      return { installed: false, supported: false, bytes: 0, name };
    default:
      return { installed: false, supported: true, bytes: 0, name };
  }
}

/** Set a component up (or follow the set-up already under way) and wait until it is there. */
function installStep(port: ComponentPort, id: string, label: string, bytes: number): Step {
  return {
    label,
    bytes,
    async run(report, signal) {
      const first = await port.status(id);
      if (first.state === "installed") return;
      if (first.state === "unsupported") throw new Error(first.reason);
      let finish: (s: ComponentStatus) => void = () => {};
      const done = new Promise<void>((resolve, reject) => {
        finish = (s) => {
          if (s.state === "installed") resolve();
          else if (s.state === "failed") reject(new Error(s.message));
          else if (s.state === "installing") report(installFraction(s.progress), s.progress.label);
        };
        signal.addEventListener("abort", () => reject(new Error("Stopped.")), { once: true });
      });
      // listen before asking, so no event is missed; look now and then too, in case one was
      const off = await port.onStatus((who, s) => who === id && finish(s));
      const look = setInterval(() => void port.status(id).then(finish, () => {}), 3000);
      try {
        finish(first);
        // the shell is told to start only when nothing is running yet
        if (first.state !== "installing") await port.install(id);
        await done;
      } finally {
        clearInterval(look);
        off();
      }
    },
  };
}

export function createEngines(port: ComponentPort = tauriPort): Engines {
  const read = (id: string, name: string) => port.status(id).then((s) => stateOf(s, name));
  return {
    image: () => read(COMFYUI, "The image engine"),
    language: () => read(LLAMACPP, "The chat engine"),
    async imageStep() {
      const s = await read(COMFYUI, "The image engine");
      return installStep(port, COMFYUI, "Setting up the image engine", s.bytes);
    },
    async languageStep() {
      const s = await read(LLAMACPP, "The chat engine");
      return installStep(port, LLAMACPP, "Setting up the chat engine", s.bytes);
    },
  };
}
